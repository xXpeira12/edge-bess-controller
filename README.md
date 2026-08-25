# Industrial Smart BESS & Power Management Controller (Desk-Scale PoC)
## Software Requirements Specification (SRS) & System Architecture Document

**Document Version:** 5.0.0  
**Target Platform:** Dual-MCU Architecture (Real-Time Control Core + Industrial Gateway Core)  
**Primary Control Core MCU (Normative Target):** **STM32G474RE** (ARM Cortex-M4F @ 170 MHz, HRTIM, Fast Internal Comparators, Symmetric Dual-Bank Flash)  
**Secondary / Porting Control Core MCU (Future Target):** **STM32F446RE** (ARM Cortex-M4F @ 168 MHz, TIM1, External Comparator Interconnect)  
**Gateway Core MCU:** **ESP32-WROOM-32** (Dual-Core Xtensa LX6 @ 240 MHz, FreeRTOS Preemptive Kernel)  
**Design Paradigm:** Hard Real-Time Deterministic Control, Multi-Tier Hardware/Software Safety, Non-Blocking Telemetry Isolation  
**PoC Standard Alignment:** IEC 60730 Class B-Oriented Safety Diagnostics & ISO 21434 Cybersecurity Concept  
**Verification Status:** Specification consistency and invariant simulation model verified; hardware physical measurements pending benchtop prototype execution.

---

### Standards & Compliance Disclaimer
> **ENGINEERING NOTICE (PoC Scope):**  
> This specification and associated firmware implement safety and cybersecurity architectural patterns **inspired by IEC 60730 Class B and ISO 21434 concepts** for an experimental desktop-scale prototype ($18-24\text{ V}$ bus, $20-50\text{ W}$). This prototype does not claim formal accredited certification (e.g. UL 1973, UL 9540, IEC 62619, SIL/ASIL ratings). Production deployment requires external physical galvanic isolation, certified hardware interlocks, and formal third-party compliance validation.

---

## 1. Single Source of Truth (SSOT) Architecture Mapping

| Domain | Authoritative SSOT Document | Key SSOT Invariants & Parameters |
| :--- | :--- | :--- |
| **System Overview & Requirements** | `README.md` | Dual-MCU topology, operational envelopes, safety boundaries |
| **Timing, Jitter & Determinism** | `docs/architecture/timing_jitter_and_bench_verification.md` | $f_{sw} = 50\text{ kHz}$, $T_s = 20\,\mu\text{s}$, WCET $5.0\,\mu\text{s}$ (25% load), 4 jitter metrics, DSO vs DWT scope |
| **Analog Front-End & Sensing** | `docs/architecture/hardware_sensing_and_analog_frontend.md` | $R_{shunt}=10\text{ m}\Omega$, INA240A1 ($G=20\text{ V/V}$), $T_{CSA\_cross}=300\text{ns}$, RM0440 pin routing |
| **Safety, Faults & Latency** | `docs/architecture/fault_handling_and_safety.md` | Distinct OC ($491\text{ns}$) & OV ($241\text{ns}$) latency budgets, itemized $\pm 0.15\text{ A}$ tolerance budget |
| **Control Finite State Machine** | `docs/architecture/state_machine.md` | STM32 authoritative FSM, `RECOVERY_CHECK`, emergency ramp fallback, derating hysteresis |
| **Inter-Processor Comm (IPC)** | `docs/architecture/ipc_protocol.md` | Master-Slave SPI, 16-bit `SEQ_NUM`, `SESSION_ID`, 1:1 Modbus alignment, 10 MHz DMA |
| **Modbus SCADA Register Map** | `docs/architecture/modbus_register_map.md` | Registers $40001 - 40018$, mailbox semantics, $0\text{x00A5}$ clear key (SAFE_STATE only), atomic snapshot |
| **Flash Memory & Bootloader** | `docs/architecture/flash_memory_partitioning.md` | Fixed base bootloader, symmetric $200\text{ KB}$ slots, SRAM `.ramfunc` RWW, WRP/RDP |
| **Specification Consistency** | `tests/test_specification_consistency.py` | Automated cross-document mathematical & invariant test assertions |

