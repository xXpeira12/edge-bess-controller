# Flash Memory Partitioning & Secure Bootloader Architecture

**Document:** `docs/architecture/flash_memory_partitioning.md`  
**Related SRS IDs:** `REQ-SEC-001`, `REQ-SEC-002`, `REQ-SEC-003`

---

## 1. Hardware Selection Dependency & Status

> **ENGINEERING NOTICE:**  
> **Status:** `TODO [Hardware Selection Pending]`  
> The exact physical flash sector and page boundaries documented herein are subject to final microcontroller silicon selection between the **STM32G474RE** and the **STM32F446RE**. The firmware architecture is designed to abstract flash operations via a Hardware Abstraction Layer (HAL Flash Driver) until hardware freeze.

---

## 2. Target Microcontroller Memory Architecture Comparison

```
+===================================================================================================+
|                                    FLASH ARCHITECTURE COMPARISON                                  |
|                                                                                                   |
|  OPTION A: STM32G474RE (Recommended for Digital Power SMPS)                                       |
|  - Total Flash: 512 KB Dual-Bank                                                                  |
|  - Organization: Bank 1 (256 KB, Pages 0-127) + Bank 2 (256 KB, Pages 128-255)                    |
|  - Page Size: Uniform 2 KB per page (256 pages total)                                             |
|  - Dual-Bank Mode: True Read-While-Write (RWW) with BFB2 Option Bit Bank Swapping                 |
|  - Zero-downtime OTA update capability without staging copy penalty                              |
|                                                                                                   |
|  OPTION B: STM32F446RE (Alternative Architecture)                                                 |
|  - Total Flash: 512 KB Single-Bank                                                                |
|  - Organization: 8 Asymmetric Sectors (4 x 16 KB, 1 x 64 KB, 3 x 128 KB)                         |
|  - Erase Granularity: Coarse (128 KB sector erase time: up to 2.0 seconds)                        |
|  - In-Application Programming (IAP): Requires dedicated RAM-based staging and sector relocation   |
+===================================================================================================+
```

---

## 3. Flash Memory Partitioning Maps

### 3.1 Option A: STM32G474RE Dual-Bank Memory Map (512 KB)

```
0x0800_0000 +-------------------------------------------------------+
            | BANK 1: PRIMARY ACTIVE BANK (256 KB)                  |
            |                                                       |
            | Pages 0 - 15   (32 KB)  : Immutable Secure Bootloader |
            | Pages 16 - 123 (216 KB) : Application Slot A (Active) |
            | Pages 124 - 127 (8 KB)  : NVRAM System Configuration  |
0x0804_0000 +-------------------------------------------------------+
            | BANK 2: SECONDARY STAGING BANK (256 KB)               |
            |                                                       |
            | Pages 128 - 239 (224 KB): Application Slot B (Staging)|
            | Pages 240 - 247 (16 KB) : Diagnostic & Fault Event Log|
            | Pages 248 - 255 (16 KB) : Cryptographic Key Store     |
0x0808_0000 +-------------------------------------------------------+
```

* **Bank Swapping Mechanism:** When a valid, authenticated update is downloaded into Slot B (Bank 2), the bootloader or application sets the `BFB2` bit in the STM32 Flash Option Bytes (`FLASH_OPTR`). Upon system reset, the MCU automatically remaps Bank 2 to address `0x0800_0000`, switching active execution instantly with zero copy overhead.

---

### 3.2 Option B: STM32F446RE Asymmetric Sector Memory Map (512 KB)

```
0x0800_0000 +-------------------------------------------------------+
            | Sector 0 (16 KB) : Immutable Secure Bootloader        |
0x0800_4000 +-------------------------------------------------------+
            | Sector 1 (16 KB) : NVRAM Config & Monotonic Version   |
0x0800_8000 +-------------------------------------------------------+
            | Sector 2 (16 KB) : Cryptographic Public Key Storage   |
0x0800_C000 +-------------------------------------------------------+
            | Sector 3 (16 KB) : Diagnostic Log / Fault History     |
0x0801_0000 +-------------------------------------------------------+
            | Sector 4 (64 KB) : Application Slot A (Lower Code)    |
0x0802_0000 +-------------------------------------------------------+
            | Sector 5 (128 KB): Application Slot A (Upper Code)    |
            |                    (Total Slot A Size: 192 KB)        |
0x0804_0000 +-------------------------------------------------------+
            | Sector 6 (128 KB): Application Slot B (Staging Part 1)|
0x0806_0000 +-------------------------------------------------------+
            | Sector 7 (128 KB): Application Slot B (Staging Part 2)|
            |                    (Total Slot B Size: 256 KB)        |
0x0808_0000 +-------------------------------------------------------+
```

* **IAP Relocation Mechanism:** In the single-bank STM32F446, new firmware images are received by the Gateway Core and written over SPI into Application Slot B (Sectors 6–7). Upon cryptographic verification and anti-rollback checks, the bootloader copies Slot B into Slot A (Sectors 4–5) while interrupts are disabled.

---

## 4. Bootloader Execution Sequence & Anti-Rollback Verification

```
                         BOOTLOADER EXECUTION FLOW
                         
            +-------------------------------------------------------+
            |                   POWER-ON RESET                      |
            +-------------------------------------------------------+
                                        |
                                        v
            +-------------------------------------------------------+
            |               BOOTLOADER INITIALIZATION               |
            |  - Hardware Clock Setup (HSI/HSE)                     |
            |  - Read NVRAM Monotonic Counter Table                 |
            +-------------------------------------------------------+
                                        |
                                        v
            +-------------------------------------------------------+
            |               INSPECT STAGING SLOT B                  |
            |  - Check Image Header Magic (0x42455353)              |
            +-------------------------------------------------------+
                                        |
                     [ New Valid Image Staged in Slot B? ]
                        /                               \
                     [YES]                             [NO]
                      /                                   \
                     v                                     v
  +-------------------------------------+   +-------------------------------+
  | VALIDATE IMAGE INTEGRITY & VERSION  |   | VERIFY ACTIVE SLOT A CRC-32   |
  | 1. SHA-256 Digest Check             |   | - Calculate HW Flash CRC-32   |
  | 2. HMAC / ECDSA Signature Check     |   +-------------------------------+
  | 3. Security Version >= Monotonic Ver|                   |
  +-------------------------------------+         [ CRC Valid? ]
          |                    |                     /         \
       [PASSED]             [FAILED]              [YES]       [NO]
          |                    |                    |           |
          v                    v                    v           v
  +---------------+    +---------------+    +-----------+  +------------+
  | COMMIT UPDATE |    | ERASE STAGING |    | JUMP TO   |  | ENTER SAFE |
  | - Bank Swap or|    | - Log Security|    | APP MAIN  |  | RECOVERY   |
  |   IAP Copy    |    |   Violation   |    +-----------+  | BOOTLOADER |
  | - Increment V |    | - Boot Slot A |                   +------------+
  +---------------+    +---------------+
          |                    |
          v                    v
     [ Soft Reset ]    [ Jump to Slot A ]
```

### 4.1 Anti-Rollback Rule
$$\text{Security\_Version}_{\text{staged}} \ge \text{Security\_Version}_{\text{active}}$$
If $\text{Security\_Version}_{\text{staged}} < \text{Security\_Version}_{\text{active}}$, the update is discarded immediately to prevent exploitation of previously patched vulnerabilities.
