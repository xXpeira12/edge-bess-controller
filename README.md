# Industrial Smart BESS & Power Management Controller (Desk-Scale PoC)
## Software Requirements Specification (SRS) & System Architecture Document

**Document Version:** 1.2.0  
**Target Platform:** Dual-MCU (Power Control Core + Industrial Gateway Core)  
**Control Core MCU:** STM32G474RE / STM32F446RE (ARM Cortex-M4F @ 168/170 MHz)  
**Gateway Core MCU:** ESP32-WROOM-32 (Dual-Core Xtensa LX6 @ 240 MHz)  
**Design Paradigm:** Hard Real-Time Deterministic Control, Multi-Tier Hardware/Software Safety, Non-Blocking Telemetry Isolation  
**PoC Standard Alignment:** IEC 60730 Class B-oriented Safety Diagnostics & ISO 21434 Cybersecurity Concept  

---

## 1. System Overview & PoC Scope

This document specifies the software requirements, system architecture, safety mechanisms, communication protocols, and verification methodologies for the **Desk-Scale Proof-of-Concept (PoC) Industrial Battery Energy Storage System (BESS) & Power Management Controller**.

The system utilizes a **Dual-MCU Architecture** physically segregating safety-critical, hard real-time power conversion loops from external network stacks, fieldbus protocols, and cloud telemetry.

```
+===================================================================================================+
|                                  DESK-SCALE BESS CONTROLLER NODE                                  |
|                                                                                                   |
|  +-------------------------------------+                   +-----------------------------------+  |
|  |     CONTROL CORE (STM32 Cortex-M4)  |                   |    GATEWAY CORE (ESP32 Dual-Core) |  |
|  |  - Cascaded Current/Voltage PID     |                   |  - FreeRTOS Preemptive Tasks      |  |
|  |  - 50 kHz PWM & Center-Point ADC    |    Full-Duplex    |  - Non-Blocking Ring Buffers      |  |
|  |  - IEC 60730 Class B Diagnostics    |     SPI + DMA     |  - Modbus-TCP / Modbus-RTU Server |  |
|  |  - Tier-0 Fast HW Break Trip (BKIN) | <===============> |  - Isolated CAN 2.0B BMS Master   |  |
|  |  - Cycle-by-Cycle Current Limiting  |   (Robust ARQ)    |  - MQTT / TLS Cloud Telemetry     |  |
|  |  - Flash Partitioning (IAP/Dual)    |                   |  - OTA Image Staging & Verifier   |  |
|  +-------------------------------------+                   +-----------------------------------+  |
|         |           |          |                                   |                 |            |
|     Complementary  Fast HW   Synchronous                        Isolated           Ethernet /     |
|      PWM (50kHz)  Trip In   Analog ADC                           CAN 2.0B            Wi-Fi        |
|         |           |          |                                   |                 |            |
|         v           |          v                                   v                 v            |
|   +-------------+   |   +--------------+                     +-----------+     +------------+     |
|   | Synchronous |   |   | Analog Front |                     | BMS Node  |     | SCADA /    |     |
|   | Buck/Boost  |   |   | End (CSA &   |                     | Battery   |     | Industrial |     |
|   | Power Stage |   |   | Div Buffers) |                     | Pack      |     | HMI Client |     |
|   +-------------+   |   +--------------+                     +-----------+     +------------+     |
|         ^           |          ^                                                                  |
|         +-----------+----------+                                                                  |
|               Tier-0 Comparator                                                                   |
|             Break Action (<=2.0us)                                                                |
+===================================================================================================+
```

### 1.1 Standards Compliance Phrasing (Desk-Scale PoC Pragmatism)
To maintain academic and industrial rigor without overstating regulatory status for a desktop-scale prototype:
* **IEC 60730 Class B-Oriented Safety Diagnostics:** The firmware implements core diagnostic patterns inspired by IEC 60730 Class B requirements—including pre-execution destructive CPU register tests, non-destructive runtime March C- SRAM tests, Flash CRC-32 integrity verification, independent watchdog (IWDG) timing windows, and Clock Security System (CSS) monitoring. These serve as architectural proofs rather than certified commercial compliance.
* **ISO 21434 Cybersecurity Concept:** The bootloader and staging architecture implement foundational automotive/industrial cybersecurity concepts, such as structured image headers, cryptographic integrity checks (SHA-256 / HMAC / CRC), monotonic security version counters (anti-rollback), and strict separation of privileged control commands from untrusted telemetry paths.
* **Scope Boundary:** This design targets low-voltage bench prototyping ($18.0\text{ V} - 24.0\text{ V}$ bus, $10.5\text{ V} - 14.6\text{ V}$ battery, $20\text{ W} - 50\text{ W}$ continuous). Mass-production certifications (e.g., UL 1973, UL 9540, IEC 62619, full SIL-3/ASIL-D certification) require dedicated external hardware safety interlocks, physical galvanic isolation barriers, and accredited lab validation.

---

## 2. Hardware Interfaces, Operational Boundaries & Analog Front-End

### 2.1 Operational Boundaries (Desk-Scale Benchmark)

| Parameter | Minimum | Nominal | Maximum | Unit | Remarks |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Input Bus Voltage ($V_{bus}$)** | $16.0$ | $24.0$ | $26.0$ | $\text{V}$ | Current-limited benchtop DC supply |
| **Battery Port Voltage ($V_{bat}$)** | $10.0$ | $12.8$ | $14.6$ | $\text{V}$ | 4S LiFePO4 / 3S Li-ion or programmable load |
| **Continuous Power Rating** | $-$ | $30.0$ | $50.0$ | $\text{W}$ | Convection cooled |
| **Continuous Inductor Current ($I_L$)** | $-3.5$ | $\pm 2.5$ | $+3.5$ | $\text{A}$ | Positive: Charge, Negative: Discharge |
| **Hardware Over-Current Trip ($I_{trip}$)** | $-$ | $5.0$ | $5.2$ | $\text{A}$ | Tier-0 Hardware Comparator to Timer Break |
| **Hardware Over-Voltage Trip ($V_{trip}$)** | $-$ | $26.0$ | $26.5$ | $\text{V}$ | Tier-0 Hardware Comparator to Timer Break |
| **PWM Switching Frequency ($f_{sw}$)** | $-$ | $50.0$ | $50.0$ | $\text{kHz}$ | Complementary with configurable dead-time |
| **Dead-Time Insertion ($t_{dead}$)** | $250$ | $350$ | $500$ | $\text{ns}$ | Hardware dead-time generator in TIM1/HRTIM |

### 2.2 Analog Front-End (AFE) Sensing Topology

To ensure high-fidelity signal acquisition and sub-microsecond fault tripping, the analog front-end separates high-speed trip paths from filtered digital sampling paths.

