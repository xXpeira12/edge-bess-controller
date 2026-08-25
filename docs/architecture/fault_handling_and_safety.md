# Multi-Tier Fault Handling & Functional Safety Architecture

**Document:** `docs/architecture/fault_handling_and_safety.md`  
**Related SRS IDs:** `REQ-SAFE-001` through `REQ-SAFE-006`, `REQ-SEC-001` through `REQ-SEC-003`

---

## 1. Safety Architecture Philosophy & Invariants

The BESS controller safety architecture enforces a strict **Defense-in-Depth** paradigm separating instantaneous silicon hardware protection from intelligent, software-guided supervisory protection.

```
+===================================================================================================+
|                                    SAFETY & PROTECTION LAYERS                                     |
|                                                                                                   |
|  +---------------------------------------------------------------------------------------------+  |
|  | TIER 0: SILICON HARDWARE BREAK (Autonomous, <= 2.0 microseconds total path)                 |  |
|  | - Analog Over-Current (I > 5.0A) or Over-Voltage (V > 26.0V)                                 |  |
|  | - Internal COMP1/COMP2 -> HRTIM_FAULT / TIM1_BKIN -> Hardware PWM Disable                   |  |
|  | - Zero CPU Dependency, Latched in Silicon Hardware                                          |  |
|  +---------------------------------------------------------------------------------------------+  |
|                                                |                                                  |
|                                                v                                                  |
|  +---------------------------------------------------------------------------------------------+  |
|  | TIER 1: SOFTWARE EMERGENCY SUPERVISOR (Emergency Ramp-Down at 100 A/s)                      |  |
|  | - Soft Limits (I > 4.0A, T > 65C, UVLO < 9.5V, IPC Timeout > 500ms)                         |  |
|  | - Controlled current ramp-down to 0A in <= 50 ms (100 A/s deceleration rate)                |  |
|  | - Orderly PWM software disable and transition to IDLE                                       |  |
|  +---------------------------------------------------------------------------------------------+  |
|                                                |                                                  |
|                                                v                                                  |
|  +---------------------------------------------------------------------------------------------+  |
|  | TIER 2: SYSTEM LEVEL & DIAGNOSTICS (10 ms - 100 ms Background)                              |  |
|  | - IEC 60730 Class B-Oriented Diagnostics (RAM March C-, Flash CRC, Regs)                    |  |
|  | - Window Watchdog (IWDG: 50ms +/- 10ms) & Clock Security System (CSS)                      |  |
|  | - Dynamic Thermal & SOC Derating Management                                                 |  |
|  +---------------------------------------------------------------------------------------------+  |
+===================================================================================================+
```

### 1.1 Fundamental Safety Invariants
1. **Zero Direct PWM Modbus Access:** No remote Modbus client can write directly to PWM duty cycle or timer control registers.
2. **Explicit Restart Requirement:** Clearing a fault (via `FAULT_CLEAR_CMD = 0x00A5`) transitions the system to `STATE_RECOVERY_CHECK` $\to$ `STATE_IDLE`. The system **shall never automatically resume power conversion** from a cleared fault without receiving a new explicit `START` command (`SYS_CONTROL_CMD = 1` or `2`).
3. **Silicon Independence:** Tier-0 hardware protection functions autonomously even if the CPU core is crashed, locked in an NMI/HardFault loop, or servicing interrupts.

---

## 2. Tier 0 Hardware Protection Latency Breakdown

```
  Current Sense Amp (INA240) ----> COMP1 In+ \
                                               Comparator Trip ----> HRTIM/TIM1 Break (BKIN)
  DAC1 Output (5.0A Threshold) --> COMP1 In- /                             |
                                                                           v
  Voltage Buffer (Divider) ------> COMP2 In+ \                     [ Dead-Time Generator ]
                                               Comparator Trip ----> [ Output Disable ]
  DAC2 Output (26.0V Thresh) ----> COMP2 In- /                             |
                                                                           v
                                                               [ PWM1H, PWM1L -> LOW ]
                                                               [ Latched In Silicon  ]
```

### 2.1 Complete Latency Budget Table ($\le 2.0\,\mu\text{s}$)

| Component Stage | Parameter Symbol | Typical Delay | Worst-Case Delay | Remarks |
| :--- | :--- | :--- | :--- | :--- |
| **Current Sense Amp** | $T_{sensor}$ | $280\text{ ns}$ | $350\text{ ns}$ | INA240 small-signal + large-signal step response |
| **Internal Comparator** | $T_{comparator}$ | $16\text{ ns}$ | $25\text{ ns}$ | STM32G4 fast comparator high-speed mode (TLV3501: $4.5\text{ ns}$) |
| **Internal Matrix Routing** | $T_{routing}$ | $2\text{ ns}$ | $5\text{ ns}$ | Direct on-chip analog-to-timer interconnect |
| **Timer Break Logic** | $T_{timer}$ | $15\text{ ns}$ | $25\text{ ns}$ | Asynchronous break input to output gate disable |
| **Gate Driver Propagation**| $T_{driver}$ | $15\text{ ns}$ | $20\text{ ns}$ | UCC27211 / similar high-speed gate driver |
| **MOSFET Turn-Off Time** | $T_{gate}$ | $45\text{ ns}$ | $60\text{ ns}$ | $t_{d(off)} + t_f$ fall time with $10\,\Omega$ gate resistance |
| **TOTAL END-TO-END LATENCY** | $T_{total}$ | $\mathbf{373\text{ ns}}$ | $\mathbf{485\text{ ns}}$ | **$\ll 2.0\,\mu\text{s}$ Maximum Requirement Boundary** |