---

## 2. Hardware Interfaces, Operational Boundaries & Analog Front-End

### 2.1 Operational Boundaries & Itemized Tolerance Budget

| Parameter | Minimum | Nominal | Maximum | Unit | Remarks |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Input Bus Voltage ($V_{bus}$)** | $16.0$ | $24.0$ | $26.0$ | $\text{V}$ | Current-limited benchtop DC supply |
| **Battery Port Voltage ($V_{bat}$)** | $10.0$ | $12.8$ | $14.6$ | $\text{V}$ | 4S LiFePO4 / 3S Li-ion or programmable load |
| **Continuous Power Rating** | $-$ | $30.0$ | $50.0$ | $\text{W}$ | Convection cooled bench scale |
| **Normal Operating Current ($I_{op}$)** | $-3.5$ | $\pm 2.5$ | $+3.5$ | $\text{A}$ | Continuous operational envelope ($0.950\text{ V} \dots 2.350\text{ V}$) |
| **Software Warning Threshold ($I_{warn}$)** | $-4.0$ | $-$ | $+4.0$ | $\text{A}$ | Triggers soft derating / emergency ramp-down ($0.850\text{ V} / 2.450\text{ V}$) |
| **Hardware Emergency Trip ($I_{trip}$)** | $\pm 4.85$ | $\pm 5.0$ | $\pm 5.15$ | $\text{A}$ | Itemized error budget: $\pm 0.15\text{ A}$ ($\pm 3\%$) worst-case |
| **Linear ADC Saturation Limit** | $-8.25$ | $-$ | $+8.25$ | $\text{A}$ | Full scale $0.0\text{ V} \dots 3.3\text{ V}$ ADC range |
| **Hardware Over-Voltage Trip ($V_{trip}$)** | $25.5$ | $26.0$ | $26.5$ | $\text{V}$ | Tier-0 Hardware Break to PWM LOW ($2.600\text{ V}$ threshold) |
| **PWM Switching Frequency ($f_{sw}$)** | $-$ | $50.0$ | $50.0$ | $\text{kHz}$ | Complementary with dead-time |
| **Dead-Time Insertion ($t_{dead}$)** | $250$ | $350$ | $500$ | $\text{ns}$ | Hardware dead-time in HRTIM/TIM1 |

### 2.2 Analog Front-End Topology & OV Fast Trip Separation

```
                                ANALOG SENSING FRONT-END TOPOLOGY
                                
  +------------------------------------------------------------------------------------------------+
  | VOLTAGE SENSING PATH (DC Bus / Battery Terminal)                                               |
  |                                                                                                |
  |  V_BUS (18-24V) ----[ R1: 90k 0.1% ]----+----[ Buffer Op-Amp ]----+-> COMP3 PA0 (Trip: 2.6V)  |
  |                                         |                         |  (Unfiltered Fast Trip)    |
  |                                  [ R2: 10k 0.1% ]                 +-> [ R_filt: 1k ]           |
  |                                         |                             [ C_filt: 3.3nF ]        |
  |                                        GND                            (fc = 48.2 kHz)          |
  |                                                                       v                        |
  |                                                                 MCU ADC Pin (0-3.0V)           |
  +------------------------------------------------------------------------------------------------+

  +------------------------------------------------------------------------------------------------+
  | CURRENT SENSING PATH (Inductor / Battery Bi-Directional Shunt)                                 |
  |                                                                                                |
  |  Power Stage ----[ Shunt: 10 mOhm, 1%, 3W ]----> Inductor                                      |
  |                         |           |                                                          |
  |                         +-----+ +---+                                                          |
  |                               | |                                                              |
  |                    +----------------------+                                                    |
  |                    | INA240A1 CSA         | (Enhanced PWM Rejection, Gain = 20 V/V)            |
  |                    | V_REF = 1.650V       | Transfer Factor: 0.200 V/A                         |
  |                    +----------------------+                                                    |
  |                               | Output: V_out = 1.650V +/- (0.200 V/A * I_L)                   |
  |                               | (-3.5A -> 0.950V, 0A -> 1.650V, +3.5A -> 2.350V)               |
  |                               +------------------------+                                       |
  |                               |                        |                                       |
  |                      [ Low-Pass Filter ]               |                                       |
  |                       R=1k, C=2.2nF (fc~72.3kHz)       | (Unfiltered Fast Trip)                |
  |                               |                        |                                       |
  |                               v                        v                                       |
  |                         MCU ADC Channel         MCU COMP1 / COMP2                              |
  |                     (Synchronous 50 kHz)       (Tier-0 Over-Current Trip)                      |
  |                                                        |                                       |
  |                                                        v                                       |
  |                                              HRTIM1_FLT4 / HRTIM1_FLT1                         |
  |                                            (PWM Forced LOW <= 2.0 us)                          |
  +------------------------------------------------------------------------------------------------+
```

