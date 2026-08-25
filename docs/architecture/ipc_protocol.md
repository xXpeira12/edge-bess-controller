# Inter-Processor Communication (IPC) Protocol & FreeRTOS Gateway Specification

**Document:** `docs/architecture/ipc_protocol.md`  
**Related SRS IDs:** `REQ-COMM-001`, `REQ-COMM-004`

---

## 1. Single Source of Truth: IPC Architecture & Master-Slave Model

This document is the authoritative **Single Source of Truth** for the SPI DMA physical transport, 16-bit sequence frame serialization format, ARQ error control, session epochs, sequence number handling, and FreeRTOS task isolation.

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

## 2. Robust SPI Frame Structure (16-bit Sequence Number)

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|       SYNC_WORD (0xA55A)      |   PROTO_VER   |  SESSION_ID   |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|          SEQ_NUM (uint16_t: 0 - 65535, 1:1 Modbus)            |
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
| **3** | `SESSION_ID` | `uint8_t` | $0 - 255$ | Link epoch counter incremented on MCU power-on/reset. |
| **4 – 5** | `SEQ_NUM` | `uint16_t` | $0 - 65535$ | Monotonic sequence counter (1:1 with Modbus `CMD_SEQ`). |
| **6** | `MSG_TYPE` | `uint8_t` | Enum | Defines payload schema and priority. |
| **7** | `MSG_FLAGS` | `uint8_t` | Bitmask | Control flags: `BIT0=ACK`, `BIT1=NACK`, `BIT2=RETRY`, `BIT3=URGENT`. |
| **8** | `PAYLOAD_LEN` | `uint8_t` | $0 - 64$ | Length $N$ of active payload data in bytes. |
| **9 .. (9+N-1)**| `PAYLOAD` | `uint8_t[N]`| Binary Data | Serialized data structure. |
| **(9+N) .. (10+N)**|`CRC16` | `uint16_t` | `0x0000-0xFFFF`| CRC-16-CCITT (`0x1021`, init `0xFFFF`) calculated over bytes $2 \dots (8+N)$. |

---

## 3. Session Synchronization & Modbus Sequence Alignment

1. **1:1 Sequence Alignment:** By defining `SEQ_NUM` as `uint16_t`, Modbus `CMD_SEQ` (Register `40016`) maps directly into the SPI frame without truncation or byte slicing.
2. **Session Handshake:** When an MCU resets, `SESSION_ID` increments. Microcontrollers exchange an initial ping handshake to flush stale transactions and reset `SEQ_NUM` to `0`.