```
                                ANALOG SENSING FRONT-END TOPOLOGY
                                
  +------------------------------------------------------------------------------------------------+
  | VOLTAGE SENSING PATH (DC Bus / Battery Terminal)                                               |
  |                                                                                                |
  |  V_BUS (18-24V) ----[ R1: 90k 0.1% ]----+----[ R_filt: 1k ]----+-----> MCU ADC Pin (0-3.0V)  |
  |                                         |                      |        (Synchronous Center-Pt)|
  |                                  [ R2: 10k 0.1% ]           [ C_filt: 3.3nF ]                  |
  |                                         |     (fc ~ 48 kHz)    |                               |
  |                                        GND                    GND                              |
  |                                         |                                                      |
  |                                         +----[ Buffer Op-Amp ]--------> MCU COMPx_INP (Tier 0) |
  |                                                                         (Over-Voltage Trip Ref)|
  +------------------------------------------------------------------------------------------------+

  +------------------------------------------------------------------------------------------------+
  | CURRENT SENSING PATH (Inductor / Battery Bi-Directional Shunt)                                 |
  |                                                                                                |
  |  Power Stage ----[ Shunt: 10 mOhm, 1%, 3W ]----> Inductor                                      |
  |                         |           |                                                          |
  |                         +-----+ +---+                                                          |
  |                               | |                                                              |
  |                    +----------------------+                                                    |
  |                    | INA240 / INA180 CSA  | (Enhanced PWM Rejection, Gain = 50 V/V)            |
  |                    | V_REF = 1.65V (Bi-Dir|                                                    |
  |                    +----------------------+                                                    |
  |                               | Output: 1.65V +/- (500 mV/A)                                   |
  |                               +------------------------+                                       |
  |                               |                        |                                       |
  |                      [ Low-Pass Filter ]               |                                       |
  |                       R=1k, C=2.2nF (fc~72kHz)         |                                       |
  |                               |                        |                                       |
  |                               v                        v                                       |
  |                         MCU ADC Channel       MCU COMP1 / COMP2                                |
  |                     (Synchronous 50 kHz)    (Tier-0 Over-Current Trip)                         |
  |                                                        |                                       |
  |                                                        v                                       |
  |                                              TIM1 / HRTIM BKIN Pin                             |
  |                                            (PWM Forced LOW <= 2.0 us)                          |
  +------------------------------------------------------------------------------------------------+
```

* **`REQ-SENS-001` (DC Bus Voltage Sensing):** The high-voltage DC bus ($18.0\text{ V} - 24.0\text{ V}$) is stepped down via a precision resistive divider ($10:1$ ratio, $0.1\%$ tolerance, $25\text{ ppm}/^\circ\text{C}$ temperature coefficient). An operational amplifier buffer prevents ADC input impedance loading, and a first-order passive RC filter ($f_c \approx 48\text{ kHz}$) suppresses high-frequency switching harmonics prior to ADC sampling.
* **`REQ-SENS-002` (Inductor & Battery Current Sensing):** Inductor current is sensed across a low-inductance $10\text{ m}\Omega$ current shunt resistor using a dedicated Current Sense Amplifier (CSA, e.g., TI INA240 with high common-mode PWM rejection or INA180). The CSA is configured with a $1.65\text{ V}$ mid-rail reference for bidirectional sensing ($+1.65\text{ V}$ offset, $500\text{ mV}/\text{A}$ sensitivity).
* **`REQ-SENS-003` (Dual-Path Trip/Sample Split):** The CSA output splits into two distinct paths:
  1. **Feedback Path:** Filtered by an RC antialiasing filter ($f_c \approx 72\text{ kHz}$) and routed to the MCU 12-bit ADC for discrete digital PID control.
  2. **Fast Trip Path:** Routed directly to the MCU internal analog comparator (`COMP1` / `COMP2`) or an external fast comparator (e.g. TLV3501, propagation delay $< 5\text{ ns}$), comparing against a DAC-configured threshold equivalent to $5.0\text{ A}$.

---

## 3. Real-Time Determinism & Jitter Verification Methodology

```
                          PWM CENTER-POINT SYNCHRONIZATION TIMING
                          
  TIM1/HRTIM Counter:
       /\                /\                /\                /\
      /  \              /  \              /  \              /  \
     /    \            /    \            /    \            /    \
    /      \          /      \          /      \          /      \
   /   CTR  \        /   CTR  \        /   CTR  \        /   CTR  \
  /    = 0   \      /    = 0   \      /    = 0   \      /    = 0   \
 +------------\----+------------\----+------------\----+------------\----+
               \  /              \  /              \  /              \  /
  PWM Trigger:  v                 v                 v                 v
             ADC Sample       ADC Sample        ADC Sample        ADC Sample
             (Center Pt)      (Center Pt)       (Center Pt)       (Center Pt)
                  |                |                 |                 |
  ISR Execution:  +--[ Ts = 20us ]-+                 |                 |
                  |<- t_lat ->|                      |                 |
                  +===========+                      |                 |
                  | PID Calc  |                      |                 |
                  +===========+                      |                 |
                     |< Jitter: <= +/- 50 ns >|
```

### 3.1 Timing Requirement (`NFR-PERF-01`)
* **Control Loop Switching Frequency ($f_{sw}$):** $50.0\text{ kHz}$ ($T_s = 20.0\,\mu\text{s}$).
* **Maximum Allowable Interrupt Jitter ($\Delta t_{jitter}$):** $\le \pm 50.0\text{ ns}$ referenced to the timer center-point counter reload event.
* **Total Execution Budget:** The inner current PID execution time plus ADC conversion latency shall not exceed $8.0\,\mu\text{s}$ ($40\%$ CPU load at $168\text{ MHz}$).

### 3.2 Bench Verification Methodology
Deterministic execution shall be verified on physical hardware using a three-tier validation setup:

