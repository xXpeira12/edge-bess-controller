# Multi-Tier Fault Handling & Functional Safety Architecture

**Document:** `docs/architecture/fault_handling_and_safety.md`  
**Related SRS IDs:** `REQ-SAFE-001` through `REQ-SAFE-006`, `REQ-SEC-001` through `REQ-SEC-003`

---

## 1. Single Source of Truth: Protection Tiers & Safety Invariants

This document is the authoritative **Single Source of Truth** for the multi-tier protection framework, Tier-0 hardware latency budgets, fault classifications, IEC 60730 diagnostic self-tests, and ISO 21434 boot authenticity concepts.

```
+===================================================================================================+
|                                    SAFETY & PROTECTION LAYERS                                     |
|                                                                                                   |
|  +---------------------------------------------------------------------------------------------+  |
|  | TIER 0: SILICON HARDWARE BREAK (Autonomous, <= 2.0 microseconds total path)                 |  |
|  | - Over-Current: |I| > 5.0A (0.650V / 2.650V) or Over-Voltage: V_bus > 26.0V                  |  |
|  | - Internal COMP1/COMP2 -> HRTIM_FAULT / TIM1_BKIN -> Hardware PWM Disable                   |  |
|  | - Latency: 485 ns worst-case total path (<< 2.0 us budget). Latched in silicon.            |  |
|  +---------------------------------------------------------------------------------------------+  |
|                                                |                                                  |
|                                                v                                                  |
|  +---------------------------------------------------------------------------------------------+  |
|  | TIER 1: SOFTWARE EMERGENCY SUPERVISOR (Emergency Ramp-Down at 100 A/s)                      |  |
|  | - Soft Limits (|I| > 4.0A, T > 65C, UVLO < 9.5V, IPC Timeout > 500ms)                       |  |
|  | - Controlled current ramp-down to 0A in <= 50 ms (100 A/s deceleration rate)                |  |
|  | - Orderly PWM software disable and transition to IDLE                                       |  |
|  +---------------------------------------------------------------------------------------------+  |
|                                                |                                                  |
|                                                v                                                  |
|  +---------------------------------------------------------------------------------------------+  |
|  | TIER 2: NORMAL OPERATION RAMPING (Commanded Setpoints, 2.0 A/s Slew Rate)                    |  |
|  | - Normal start/stop and setpoint tracking (2 mA per 1 ms FSM supervisory tick)               |  |
|  +---------------------------------------------------------------------------------------------+  |
+===================================================================================================+
```

### 1.1 Fundamental Safety Invariants
1. **Zero Direct PWM Modbus Access:** No remote Modbus client can write directly to PWM duty cycle or timer control registers.
2. **Explicit Restart Requirement:** Clearing a fault (via `FAULT_CLEAR_CMD = 0x00A5`) transitions the system `SAFE_STATE` $\to$ `STATE_RECOVERY_CHECK` $\to$ `STATE_IDLE`. The system **shall never automatically resume power conversion** without receiving a new explicit `START` command (`SYS_CONTROL_CMD = 1` or `2`).
3. **Silicon Independence:** Tier-0 hardware protection functions autonomously even if the CPU core is crashed, locked in an NMI/HardFault loop, or servicing interrupts.

---

## 2. Tier 0 Hardware Protection Latency Breakdown

```
  Current Sense Amp (INA240) ----> COMP1 In+ \
                                               Comparator Trip ----> HRTIM/TIM1 Break (BKIN)
  DAC1 Output (2.650V/0.650V) ---> COMP1 In- /                             |
                                                                           v
  Voltage Buffer (Divider) ------> COMP2 In+ \                     [ Dead-Time Generator ]
                                               Comparator Trip ----> [ Output Disable ]
  DAC2 Output (26.0V Thresh) ----> COMP2 In- /                             |
                                                                           v
                                                               [ PWM1H, PWM1L -> LOW ]
                                                               [ Latched In Silicon  ]
```

### 2.1 Complete Latency Budget Table ($\le 2.0\,\mu\text{s}$)

| Component Stage | Parameter Symbol | Typical Delay | Worst-Case Delay | Source / Categorization | Remarks |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Shunt Parasitic Time** | $T_{shunt}$ | $5\text{ ns}$ | $10\text{ ns}$ | **Calculated** ($L/R$ time constant) | Low-inductance 2512 SMD shunt ($< 0.1\text{ nH}$) |
| **Current Sense Amp** | $T_{AFE}$ | $200\text{ ns}$ | $250\text{ ns}$ | **Datasheet-Guaranteed** | INA240 small-signal step response to $90\%$ |
| **Internal Comparator** | $T_{comparator}$ | $16\text{ ns}$ | $25\text{ ns}$ | **Datasheet-Guaranteed** | STM32G4 fast comparator high-speed mode |
| **MCU Break Logic & Matrix**| $T_{MCU\_break}$ | $30\text{ ns}$ | $50\text{ ns}$ | **Datasheet-Guaranteed** | Internal analog matrix + HRTIM asynchronous fault kill |
| **Gate Driver Propagation**| $T_{gate\_driver}$ | $30\text{ ns}$ | $50\text{ ns}$ | **Datasheet-Guaranteed** | UCC27211 propagation delay ($t_{pHL}$) |
| **Power Stage MOSFET** | $T_{power\_stage}$| $60\text{ ns}$ | $100\text{ ns}$ | **Bench-Measured / Datasheet** | $t_{d(off)} + t_f$ fall time with $10\,\Omega$ gate pull-down |
| **TOTAL TRIP LATENCY** | $T_{total\_trip}$ | $\mathbf{341\text{ ns}}$ | $\mathbf{485\text{ ns}}$ | **Combined Latency Budget** | **$\ll 2.0\,\mu\text{s}$ Maximum Requirement Boundary** |

