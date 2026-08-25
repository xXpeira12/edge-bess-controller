# Flash Memory Partitioning & Secure Bootloader Architecture

**Document:** `docs/architecture/flash_memory_partitioning.md`  
**Related SRS IDs:** `REQ-SEC-001`, `REQ-SEC-002`, `REQ-SEC-003`

---

## 1. Single Source of Truth: Memory Geometry & Fixed Bootloader Architecture

This document is the authoritative **Single Source of Truth** for Flash memory partitioning, symmetric slot geometries, power-loss-safe metadata formats, confirmed boot sequences, SRAM flash driver execution, and public key management.

```
+===================================================================================================+
|                                    FLASH ARCHITECTURE (FIXED BOOTLOADER)                          |
|                                                                                                   |
|  PRIMARY TARGET: STM32G474RE (512 KB Dual-Bank Flash, Symmetric 200 KB App Slots)                 |
|  - Bank 1 (256 KB, Pages 0-127, Addr 0x0800_0000) + Bank 2 (256 KB, Pages 0-127, Addr 0x0804_0000)|
|  - Page Size: Uniform 2 KB per page (256 pages total across two banks)                            |
|  - Symmetric Dual-Bank Layout: Slot A (200 KB) and Slot B (200 KB)                                |
|  - SRAM Driver Execution: Flash routines execute from RAM via __attribute__((section(".ramfunc")))|
|  - Hardware Protection: Flash Write Protection (WRP) on Pages 120-127 & Readout Protection (RDP)  |
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
            | * Pages 120-127 Protected by Flash WRP & RDP Level 1   |
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

## 3. SRAM Execution & Dual-Bank Read-While-Write (RWW)

* **SRAM Driver Routine Execution:** All low-level Flash write and erase functions are linked into SRAM:
  ```c
  __attribute__((section(".ramfunc"), noinline))
  HAL_StatusTypeDef Flash_ErasePage_SRAM(uint32_t page_address);
  ```
* **Zero CPU Stall Dual-Bank Updating:** While the CPU executes real-time power control code from Application Slot A in Bank 1, the bootloader/application can erase and program staging blocks in Bank 2 without blocking the Cortex-M4 instruction pipeline or missing $50\text{ kHz}$ control loop interrupts.

---

## 4. Power-Loss Safe Metadata Record Structure

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

---

## 5. Confirmed Boot Sequence & Automatic Rollback

* **Maximum 3 Boot Attempts:** Application is given a maximum of 3 boot attempts ($1 \to 2 \to 3$). If a watchdog reset or crash occurs before safety initialization writes `CONFIRMED`, automatic rollback to the previous confirmed slot triggers before the 4th attempt.