```
+===================================================================================================+
|                                    JITTER VERIFICATION TESTBENCH                                  |
|                                                                                                   |
|  +-------------------------------------+                                                          |
|  | CONTROL MCU (STM32)                 |                                                          |
|  |  - TIM1 Center-Point TRGO Event     |                                                          |
|  |  - ADC End-of-Conversion (EOC) ISR  |                                                          |
|  |  - GPIO Pin Toggle (Debug Fast Out) |                                                          |
|  |  - Cortex-M4 DWT Cycle Counter      |                                                          |
|  +-------------------------------------+                                                          |
|         |                      |                                                                  |
|    Channel 1 (CH1)        Channel 2 (CH2)                                                         |
|    Timer Center-Point     GPIO Toggle at                                                          |
|    TRGO Output Pulse      ADC_IRQHandler Entry                                                    |
|         |                      |                                                                  |
|         v                      v                                                                  |
|  +---------------------------------------------------------------------------------------------+  |
|  | DIGITAL STORAGE OSCILLOSCOPE (DSO >= 100 MHz Bandwidth, >= 1 GSa/s Sample Rate)              |  |
|  |                                                                                             |  |
|  |  Trigger: Rising edge on CH1 (TRGO center point)                                            |  |
|  |  Measurement: Time delay Delta-T between CH1 rising edge and CH2 rising edge                |  |
|  |  Persistence Mode: Infinite Persistence + Hardware Histogram Mode                           |  |
|  |  Pass/Fail Criterion: Delta-T Max - Delta-T Min <= 100 ns (Jitter <= +/- 50 ns)             |  |
|  |  Sample Population: N >= 100,000 continuous switching cycles                                |  |
|  +---------------------------------------------------------------------------------------------+  |
|                                                                                                   |
|  +---------------------------------------------------------------------------------------------+  |
|  | EMBEDDED DWT TELEMETRY RUNTIME MONITOR                                                      |  |
|  |                                                                                             |  |
|  |  // Cycle-accurate latency tracking via Cortex-M4 DWT->CYCCNT                              |  |
|  |  uint32_t t_start = DWT->CYCCNT;                                                           |  |
|  |  // ... Control Loop PID execution ...                                                      |  |
|  |  uint32_t t_delta = DWT->CYCCNT - t_start;                                                  |  |
|  |  if (t_delta > g_isr_max_cycles) g_isr_max_cycles = t_delta;                                |  |
|  |  if (t_delta < g_isr_min_cycles) g_isr_min_cycles = t_delta;                                |  |
|  |  // Jitter = (g_isr_max_cycles - g_isr_min_cycles) * (1 / 168 MHz) <= 100 ns                |  |
|  +---------------------------------------------------------------------------------------------+  |
+===================================================================================================+
```

1. **Hardware Pin Instrumentation:**
   - Configure a dedicated high-speed push-pull GPIO pin (`DEBUG_ISR_GPIO`) configured for maximum output slew rate ($50\text{ MHz}$).
   - Set `DEBUG_ISR_GPIO` to `HIGH` at the very first instruction of `ADC_IRQHandler` (or `HRTIM_Master_IRQHandler`) and clear to `LOW` upon completion.
2. **DSO Persistence & Histogram Measurement:**
   - Connect a $\ge 100\text{ MHz}$ Digital Storage Oscilloscope with active probes:
     * CH1: TIM1 TRGO / PWM center-point sync pulse.
     * CH2: `DEBUG_ISR_GPIO`.
   - Set trigger to CH1 rising edge, enable **Infinite Persistence** and **Histogram Window** over $\Delta t$ ($t_{CH2\_rise} - t_{CH1\_rise}$).
   - Run across $\ge 100,000$ consecutive switching cycles ($2.0\text{ seconds}$ continuous sampling). The peak-to-peak distribution spread must satisfy $\Delta t_{max} - \Delta t_{min} \le 100\text{ ns}$ ($\pm 50\text{ ns}$).
3. **Cortex-M4 DWT Cycle Counter Telemetry:**
   - Enable `CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk` and `DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk`.
   - Capture `DWT->CYCCNT` at ISR entry and calculate execution cycle variance. Min, max, and current cycle counts are reported over IPC telemetry every $100\text{ ms}$.

---

## 4. Two-Tier Protection Architecture

To ensure fail-safe operation during transient over-currents or catastrophic software crashes, protection is divided into two distinct, decoupled tiers.

```
+===================================================================================================+
|                                TWO-TIER PROTECTION ARCHITECTURE                                   |
|                                                                                                   |
|   +--------------------------------------------------------------------------------------------+  |
|   | TIER 0: HARDWARE PROTECTION LAYER (Autonomous Silicon Protection)                          |  |
|   | Latency: <= 2.0 microseconds (Typical Hardware Delay: < 100 nanoseconds)                   |  |
|   | CPU Dependency: ZERO (Operates when CPU is halted, hung, or servicing other interrupts)    |  |
|   |                                                                                            |  |
|   |   Analog Signals           Fast Comparators              Timer Break Circuit               |  |
|   |   (Current / Voltage)       (COMP1 / COMP2)             (TIM1_BKIN / HRTIM_FAULT1)         |  |
|   |                                                                                            |  |
|   |   I_Sense (Shunt)   -----> [ COMP1 Trip Ref: 5.0A ] -+                                     |  |
|   |                                                      +--> [ BKIN Input ]                   |  |
|   |   V_Bus (Divider)   -----> [ COMP2 Trip Ref: 26.0V]-+           |                         |  |
|   |                                                                 v                         |  |
|   |                                                    [ PWM Outputs FORCED LOW / Hi-Z ]      |  |
|   |                                                    [ Hardware Latched Safe-State   ]      |  |
|   +--------------------------------------------------------------------------------------------+  |
|                                                                                                   |
|   +--------------------------------------------------------------------------------------------+  |
|   | TIER 1: SOFTWARE PROTECTION LAYER (Intelligent Supervisory Protection)                     |  |
|   | Latency: 20 microseconds (Inner Loop) to 100 milliseconds (Diagnostics)                   |  |
|   | Features: Trend analysis, soft limits, derating, plausible sensor cross-checks            |  |
|   |                                                                                            |  |
|   |   - Soft Over-Current ($I > 4.2\text{ A}$ for $\ge 5$ cycles) -> Staged Current Throttling  |  |
|   |   - Soft Over-Voltage ($V > 25.0\text{ V}$) -> Closed-loop voltage clamp                   |  |
|   |   - Over-Temperature ($T > 65.0^\circ\text{C}$) -> Linear power derating (50% power at 75C)| |
|   |   - Under-Voltage ($V_{bat} < 9.5\text{ V}$) -> Controlled Ramp-Down to IDLE               |  |
|   |   - Plausibility Check ($|V_{bus} - V_{out}| > \text{threshold}$) -> Controlled Ramp-Down  |  |
|   |   - IEC 60730 Self-Test Anomaly -> Soft-Stop & Lockout Transition                         |  |
|   +--------------------------------------------------------------------------------------------+  |
+===================================================================================================+
```

### 4.1 Tier 0: Hardware Protection Layer (`REQ-SAFE-005`)
* **Trigger Conditions:** Current $I > 5.0\text{ A}$ or DC Bus Voltage $V > 26.0\text{ V}$.
* **Trip Mechanism:** Fast internal comparators (`COMP1`/`COMP2`) or external ultra-fast comparators route asynchronously into the timer's Break Input (`TIM1_BKIN` or `HRTIM_FAULT1`).
* **Response Action:** Timer hardware immediately forces all complementary PWM output pins (High-Side and Low-Side) to inactive state (`LOW` / High-Z) within $\le 2.0\,\mu\text{s}$ (silicon propagation delay typically $< 100\text{ ns}$).
* **Independence:** Operates independently of the Cortex-M4 CPU core, RTOS context, or interrupt vector execution. The trip condition latches into hardware; PWM outputs cannot toggle until hardware break registers are cleared via verified supervisory rearm command.

