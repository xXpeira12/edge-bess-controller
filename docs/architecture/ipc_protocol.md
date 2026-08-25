# Inter-Processor Communication (IPC) Protocol & FreeRTOS Gateway Specification

**Document:** `docs/architecture/ipc_protocol.md`  
**Related SRS IDs:** `REQ-COMM-001`, `REQ-COMM-004`

---

## 1. IPC Physical & Master-Slave Transport Model

The Gateway MCU (ESP32) acts as the **SPI Master**, and the Control MCU (STM32) acts as the **SPI Slave**.

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
| **3** | `SEQ_NUM` | `uint8_t` | $0 - 255$ | Monotonic sequence number. Incremented per unique packet. |
| **4** | `MSG_TYPE` | `uint8_t` | Enum | Defines payload schema and priority. |
| **5** | `MSG_FLAGS` | `uint8_t` | Bitmask | Control flags: `BIT0=ACK`, `BIT1=NACK`, `BIT2=RETRY`, `BIT3=URGENT`. |
| **6** | `PAYLOAD_LEN` | `uint8_t` | $0 - 64$ | Length $N$ of active payload data in bytes. |
| **7 .. (7+N-1)**| `PAYLOAD` | `uint8_t[N]`| Binary Data | Serialized data structure. |
| **(7+N) .. (8+N)**|`CRC16` | `uint16_t` | `0x0000-0xFFFF` | CRC-16-CCITT (`0x1021`, init `0xFFFF`) calculated over bytes $2 \dots (6+N)$. |

### 2.2 Message Types (`MSG_TYPE`)

| Type ID | Enum Identifier | Direction | Description |
| :--- | :--- | :--- | :--- |
| **`0x01`** | `MSG_TELEMETRY_FAST` | STM32 $\to$ ESP32 | High-speed feedback: $V_{bus}, I_L, V_{bat}$, State, Flags ($50\text{ Hz}$). |
| **`0x02`** | `MSG_TELEMETRY_SLOW` | STM32 $\to$ ESP32 | Diagnostics: Temp, DWT cycle jitter, March C- status ($10\text{ Hz}$). |
| **`0x10`** | `MSG_CMD_SET_STATE` | ESP32 $\to$ STM32 | Supervisory command: Stop / Charge / Discharge. |
| **`0x11`** | `MSG_CMD_SET_CURRENT` | ESP32 $\to$ STM32 | Setpoint current target: $I_{ref}$ target in $\text{mA}$. |
| **`0x20`** | `MSG_FAULT_ALERT` | STM32 $\to$ ESP32 | Asynchronous high-priority fault trip notification (via `ALERT_OUT`). |
| **`0x21`** | `MSG_FAULT_CLEAR` | ESP32 $\to$ STM32 | Authenticated clear command (`0x00A5`). |
| **`0xFE`** | `MSG_PING` | Bi-directional | Heartbeat link integrity check packet. |
| **`0xFF`** | `MSG_ACK_NACK` | Bi-directional | Explicit confirmation of received frame sequence number. |

---

## 3. Protocol State Machine & Automatic Repeat Request (ARQ)

```
                            IPC PROTOCOL STATE MACHINE
                            
            +-------------------------------------------------------+
            |                      IPC_UNINIT                       |
            |  - Hardware reset; DMA registers cleared              |
            +-------------------------------------------------------+
                                        |
                          [ Peripheral Init Completed ]
                                        v
            +-------------------------------------------------------+
            |                      IPC_SYNCING                      |
            |  - ESP32 sends periodic MSG_PING (100 ms interval)    |
            |  - STM32 scans DMA buffer for SYNC_WORD (0xA55A)      |
            +-------------------------------------------------------+
                                        |
                         [ 3 Consecutive Valid Pings ACKed ]
                                        v
            +-------------------------------------------------------+
    +-----> |                  IPC_CONNECTED_IDLE                   |
    |       |  - Heartbeat timer active (100 ms timeout)            |
    |       +-------------------------------------------------------+
    |                                   |
    |                 [ ALERT_OUT HIGH or Outgoing Cmd Ready ]
    |                                   v
    |       +-------------------------------------------------------+
    |       |                   IPC_TX_RX_ACTIVE                    |
    |       |  - Full-Duplex DMA Transfer Executed (SPI @ 10 MHz)   |
    |       +-------------------------------------------------------+
    |                                   |
    |                         [ DMA Transfer Complete ]
    |                                   v
    |       +-------------------------------------------------------+
    |       |                     IPC_WAIT_ACK                      |
    |       |  - Start ACK Timer (Timeout = 5.0 ms)                 |
    |       +-------------------------------------------------------+
    |                 |                                   |
    |        [ ACK Received Valid ]               [ Timeout / NACK ]
    |                 |                                   |
    +-----------------+                      [ Retry Count < 3 ]  [ Retry Count >= 3 ]
                                                     |                      |
                                            (Send with RETRY Flag)          v
                                                     |         +-------------------------+
                                                     +-------> | IPC_COMM_FAULT_DEGRADED |
                                                               | - Emergency Ramp (100A/s|
                                                               | - Latch COMM_LOST Flag  |
                                                               +-------------------------+
```

