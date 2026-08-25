# Inter-Processor Communication (IPC) Protocol & FreeRTOS Gateway Specification

**Document:** `docs/architecture/ipc_protocol.md`  
**Related SRS IDs:** `REQ-COMM-001`, `REQ-COMM-004`

---

## 1. Single Source of Truth: IPC Architecture & Master-Slave Model

This document is the authoritative **Single Source of Truth** for the SPI DMA physical transport, frame serialization format, ARQ error control, transaction idempotency, sequence number handling, and FreeRTOS task isolation.

```
+===================================================================================================+
|                                    HARDWARE IPC INTERCONNECT                                      |
|                                                                                                   |
|  +---------------------------+                             +----------------------------------+   |
|  | CONTROL MCU (STM32)       |                             | GATEWAY MCU (ESP32)              |   |
|  | (SPI Slave + DMA)         |                             | (SPI Master + DMA)               |   |
|  |                           |                             |                                  |   |
|  |  SPI1_SCK (Slave Clock)  <+=============================+--- SPI2_CLK (Master Clock, 10MHz)|   |
|  |  SPI1_MISO (Slave Out)   -+============================>+--- SPI2_MISO (Master In)         |   |
|  |  SPI1_MOSI (Slave In)    <+=============================+--- SPI2_MOSI (Master Out)        |   |
|  |  SPI1_NSS (Chip Select)  <+=============================+--- SPI2_CS (Chip Select Active L)|   |
|  |                           |                             |                                  |   |
|  |  ALERT_OUT (Active HIGH) -+============================>+--- ALERT_IN (GPIO Int Rising)    |   |
|  |  (Held HIGH until ACKed)  |                             |    (Triggers SPI Master Read)    |   |
|  +---------------------------+                             +----------------------------------+   |
+===================================================================================================+
```

### 1.1 Master-Slave Transaction Semantics & ALERT_OUT Line
* **Physical Constraint:** In standard SPI, slave devices cannot generate clock pulses or initiate transfers autonomously.
* **Slave Interrupt Signalling:** When the STM32 Control Core has high-priority telemetry ready ($50\text{ Hz}$) or detects an asynchronous fault event:
  1. The STM32 prepares the outbound frame inside its SPI DMA TX buffer.
  2. The STM32 asserts the `ALERT_OUT` GPIO line from `LOW` to `HIGH`.
  3. The `ALERT_OUT` line remains **latched `HIGH`** until the ESP32 performs an SPI transaction that successfully reads and acknowledges the frame.
* **Master Transaction Clocking:** The ESP32 detects the rising edge on `ALERT_IN` via FreeRTOS GPIO interrupt, which unblocks the high-priority `IPC_Master_Task` to assert `CS` (LOW) and clock out the full-duplex SPI DMA transaction.

---

## 2. Robust SPI Frame Structure

All packets conform to a fixed header with variable payload length and trailing CRC-16:

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|       SYNC_WORD (0xA55A)      |   PROTO_VER   |    SEQ_NUM    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|   MSG_TYPE    |   MSG_FLAGS   |  PAYLOAD_LEN  |  PAYLOAD...   |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
| ... PAYLOAD (0 to 64 bytes) ...               |     CRC16     |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### 2.1 Frame Field Descriptions

| Byte Offset | Field Name | Data Type | Value / Range | Description |
| :--- | :--- | :--- | :--- | :--- |
| **0 – 1** | `SYNC_WORD` | `uint16_t` | `0xA55A` | Constant synchronization preamble for byte alignment. |
| **2** | `PROTO_VER` | `uint8_t` | `0x01` | Protocol major version. |
| **3** | `SEQ_NUM` | `uint8_t` | $0 - 255$ | Monotonic sequence counter with wraparound. |
| **4** | `MSG_TYPE` | `uint8_t` | Enum | Defines payload schema and priority. |
| **5** | `MSG_FLAGS` | `uint8_t` | Bitmask | Control flags: `BIT0=ACK`, `BIT1=NACK`, `BIT2=RETRY`, `BIT3=URGENT`. |
| **6** | `PAYLOAD_LEN` | `uint8_t` | $0 - 64$ | Length $N$ of active payload data in bytes. |
| **7 .. (7+N-1)**| `PAYLOAD` | `uint8_t[N]`| Binary Data | Serialized data structure. |
| **(7+N) .. (8+N)**|`CRC16` | `uint16_t` | `0x0000-0xFFFF` | CRC-16-CCITT (`0x1021`, init `0xFFFF`) calculated over bytes $2 \dots (6+N)$. |

---

## 3. Transaction Idempotency & Sequence Number Handling

### 3.1 Duplicate-Command Filtering
To prevent repeated execution of critical commands (such as Start Charge or Start Discharge) due to lost ACK retransmissions:
1. The STM32 maintains `last_processed_seq_num` and `last_cached_cmd_result`.
2. When an incoming command packet arrives with `SEQ_NUM == last_processed_seq_num`, the STM32 **does not re-execute the command**.
3. It immediately returns an ACK frame containing the cached `last_cached_cmd_result`.

### 3.2 Sequence Number Wraparound
* The `SEQ_NUM` increments monotonically from $0 \to 255 \to 0$ ($0\text{xFF} \to 0\text{x00}$).
* Acceptance Window: A packet is considered valid and new if:
  $$\Delta_{\text{seq}} = (\text{SEQ\_NUM}_{\text{new}} - \text{last\_processed\_seq\_num}) \pmod{256} \in [1, 127]$$

---

## 4. Communication Loss Fail-Safe Policy

If SPI DMA communication is lost (no valid frames received for $> 500\text{ ms}$):
* In `STATE_CHARGE_ACTIVE` or `STATE_DISCHARGE_ACTIVE`: STM32 autonomously initiates an **emergency software ramp-down at $100\text{ A/s}$** ($50\text{ ms}$ to $0\text{ A}$), disables PWM outputs, and enters `STATE_IDLE`.
* In `STATE_IDLE`: STM32 inhibits transition to charge/discharge until communication is re-synchronized.

---

## 5. FreeRTOS Non-Blocking Gateway Architecture

* **Task 1: IPC Master Task (`Priority 5` - High / Real-Time):** Non-blocking queues (`IPC_TX_QUEUE_LEN = 16`, `IPC_RX_QUEUE_LEN = 16`), timeout `pdMS_TO_TICKS(10)`.
* **Task 2: CAN BMS Ingestion (`Priority 3` - Medium):** Ingests pack telemetry @ $100\text{ ms}$.
* **Task 3: Modbus Server (`Priority 2` - Normal):** Serves SCADA registers $40001 - 40018$.
* **Task 4: MQTT Cloud Telemetry (`Priority 1` - Low):** JSON telemetry @ $1\text{ Hz}$. Drops frames on backpressure without stalling IPC.
* **Watchdogs & Stacks:** Task Watchdog Timer ($500\text{ ms}$ timeout) and `uxTaskGetStackHighWaterMark()` monitoring.