---

## 3. Multi-Level Fault Handling Framework

| Fault ID | Level | Trigger Condition | System Response Action | Clearing & Recovery Mechanism |
| :--- | :--- | :--- | :--- | :--- |
| `FLT_TEMP_WARN` | **WARNING** | $55^\circ\text{C} \le T \le 65^\circ\text{C}$ | Set bit 2 in `40005`; linear current derating ($100\%$ at $55^\circ\text{C} \to 50\%$ at $65^\circ\text{C}$). | Auto-clears when $T < 50^\circ\text{C}$ for $> 5.0\text{ s}$. |
| `FLT_SOC_LOW` | **WARNING** | $10\% \le \text{SOC} \le 15\%$ | Set bit 3 in `40005`; clamp discharge current to $1.0\text{ A}$. | Auto-clears when $\text{SOC} > 18\%$. |
| `FLT_SPI_CRC` | **WARNING** | Single dropped CRC frame | Set bit 4 in `40005`; issue ARQ retransmit request; increment drop counter. | Auto-clears on next valid packet. |
| `FLT_IPC_TIMEOUT`| **FAULT** | $\ge 3$ retries fail / silence $> 500\text{ ms}$ | **Emergency ramp-down at $100\text{ A/s}$**; disable PWM; transition to `IDLE`. | Requires IPC link sync and Modbus `40014 = 0x00A5`. |
| `FLT_SOFT_OC` | **FAULT** | $|I| > 4.0\text{ A}$ for $\ge 5$ cycles | **Emergency ramp-down at $100\text{ A/s}$**; disable PWM; transition to `IDLE`. | Write `0x00A5` to `40014` after $|I| < 0.5\text{ A}$. |
| `FLT_SOFT_OT` | **FAULT** | $T > 65^\circ\text{C}$ | **Emergency ramp-down at $100\text{ A/s}$**; disable PWM; transition to `IDLE`. | Write `0x00A5` to `40014` after $T < 45^\circ\text{C}$. |
| `FLT_UVLO` | **FAULT** | $V_{bat} < 9.5\text{ V}$ or $V_{bus} < 16.0\text{ V}$ | **Emergency ramp-down at $100\text{ A/s}$**; transition to `IDLE`. | Voltage restored $> 11.0\text{ V}$ + write `0x00A5` to `40014`. |
| `FLT_HARD_OC` | **CRITICAL** | $|I| > 5.0\text{ A}$ ($0.650\text{V} / 2.650\text{V}$) | **Tier 0:** Hardware break input forces PWM LOW $\le 2.0\,\mu\text{s}$; latches `SAFE_STATE`. | Write `0x00A5` to `40014` $\to$ `RECOVERY_CHECK` $\to$ `IDLE`. |
| `FLT_HARD_OV` | **CRITICAL** | $V_{bus} > 26.0\text{ V}$ peak | **Tier 0:** Hardware break input forces PWM LOW $\le 2.0\,\mu\text{s}$; latches `SAFE_STATE`. | Write `0x00A5` to `40014` $\to$ `RECOVERY_CHECK` $\to$ `IDLE`. |
| `FLT_IEC_REG` | **CRITICAL** | CPU Register stuck-at bit | Execution trapped in endless while loop; PWM forced LOW; `SAFE_STATE`. | Power-on cold reboot required. |
| `FLT_IEC_RAM` | **CRITICAL** | SRAM pattern mismatch | Timer Break triggered; state machine enters `SAFE_STATE`; error log written. | Power-on cold reboot required. |
| `FLT_IEC_FLASH` | **CRITICAL** | Flash CRC $\ne$ Golden CRC | Bootloader aborts jump to application; boots into recovery staging mode. | Reflash valid authenticated image. |
| `FLT_WATCHDOG` | **CRITICAL** | Refresh window violation ($<40\text{ms}$ or $>60\text{ms}$) | Hardware reset triggered by microcontroller watchdog unit. | MCU Reset Vector. |
| `FLT_CSS_CLOCK` | **CRITICAL** | HSE 8 MHz crystal failure | CSS NMI asserts; Timer Break triggers; clock fails over to HSI 16MHz; `SAFE_STATE`. | Physical crystal inspection & restart. |

---

## 4. IEC 60730 Class B-Oriented Diagnostic Routines

```c
/* CPU Register Test (Cortex-M4 Specific) */
bool Safety_TestCPURegisters(void)
{
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
```

---

## 5. ISO 21434 Cybersecurity Concept (PoC Scope)

* **Cryptographic Signing:** Images signed with SHA-256 + ECDSA (secp256r1).
* **On-Chip Key Store:** Holds public verification key only (never private signing keys).
* **Monotonic Anti-Rollback:** $\text{Image\_Security\_Version} \ge \text{NVRAM\_Monotonic\_Counter}$.