### 3.1 Timing & Retry Policy
* **Acknowledgement Timeout ($T_{ack}$):** $5.0\text{ ms}$.
* **Maximum ARQ Retries ($N_{retry}$):** $3$ attempts.
* **Degraded Transition Policy:** If 3 consecutive retransmissions fail, both microcontrollers transition their IPC state machine to `IPC_COMM_FAULT_DEGRADED`. The Control MCU initiates an emergency current ramp-down at $100\text{ A/s}$ to `STATE_IDLE`.

---

## 4. FreeRTOS Non-Blocking Gateway Architecture

```
+===================================================================================================+
|                                    GATEWAY FREERTOS ARCHITECTURE                                  |
|                                                                                                   |
|  Priority 5 [High / Real-Time]                                                                    |
|  +---------------------------------------------------------------------------------------------+  |
|  | IPC Master Task: Handles SPI DMA transfers, parses CRC, posts to ring buffers               |  |
|  | Queue Length: IPC_TX_QUEUE_LEN = 16, IPC_RX_QUEUE_LEN = 16                                   |  |
|  | Timeout: Strict pdMS_TO_TICKS(10); High-Water Mark: > 512 bytes                              |  |
|  +---------------------------------------------------------------------------------------------+  |
|                                  |                         ^                                      |
|                                  v                         |                                      |
|  Priority 3 [Medium]                                                                              |
|  +---------------------------------------------------------------------------------------------+  |
|  | CAN BMS Ingestion Task: Ingests pack telemetry @ 100 ms; computes dynamic charge limits     |  |
|  | Queue: CAN_RX_QUEUE_LEN = 32; Non-blocking xQueueSend(timeout = 0)                         |  |
|  +---------------------------------------------------------------------------------------------+  |
|                                  |                         |                                      |
|                                  v                         v                                      |
|  Priority 2 [Normal]                                                                              |
|  +---------------------------------------------------------------------------------------------+  |
|  | Modbus Server Task: Serves SCADA registers 40001-40018; enforces setpoint validation        |  |
|  +---------------------------------------------------------------------------------------------+  |
|                                  |                                                                |
|                                  v                                                                |
|  Priority 1 [Low / Telemetry]                                                                     |
|  +---------------------------------------------------------------------------------------------+  |
|  | MQTT Publisher Task: JSON cloud telemetry @ 1 Hz. Drops frames on socket stall (No blocking)|  |
|  +---------------------------------------------------------------------------------------------+  |
+===================================================================================================+
```

### 4.1 FreeRTOS Non-Blocking Safety Mechanisms
1. **Bounded Queues & Zero-Wait Backpressure:**
   ```c
   if (xQueueSend(g_mqtt_telemetry_queue, &telemetry_item, 0) != pdPASS) {
       /* Queue full due to network delay: drop frame and log diagnostic counter */
       g_network_dropped_frames_count++;
   }
   ```
2. **Task Watchdog Timer (TWDT):** All tasks register with the hardware TWDT ($500\text{ ms}$ timeout).
3. **Stack Monitoring:** `uxTaskGetStackHighWaterMark()` reported over diagnostics.