* **Over-Voltage Fast Trip Separation:** The Over-Voltage comparator (`COMP3`) taps directly from the op-amp buffer output **prior to** the RC antialiasing filter ($f_c = 48.2\text{ kHz}$), eliminating filter delay from the Tier-0 trip path.
* **STM32G474RE Exact Peripheral Routing Matrix (RM0440 / AN5094):**
  - `COMP1`: Non-inverting `PA1` (CSA $V_{out}$), Inverting `DAC1_CH1` ($2.650\text{ V}$) $\to$ `HRTIM1_FLT4` (Hard OC+).
  - `COMP2`: Non-inverting `DAC3_CH2` ($0.650\text{ V}$), Inverting `PA7` (CSA $V_{out}$) $\to$ `HRTIM1_FLT1` (Hard OC-).
  - `COMP3`: Non-inverting `PA0` ($V_{bus}$ 10:1 AFE), Inverting `DAC1_CH2` ($2.600\text{ V}$) $\to$ `HRTIM1_FLT5` (Hard OV).
  - HRTIM fault digital filters disabled (`FLTxF = 0000`) for zero-delay hardware trip.

---

## 3. Real-Time Determinism & Jitter Verification Protocols

### 3.1 Timing Budget & WCET Schedule ($50\text{ kHz}$ Loop)
* **Switching Period ($T_s$):** $20.0\,\mu\text{s}$ ($50.0\text{ kHz}$).
* **Execution Schedule (WCET):**
  - Timer center-point trigger to ADC conversion complete: $1.0\,\mu\text{s}$
  - DMA / NVIC IRQ dispatch: $0.2\,\mu\text{s}$
  - Cascaded PID computation & clamping: $3.6\,\mu\text{s}$
  - HRTIM compare shadow register reload: $0.2\,\mu\text{s}$
  - **Total Worst-Case Execution Time (WCET):** $\mathbf{5.0\,\mu\text{s}}$ ($25\%$ CPU load @ 170 MHz, well below $8.0\,\mu\text{s}$ / $40\%$ budget).
* **SPI DMA Background Telemetry:** 76-byte frame transfer @ 10 MHz SPI takes $\approx 60.8\,\mu\text{s}$ via background circular DMA and does not block the real-time control loop.
* **Four Jitter Metrics:**
  - Trigger Jitter: $\le \pm 5.0\text{ ns}$ (DSO)
  - IRQ Latency Jitter: $\le \pm 15.0\text{ ns}$ (DSO)
  - Execution Time Jitter: $\le \pm 20.0\text{ ns}$ (DWT)
  - Sample-to-Duty-Update Jitter: $\le \pm 50.0\text{ ns}$ (DSO)
* **Preemption Policy:** No intentional software ISR preemption is permitted during the control loop.

---

