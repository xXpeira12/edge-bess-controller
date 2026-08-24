# Multi-Tier Fault Handling & Functional Safety Architecture

**Document:** `docs/architecture/fault_handling_and_safety.md`  
**Related SRS IDs:** `REQ-SAFE-001` through `REQ-SAFE-006`, `REQ-SEC-001` through `REQ-SEC-003`

---

## 1. Safety Architecture Philosophy

The BESS controller safety architecture enforces a strict **Defense-in-Depth** paradigm separating instantaneous silicon hardware protection from intelligent, software-guided supervisory protection.

```
+===================================================================================================+
|                                    SAFETY & PROTECTION LAYERS                                     |
|                                                                                                   |
|  +---------------------------------------------------------------------------------------------+  |
|  | TIER 0: SILICON HARDWARE BREAK (Autonomous, <= 2.0 microseconds)                             |  |
|  | - Analog Over-Current (I > 5.0A)                                                            |  |
|  | - Analog Over-Voltage (V > 26.0V)                                                           |  |
|  | - Direct Comparator -> TIM1_BKIN / HRTIM_FAULT -> Gate Driver Inhibit                        |  |
|  | - Zero CPU Dependency, Zero Interrupt Jitter, Hardware Latched                              |  |
|  +---------------------------------------------------------------------------------------------+  |
|                                                |                                                  |
|                                                v                                                  |
|  +---------------------------------------------------------------------------------------------+  |
|  | TIER 1: SOFTWARE INNER-LOOP SUPERVISOR (20 us - 1 ms)                                       |  |
|  | - Soft Current/Voltage Saturation Clamping                                                  |  |
|  | - Plausibility checks, Rate-of-change (dI/dt, dV/dt) limiters                               |  |
|  | - Controlled soft current ramp-down (dI/dt <= 2.0 A/s)                                      |  |
|  +---------------------------------------------------------------------------------------------+  |
|                                                |                                                  |
|                                                v                                                  |
|  +---------------------------------------------------------------------------------------------+  |
|  | TIER 2: SYSTEM LEVEL & DIAGNOSTICS (10 ms - 100 ms)                                         |  |
|  | - IEC 60730 Class B-Oriented Diagnostics (RAM March C-, Flash CRC, Regs)                    |  |
|  | - Window Watchdog (IWDG: 50ms +/- 10ms) & Clock Security System (CSS)                      |  |
|  | - Dynamic Thermal & SOC Derating Management                                                 |  |
|  | - FreeRTOS Task Watchdog Timer (TWDT) & IPC Heartbeat Monitor                               |  |
|  +---------------------------------------------------------------------------------------------+  |
+===================================================================================================+
```

---

## 2. Hardware Protection Layer (Tier 0 - Silicon Autonomous)

### 2.1 Circuit Interconnect & Operation
The Tier 0 hardware layer protects switching MOSFETs and inductors against shoot-through, inductive flashover, and catastrophic short circuits.

```
  Current Sense Amp (INA240) ----> COMP1 In+ \
                                               Comparator Trip ----> TIM1 Break (BKIN)
  DAC1 Output (5.0A Threshold) --> COMP1 In- /                             |
                                                                           v
  Voltage Buffer (Divider) ------> COMP2 In+ \                     [ Dead-Time Generator ]
                                               Comparator Trip ----> [ Output Disable ]
  DAC2 Output (26.0V Thresh) ----> COMP2 In- /                             |
                                                                           v
                                                               [ PWM1H, PWM1L -> LOW ]
                                                               [ Latched In Silicon  ]
```

* **Reaction Time:** $\le 2.0\,\mu\text{s}$ (Typical internal comparator propagation delay: $16\text{ ns}$ + timer break logic: $50\text{ ns} = \approx 66\text{ ns}$).
* **Hardware Lockout:** When `BKIN` is asserted:
  - Timer output channels `CH1` and `CH1N` are immediately driven to their inactive programmed level (`GPIO_PIN_RESET` / High-Z).
  - The Break Status Flag (`TIM_SR_BIF` or `HRTIM_ISR_FLTx`) is set in hardware.
  - Software cannot re-enable PWM outputs without completing the formal safe recovery sequence.

