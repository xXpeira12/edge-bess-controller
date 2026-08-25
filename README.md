# Industrial Smart BESS & Power Management Controller (Desk-Scale PoC)
## Software Requirements Specification (SRS) & System Architecture Document

**Document Version:** 1.3.0  
**Target Platform:** Dual-MCU Architecture (Real-Time Control Core + Industrial Gateway Core)  
**Primary Control Core MCU:** **STM32G474RE** (ARM Cortex-M4F @ 170 MHz, HRTIM, Fast Internal Comparators, Dual-Bank Flash)  
**Secondary / Porting Control Core MCU:** **STM32F446RE** (ARM Cortex-M4F @ 168 MHz, TIM1, External Comparator Interconnect)  
**Gateway Core MCU:** **ESP32-WROOM-32** (Dual-Core Xtensa LX6 @ 240 MHz, FreeRTOS Preemptive Kernel)  
**Design Paradigm:** Hard Real-Time Deterministic Control, Multi-Tier Hardware/Software Safety, Non-Blocking Telemetry Isolation  
**PoC Standard Alignment:** IEC 60730 Class B-Oriented Safety Diagnostics & ISO 21434 Cybersecurity Concept  

---

## 1. System Overview & PoC Scope

This document specifies the software requirements, system architecture, safety mechanisms, communication protocols, and verification methodologies for the **Desk-Scale Proof-of-Concept (PoC) Industrial Battery Energy Storage System (BESS) & Power Management Controller**.

The system utilizes a **Dual-MCU Architecture** physically segregating safety-critical, hard real-time power conversion loops from external network stacks, fieldbus protocols, and cloud telemetry.

