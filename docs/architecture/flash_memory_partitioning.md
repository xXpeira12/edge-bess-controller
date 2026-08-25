# Flash Memory Partitioning & Secure Bootloader Architecture

**Document:** `docs/architecture/flash_memory_partitioning.md`  
**Related SRS IDs:** `REQ-SEC-001`, `REQ-SEC-002`, `REQ-SEC-003`

---

## 1. Target Microcontroller Memory Architectures

```
+===================================================================================================+
|                                    FLASH ARCHITECTURE COMPARISON                                  |
|                                                                                                   |
|  PRIMARY TARGET: STM32G474RE (512 KB Dual-Bank Flash, Symmetric 200 KB App Slots)                 |
|  - Bank 1 (256 KB, Pages 0-127) + Bank 2 (256 KB, Pages 128-255)                                  |
|  - Page Size: Uniform 2 KB per page (256 pages total)                                             |
|  - Symmetric Dual-Bank Layout: Slot A (200 KB) and Slot B (200 KB)                                |
|  - True Read-While-Write (RWW) and Zero-Downtime Bank Swapping via BFB2 Option Bit                |
|                                                                                                   |
|  SECONDARY / PORTING TARGET: STM32F446RE (512 KB Single-Bank Flash)                               |
|  - 8 Asymmetric Sectors (4 x 16 KB, 1 x 64 KB, 3 x 128 KB)                                        |
|  - In-Application Programming (IAP) staging via RAM-buffered sector relocation                   |
+===================================================================================================+
```

---

## 2. Symmetric Flash Memory Partitioning Maps

### 2.1 Primary Target: STM32G474RE Symmetric Memory Map (512 KB)

```
0x0800_0000 +-------------------------------------------------------+
            | BANK 1: PRIMARY BANK (256 KB)                         |
            |                                                       |
            | Pages 0 - 15   (32 KB)  : Immutable Secure Bootloader |
            | Pages 16 - 115 (200 KB) : Application Slot A          |
            | Pages 116 - 123 (16 KB) : NVRAM System Configuration  |
            | Pages 124 - 127 (8 KB)  : Public Key Verification Reg |
0x0804_0000 +-------------------------------------------------------+
            | BANK 2: SECONDARY BANK (256 KB)                       |
            |                                                       |
            | Pages 128 - 227 (200 KB): Application Slot B          |
            |                           (Symmetric Staging/Active)  |
            | Pages 228 - 243 (32 KB) : Diagnostic & Fault Event Log|
            | Pages 244 - 255 (24 KB) : Bootloader Metadata Table   |
0x0808_0000 +-------------------------------------------------------+
```

* **Slot Symmetry:** Application Slot A ($200\text{ KB}$, 100 pages) and Application Slot B ($200\text{ KB}$, 100 pages) have **identical capacity**, guaranteeing any binary that runs in Slot A fits perfectly into Slot B.

---

## 3. Fixed Bootloader Architecture & Metadata Table

The immutable Secure Bootloader occupies physical base address `0x0800_0000` ($32\text{ KB}$). Upon every reset, the Bootloader executes before any application code:

```
                         BOOTLOADER EXECUTION FLOW
                         
            +-------------------------------------------------------+
            |                   POWER-ON RESET                      |
            +-------------------------------------------------------+
                                        |
                                        v
            +-------------------------------------------------------+
            |               BOOTLOADER INITIALIZATION               |
            |  - Hardware Clock Setup (HSI 16 MHz)                  |
            |  - Read Shared Metadata Table from Bank 2 (Page 244)  |
            +-------------------------------------------------------+
                                        |
                                        v
            +-------------------------------------------------------+
            |              EVALUATE ACTIVE SLOT STATE               |
            +-------------------------------------------------------+
                 |                                      |
         [ State == TESTING ]                  [ State == CONFIRMED ]
                 |                                      |
         [ Boot Count >= 3? ]                           v
            /          \                       +--------------------+
          [YES]        [NO]                    | VERIFY SLOT DIGEST |
          /              \                     +--------------------+
         v                v                             |
  +--------------+  +-------------------+          [ CRC / SHA OK? ]
  | MARK INVALID |  | INCREMENT COUNT   |              /         \
  | FALLBACK TO  |  | JUMP TO TESTING   |           [YES]       [NO]
  | PREV CONFIRM |  | SLOT              |            /             \
  +--------------+  +-------------------+           v               v
                                            +---------------+ +--------------+
                                            | JUMP TO MAIN  | | ENTER SAFE   |
                                            | APPLICATION   | | RECOVERY     |
                                            +---------------+ +--------------+
```

### 3.1 Slot Lifecycle State Machine
Each slot progresses through explicit states in the Flash Metadata Table:

$$\text{SLOT\_EMPTY} \longrightarrow \text{SLOT\_STAGED} \longrightarrow \text{SLOT\_VALIDATED} \longrightarrow \text{SLOT\_TESTING} \longrightarrow \text{SLOT\_CONFIRMED}$$
$$\text{or} \longrightarrow \text{SLOT\_INVALID}$$

* **Failure Policy:** If cryptographic verification or CRC fails on a staging image, the bootloader **does not erase Slot B**. It marks `Slot_State = SLOT_INVALID` and records the diagnostic error code in the metadata log for remote SCADA inspection.
* **Confirmed Boot & Automatic Rollback:**
  - When a new image boots for the first time, its state is marked `SLOT_TESTING` and `Boot_Attempts = 1`.
  - If the application starts successfully and initializes all safety diagnostics, it sends an IPC confirmation to mark `Slot_State = SLOT_CONFIRMED` and `Boot_Attempts = 0`.
  - If the system crashes or watchdog resets before confirmation, `Boot_Attempts` increments on next boot. Upon reaching `Boot_Attempts >= 3`, the bootloader marks the slot `SLOT_INVALID` and rolls back to the previous confirmed slot.

---

## 4. Cryptographic Authentication & Public Key Management

* **Authentication Standard:** Firmware binaries are signed using **ECDSA with NIST P-256 (secp256r1) curve and SHA-256 hash**.
* **Key Storage Policy:**
  - The device Flash contains **ONLY the Public Verification Key** in the dedicated write-protected Key Region (Bank 1, Pages 124–127).
  - Private signing keys are **NEVER stored on the microcontroller** and reside exclusively in secure CI/CD hardware security modules (HSM).
* **Anti-Rollback Version Rule:**
  $$\text{Image\_Security\_Version} \ge \text{NVRAM\_Monotonic\_Counter}$$
  Images with lower security counters are rejected immediately.