## 4. Multi-Tier Protection Latency Models

```
+===================================================================================================+
|                                DISTINCT TRIP LATENCY BREAKDOWNS                                   |
|                                                                                                   |
|  OVER-CURRENT (OC) HARDWARE TRIP PATH (Preliminary Model: 491 ns / Worst-Case 691 ns << 2.0 us)   |
|  T_trip,OC = T_shunt(10ns) + T_CSA_cross(300ns/500ns) + T_COMP_HRTIM(31ns) + T_driver(50ns)      |
|              + T_power_stage(100ns) = 491 ns (benchmark 1.5A step) / 691 ns (full 5A step)       |
|                                                                                                   |
|  OVER-VOLTAGE (OV) HARDWARE TRIP PATH (Preliminary Model: 241 ns << 2.0 us Budget)                |
|  T_trip,OV = T_divider(10ns) + T_buffer(50ns) + T_COMP_HRTIM(31ns) + T_driver(50ns)               |
|              + T_power_stage(100ns) = 241 ns                                                      |
+===================================================================================================+
```

---

## 5. System Control State Machine & Transition Rules

* **Exclusive Authority:** The STM32 Control Core FSM is the **exclusive, authoritative owner** of system state.
* **State Transition Invariant:** Direct transitions between `STATE_CHARGE_ACTIVE` and `STATE_DISCHARGE_ACTIVE` are **strictly prohibited**; all mode changes must pass through a controlled ramp-down to `STATE_IDLE`.
* **Tier-1 Emergency Ramp Fallback:** If a Level 2 software emergency ramp-down ($100\text{ A/s}$ within $50\text{ ms}$) encounters sensor failure or fails to reduce current, the FSM triggers an immediate hardware Timer Break trip to `STATE_SAFE_STATE`.
* **Quantified Derating Hysteresis:**
  - Heatsink Temp: Entry at $T > 55.0^\circ\text{C}$, Exit at $T < 45.0^\circ\text{C}$.
  - Low SOC: Entry at $\text{SOC} < 15.0\%$, Exit at $\text{SOC} > 20.0\%$.
  - High SOC: Entry at $\text{SOC} > 95.0\%$, Exit at $\text{SOC} < 90.0\%$.
* **Safe Recovery:** `FAULT_CLEAR_CMD = 0x00A5` (accepted only in `SAFE_STATE`) $\to$ `STATE_RECOVERY_CHECK` (verifies $V_{bat} \ge 11.0\text{ V}$, $16.0\text{ V} \le V_{bus} \le 25.0\text{ V}$, $|I_L| < 0.2\text{ A}$, $T < 45^\circ\text{C}$) $\to$ `STATE_IDLE`. Power flow requires a new explicit `START` command (`SYS_CONTROL_CMD = 1` or `2`).

---

## 6. Gateway Architecture & Resilient Master-Slave IPC

* **16-bit Sequence Number Alignment:** SPI Frame `SEQ_NUM` (`uint16_t`, $0 - 65535$) aligns 1:1 with Modbus `CMD_SEQ` (Register `40016`).
* **Frame Header:** `SYNC` (`0xA55A`, 2B) + `PROTO_VER` (1B) + `SESSION_ID` (1B) + `SEQ_NUM` (2B) + `MSG_TYPE` (1B) + `MSG_FLAGS` (1B) + `PAYLOAD_LEN` (1B) + `PAYLOAD` ($0-64\text{ B}$) + `CRC16` (2B). Total frame size = $11 + N$ bytes.

---

## 7. SCADA Modbus Holding Registers Map ($40001 - 40018$)