```
+===================================================================================================+
|                                  DESK-SCALE BESS CONTROLLER NODE                                  |
|                                                                                                   |
|  +-------------------------------------+                   +-----------------------------------+  |
|  |     PRIMARY CONTROL CORE (STM32G4)  |                   |    GATEWAY CORE (ESP32 Dual-Core) |  |
|  |  - Cascaded Current/Voltage PID     |                   |  - FreeRTOS Preemptive Tasks      |  |
|  |  - 50 kHz HRTIM & Synchronous ADC   |    Full-Duplex    |  - Non-Blocking Ring Buffers      |  |
|  |  - IEC 60730 Class B Diagnostics    |     SPI + DMA     |  - Modbus-TCP / Modbus-RTU Server |  |
|  |  - Tier-0 Fast HW Break Trip (BKIN) | <===============> |  - Isolated CAN 2.0B BMS Master   |  |
|  |  - Cycle-by-Cycle Current Limiting  |  + ALERT_OUT Line |  - MQTT / TLS Cloud Telemetry     |  |
|  |  - Symmetric Dual-Bank Flash (200KB)|   (Robust ARQ)    |  - OTA Image Staging & Verifier   |  |
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
* **IEC 60730 Class B-Oriented Safety Diagnostics:** The firmware implements core diagnostic patterns inspired by IEC 60730 Class B requirements—including pre-execution deterministic CPU register tests (R0-R12, SP, LR, APSR patterns), non-destructive runtime sliced March C- SRAM tests, Flash CRC-32 integrity verification, independent watchdog (IWDG) timing windows ($50\text{ ms} \pm 10\text{ ms}$), and Clock Security System (CSS) monitoring. These serve as architectural proofs rather than certified commercial compliance.
* **ISO 21434 Cybersecurity Concept:** The bootloader and staging architecture implement foundational cybersecurity concepts, such as structured image headers, SHA-256 cryptographic hashing with ECDSA (secp256r1) digital signatures verified against on-chip immutable public keys, monotonic security version counters (anti-rollback), and strict separation of privileged control commands from untrusted telemetry paths.
* **Scope Boundary:** This design targets low-voltage bench prototyping ($18.0\text{ V} - 24.0\text{ V}$ bus, $10.0\text{ V} - 14.6\text{ V}$ battery, $20\text{ W} - 50\text{ W}$ continuous). Mass-production certifications (e.g., UL 1973, UL 9540, IEC 62619, full SIL-3/ASIL-D certification) require dedicated external hardware safety interlocks, physical galvanic isolation barriers, and accredited lab validation.

---

## 2. Hardware Interfaces, Operational Boundaries & Analog Front-End

### 2.1 Operational Boundaries & Multi-Threshold Current Limits

| Parameter | Minimum | Nominal | Maximum | Unit | Remarks |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Input Bus Voltage ($V_{bus}$)** | $16.0$ | $24.0$ | $26.0$ | $\text{V}$ | Current-limited benchtop DC supply |
| **Battery Port Voltage ($V_{bat}$)** | $10.0$ | $12.8$ | $14.6$ | $\text{V}$ | 4S LiFePO4 / 3S Li-ion or programmable load |
| **Continuous Power Rating** | $-$ | $30.0$ | $50.0$ | $\text{W}$ | Convection cooled bench scale |
| **Normal Operating Current ($I_{op}$)** | $-3.5$ | $\pm 2.5$ | $+3.5$ | $\text{A}$ | Continuous operational envelope |
| **Software Warning Threshold ($I_{warn}$)** | $-4.0$ | $-$ | $+4.0$ | $\text{A}$ | Triggers soft derating / emergency ramp-down |
| **Hardware Emergency Trip ($I_{trip}$)** | $-5.0$ | $-$ | $+5.0$ | $\text{A}$ | Tier-0 Hardware Break to PWM LOW ($\le 2.0\,\mu\text{s}$) |
| **Hardware Over-Voltage Trip ($V_{trip}$)** | $-$ | $26.0$ | $26.5$ | $\text{V}$ | Tier-0 Hardware Break to PWM LOW ($\le 2.0\,\mu\text{s}$) |
| **PWM Switching Frequency ($f_{sw}$)** | $-$ | $50.0$ | $50.0$ | $\text{kHz}$ | Complementary with dead-time |
| **Dead-Time Insertion ($t_{dead}$)** | $250$ | $350$ | $500$ | $\text{ns}$ | Hardware dead-time in HRTIM/TIM1 |

### 2.2 Analog Front-End (AFE) Sensing Topology & Anti-Aliasing Filter Design

```
                                ANALOG SENSING FRONT-END TOPOLOGY
                                
  +------------------------------------------------------------------------------------------------+
  | VOLTAGE SENSING PATH (DC Bus / Battery Terminal)                                               |
  |                                                                                                |
  |  V_BUS (18-24V) ----[ R1: 90k 0.1% ]----+----[ R_filt: 1k ]----+-----> MCU ADC Pin (0-3.0V)  |
  |                                         |                      |        (Synchronous Center-Pt)|
  |                                  [ R2: 10k 0.1% ]           [ C_filt: 3.3nF ]                  |
  |                                         |     (fc ~ 48.2 kHz)  |                               |
  |                                        GND                    GND                              |
  |                                         |                                                      |
  |                                         +----[ Buffer Op-Amp ]--------> MCU COMP2 (Tier 0)     |
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
  |                    | INA240A1 / INA180    | (Enhanced PWM Rejection, Gain = 40 V/V)            |
  |                    | V_REF = 1.650V       | Transfer Factor: 0.400 V/A                         |
  |                    +----------------------+                                                    |
  |                               | Output: V_out = 1.65V +/- (0.400 V/A * I_L)                    |
  |                               | (-3.5A -> 0.25V, 0A -> 1.65V, +3.5A -> 3.05V)                  |
  |                               +------------------------+                                       |
  |                               |                        |                                       |
  |                      [ Low-Pass Filter ]               |                                       |
  |                       R=1k, C=2.2nF (fc~72.3kHz)       |                                       |
  |                               |                        |                                       |
  |                               v                        v                                       |
  |                         MCU ADC Channel         MCU COMP1 (Primary)                            |
  |                     (Synchronous 50 kHz)       (Tier-0 Over-Current Trip)                      |
  |                                                        |                                       |
  |                                                        v                                       |
  |                                              HRTIM / TIM1 BKIN Pin                             |
  |                                            (PWM Forced LOW <= 2.0 us)                          |
  +------------------------------------------------------------------------------------------------+