---

## 3. Multi-Level Fault Classification & Handling Matrix

All potential abnormal events are categorized into three severity tiers:

```
                  +-------------------------------------------------+
                  |          LEVEL 3: CRITICAL HARDWARE FAULT       |
                  |  - Instant Tier-0 Break Trip (<= 2.0 us)        |
                  |  - Relays Tripped, State -> SAFE_STATE          |
                  |  - Power-cycle or Authenticated Reset required  |
                  +-------------------------------------------------+
                                           ^
                                           | Escalates on hardware limit breach
                  +-------------------------------------------------+
                  |          LEVEL 2: SYSTEM / SOFTWARE FAULT       |
                  |  - Controlled Current Ramp-Down (dI/dt <= 2A/s) |
                  |  - PWM Soft-Stop, State -> IDLE                 |
                  |  - Diagnostic Clear Command Required            |
                  +-------------------------------------------------+
                                           ^
                                           | Escalates on persistent condition
                  +-------------------------------------------------+
                  |          LEVEL 1: WARNING / ADAPTIVE DERATING   |
                  |  - Dynamic Power / Current Setpoint Clamping    |
                  |  - Modbus Register 40005 Flag Set               |
                  |  - Continuous Operation Maintained              |
                  +-------------------------------------------------+
```

### 3.1 Detailed Fault Handling Matrix

| Fault ID | Level | Detection Source | Threshold / Criteria | System Response Action | Clearing & Recovery Mechanism |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `FLT_TEMP_WARN` | **WARNING** | NTC ADC Channel | $55^\circ\text{C} \le T \le 65^\circ\text{C}$ | Set bit 2 in `40005`; throttle current setpoint $I_{ref}$ linearly ($100\%$ at $55^\circ\text{C}$, $50\%$ at $65^\circ\text{C}$). | Auto-clears when temperature drops $< 50^\circ\text{C}$ for $> 5\text{ s}$. |
| `FLT_SOC_LOW` | **WARNING** | BMS CAN / OCV | $10\% \le \text{SOC} \le 15\%$ | Set bit 3 in `40005`; clamp discharge current to $1.0\text{ A}$. | Auto-clears when $\text{SOC} > 18\%$. |
| `FLT_SPI_CRC` | **WARNING** | IPC SPI DMA | Single dropped CRC frame | Set bit 4 in `40005`; issue ARQ retransmit request; increment drop counter. | Auto-clears on next valid packet. |
| `FLT_IPC_TIMEOUT`| **FAULT** | IPC Master/Slave | $\ge 3$ retry failures or silence $> 500\text{ ms}$ | Execute controlled soft-ramp down to $0\text{ A}$ within $50\text{ ms}$; disable PWM; transition to `IDLE`. | Requires IPC link sync and Modbus `40001 = 0xFF`. |
| `FLT_SOFT_OC` | **FAULT** | ADC Current Sample | $I > 4.2\text{ A}$ for $\ge 5$ consecutive cycles | Ramp $I_{ref} \to 0\text{ A}$; disable PWM; transition to `IDLE`. | Host clear command after $I < 0.5\text{ A}$. |
| `FLT_SOFT_OT` | **FAULT** | NTC ADC Channel | $T > 65^\circ\text{C}$ | Ramp $I_{ref} \to 0\text{ A}$; disable PWM; transition to `IDLE`; fan max. | Host clear command after $T < 45^\circ\text{C}$. |
| `FLT_UVLO` | **FAULT** | ADC Voltage Sample | $V_{bat} < 9.5\text{ V}$ or $V_{bus} < 16.0\text{ V}$ | Ramp down current; disable PWM; transition to `IDLE`. | Voltage restored $> 11.0\text{ V}$ + host clear. |
| `FLT_PLAUS_ADC` | **FAULT** | Dual ADC Channels | $|V_{sense1} - V_{sense2}| > 1.5\text{ V}$ | Disable PWM immediately; transition to `IDLE`. | System re-initialization + host clear. |
| `FLT_HARD_OC` | **CRITICAL** | Analog Comparator 1 | $I > 5.0\text{ A}$ peak | **Tier 0:** Hardware break input forces PWM LOW $\le 2.0\,\mu\text{s}$; latches `SAFE_STATE`. | Diagnostic verification + Manual reboot / reset command. |
| `FLT_HARD_OV` | **CRITICAL** | Analog Comparator 2 | $V_{bus} > 26.0\text{ V}$ peak | **Tier 0:** Hardware break input forces PWM LOW $\le 2.0\,\mu\text{s}$; latches `SAFE_STATE`. | Diagnostic verification + Manual reboot / reset command. |
| `FLT_IEC_REG` | **CRITICAL** | Boot Self-Test | CPU Register stuck-at bit | Execution trapped in endless while loop; PWM forced LOW; `SAFE_STATE`. | Power-on cold boot. |
| `FLT_IEC_RAM` | **CRITICAL** | March C- Sliced Test | SRAM pattern mismatch | Timer Break triggered; state machine enters `SAFE_STATE`; error log written. | Power-on cold boot. |
| `FLT_IEC_FLASH` | **CRITICAL** | Hardware CRC Unit | Flash CRC $\ne$ Golden CRC | Bootloader aborts jump to application; boots into recovery staging mode. | Re-flash valid authenticated image. |
| `FLT_WATCHDOG` | **CRITICAL** | Hardware IWDG | Refresh window violation ($<40\text{ms}$ or $>60\text{ms}$) | Hardware reset triggered by microcontroller watchdog unit. | MCU Reset Vector. |
| `FLT_CSS_CLOCK` | **CRITICAL** | Clock Security System | HSE 8 MHz crystal failure | CSS NMI asserts; Timer Break triggers; clock fails over to HSI 16MHz; `SAFE_STATE`. | Physical crystal inspection & restart. |