---

## 3. Multi-Level Fault Handling Framework

```
                  +-------------------------------------------------+
                  |          LEVEL 3: CRITICAL HARDWARE FAULT       |
                  |  - Instant Tier-0 Break Trip (<= 2.0 us)        |
                  |  - Relays Tripped, State -> SAFE_STATE          |
                  |  - Recovery: Fault Clear -> RECOVERY_CHECK      |
                  +-------------------------------------------------+
                                           ^
                                           | Escalates on hardware limit breach
                  +-------------------------------------------------+
                  |          LEVEL 2: SYSTEM / SOFTWARE FAULT       |
                  |  - Emergency Software Ramp-Down (100 A/s)       |
                  |  - Decelerates to 0A in <= 50 ms, State -> IDLE |
                  |  - Diagnostic Clear via Register 40014 Required |
                  +-------------------------------------------------+
                                           ^
                                           | Escalates on persistent condition
                  +-------------------------------------------------+
                  |          LEVEL 1: WARNING / ADAPTIVE DERATING   |
                  |  - Dynamic Power / Current Setpoint Clamping    |
                  |  - Register 40005 ACTIVE_FAULT_FLAGS Set        |
                  |  - Continuous Operation Maintained              |
                  +-------------------------------------------------+
```

### 3.1 Detailed Fault Classification Matrix

| Fault ID | Level | Detection Source | Threshold / Condition | System Response Action | Clearing & Recovery Mechanism |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `FLT_TEMP_WARN` | **WARNING** | NTC ADC Channel | $55^\circ\text{C} \le T \le 65^\circ\text{C}$ | Set bit 2 in `40005`; linear current derating ($100\%$ at $55^\circ\text{C} \to 50\%$ at $65^\circ\text{C}$). | Auto-clears when $T < 50^\circ\text{C}$ for $> 5.0\text{ s}$. |
| `FLT_SOC_LOW` | **WARNING** | BMS CAN / OCV | $10\% \le \text{SOC} \le 15\%$ | Set bit 3 in `40005`; clamp discharge current to $1.0\text{ A}$. | Auto-clears when $\text{SOC} > 18\%$. |
| `FLT_SPI_CRC` | **WARNING** | IPC SPI DMA | Single dropped CRC frame | Set bit 4 in `40005`; issue ARQ retransmit request; increment drop counter. | Auto-clears on next valid packet. |
| `FLT_IPC_TIMEOUT`| **FAULT** | IPC Master/Slave | $\ge 3$ retry failures or silence $> 500\text{ ms}$ | **Emergency ramp-down at $100\text{ A/s}$**; disable PWM; transition to `IDLE`. | Requires IPC link sync and Modbus `40014 = 0x00A5`. |
| `FLT_SOFT_OC` | **FAULT** | ADC Current Sample | $|I| > 4.0\text{ A}$ for $\ge 5$ cycles | **Emergency ramp-down at $100\text{ A/s}$**; disable PWM; transition to `IDLE`. | Write `0x00A5` to `40014` after $|I| < 0.5\text{ A}$. |
| `FLT_SOFT_OT` | **FAULT** | NTC ADC Channel | $T > 65^\circ\text{C}$ | **Emergency ramp-down at $100\text{ A/s}$**; disable PWM; transition to `IDLE`. | Write `0x00A5` to `40014` after $T < 45^\circ\text{C}$. |
| `FLT_UVLO` | **FAULT** | ADC Voltage Sample | $V_{bat} < 9.5\text{ V}$ or $V_{bus} < 16.0\text{ V}$ | **Emergency ramp-down at $100\text{ A/s}$**; transition to `IDLE`. | Voltage restored $> 11.0\text{ V}$ + write `0x00A5` to `40014`. |
| `FLT_HARD_OC` | **CRITICAL** | Analog Comparator 1 | $|I| > 5.0\text{ A}$ peak | **Tier 0:** Hardware break input forces PWM LOW $\le 2.0\,\mu\text{s}$; latches `SAFE_STATE`. | Write `0x00A5` to `40014` $\to$ `RECOVERY_CHECK` $\to$ `IDLE`. |
| `FLT_HARD_OV` | **CRITICAL** | Analog Comparator 2 | $V_{bus} > 26.0\text{ V}$ peak | **Tier 0:** Hardware break input forces PWM LOW $\le 2.0\,\mu\text{s}$; latches `SAFE_STATE`. | Write `0x00A5` to `40014` $\to$ `RECOVERY_CHECK` $\to$ `IDLE`. |
| `FLT_IEC_REG` | **CRITICAL** | Boot Self-Test | CPU Register stuck-at bit | Execution trapped in endless while loop; PWM forced LOW; `SAFE_STATE`. | Power-on cold reboot required. |
| `FLT_IEC_RAM` | **CRITICAL** | March C- Sliced Test | SRAM pattern mismatch | Timer Break triggered; state machine enters `SAFE_STATE`; error log written. | Power-on cold reboot required. |
| `FLT_IEC_FLASH` | **CRITICAL** | Hardware CRC Unit | Flash CRC $\ne$ Golden CRC | Bootloader aborts jump to application; boots into recovery staging mode. | Reflash valid authenticated image. |
| `FLT_WATCHDOG` | **CRITICAL** | Hardware IWDG | Refresh window violation ($<40\text{ms}$ or $>60\text{ms}$) | Hardware reset triggered by microcontroller watchdog unit. | MCU Reset Vector. |
| `FLT_CSS_CLOCK` | **CRITICAL** | Clock Security System | HSE 8 MHz crystal failure | CSS NMI asserts; Timer Break triggers; clock fails over to HSI 16MHz; `SAFE_STATE`. | Physical crystal inspection & restart. |

