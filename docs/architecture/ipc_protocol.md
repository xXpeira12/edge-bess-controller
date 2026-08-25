# Inter-Processor Communication (IPC) Protocol & FreeRTOS Gateway Specification

**Document:** `docs/architecture/ipc_protocol.md`  
**Related SRS IDs:** `REQ-COMM-001`, `REQ-COMM-004`

---

## 1. Single Source of Truth: IPC Architecture & Master-Slave Model

This document is the authoritative **Single Source of Truth** for the SPI DMA physical transport, frame serialization format, ARQ error control, session epochs, sequence number handling, and FreeRTOS task isolation.

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

---

## 2. Robust SPI Frame Structure with Session Epoch

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|       SYNC_WORD (0xA55A)      |   PROTO_VER   |  SESSION_ID   |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|    SEQ_NUM    |   MSG_TYPE    |   MSG_FLAGS   |  PAYLOAD_LEN  |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
| ... PAYLOAD (0 to 64 bytes) ...               |     CRC16     |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### 2.1 Frame Field Descriptions

| Byte Offset | Field Name | Data Type | Value / Range | Description |
| :--- | :--- | :--- | :--- | :--- |
| **0 – 1** | `SYNC_WORD` | `uint16_t` | `0xA55A` | Constant synchronization preamble for byte alignment. |
| **2** | `PROTO_VER` | `uint8_t` | `0x01` | Protocol major version. |
| **3** | `SESSION_ID` | `uint8_t` | $0 - 255$ | Link epoch counter incremented on MCU power-on/reset. |
| **4** | `SEQ_NUM` | `uint8_t` | $0 - 255$ | Monotonic sequence counter with wraparound. |
| **5** | `MSG_TYPE` | `uint8_t` | Enum | Defines payload schema and priority. |
| **6** | `MSG_FLAGS` | `uint8_t` | Bitmask | Control flags: `BIT0=ACK`, `BIT1=NACK`, `BIT2=RETRY`, `BIT3=URGENT`. |
| **7** | `PAYLOAD_LEN` | `uint8_t` | $0 - 64$ | Length $N$ of active payload data in bytes. |
| **8 .. (8+N-1)**| `PAYLOAD` | `uint8_t[N]`| Binary Data | Serialized data structure. |
| **(8+N) .. (9+N)**|`CRC16` | `uint16_t` | `0x0000-0xFFFF` | CRC-16-CCITT (`0x1021`, init `0xFFFF`) calculated over bytes $2 \dots (7+N)$. |

---

## 3. Session Synchronization & Modbus Sequence Mapping

1. **Session Epoch Re-synchronization:** When either MCU resets, `SESSION_ID` changes. Upon detecting a new `SESSION_ID`, both microcontrollers flush transaction queues and reset `SEQ_NUM` to `0` before accepting new commands.
2. **Modbus Sequence Mapping:** Modbus `CMD_SEQ` (Register `40016`, `uint16_t`) is mapped by the Gateway Core to the lower 8 bits of the SPI frame `SEQ_NUM` (`uint8_t`), preserving sequence tracking across industrial fieldbus and inter-processor buses.