### 4.2 Tier 1: Software Supervisory Protection (`REQ-SAFE-006`)
* **Trigger Conditions:** Soft limits reached ($I > 4.2\text{ A}$, $V_{bus} > 25.0\text{ V}$, $T_{heatsink} > 65^\circ\text{C}$, $V_{bat} < 9.5\text{ V}$, or IPC heartbeat loss).
* **Response Action:** Execute smooth, deterministic soft-current ramp-down ($dI/dt \le 2.0\text{ A/s}$) to prevent inductive switching spikes, followed by disabling PWM software gates and transitioning the controller state machine into `IDLE` or `SAFE_STATE`.

---

## 5. Multi-Level Fault Handling Framework

Faults are classified into three hierarchical severity levels:

```
+---------------------------------------------------------------------------------------------------+
|                                 MULTI-LEVEL FAULT HIERARCHY                                       |
|                                                                                                   |
|  [ LEVEL 3: CRITICAL FAULT ]  <--- Instant Hardware Break Trip (Tier 0), PWM Lockout, SAFE_STATE  |
|         ^                                                                                         |
|         | Escalates on persistence or hardware boundary breach                                    |
|  [ LEVEL 2: FAULT ]           <--- Controlled Ramp-Down (dI/dt <= 2A/s), PWM Disabled, IDLE State |
|         ^                                                                                         |
|         | Escalates on thermal saturation or communication timeout                                |
|  [ LEVEL 1: WARNING ]         <--- Dynamic Derating (Power Clamping), Warning Flags, Running OK   |
+---------------------------------------------------------------------------------------------------+
```

### 5.1 Fault Level Matrix

| Fault Class | Trigger Source | Detection Threshold & Criteria | Action & System Behavior | Recovery Policy |
| :--- | :--- | :--- | :--- | :--- |
| **WARNING** | High Heatsink Temp | $55^\circ\text{C} \le T \le 65^\circ\text{C}$ | Set warning flag in register `40005`; linear current derating ($100\%$ at $55^\circ\text{C}$ to $50\%$ at $65^\circ\text{C}$). System continues running. | Auto-clears when temperature drops $< 50^\circ\text{C}$. |
| **WARNING** | Low Battery SOC | $10\% \le \text{SOC} \le 15\%$ | Set warning flag in register `40005`; discharge current clamped to $1.0\text{ A}$. | Auto-clears when $\text{SOC} > 18\%$. |
| **WARNING** | Dropped SPI Packet | 1 or 2 isolated CRC errors | Request ARQ retransmission; increment telemetry error counter; continue active control. | Auto-clears on successful packet exchange. |
| **FAULT** | Sustained IPC Timeout | $\ge 3$ consecutive retries or silence $> 500\text{ ms}$ | Execute controlled current ramp-down to $0\text{ A}$ within $50\text{ ms}$; disable PWM gating; transition to `IDLE`. | Requires IPC link re-synchronization and `SYS_CONTROL_CMD = 0xFF` (Clear Fault). |
| **FAULT** | Soft Over-Current | $I > 4.2\text{ A}$ sustained for $> 10\text{ ms}$ | Software PID current reference ramped to $0\text{ A}$; disable PWM; transition to `IDLE`. | Host clear command after current drops $< 0.5\text{ A}$. |
| **FAULT** | Soft Over-Temperature | $T > 65^\circ\text{C}$ | Software disabled; ramp to $0\text{ A}$; transition to `IDLE`; fan cooling maximum. | Host clear command after $T < 45^\circ\text{C}$. |
| **FAULT** | Under-Voltage Lockout | $V_{bat} < 9.5\text{ V}$ or $V_{bus} < 16.0\text{ V}$ | Software ramps down discharge current; transitions to `IDLE`. | Voltage restored to valid band ($> 11.0\text{ V}$) + Host clear command. |
| **FAULT** | Sensor Plausibility | $|V_{sense1} - V_{sense2}| > 1.5\text{ V}$ | Software detects ADC channel discrepancy; disables PWM; transition to `IDLE`. | System re-initialization and host clear. |
| **CRITICAL** | Hardware Over-Current | $I > 5.0\text{ A}$ analog comparator | **Tier 0:** Hardware Break input forces PWM `LOW` $\le 2.0\,\mu\text{s}$. Latches `SAFE_STATE`. | Hard manual reset or host power-cycle sequence after diagnostic verification. |
| **CRITICAL** | Hardware Over-Voltage | $V > 26.0\text{ V}$ analog comparator | **Tier 0:** Hardware Break input forces PWM `LOW` $\le 2.0\,\mu\text{s}$. Latches `SAFE_STATE`. | Hard manual reset or host power-cycle sequence after diagnostic verification. |
| **CRITICAL** | IEC 60730 Self-Test | CPU reg, March C- RAM, or Flash CRC fail | Hardware Break trip forced; execution halted; error pattern pulsed on diagnostic LED; `SAFE_STATE`. | Power-on cold reboot required. |
| **CRITICAL** | Watchdog (IWDG) / CSS | IWDG window breach or HSE clock failure | Hardware watchdog reset triggered; Clock Security System switches to HSI and forces break trip. | Hardware reset vector. |

---

## 6. System Control State Machine

The Control MCU operates under a strictly deterministic finite state machine (FSM) executed within the real-time supervisory loop:

```
                            SYSTEM CONTROL STATE MACHINE
                            
            +-------------------------------------------------------+
            |                       POWER_ON                        |
            +-------------------------------------------------------+
                                        |
                                        v
            +-------------------------------------------------------+
            |                  INIT & SELF-TEST                     |
            |  - IEC 60730 Pre-Execution Reg & RAM Tests           |
            |  - Clock & Peripheral Setup (TIM1, ADC, DMA)          |
            |  - Flash Golden CRC-32 Verification                   |
            +-------------------------------------------------------+
                       |                                  |
            [ Self-Test Passed ]               [ Self-Test Failed / HW Trip ]
                       v                                  |
            +----------------------+                      |
    +-----> |         IDLE         |                      |
    |       |  - PWM High-Z        |                      |
    |       |  - Relays Open       |                      |
    |       |  - Diagnostics Active|                      |
    |       +----------------------+                      |
    |            |            |                           |
    |   [ Cmd = Charge ]   [ Cmd = Discharge ]            |
    |            v            v                           |
    |     +------------+ +---------------+                |
    |     | CHARGE_RAMP| | DISCHARGE_RAMP|                |
    |     | - Soft-Start | - Soft-Start  |                |
    |     | - Ramp I_ref | - Ramp I_ref  |                |
    |     +------------+ +---------------+                |
    |            |            |                           |
    |     [ Ramp Done ]  [ Ramp Done ]                    |
    |            v            v                           |
    |     +------------+ +---------------+                |
    |     |CHARGE_ACTIV| |DISCHARGE_ACTIV|                |
    |     | - 50kHz PID| | - 50kHz PID   |                |
    |     | - Buck Mode| | - Boost Mode  |                |
    |     +------------+ +---------------+                |
    |            |            |                           |
    |     [ Warn Temp/V ] [ Warn Temp/V ]                 |
    |            \            /                           |
    |             v          v                            |
    |       +---------------------+                       |
    |       |   DERATING_ACTIVE   |                       |
    |       | - Throttled I_ref   |                       |
    |       +---------------------+                       |
    |            |            |                           |
    | [ Normal ] |            | [ Fault Event / Stop Cmd ]|
    +------------+            +---------------------------+
                                          |
                                          |
  [ Any Level 2 Fault / Stop Cmd ]        | [ Any Tier-0 Critical Fault ]
  +---------------------------------------+               |
  |                                                       v
  v                                           +=======================+
[ Controlled Ramp-Down (dI/dt <= 2A/s) ]      |      SAFE_STATE       |
  |                                           | - Hardware PWM Break  |
  +-----------------> IDLE                    | - Relays Open         |
                                              | - Fault Code Latched  |
                                              +=======================+
```