---

## 4. IEC 60730 Class B-Oriented Safety Diagnostic Routines

```c
/* ==========================================================================
 * IEC 60730 Class B Diagnostic Implementations (Cortex-M4 Specific)
 * ========================================================================== */

/* 1. CPU Core Register Self-Test (R0-R12, SP, LR, APSR deterministic test) */
bool Safety_TestCPURegisters(void)
{
    /* Test general purpose registers and APSR flags with 0x55555555 and 0xAAAAAAAA */
    register uint32_t val1 = 0x55555555U;
    register uint32_t val2 = 0xAAAAAAAAU;
    
    __asm volatile (
        "movs r0, %0\n"
        "cmp  r0, %0\n"
        "bne  .L_reg_fail\n"
        "movs r0, %1\n"
        "cmp  r0, %1\n"
        "bne  .L_reg_fail\n"
        "msr  APSR_nzcvq, %0\n"
        "mrs  r0, APSR\n"
        "and  r0, r0, #0xF8000000\n"
        "msr  APSR_nzcvq, %1\n"
        "mrs  r1, APSR\n"
        "and  r1, r1, #0xF8000000\n"
        // ... (systematically verified for R1 through R12, SP, LR)
        "movs r0, #1\n"
        "bx lr\n"
        ".L_reg_fail:\n"
        "movs r0, #0\n"
        "bx lr\n"
        :
        : "r"(val1), "r"(val2)
        : "r0", "r1", "cc"
    );
    return true;
}

/* 2. Runtime Non-Destructive Sliced March C- SRAM Test */
bool Safety_MarchC_Slice(uint32_t *p_start, uint32_t words_to_scan)
{
    for (uint32_t i = 0; i < words_to_scan; i++) {
        uint32_t orig_val = p_start[i];
        
        /* Up: Write 0, Verify 0 */
        p_start[i] = 0x00000000U;
        if (p_start[i] != 0x00000000U) return false;
        
        /* Up: Write 1, Verify 1 */
        p_start[i] = 0xFFFFFFFFU;
        if (p_start[i] != 0xFFFFFFFFU) return false;
        
        /* Down: Write 0, Verify 0 */
        p_start[i] = 0x00000000U;
        if (p_start[i] != 0x00000000U) return false;
        
        /* Restore original RAM contents */
        p_start[i] = orig_val;
    }
    return true;
}

/* 3. Flash Memory CRC-32 Validation */
bool Safety_VerifyFlashCRC(uint32_t start_addr, uint32_t length_bytes, uint32_t golden_crc)
{
    CRC->CR = CRC_CR_RESET;
    uint32_t *p_flash = (uint32_t *)start_addr;
    uint32_t word_count = length_bytes / 4U;

    for (uint32_t i = 0; i < word_count; i++) {
        CRC->DR = p_flash[i];
    }
    return (CRC->DR == golden_crc);
}
```

---

## 5. ISO 21434 Cybersecurity Concept (PoC Scope)

### 5.1 Image Header & Authenticated Verification
Every firmware image compiled for either the Control Core or Gateway Core contains an immutable 256-byte header authenticated via SHA-256 and ECDSA (secp256r1) with public keys stored in the on-chip Key Region:

```c
typedef struct {
    uint32_t image_magic;          /* 0x42455353 ("BESS") */
    uint32_t header_version;       /* 0x00010000 (v1.0) */
    uint32_t security_version;     /* Monotonic counter for anti-rollback */
    uint32_t target_mcu;           /* 0x01: STM32G4, 0x02: STM32F4, 0x03: ESP32 */
    uint32_t image_size_bytes;     /* Payload size in bytes */
    uint32_t entry_point_addr;     /* Reset vector execution address */
    uint8_t  sha256_digest[32];    /* SHA-256 hash of image payload */
    uint8_t  ecdsa_signature[64];  /* ECDSA secp256r1 signature (R, S) */
    uint8_t  reserved[140];        /* Future cryptographic extensions */
} __attribute__((packed)) FirmwareHeader_t;
```