```

* **`REQ-SENS-001` (DC Bus Voltage Sensing & Anti-Aliasing):** DC bus voltage is attenuated via a $10:1$ divider ($R_1 = 90.0\text{ k}\Omega, R_2 = 10.0\text{ k}\Omega \pm 0.1\%$). An op-amp buffer feeds a first-order RC anti-aliasing filter ($R = 1.0\text{ k}\Omega, C = 3.3\text{ nF}, f_c = 48.2\text{ kHz}$). At the $25\text{ kHz}$ Nyquist frequency, attenuation is $-1.7\text{ dB}$; at the $50\text{ kHz}$ switching frequency, attenuation is $-4.5\text{ dB}$, with phase lag deterministically compensated in PID loop coefficients.
* **`REQ-SENS-002` (Current Sensing Transfer Function):** Current is sensed via a $10\text{ m}\Omega$ precision shunt and an INA240 Current Sense Amplifier configured with Gain $G = 40\text{ V/V}$ and mid-rail reference $V_{REF} = 1.650\text{ V}$:
  $$V_{csa\_out} = 1.650\text{ V} + (I_L \times 0.010\,\Omega \times 40\,\text{V/V}) = 1.650\text{ V} + (I_L \times 0.400\,\text{V/A})$$
  - Continuous $\pm 3.5\text{ A}$ operating range maps to $0.250\text{ V} \dots 3.050\text{ V}$ ($310 \dots 3785$ ADC counts on 12-bit 3.3V ADC), leaving generous headroom against $0\text{V}$ and $3.3\text{V}$ rail saturation.
  - Emergency $\pm 5.0\text{ A}$ trip thresholds correspond to $-0.35\text{ V}$ and $+3.65\text{ V}$ (clamped to supply rails).
* **`REQ-SENS-003` (Dual-Path Split & Primary Comparator):** The CSA output splits into:
  1. Filtered ADC channel ($f_c \approx 72.3\text{ kHz}$) for $50\text{ kHz}$ discrete digital PID loop execution.
  2. Internal fast analog comparator (`COMP1` on STM32G474 as PRIMARY path, $16\text{ ns}$ delay) connected directly to HRTIM/TIM1 `BKIN` for sub-microsecond hardware shutdown.

---

## 3. Real-Time Determinism & Jitter Verification Methodology

### 3.1 Four Jitter Metrics Disambiguation (`NFR-PERF-01`)
To ensure rigorous real-time determinism across the power stage, four distinct timing metrics are defined and tracked:

```
  +-------------------------------------------------------------------------------------------------+
  | 1. Trigger Jitter (t_trig_jitter):                                                              |
  |    Timer TRGO event to ADC Sample-and-Hold aperture initiation. Limit: <= +/- 5 ns              |
  | 2. Interrupt Latency Jitter (t_irq_jitter):                                                     |
  |    ADC End-of-Conversion (EOC) pulse to first instruction of ADC_IRQHandler. Limit: <= +/- 15 ns|
  | 3. Execution Time Jitter (t_exec_jitter):                                                       |
  |    ISR entry to PID math & saturation computation completion. Limit: <= +/- 20 ns               |
  | 4. Sample-to-Duty-Update Timing Jitter (t_update_jitter):                                       |
  |    ADC instantaneous sample to physical PWM register (CCR/CMP) reload effect. Limit: <= +/- 50 ns|
  +-------------------------------------------------------------------------------------------------+