| Register | Register Name | Data Type | Scaling | Access | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`40001`** | `SYS_CONTROL_CMD` | `uint16_t` | Enum | R/W | Edge-triggered command mailbox (`0`=STOP, `1`=START_CHARGE, `2`=START_DISCHARGE) |
| **`40002`** | `BUS_VOLTAGE_RAW` | `uint16_t` | $10\text{ mV}$ | R | DC Bus Voltage (`0xFFFF` = Invalid Sentinel) |
| **`40003`** | `BAT_CURRENT_RAW` | `int16_t` | $10\text{ mA}$ | R | Battery Current (`0x7FFF` = Invalid Sentinel) |
| **`40004`** | `BAT_SOC` | `uint16_t` | $0.1\%$ | R | State of Charge (`0xFFFF` = Invalid Sentinel) |
| **`40005`** | `ACTIVE_FAULT_FLAGS` | `uint16_t` | Bitmap | R | Active real-time fault flag bitmap |
| **`40006`** | `VOUT` | `uint16_t` | $10\text{ mV}$ | R | Regulated Output Voltage (`0xFFFF` = Invalid) |
| **`40007`** | `IOUT` | `int16_t` | $10\text{ mA}$ | R | Output Current (`0x7FFF` = Invalid) |
| **`40008`** | `TEMPERATURE` | `int16_t` | $0.1^\circ\text{C}$ | R | Heatsink Temperature (`0x7FFF` = Invalid) |
| **`40009`** | `OPERATING_MODE` | `uint16_t` | Enum | R | `0`=IDLE, `1`=CHARGE, `2`=DISCHARGE, `3`=SAFE |
| **`40010`** | `FAULT_CODE` | `uint16_t` | Hex Code | R | Highest priority active fault code |
| **`40011`** | `FW_VERSION` | `uint16_t` | BCD | R | BCD format `0xMMmm` (e.g. `0x0130` = v1.3.0) |
| **`40012`** | `UPTIME_MSW` | `uint16_t` | Seconds | R | Atomic 32-bit Uptime Counter (MSW) |
| **`40013`** | `UPTIME_LSW` | `uint16_t` | Seconds | R | Atomic 32-bit Uptime Counter (LSW) |
| **`40014`** | `FAULT_CLEAR_CMD` | `uint16_t` | Magic Key | R/W | Dedicated Fault Clear: write `0x00A5` (Accepted only in `SAFE_STATE`) |
| **`40015`** | `CMD_RESULT` | `uint16_t` | Enum | R | `0`=None, `1`=Accepted, `2`=Rejected_InvalidState, `3`=Rejected_FaultActive, `4`=Rejected_Limit, `5`=Rejected_Safety, `6`=Rejected_IPC |
| **`40016`** | `CMD_SEQ` | `uint16_t` | Counter | R | Echo of last processed command sequence number (1:1 with SPI SEQ_NUM) |
| **`40017`** | `FSM_STATE` | `uint16_t` | Enum | R | Detailed Internal FSM State ($0-9$) |
| **`40018`** | `LATCHED_FAULT_FLAGS`| `uint16_t` | Bitmap | R | Historical latched fault bitmap (cleared by 40014) |

* Double-buffered shadow RAM snapshot with atomic buffer swap ($\le 20\text{ ms}$ age).
* Modbus exception `0x02` on unauthorized writes. Direct raw PWM duty cycle writes are strictly prohibited.

---

## 8. Fixed Bootloader & Confirmed Boot Architecture

* **Fixed Base Bootloader:** Bootloader resides at immutable fixed base address `0x0800_0000` ($32\text{ KB}$), reads metadata table, validates SHA-256 + ECDSA signature via on-chip public key, selects confirmed slot, and jumps.
* **SRAM Driver Execution & Dual-Bank RWW:** Flash erase/programming routines execute from SRAM (`__attribute__((section(".ramfunc")))`) allowing background updates to Bank 2 while running from Bank 1 without pipeline stalls.
* **Hardware Protection:** Flash Write Protection (WRP) protects Bank 1 Pages 120–127 (Key Region and NVRAM) combined with Readout Protection (RDP Level 1).
* **Confirmed Boot Rollback:** Maximum 3 application boot attempts permitted ($1 \to 2 \to 3$); automatic rollback occurs before the 4th boot attempt.
