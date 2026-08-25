# Flash Memory Partitioning & Secure Bootloader Architecture

**Document:** `docs/architecture/flash_memory_partitioning.md`  
**Related SRS IDs:** `REQ-SEC-001`, `REQ-SEC-002`, `REQ-SEC-003`

---

## 1. Single Source of Truth: Memory Geometry & Fixed Bootloader Architecture

This document is the authoritative **Single Source of Truth** for Flash memory partitioning, symmetric slot geometries, power-loss-safe metadata formats, confirmed boot sequences, and public key management.

```
+===================================================================================================+
|                                    FLASH ARCHITECTURE (FIXED BOOTLOADER)                          |
|                                                                                                   |
|  PRIMARY TARGET: STM32G474RE (512 KB Dual-Bank Flash, Symmetric 200 KB App Slots)                 |
|  - Bank 1 (256 KB, Pages 0-127, Addr 0x0800_0000) + Bank 2 (256 KB, Pages 0-127, Addr 0x0804_0000)|
|  - Page Size: Uniform 2 KB per page (256 pages total across two banks)                            |
|  - Symmetric Dual-Bank Layout: Slot A (200 KB) and Slot B (200 KB)                                |
|  - Fixed Base Bootloader: Executes from 0x0800_0000, validates metadata, jumps to active slot     |
+===================================================================================================+
```

---

## 2. Symmetric Flash Memory Partitioning Maps

### 2.1 Primary Target: STM32G474RE Symmetric Memory Map (512 KB)

```
0x0800_0000 +-------------------------------------------------------+
            | BANK 1: PRIMARY BANK (256 KB - Pages 0 to 127)        |
            |                                                       |
            | Pages 0 - 15   (32 KB)  : Fixed Immutable Bootloader  |
            | Pages 16 - 115 (200 KB) : Application Slot A          |
            | Pages 116 - 123 (16 KB) : NVRAM System Configuration  |
            | Pages 124 - 127 (8 KB)  : Public Key Verification Reg |
0x0804_0000 +-------------------------------------------------------+
            | BANK 2: SECONDARY BANK (256 KB - Pages 0 to 127)      |
            |                                                       |
            | Pages 0 - 99   (200 KB) : Application Slot B          |
            |                           (Symmetric Staging/Active)  |
            | Pages 100 - 115 (32 KB) : Diagnostic & Fault Event Log|
            | Pages 116 - 127 (24 KB) : Power-Loss Safe Metadata    |
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
    uint32_t payload_crc32;      /* CRC-32 calculated over bytes 0 to (sizeof - 8) */
    uint32_t commit_marker;      /* 0xAA55AA55 written LAST as atomic commit marker */
} __attribute__((packed)) BootMetadataRecord_t;
```

* **Atomic Verification Rule:** The bootloader verifies `commit_marker == 0xAA55AA55` AND `payload_crc32 == CRC32(record[0..offset_of_crc])`. If a power cut occurred before the commit marker was written, the record is discarded and the previous valid double-buffered record is loaded.

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
5. If crash or watchdog trip occurs before confirmation: System reboots. Bootloader reads `Slot_State == TESTING` and increments `Boot_Attempts` ($1 \to 2 \to 3$).
6. Upon `Boot_Attempts >= 3`: Bootloader marks `Slot_State = SLOT_INVALID`, rolls back to the previous confirmed slot, and logs diagnostic alarm.