```

* **Control Loop Switching Frequency ($f_{sw}$):** $50.0\text{ kHz}$ ($T_s = 20.0\,\mu\text{s}$).
* **Total End-to-End Jitter ($\Delta t_{jitter}$):** $\le \pm 50.0\text{ ns}$ ($\Delta T_{p-p} \le 100\text{ ns}$).
* **Execution Budget:** Inner current PID execution duration $\le 8.0\,\mu\text{s}$ ($40\%$ CPU load @ 170 MHz).
* **NVIC Priority:** `ADC_IRQHandler` / `HRTIM_Master_IRQHandler` assigned to **NVIC Priority 0** (highest priority, unmasked by FreeRTOS syscalls).

### 3.2 Bench Verification Methodology
1. **Fast GPIO Pin Toggle:** Dedicated high-speed GPIO toggled at ISR entry/exit (1 CPU cycle register write).
2. **DSO Infinite Persistence & Histogram:** Digital Storage Oscilloscope ($\ge 100\text{ MHz}$, $\ge 1\text{ GSa/s}$) triggered on TIM1/HRTIM TRGO, measuring delay to GPIO toggle with infinite persistence and horizontal histogram over $\ge 100,000$ consecutive cycles ($\ge 2.0\text{ s}$ continuous runtime).
3. **Cortex-M4 DWT Telemetry:** `DWT->CYCCNT` cycle counter measures execution cycles per ISR; min/max cycles reported over telemetry.

---

## 4. Multi-Tier Protection Architecture & Slew Rates

```
+===================================================================================================+
|                                MULTI-TIER PROTECTION ARCHITECTURE                                 |
|                                                                                                   |
|  TIER 0: SILICON HARDWARE BREAK (Autonomous, <= 2.0 microseconds total path)                      |
|  - Trigger: I > 5.0A or V_bus > 26.0V (Analog Comparators COMP1/COMP2)                            |
|  - Action: HRTIM/TIM1 BKIN asynchronously forces PWM LOW / High-Z. Latched in silicon.            |
|  - Latency: Sensor(350ns) + COMP(16ns) + Matrix(5ns) + Timer(25ns) + Driver(20ns) + Gate(60ns)    |
|             = ~476 ns worst-case total latency (<< 2.0 us limit). Zero CPU dependency.            |
|                                                                                                   |
|  TIER 1: SOFTWARE EMERGENCY RAMP-DOWN (Fast Supervisory, 100 A/s Slew Rate)                       |
|  - Trigger: Level 2 Fault (Soft OC > 4.0A, Soft OT > 65C, UVLO < 9.5V, IPC Timeout > 500ms)       |
|  - Action: Decelerates current setpoint at 100 A/s (5.0A -> 0A in <= 50 ms), disables PWM,       |
|             transitions FSM to IDLE.                                                              |
|                                                                                                   |
|  TIER 2: NORMAL OPERATION RAMPING (Commanded Setpoints, 2.0 A/s Slew Rate)                        |
|  - Trigger: Normal start/stop and setpoint tracking.                                              |
|  - Action: Ramps current at 2.0 A/s (2 mA per 1 ms FSM supervisory tick).                         |
+===================================================================================================+
```

---

## 5. Multi-Level Fault Handling Framework

| Fault Level | Examples | Slew Rate & Action | Recovery Policy |
| :--- | :--- | :--- | :--- |
| **Level 1: WARNING** | High Temp ($55-65^\circ\text{C}$), Low SOC ($10-15\%$), Isolated SPI drop | Dynamic current derating ($20-50\%$), set register `40005` warning flags. Continuous run. | Auto-clears when temperature $< 50^\circ\text{C}$ / $\text{SOC} > 18\%$. |
| **Level 2: FAULT** | Soft OC ($> 4.0\text{ A}$), Soft OT ($> 65^\circ\text{C}$), UVLO ($< 9.5\text{ V}$), IPC Timeout ($> 500\text{ ms}$) | **Emergency software ramp-down at $100\text{ A/s}$** ($50\text{ ms}$ to $0\text{ A}$), disable PWM, transition to `IDLE`. | Requires fault clearing via Modbus register `40014 = 0x00A5`. |
| **Level 3: CRITICAL** | Hardware OC ($> 5.0\text{ A}$), Hardware OV ($> 26.0\text{ V}$), IEC 60730 Self-Test Fail, Watchdog / CSS Trip | **Tier 0 Hardware Break Trip ($\le 2.0\,\mu\text{s}$)** forces PWM `LOW`, open relays, latches `SAFE_STATE`. | Requires authenticated fault clear $\to$ `RECOVERY_CHECK` $\to$ `IDLE` $\to$ new explicit `START` command. |

---

## 6. System Control State Machine (with `RECOVERY_CHECK`)

```
                            SYSTEM CONTROL STATE MACHINE
                            
            +-------------------------------------------------------+
            |                       POWER_ON                        |
            +-------------------------------------------------------+
                                        |
                                        v
            +-------------------------------------------------------+
            |                  INIT & SELF-TEST                     |
            |  - IEC 60730 Reg Test (R0-R12, SP, LR, APSR patterns) |
            |  - SRAM Sliced March C- & Flash Golden CRC-32         |
            +-------------------------------------------------------+
                       |                                  |
            [ Self-Test Passed ]               [ Self-Test Failed / HW Trip ]
                       v                                  |
            +----------------------+                      |
    +-----> |         IDLE         |                      |
    |       |  - PWM High-Z        |                      |
    |       |  - Relays Open       |                      |
    |       |  - Sliced Diagnostics|                      |
    |       +----------------------+                      |
    |            |            |                           |
    |   [ Cmd = Charge ]   [ Cmd = Discharge ]            |
    |            v            v                           |
    |     +------------+ +---------------+                |
    |     | CHARGE_RAMP| | DISCHARGE_RAMP|                |
    |     | (2.0 A/s)  | | (2.0 A/s)     |                |
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
  [ Level 2 Fault: Emergency Ramp-Down (100 A/s) ]        |
  +---------------------------------------+               |
  |                                                       |
  v                                                       | [ Level 3 Critical Fault: ]