---

## 4. IEC 60730 Class B-Oriented Safety Diagnostic Routines

```c
/* ==========================================================================
 * IEC 60730 Class B Diagnostic Implementations (PoC Reference)
 * ========================================================================== */

/* 1. CPU Register Test (Pre-Execution Destructive Pattern Test) */
bool Safety_TestCPURegisters(void)
{
    /* Test pattern 0x55555555 and 0xAAAAAAAA across R0-R12 */
    __asm volatile (
        "movs r0, #0x55555555\n"
        "cmp  r0, #0x55555555\n"
        "bne  .L_cpu_fail\n"
        "movs r0, #0xAAAAAAAA\n"
        "cmp  r0, #0xAAAAAAAA\n"
        "bne  .L_cpu_fail\n"
        // ... (repeated for R1 through R12, LR)
        "movs r0, #1\n"
        "bx lr\n"
        ".L_cpu_fail:\n"
        "movs r0, #0\n"
        "bx lr\n"
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
Every firmware image compiled for either the Control Core or Gateway Core contains an immutable 256-byte header:

```c
typedef struct {
    uint32_t image_magic;          /* 0x42455353 ("BESS") */
    uint32_t header_version;       /* 0x00010000 (v1.0) */
    uint32_t security_version;     /* Monotonic counter for anti-rollback */
    uint32_t target_mcu;           /* 0x01: STM32G4, 0x02: STM32F4, 0x03: ESP32 */
    uint32_t image_size_bytes;     /* Payload size in bytes */
    uint32_t entry_point_addr;     /* Reset vector execution address */
    uint8_t  sha256_digest[32];    /* SHA-256 hash of image payload */
    uint8_t  hmac_signature[32];   /* HMAC-SHA256 authentication tag */
    uint8_t  reserved[172];        /* Future cryptographic extensions */
} __attribute__((packed)) FirmwareHeader_t;
```

### 5.2 Anti-Rollback Enforcement
Before any staging image is written to operational flash or swapped:
1. Bootloader reads active monotonic security counter $V_{active}$ stored in NVRAM sector.
2. Staging image header counter $V_{staged}$ is compared.
3. If $V_{staged} < V_{active}$, update is rejected with security error code `0xSEC_ROLLBACK_DETECTED` and staging partition is erased.