### 6.1 State Descriptions & Transition Guard Conditions

1. **`STATE_POWER_ON`:** Initial hardware power-up state. Microcontroller executes reset vector and configures minimum core clocks.
2. **`STATE_INIT_AND_SELF_TEST`:**
   - Executes IEC 60730 Class B startup routines (destructive CPU core register patterns `0x55555555` / `0xAAAAAAAA`, destructive/non-destructive March C- SRAM check, Flash golden CRC verification).
   - Initializes ADC calibration, GPIO configurations, DMA buffers, and Timer Break inputs.
   - *Guard Transition:* If all self-tests pass, transitions to `STATE_IDLE`. If any test fails, latches into `STATE_SAFE_STATE`.
3. **`STATE_IDLE`:**
   - Power conversion inactive: PWM outputs configured to High-Z/LOW; soft-start circuits open.
   - Continuous runtime diagnostics active (non-destructive sliced March C- test, IWDG window refresh, thermal monitoring).
   - *Guard Transition:* Receives valid IPC command `SYS_CONTROL_CMD = 1` $\rightarrow$ `STATE_CHARGE_RAMP`; `SYS_CONTROL_CMD = 2` $\rightarrow$ `STATE_DISCHARGE_RAMP`.
4. **`STATE_CHARGE_RAMP`:**
   - Pre-flight bus voltage checks confirmed ($18.0\text{ V} \le V_{bus} \le 24.5\text{ V}$, $10.0\text{ V} \le V_{bat} \le 14.4\text{ V}$).
   - High-Side complementary PWM enabled in Buck mode; target current setpoint $I_{ref}$ ramps up smoothly from $0\text{ A}$ to configured target ($dI/dt \le 2.0\text{ A/s}$).
   - *Guard Transition:* Upon reaching target current, transitions to `STATE_CHARGE_ACTIVE`.
5. **`STATE_CHARGE_ACTIVE`:**
   - Real-time dual-loop cascaded PID executing at $50\text{ kHz}$ (inner current) / $5\text{ kHz}$ (outer voltage).
   - Continuous over-voltage, over-current, and temperature monitoring.
   - *Guard Transition:* If warning temperature or SOC threshold reached $\rightarrow$ `STATE_DERATING_ACTIVE`. If stop command received $\rightarrow$ ramps down to `STATE_IDLE`. If Level 3 fault $\rightarrow$ `STATE_SAFE_STATE`.
6. **`STATE_DISCHARGE_RAMP`:**
   - Pre-flight battery and load checks confirmed ($V_{bat} \ge 10.5\text{ V}$, $V_{bus} \le 24.0\text{ V}$).
   - Low-Side complementary PWM enabled in Boost mode; discharge current setpoint ramps up smoothly ($dI/dt \le 2.0\text{ A/s}$).
   - *Guard Transition:* Upon reaching target current, transitions to `STATE_DISCHARGE_ACTIVE`.
7. **`STATE_DISCHARGE_ACTIVE`:**
   - Real-time Boost mode regulation active supplying power from battery port to DC bus.
   - *Guard Transition:* Warning threshold reached $\rightarrow$ `STATE_DERATING_ACTIVE`. Stop command $\rightarrow$ ramps down to `STATE_IDLE`. Critical fault $\rightarrow$ `STATE_SAFE_STATE`.
8. **`STATE_DERATING_ACTIVE`:**
   - Power setpoint dynamically clamped to derated curve ($20\% - 50\%$ nominal current) based on heatsink thermal slope or battery SOC lower knee.
   - *Guard Transition:* If thermal conditions recover ($T < 50^\circ\text{C}$ for $> 5\text{ s}$), transitions back to `STATE_CHARGE_ACTIVE` or `STATE_DISCHARGE_ACTIVE`.
9. **`STATE_SAFE_STATE`:**
   - Emergency fail-safe lockout state.
   - PWM outputs permanently forced to inactive `LOW` by hardware Timer Break circuit and software register disable.
   - Isolation relays opened; diagnostic fault code latched in Modbus register `40010`.
   - Cannot be exited without a verified diagnostic clear command or hard system reset.

---

## 7. Gateway Core Architecture & Resilient Inter-Processor Communication (IPC)

### 7.1 FreeRTOS Task Isolation & Non-Blocking Gateway

The ESP32 Gateway MCU runs FreeRTOS with preemptive priority task scheduling to ensure networking delays (Modbus-TCP socket retransmission, Wi-Fi reconnection, CAN arbitration) never block high-speed IPC telemetry.

```
+===================================================================================================+
|                                GATEWAY FREERTOS TASK ARCHITECTURE                                 |
|                                                                                                   |
|  +---------------------------------------------------------------------------------------------+  |
|  | Task 1: IPC Master Task (Priority: 5 - High / Real-Time)                                    |  |
|  |  - Full-Duplex SPI + DMA Master Controller @ 10 MHz                                         |  |
|  |  - Non-blocking circular ring buffers (IPC_TX_QUEUE_LEN=16, IPC_RX_QUEUE_LEN=16)            |  |
|  |  - Bounded timeouts (pdMS_TO_TICKS(10)) on all queue calls; TWDT monitored                  |  |
|  |  - Continuous stack tracking via uxTaskGetStackHighWaterMark()                             |  |
|  +---------------------------------------------------------------------------------------------+  |
|         |                                      ^                                                  |
|         v (Decoded Telemetry)                  | (Validated Control Commands)                     |
|  +---------------------------------------------------------------------------------------------+  |
|  | Task 2: CAN Bus BMS Ingestion Task (Priority: 3 - Medium)                                    |  |
|  |  - Ingests BMS pack/cell telemetry over Isolated CAN 2.0B (500 kbps) every 100ms            |  |
|  |  - Computes dynamic charge/discharge current limits (CCL / DCL)                             |  |
|  +---------------------------------------------------------------------------------------------+  |
|         |                                      |                                                  |
|         v                                      v                                                  |
|  +---------------------------------------------------------------------------------------------+  |
|  | Task 3: Modbus-TCP / RTU Server Task (Priority: 2 - Normal)                                  |  |
|  |  - Serves SCADA / HMI holding registers 40001 - 40013                                       |  |
|  |  - Enforces Modbus Control Policy: Rejects direct PWM writes; validates setpoints            |  |
|  +---------------------------------------------------------------------------------------------+  |
|         |                                                                                         |
|         v                                                                                         |
|  +---------------------------------------------------------------------------------------------+  |
|  | Task 4: MQTT & Cloud Diagnostics Task (Priority: 1 - Low / Background)                       |  |
|  |  - Formats JSON telemetry packet; publishes to cloud broker via TLS @ 1 Hz                  |  |
|  |  - Drops non-critical telemetry frames upon network backpressure without stalling IPC       |  |
|  +---------------------------------------------------------------------------------------------+  |
+===================================================================================================+
```