[ Emergency Ramp-Down (<= 50ms) ]                         | [ Instant Tier-0 Break    ]
  |                                                       |
  +-----------------> IDLE                                v
                        ^                     +=======================+
                        |                     |      SAFE_STATE       |
             +--------------------+           | - Hardware PWM Break  |
             |   RECOVERY_CHECK   | <---------| - Relays Open         |
             | - Sensor Re-check  | [ClearCmd]| - Fault Code Latched  |
             | - Gate Check Passed|           +=======================+
             +--------------------+
```

---

## 7. Gateway Core Architecture & Master-Slave IPC

### 7.1 Master-Slave SPI Model & ALERT_OUT Interrupt Line
* **Master-Slave Topology:** ESP32 is SPI Master; STM32 is SPI Slave.
* **Slave Interrupt Signalling:** STM32 cannot initiate SPI transfers on its own. When an urgent fault occurs or periodic telemetry is ready, STM32 asserts the `ALERT_OUT` GPIO line (`ACTIVE HIGH`).
* **Master Service Routine:** The ESP32 detects the rising edge on `ALERT_IN` via GPIO interrupt and immediately executes an SPI DMA transaction to read the frame from the STM32.

```
  +-----------------------+                         +----------------------+
  | CONTROL CORE (STM32)  |                         | GATEWAY CORE (ESP32) |
  | (SPI Slave + DMA)     |                         | (SPI Master + DMA)   |
  |                       |   ALERT_OUT (ACTIVE HIGH)                      |
  |  [ Fault / Telemetry ]+========================>| [ GPIO ISR Trigger ] |
  |  [ Frame Staged in DMA|                         | [ SPI Master Read  ] |
  |                       |<========================+                      |
  |                       |   SPI DMA Clock / Data  |                      |
  +-----------------------+                         +----------------------+
```

### 7.2 Robust SPI Frame Protocol
* Preamble `0xA55A`, `PROTO_VER`, `SEQ_NUM`, `MSG_TYPE`, `MSG_FLAGS` (`ACK`/`NACK`/`RETRY`), `PAYLOAD_LEN` ($0-64\text{ B}$), `PAYLOAD`, and trailing `CRC16-CCITT` (`0x1021`, init `0xFFFF`).
* ARQ timeout: $5.0\text{ ms}$, maximum $3$ retries before degraded mode.

---

## 8. Industrial Modbus Holding Registers Map ($40001 - 40018$)

| Register | Register Name | Data Type | Units / Scaling | Access | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`40001`** | `SYS_CONTROL_CMD` | `uint16_t` | Enum | R/W | `0`=STOP, `1`=START_CHARGE, `2`=START_DISCHARGE |
| **`40002`** | `BUS_VOLTAGE_RAW` | `uint16_t` | $10\text{ mV/LSB}$ | R | DC Bus Voltage (`0xFFFF` = Invalid Sentinel) |
| **`40003`** | `BAT_CURRENT_RAW` | `int16_t` | $10\text{ mA/LSB}$ | R | Battery Current (`0x7FFF` = Invalid Sentinel) |
| **`40004`** | `BAT_SOC` | `uint16_t` | $0.1\%\text{/LSB}$ | R | State of Charge (`0xFFFF` = Invalid Sentinel) |
| **`40005`** | `ACTIVE_FAULT_FLAGS` | `uint16_t` | Bitmap | R | Active real-time fault flag bitmap |
| **`40006`** | `VOUT` | `uint16_t` | $10\text{ mV/LSB}$ | R | Regulated Output Voltage (`0xFFFF` = Invalid) |
| **`40007`** | `IOUT` | `int16_t` | $10\text{ mA/LSB}$ | R | Output Current (`0x7FFF` = Invalid) |
| **`40008`** | `TEMPERATURE` | `int16_t` | $0.1^\circ\text{C/LSB}$ | R | Heatsink Temperature (`0x7FFF` = Invalid) |
| **`40009`** | `OPERATING_MODE` | `uint16_t` | Enum | R | `0`=IDLE, `1`=CHARGE, `2`=DISCHARGE, `3`=SAFE |
| **`40010`** | `FAULT_CODE` | `uint16_t` | Hex Code | R | Highest priority active fault code |
| **`40011`** | `FW_VERSION` | `uint16_t` | BCD | R | Firmware Version (e.g. `0x0130` = v1.3.0) |
| **`40012`** | `UPTIME_MSW` | `uint16_t` | Seconds | R | System Uptime 32-bit Counter (MSW) |
| **`40013`** | `UPTIME_LSW` | `uint16_t` | Seconds | R | System Uptime 32-bit Counter (LSW) |
| **`40014`** | `FAULT_CLEAR_CMD` | `uint16_t` | Magic Cmd | R/W | Dedicated Fault Clear: write `0x00A5` to request clear |
| **`40015`** | `CMD_RESULT` | `uint16_t` | Enum | R | Command execution result (`0`=OK, `1`=Err, `2`=Rejected) |
| **`40016`** | `CMD_SEQ` | `uint16_t` | Counter | R | Echo of last processed command sequence number |
| **`40017`** | `FSM_STATE` | `uint16_t` | Enum | R | Internal FSM state enum ($0-9$) |
| **`40018`** | `LATCHED_FAULT_FLAGS`| `uint16_t` | Bitmap | R | Historical latched fault bitmap (cleared by 40014) |

---

## 9. Flash Memory Partitioning & Secure Bootloader Architecture

```
+===================================================================================================+
|                                    FLASH PARTITIONING MEMORY MAP                                  |
|                                                                                                   |
|  PRIMARY TARGET: STM32G474RE (512 KB Dual-Bank Flash, Symmetric 200 KB App Slots)                 |
|  +------------------------------------+------------------------------------+                      |
|  | BANK 1 (256 KB - Pages 0 to 127)   | BANK 2 (256 KB - Pages 128 to 255) |                      |
|  |                                    |                                    |                      |
|  | [ Page 0-15: Bootloader (32 KB)  ] | [ Page 128-227: App Slot B (200KB)]|                      |
|  | [ Page 16-115: App Slot A (200KB)] |   (Symmetric Staging/Alternate)    |                      |
|  | [ Page 116-123: NV Config (16 KB)] | [ Page 228-243: Diag Log (32 KB)  ]|                      |
|  | [ Page 124-127: Key Region (8 KB)] | [ Page 244-255: Metadata (24 KB)  ]|                      |
|  +------------------------------------+------------------------------------+                      |
+===================================================================================================+
```

* **Symmetric Slots:** Slot A and Slot B have identical capacity ($200\text{ KB}$ each).
* **Fixed Bootloader:** Immutable $32\text{ KB}$ bootloader at base address validates image SHA-256 and ECDSA signature via on-chip public key, verifies anti-rollback version, and enforces a 3-attempt confirmed boot mechanism with automatic fallback.
