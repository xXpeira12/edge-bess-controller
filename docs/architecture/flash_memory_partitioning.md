# Flash Memory Partitioning & Secure Bootloader Architecture

**Document:** `docs/architecture/flash_memory_partitioning.md`  
**Related SRS IDs:** `REQ-SEC-001`, `REQ-SEC-002`, `REQ-SEC-003`

---

## 1. Single Source of Truth: Memory Geometry & Bootloader Concepts

This document is the authoritative **Single Source of Truth** for Flash memory partitioning, slot geometries, power-loss-safe metadata formats, confirmed boot sequences, and public key management.

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
            | Pages 244 - 255 (24 KB) : Power-Loss Safe Metadata    |
0x0808_0000 +-------------------------------------------------------+
```

* **Slot Symmetry Invariant:** $\text{Slot\_A\_Capacity} = \text{Slot\_B\_Capacity} = 200\text{ KB}$ ($100\text{ pages} \times 2\text{ KB/page} = 204,800\text{ bytes}$).

---

## 3. Power-Loss Safe Metadata Record Structure

To prevent metadata corruption during mid-write brownouts, the metadata table uses an atomic double-buffered commit record:

```c
typedef struct {
    uint32_t record_magic;       /* 0x42455353 ("BESS") */
    uint32_t sequence_num;       /* Monotonically increasing record sequence */
    uint32_t active_slot;        /* 0: Slot A, 1: Slot B */
    uint32_t slot_state;         /* EMPTY, STAGED, VALIDATED, TESTING, CONFIRMED, INVALID */
    uint32_t security_version;   /* Monotonic anti-rollback security version */
    uint32_t boot_attempts;      /* Boot retry counter for rollback (0 to 3) */
    uint32_t image_size_bytes;   /* Image payload byte length */
    uint32_t image_crc32;        /* Golden CRC-32 of active image */
    uint8_t  sha256_digest[32];  /* SHA-256 digest */
    uint8_t  ecdsa_signature[64];/* ECDSA secp256r1 signature (R, S) */
    uint32_t commit_marker;      /* 0xAA55AA55 written ONLY after full record commit */
    uint32_t header_crc32;       /* CRC-32 over entire metadata record */
} __attribute__((packed)) BootMetadataRecord_t;
```

---

## 4. Confirmed Boot Sequence & Automatic Rollback

```
                         CONFIRMED BOOT STATE MACHINE
                         
            +-------------------------------------------------------+
            |                   POWER-ON RESET                      |
            +-------------------------------------------------------+
                                        |
                                        v
            +-------------------------------------------------------+
            |               BOOTLOADER INITIALIZATION               |
            |  - Read & Validate Active Metadata Record             |
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
  +--------------+  +-------------------+          [ Digest OK? ]
  | MARK INVALID |  | INCREMENT COUNT   |              /         \
  | ROLLBACK TO  |  | JUMP TO TESTING   |           [YES]       [NO]
  | PREV CONFIRM |  | IMAGE             |            /             \
  +--------------+  +-------------------+           v               v
                                            +---------------+ +--------------+
                                            | JUMP TO MAIN  | | ENTER SAFE   |
                                            | APPLICATION   | | RECOVERY     |
                                            +---------------+ +--------------+
```

### 4.1 Step-by-Step Confirmed Boot Sequence
1. Staged image verified in RAM: SHA-256 + ECDSA secp256r1 signature verified against immutable on-chip public key.
2. Metadata updated: `Slot_State = SLOT_TESTING`, `Boot_Attempts = 1`.
3. Application boots and executes IEC 60730 Pre-Execution CPU/RAM self-tests and hardware safety initialization.
4. If self-tests pass: Application sends IPC confirmation $\to$ Metadata updated to `Slot_State = SLOT_CONFIRMED` and `Boot_Attempts = 0`.
5. If crash or watchdog trip occurs before confirmation: System reboots. Bootloader reads `Slot_State == TESTING` and increments `Boot_Attempts`.
6. Upon `Boot_Attempts >= 3`: Bootloader marks `Slot_State = SLOT_INVALID`, rolls back to the previous confirmed slot, and logs diagnostic alarm.

---

## 5. Cryptographic Key Management

* **Public Verification Key Only:** The MCU Flash stores **ONLY the public verification key** in the write-protected Key Region (Pages 124–127).
* **Zero Private Key Storage:** Private signing keys are **never stored on the microcontroller** and reside solely in secure CI/CD build environments.