* **`REQ-COMM-004` (FreeRTOS Non-Blocking Isolation):**
  - All communication queues are statically bounded (`IPC_TX_QUEUE_LEN = 16`, `IPC_RX_QUEUE_LEN = 16`, `CAN_RX_QUEUE_LEN = 32`).
  - Queue operations specify strict timeouts (`pdMS_TO_TICKS(10)`). If a downstream network queue (e.g. MQTT) fills due to connection jitter, frames are dropped with an incremented drop counter rather than asserting backpressure onto Task 1 (`IPC Master`).
  - Every task registers with the FreeRTOS Task Watchdog Timer (TWDT, timeout $500\text{ ms}$).
  - FreeRTOS stack high-water mark is monitored continuously using `uxTaskGetStackHighWaterMark()`. If any task stack margin falls below $256\text{ bytes}$, a warning diagnostic is published.

### 7.2 Robust SPI Frame Protocol (`REQ-COMM-001`)

IPC communication over full-duplex SPI with DMA utilizes a strictly typed, byte-aligned frame format:

| Byte Offset | Field Name | Type | Description |
| :--- | :--- | :--- | :--- |
| **0 – 1** | `SYNC_WORD` | `uint16_t` | Frame start delimiter: `0xA55A` (Big-Endian) |
| **2** | `PROTO_VER` | `uint8_t` | Protocol Version (Current: `0x01`) |
| **3** | `SEQ_NUM` | `uint8_t` | Monotonic Sequence Counter ($0 - 255$) |
| **4** | `MSG_TYPE` | `uint8_t` | Message Type Identifier (see table below) |
| **5** | `MSG_FLAGS` | `uint8_t` | Control flags: `BIT0=ACK`, `BIT1=NACK`, `BIT2=RETRY`, `BIT3=URGENT` |
| **6** | `PAYLOAD_LEN` | `uint8_t` | Length of data payload $N$ ($0 \le N \le 64$) |
| **7 .. (7+N-1)** | `PAYLOAD` | `uint8_t[N]` | Serialized command / telemetry payload |
| **(7+N) .. (8+N)**| `CRC16` | `uint16_t` | CRC-16-CCITT (Polynomial `0x1021`, Init `0xFFFF`) over bytes $2 \dots (6+N)$ |

#### Message Types (`MSG_TYPE`)
* `0x01` `MSG_TELEMETRY_FAST`: Inner loop fast metrics ($V_{bus}$, $I_L$, $V_{bat}$, $50\text{ Hz}$).
* `0x02` `MSG_TELEMETRY_SLOW`: Thermal, diagnostic counters, DWT jitter metrics ($10\text{ Hz}$).
* `0x10` `MSG_CMD_SET_STATE`: Supervisory state transition command (`IDLE`, `CHARGE`, `DISCHARGE`, `SAFE_STOP`).
* `0x11` `MSG_CMD_SET_CURRENT_LIMIT`: Validated current reference setpoint ($I_{ref}$ in $\text{mA}$).
* `0x20` `MSG_FAULT_ALERT`: Unsolicited fault event from Control MCU to Gateway.
* `0x21` `MSG_FAULT_CLEAR`: Authenticated fault reset command.
* `0xFE` `MSG_PING`: Link integrity heartbeat ping.
* `0xFF` `MSG_ACK_NACK`: Dedicated frame acknowledgement packet.

### 7.3 IPC Protocol State Machine

```
                            IPC PROTOCOL STATE MACHINE
                            
            +-------------------------------------------------------+
            |                      IPC_UNINIT                       |
            |  - Hardware Reset; SPI & DMA Peripheral Reset         |
            +-------------------------------------------------------+
                                        |
                            [ Init SPI & DMA OK ]
                                        v
            +-------------------------------------------------------+
            |                      IPC_SYNCING                      |
            |  - Master sends MSG_PING (0xFE) with SYNC_WORD        |
            |  - Slave searches for 0xA55A frame alignment          |
            +-------------------------------------------------------+
                                        |
                          [ Valid ACK Received (3/3) ]
                                        v
            +-------------------------------------------------------+
    +-----> |                  IPC_CONNECTED_IDLE                   |
    |       |  - Link synced; 100ms Heartbeat Ping Active           |
    |       +-------------------------------------------------------+
    |                                   |
    |                         [ Outgoing Data Ready ]
    |                                   v
    |       +-------------------------------------------------------+
    |       |                   IPC_TX_RX_ACTIVE                    |
    |       |  - Full-Duplex DMA Transfer Initiated (SPI @ 10 MHz)  |
    |       +-------------------------------------------------------+
    |                                   |
    |                         [ Transfer Complete ]
    |                                   v
    |       +-------------------------------------------------------+
    |       |                     IPC_WAIT_ACK                      |
    |       |  - Await ACK with Timeout (T_ack <= 10 ms)            |
    |       +-------------------------------------------------------+
    |                 |                                   |
    |     [ Valid ACK Received ]                [ Timeout / CRC Error ]
    |                 |                                   |
    +-----------------+                     [ Retry Count < 3 ]   [ Retry Count >= 3 ]
                                                    |                      |
                                            (Send MSG_RETRY)               v
                                                    |         +-------------------------+
                                                    +-------> | IPC_COMM_FAULT_DEGRADED |
                                                              | - Ramp to IDLE          |
                                                              | - Set Flag in Modbus    |
                                                              +-------------------------+
```

---

## 8. Industrial Modbus-TCP / RTU Register Map & Control Policy

### 8.1 Modbus Supervisory Control Policy (`REQ-COMM-003`)
* **Strict Safety Prohibition:** Direct modification of PWM duty cycle, dead-time, or inner PID proportional/integral gains over Modbus is **strictly prohibited**.
* **Supervisory Setpoint Validation:** Modbus clients may only issue high-level operational commands (`SYS_CONTROL_CMD`) and voltage/current setpoints. The Gateway sanitizes and clamps all setpoints against pre-compiled safety envelopes before transmitting them across the IPC to the Control MCU.

### 8.2 Modbus Holding Registers Map ($40001 - 40013$)

| Register Address | Register Name | Data Type | Units / Scaling | Access | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`40001`** | `SYS_CONTROL_CMD` | `uint16_t` | Enum | R/W | `0x00` = Stop/Idle<br>`0x01` = Charge<br>`0x02` = Discharge<br>`0xFF` = Clear Latched Faults |
| **`40002`** | `BUS_VOLTAGE_RAW` | `uint16_t` | $10\text{ mV} / \text{LSB}$ | R | DC Bus Voltage (e.g., $2400 = 24.00\text{ V}$) |
| **`40003`** | `BAT_CURRENT_RAW` | `int16_t` | $10\text{ mA} / \text{LSB}$ | R | Battery Current (Signed: $+300 = +3.00\text{ A}$ charge, $-250 = -2.50\text{ A}$ discharge) |
| **`40004`** | `BAT_SOC` | `uint16_t` | $0.1\% / \text{LSB}$ | R | Battery State of Charge (e.g., $850 = 85.0\%$) |
| **`40005`** | `FAULT_STATUS_FLAGS` | `uint16_t` | Bitmap | R | Safety & Limit Bitmap (see bit definitions below) |
| **`40006`** | `VOUT` | `uint16_t` | $10\text{ mV} / \text{LSB}$ | R | Regulated Battery Terminal Voltage |
| **`40007`** | `IOUT` | `int16_t` | $10\text{ mA} / \text{LSB}$ | R | Filtered Inductor Output Current |
| **`40008`** | `TEMPERATURE` | `int16_t` | $0.1^\circ\text{C} / \text{LSB}$ | R | Power Stage Heatsink Temperature (e.g., $254 = 25.4^\circ\text{C}$) |
| **`40009`** | `CONTROL_STATUS` | `uint16_t` | Enum | R | `0` = Init, `1` = Idle, `2` = Charge, `3` = Discharge, `4` = Derating, `5` = Safe State |
| **`40010`** | `FAULT_CODE` | `uint16_t` | Hex Code | R | Hex code of active latched fault (e.g., `0xE001` = Tier-0 OC Break, `0xE002` = Tier-0 OV Break) |
| **`40011`** | `FW_VERSION` | `uint16_t` | BCD | R | Firmware Version (e.g., `0x0120` = v1.2.0) |
| **`40012`** | `SYSTEM_UPTIME_MSW`| `uint16_t` | Seconds | R | System Uptime 32-bit Counter (High 16 bits) |
| **`40013`** | `SYSTEM_UPTIME_LSW`| `uint16_t` | Seconds | R | System Uptime 32-bit Counter (Low 16 bits) |

#### `FAULT_STATUS_FLAGS` (Register `40005`) Bit Assignment:
* `Bit 0`: Over-Voltage Warning / Trip ($V_{bus} > 25.0\text{ V}$)
* `Bit 1`: Over-Current Warning / Trip ($I > 4.2\text{ A}$)
* `Bit 2`: Over-Temperature Warning / Trip ($T > 65.0^\circ\text{C}$)
* `Bit 3`: Under-Voltage Inhibit ($V_{bat} < 10.0\text{ V}$)
* `Bit 4`: IPC Link Timeout / Comm Lost
* `Bit 5`: IEC 60730 Self-Test Anomaly
* `Bit 6`: Window Watchdog / CSS Failure
* `Bit 7`: Tier-0 Hardware Break Trip Latched
* `Bit 8`: Battery BMS CAN Communication Lost
* `Bits 9–15`: Reserved for Future Expansion

---

## 9. Functional Safety & Cybersecurity Concept (PoC Scope)

### 9.1 IEC 60730 Class B-Oriented Safety Diagnostics (`REQ-SAFE`)

```
+===================================================================================================+
|                               IEC 60730 CLASS B DIAGNOSTIC SUITE                                  |
|                                                                                                   |
|  +--------------------------+  +--------------------------+  +---------------------------------+  |
|  | CPU Register Test        |  | RAM March C- Test        |  | Flash Memory CRC-32             |  |
|  | - Target: R0-R12, LR, PC |  | - Target: SRAM Data/BSS  |  | - Golden CRC in Image Header    |  |
|  | - Test: 0x5555 / 0xAAAA  |  | - Mode: Startup Full,    |  | - Hardware CRC Calculation Unit |  |
|  | - Action: Halt on Stuck  |  |   Runtime Sliced <=100ms |  | - Verify on boot & idle cycles  |  |
|  +--------------------------+  +--------------------------+  +---------------------------------+  |
|                                                                                                   |
|  +--------------------------+  +--------------------------+  +---------------------------------+  |
|  | Window Watchdog (IWDG)   |  | Clock Security (CSS)     |  | Invariable Plausibility Checks  |  |
|  | - Fixed Refresh Window   |  | - Monitors HSE 8MHz OSC  |  | - Dual-sampled sensor cross-chk |  |
|  |   (50ms +/- 10ms)        |  | - Hardware NMI on fail   |  | - dI/dt & dV/dt slew bounds     |  |
|  | - Early/Late kick resets |  | - Auto-switches to HSI   |  | - Duty cycle clamp [5% - 95%]   |  |
|  +--------------------------+  +--------------------------+  +---------------------------------+  |
+===================================================================================================+
```

* **`REQ-SAFE-001` (CPU Register Self-Test):** At boot prior to main control execution, the startup routine executes a destructive pattern test across all core ARM Cortex-M4 registers (R0–R12, SP, LR, APSR). If any bit fails to toggle between `0x55555555` and `0xAAAAAAAA`, the MCU halts execution in a dedicated trap loop.
* **`REQ-SAFE-002` (RAM March C- Algorithm):**
  - At startup: Destructive March C- validates the entire SRAM address space.
  - At runtime: Non-destructive March C- executes across operational SRAM slices within a background diagnostic task every $\le 100\text{ ms}$, ensuring execution times do not introduce jitter to time-critical loops.
* **`REQ-SAFE-003` (Flash Integrity Verification):** Hardware CRC-32 unit calculates the checksum over active application flash space and validates it against the golden CRC stored in the immutable image header table.
* **`REQ-SAFE-004` (Independent Window Watchdog & CSS):**
  - An independent watchdog (IWDG) must be kicked within a strictly bounded window ($50\text{ ms} \pm 10\text{ ms}$). Kicking too early or too late asserts a hardware MCU reset.
  - The Clock Security System (CSS) monitors the external high-speed crystal (HSE). If crystal failure occurs, CSS triggers an NMI interrupt, forces Timer Break PWM shutdown, and automatically fails over to the internal $16\text{ MHz}$ HSI oscillator.

### 9.2 ISO 21434 Cybersecurity Concept (`REQ-SEC`)
* **`REQ-SEC-001` (Structured Firmware Image Header):** All staged firmware binaries must carry a structured 256-byte header containing Image Magic (`0x42455353`), Target MCU Type, Monotonic Security Version Counter, SHA-256 Digest, and Cryptographic HMAC / Signature.
* **`REQ-SEC-002` (Monotonic Anti-Rollback):** The bootloader inspects the security version counter of any staged firmware update. If the counter is lower than the active installed version, the update is rejected and purged to prevent downgrade attacks.
* **`REQ-SEC-003` (Image Verification Prior to Swap):** Dual-bank staging images are fully authenticated and decrypted/verified in RAM before committing boot address pointers.

---

## 10. Flash Memory Partitioning & Bootloader Architecture

> **NOTE:** Memory sector and page layouts are subject to final microcontroller model selection.

```
+===================================================================================================+
|                                    FLASH PARTITIONING MEMORY MAP                                  |
|                             TODO [Hardware Selection Pending: STM32G474 vs STM32F446]             |
|                                                                                                   |
|  OPTION A: STM32G474RE (512 KB Dual-Bank Flash, 2 KB Uniform Pages)                               |
|  +------------------------------------+------------------------------------+                      |
|  | BANK 1 (256 KB - Pages 0 to 127)   | BANK 2 (256 KB - Pages 128 to 255) |                      |
|  |                                    |                                    |                      |
|  | [ Page 0-15: Bootloader (32 KB)  ] | [ Page 128-239: App Slot B (224KB) ]                      |
|  | [ Page 16-123: App Slot A (216KB)] |   (Staging / Alternate Bank)       |                      |
|  | [ Page 124-127: NV Config (8 KB) ] | [ Page 240-255: Key Store (32 KB)  ]                      |
|  |                                    |                                    |                      |
|  | * Supports true Dual-Bank Read-While-Write (RWW) and Zero-Downtime Bank Swapping               |
|  +------------------------------------+------------------------------------+                      |
|                                                                                                   |
|  OPTION B: STM32F446RE (512 KB Single-Bank Flash, Asymmetric Sectors)                             |
|  +-------------------------------------------------------------------------+                      |
|  | [ Sector 0 (16 KB) ]: Primary Secure Bootloader (Immutable)             |                      |
|  | [ Sector 1 (16 KB) ]: NVRAM Configuration & Monotonic Counter Table     |                      |
|  | [ Sector 2 (16 KB) ]: Cryptographic Public Key Storage & Metadata      |                      |
|  | [ Sector 3 (16 KB) ]: Reserved Diagnostic Log Flash                     |                      |
|  | [ Sector 4 (64 KB) ]: Application Slot A (Part 1)                       |                      |
|  | [ Sector 5 (128 KB)]: Application Slot A (Part 2 - Total Slot A: 192KB) |                      |
|  | [ Sector 6 (128 KB)]: Application Slot B (Part 1 - Staging Buffer)      |                      |
|  | [ Sector 7 (128 KB)]: Application Slot B (Part 2 - Total Slot B: 256KB) |                      |
|  |                                                                         |                      |
|  | * Requires In-Application Programming (IAP) staging and sector erase mgmt                      |
|  +-------------------------------------------------------------------------+                      |
+===================================================================================================+
```

### 10.1 MCU Comparison & Architectural Trade-Offs

| Evaluation Metric | STM32G474RE (Recommended for Power) | STM32F446RE (Alternative Architecture) |
| :--- | :--- | :--- |
| **Flash Architecture** | **512 KB Dual-Bank** ($2 \times 256\text{ KB}$ with $2\text{ KB}$ uniform pages) | **512 KB Single-Bank** (Asymmetric: $4 \times 16\text{ KB}$, $1 \times 64\text{ KB}$, $3 \times 128\text{ KB}$) |
| **OTA Bank Swapping** | **True Dual-Bank Swap:** Boot from Bank 1 or Bank 2 via `BFB2` bit without image copy. Zero downtime. | **IAP Sector Staging:** Requires copying Slot B image to Slot A while running in RAM or bootloader. |
| **Timer Resolution** | **High-Resolution Timer (HRTIM):** $184\text{ ps}$ resolution. Ideal for digital SMPS. | **Advanced Timer (TIM1/TIM8):** Standard timer @ $168\text{ MHz}$ ($\approx 5.95\text{ ns}$ resolution). |
| **Analog Integration** | 5x Ultra-Fast ADCs ($4\text{ MSPS}$), 7x DACs, 4x Comparators ($16\text{ ns}$ delay), 6x PGAs | 3x ADCs ($2.4\text{ MSPS}$), 2x DACs, No internal analog comparators |
| **Hardware Break** | Native HRTIM/TIM1 multi-source BKIN with internal comparator interconnect | TIM1 BKIN pin requires external comparator routing |

---

## 11. Verification, Testing & Quality Assurance

### 11.1 Quality Metrics & Standards
* **`NFR-CODE-01` (MISRA-C:2012 Compliance):** Core power stage drivers, PID algorithms, and safety modules shall comply with MISRA-C:2012 Mandatory and Required guidelines.
* **`NFR-TEST-01` (Automated Unit Testing):** All discrete math blocks (PID calculation, CRC routines, frame serialization, state machine transitions) shall achieve $>90\%$ line and branch coverage using the **Unity / CMock** test framework within the automated CI/CD pipeline.
* **`NFR-TEST-02` (Hardware-in-the-Loop Simulation):** Real-time closed-loop stability shall be validated on a hardware bench using resistive dummy loads, electronic DC loads, and programmable DC power supplies before live battery connection.

---

## 12. Supplementary Architecture Documentation Directory

For deep-dive implementation specifications, signal formulas, circuit parameters, and protocol frame structures, refer to the following architectural design documents under `docs/architecture/`:

* [`docs/architecture/timing_jitter_and_bench_verification.md`](docs/architecture/timing_jitter_and_bench_verification.md) - Jitter verification bench, DSO configuration, and DWT cycle counter telemetry.
* [`docs/architecture/hardware_sensing_and_analog_frontend.md`](docs/architecture/hardware_sensing_and_analog_frontend.md) - Analog front-end calculations, CSA INA240 circuitry, and resistive divider buffering.
* [`docs/architecture/fault_handling_and_safety.md`](docs/architecture/fault_handling_and_safety.md) - Multi-tier hardware/software fault hierarchy, comparator break input configuration, and IEC 60730 diagnostic procedures.
* [`docs/architecture/state_machine.md`](docs/architecture/state_machine.md) - Complete system control state machine specifications, state transitions, guard conditions, and timing timeouts.
* [`docs/architecture/ipc_protocol.md`](docs/architecture/ipc_protocol.md) - FreeRTOS task segregation, bounded IPC queues, SPI frame definitions, and ARQ state machine.
* [`docs/architecture/modbus_register_map.md`](docs/architecture/modbus_register_map.md) - SCADA Modbus-TCP/RTU register layout, scaling factors, data types, and supervisory control policies.
* [`docs/architecture/flash_memory_partitioning.md`](docs/architecture/flash_memory_partitioning.md) - Dual-Bank STM32G474 vs Asymmetric STM32F446 Flash layout, secure bootloader and anti-rollback staging.
