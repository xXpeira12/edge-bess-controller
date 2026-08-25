# Industrial Smart BESS & Power Management Controller (Desk-Scale PoC)
## Software Requirements Specification (SRS) & System Architecture Document

**Document Version:** 2.0.0  
**Target Platform:** Dual-MCU Architecture (Real-Time Control Core + Industrial Gateway Core)  
**Primary Control Core MCU:** **STM32G474RE** (ARM Cortex-M4F @ 170 MHz, HRTIM, Fast Internal Comparators, Dual-Bank Flash)  
**Secondary / Porting Control Core MCU:** **STM32F446RE** (ARM Cortex-M4F @ 168 MHz, TIM1, External Comparator Interconnect)  
**Gateway Core MCU:** **ESP32-WROOM-32** (Dual-Core Xtensa LX6 @ 240 MHz, FreeRTOS Preemptive Kernel)  
**Design Paradigm:** Hard Real-Time Deterministic Control, Multi-Tier Hardware/Software Safety, Non-Blocking Telemetry Isolation  
**PoC Standard Alignment:** IEC 60730 Class B-Oriented Safety Diagnostics & ISO 21434 Cybersecurity Concept  

---

## 1. Single Source of Truth (SSOT) Architecture Mapping

To guarantee absolute architectural consistency across all project specifications and implementations, the following Single Source of Truth mappings are established:

| Domain | Authoritative SSOT Document | Key SSOT Invariants & Parameters |
| :--- | :--- | :--- |
| **System Overview & Requirements** | `README.md` | Dual-MCU topology, operational envelopes, safety boundaries |
| **Timing, Jitter & Determinism** | `docs/architecture/timing_jitter_and_bench_verification.md` | $f_{sw} = 50\text{ kHz}$, $T_s = 20\,\mu\text{s}$, 4 jitter metrics, $\le \pm 50\text{ ns}$ limit |
| **Analog Front-End & Sensing** | `docs/architecture/hardware_sensing_and_analog_frontend.md` | $R_{shunt}=10\text{ m}\Omega$, INA240A1 ($G=20\text{ V/V}, 0.2\text{ V/A}$), $V_{ref}=1.65\text{ V}$ |
| **Safety, Faults & Latency** | `docs/architecture/fault_handling_and_safety.md` | Tier-0 latency ($485\text{ ns} \ll 2.0\,\mu\text{s}$), 3-tier fault matrix, IEC 60730, ISO 21434 |
| **Control Finite State Machine** | `docs/architecture/state_machine.md` | STM32 authoritative FSM, `RECOVERY_CHECK`, $2.0\text{ A/s}$ / $100\text{ A/s}$ slew |
| **Inter-Processor Comm (IPC)** | `docs/architecture/ipc_protocol.md` | Master-Slave SPI + `ALERT_OUT`, frame format, ARQ idempotency & wraparound |
| **Modbus SCADA Register Map** | `docs/architecture/modbus_register_map.md` | Registers $40001 - 40018$, mailbox semantics, $0\text{x00A5}$ clear key, atomic snapshot |
| **Flash Memory & Bootloader** | `docs/architecture/flash_memory_partitioning.md` | Symmetric $200\text{ KB}$ dual-bank slots, power-loss-safe metadata, confirmed boot |
| **Specification Consistency** | `tests/test_specification_consistency.py` | Automated cross-document mathematical & invariant test assertions |

---

## 2. System Overview & PoC Scope

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

### 2.1 Standards Compliance Phrasing (Desk-Scale PoC Pragmatism)
* **IEC 60730 Class B-Oriented Safety Diagnostics:** Firmware implements core diagnostic patterns inspired by IEC 60730 Class B requirements—including pre-execution deterministic CPU register tests (R0-R12, SP, LR, APSR patterns), non-destructive runtime sliced March C- SRAM tests, Flash CRC-32 integrity verification, independent watchdog (IWDG) timing windows ($50\text{ ms} \pm 10\text{ ms}$), and Clock Security System (CSS) monitoring.
* **ISO 21434 Cybersecurity Concept:** Foundational cybersecurity concepts include structured image headers, SHA-256 cryptographic hashing with ECDSA (secp256r1) digital signatures verified against on-chip immutable public keys, monotonic security version counters (anti-rollback), and strict separation of privileged control commands from untrusted telemetry paths.
* **Scope Boundary:** Low-voltage bench prototyping ($18.0\text{ V} - 24.0\text{ V}$ bus, $10.0\text{ V} - 14.6\text{ V}$ battery, $20\text{ W} - 50\text{ W}$ continuous). Mass-production certifications require dedicated external hardware safety interlocks, galvanic isolation barriers, and accredited laboratory certification.

---

## 3. Hardware Interfaces, Operational Boundaries & Analog Front-End

### 3.1 Operational Boundaries & Multi-Threshold Current Limits

| Parameter | Minimum | Nominal | Maximum | Unit | Remarks |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Input Bus Voltage ($V_{bus}$)** | $16.0$ | $24.0$ | $26.0$ | $\text{V}$ | Current-limited benchtop DC supply |
| **Battery Port Voltage ($V_{bat}$)** | $10.0$ | $12.8$ | $14.6$ | $\text{V}$ | 4S LiFePO4 / 3S Li-ion or programmable load |
| **Continuous Power Rating** | $-$ | $30.0$ | $50.0$ | $\text{W}$ | Convection cooled bench scale |
| **Normal Operating Current ($I_{op}$)** | $-3.5$ | $\pm 2.5$ | $+3.5$ | $\text{A}$ | Continuous operational envelope ($0.950\text{ V} \dots 2.350\text{ V}$) |
| **Software Warning Threshold ($I_{warn}$)** | $-4.0$ | $-$ | $+4.0$ | $\text{A}$ | Triggers soft derating / emergency ramp-down ($0.850\text{ V} / 2.450\text{ V}$) |
| **Hardware Emergency Trip ($I_{trip}$)** | $-5.0$ | $-$ | $+5.0$ | $\text{A}$ | Tier-0 Hardware Break to PWM LOW ($0.650\text{ V} / 2.650\text{ V}$) |
| **Linear ADC Saturation Limit** | $-8.25$ | $-$ | $+8.25$ | $\text{A}$ | Full scale $0.0\text{ V} \dots 3.3\text{ V}$ ADC range |
| **Hardware Over-Voltage Trip ($V_{trip}$)** | $-$ | $26.0$ | $26.5$ | $\text{V}$ | Tier-0 Hardware Break to PWM LOW ($\le 2.0\,\mu\text{s}$) |
| **PWM Switching Frequency ($f_{sw}$)** | $-$ | $50.0$ | $50.0$ | $\text{kHz}$ | Complementary with dead-time |
| **Dead-Time Insertion ($t_{dead}$)** | $250$ | $350$ | $500$ | $\text{ns}$ | Hardware dead-time in HRTIM/TIM1 |

### 3.2 Analog Front-End (AFE) Sensing Topology

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
  |                    | INA240A1 CSA         | (Enhanced PWM Rejection, Gain = 20 V/V)            |
  |                    | V_REF = 1.650V       | Transfer Factor: 0.200 V/A                         |
  |                    +----------------------+                                                    |
  |                               | Output: V_out = 1.650V +/- (0.200 V/A * I_L)                   |
  |                               | (-3.5A -> 0.950V, 0A -> 1.650V, +3.5A -> 2.350V)               |
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

* **`REQ-SENS-001` (DC Bus Voltage Sensing & Anti-Aliasing):** DC bus voltage is attenuated via a $10:1$ divider ($R_1 = 90.0\text{ k}\Omega, R_2 = 10.0\text{ k}\Omega \pm 0.1\%$). An op-amp buffer feeds a first-order RC anti-aliasing filter ($R = 1.0\text{ k}\Omega, C = 3.3\text{ nF}, f_c = 48.2\text{ kHz}$). At $f_{Nyquist} = 25\text{ kHz}$, attenuation is $-1.04\text{ dB}$ ($\theta = -27.4^\circ$); at $f_{sw} = 50\text{ kHz}$, attenuation is $-3.17\text{ dB}$ ($\theta = -46.0^\circ$).
* **`REQ-SENS-002` (Current Sensing Transfer Function):** Current is sensed via a $10\text{ m}\Omega$ precision shunt and an off-the-shelf **INA240A1** Current Sense Amplifier (Gain $G = 20\text{ V/V}$, sensitivity $0.200\text{ V/A}$, midpoint $V_{REF} = 1.650\text{ V}$):
  $$V_{csa\_out} = V_{REF} + (I_L \cdot R_{shunt} \cdot G) = 1.650\text{ V} + (I_L \times 0.200\,\text{V/A})$$
  - $\pm 3.5\text{ A}$ nominal operating range maps to $0.950\text{ V} \dots 2.350\text{ V}$ ($1179 \dots 2916$ ADC counts), well within linear ADC bounds.
  - $\pm 4.0\text{ A}$ software warning maps to $0.850\text{ V} \dots 2.450\text{ V}$ ($1055 \dots 3041$ ADC counts).
  - $\pm 5.0\text{ A}$ hardware break trip maps to $V_{comp\_low} = 0.650\text{ V}$ and $V_{comp\_high} = 2.650\text{ V}$ ($807 \dots 3289$ ADC counts).
* **`REQ-SENS-003` (Dual-Path Split & Primary Comparator):** CSA output splits into filtered ADC feedback ($f_c \approx 72.3\text{ kHz}$) and internal fast analog comparator (`COMP1` on STM32G474, $25\text{ ns}$ delay) connected directly to HRTIM/TIM1 `BKIN` for sub-microsecond hardware shutdown.

---

## 4. Real-Time Determinism & Jitter Verification Methodology

### 4.1 Four Jitter Metrics Disambiguation (`NFR-PERF-01`)

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

* **Control Loop Frequency ($f_{sw}$):** $50.0\text{ kHz}$ ($T_s = 20.0\,\mu\text{s}$).
* **Total Jitter Budget ($\Delta t_{jitter}$):** $\le \pm 50.0\text{ ns}$ ($\Delta T_{p-p} \le 100\text{ ns}$, $\le 17$ DWT cycles @ 170 MHz).
* **Execution Budget:** Inner current PID execution duration $\le 8.0\,\mu\text{s}$ ($40\%$ CPU load @ 170 MHz).
* **NVIC Priority:** `ADC_IRQHandler` / `HRTIM_Master_IRQHandler` assigned to **NVIC Priority 0** (highest priority, unmasked by FreeRTOS syscalls).

---

## 5. Multi-Tier Protection Architecture & End-to-End Latency

```
+===================================================================================================+
|                                MULTI-TIER PROTECTION ARCHITECTURE                                 |
|                                                                                                   |
|  TIER 0: SILICON HARDWARE BREAK (Autonomous, <= 2.0 microseconds total path)                      |
|  - Trigger: |I| > 5.0A (0.650V / 2.650V) or V_bus > 26.0V (Analog Comparators COMP1/COMP2)        |
|  - Action: HRTIM/TIM1 BKIN asynchronously forces PWM LOW / High-Z. Latched in silicon.            |
|  - Latency: T_shunt(10ns) + T_AFE(250ns) + T_comp(25ns) + T_mcu(50ns) + T_driver(50ns)           |
|             + T_power(100ns) = 485 ns worst-case (<< 2.0 us budget). Zero CPU dependency.         |
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

## 6. System Control State Machine (with `RECOVERY_CHECK`)

* **State Authority:** The STM32 Control Core FSM is the **exclusive, authoritative owner** of system state. Gateway and SCADA commands are requests only.
* **Invariant:** Clearing a fault (via `FAULT_CLEAR_CMD = 0x00A5`) transitions `SAFE_STATE` $\to$ `RECOVERY_CHECK` $\to$ `IDLE`. Power conversion **never automatically resumes** without a new explicit `START` command (`SYS_CONTROL_CMD = 1` or `2`).

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
    |     [ Warn Temp/SOC ] [ Warn Temp/SOC ]             |
    |            \            /                           |
    |             v          v                            |
    |       +---------------------+                       |
    |       |   DERATING_ACTIVE   | (Reason Bitmap: Temp, SOC, Bus Ripple)
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
             | - Sensor Re-check  | [0x00A5   | - Fault Code Latched  |
             | - Gate Check Passed|  ClearCmd]|=======================+
             +--------------------+
```

---

## 7. Gateway Core Architecture & Master-Slave IPC

* **Master-Slave SPI Model:** ESP32 is SPI Master; STM32 is SPI Slave with hardware `ALERT_OUT` interrupt line (`ACTIVE HIGH`, held until transaction acknowledged).
* **Idempotency & Sequence Wraparound:** `SEQ_NUM` ($0\text{x00} - 0\text{xFF}$ or $0\text{x0000} - 0\text{xFFFF}$) uniquely identifies transactions. If a duplicate `SEQ_NUM` arrives due to a lost ACK retry, STM32 does not re-execute the command and returns the cached result.
* **Fail-Safe Policy:** If IPC communication is lost $> 500\text{ ms}$ during `CHARGE_ACTIVE` or `DISCHARGE_ACTIVE`, STM32 autonomously initiates an emergency software ramp-down ($100\text{ A/s}$) to `IDLE`.

---

## 8. Industrial Modbus Holding Registers Map ($40001 - 40018$)

| Register | Register Name | Data Type | Units / Scaling | Access | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`40001`** | `SYS_CONTROL_CMD` | `uint16_t` | Enum | R/W | Edge-triggered mailbox: `0`=STOP, `1`=START_CHARGE, `2`=START_DISCHARGE |
| **`40002`** | `BUS_VOLTAGE_RAW` | `uint16_t` | $10\text{ mV/LSB}$ | R | DC Bus Voltage (`0xFFFF` = Sentinel Invalid) |
| **`40003`** | `BAT_CURRENT_RAW` | `int16_t` | $10\text{ mA/LSB}$ | R | Battery Current (`0x7FFF` = Sentinel Invalid) |
| **`40004`** | `BAT_SOC` | `uint16_t` | $0.1\%\text{/LSB}$ | R | State of Charge (`0xFFFF` = Sentinel Invalid) |
| **`40005`** | `ACTIVE_FAULT_FLAGS` | `uint16_t` | Bitmap | R | Active real-time fault flag bitmap |
| **`40006`** | `VOUT` | `uint16_t` | $10\text{ mV/LSB}$ | R | Regulated Output Voltage (`0xFFFF` = Invalid) |
| **`40007`** | `IOUT` | `int16_t` | $10\text{ mA/LSB}$ | R | Output Current (`0x7FFF` = Invalid) |
| **`40008`** | `TEMPERATURE` | `int16_t` | $0.1^\circ\text{C/LSB}$ | R | Heatsink Temperature (`0x7FFF` = Invalid) |
| **`40009`** | `OPERATING_MODE` | `uint16_t` | Enum | R | `0`=IDLE, `1`=CHARGE, `2`=DISCHARGE, `3`=SAFE |
| **`40010`** | `FAULT_CODE` | `uint16_t` | Hex Code | R | Highest priority active fault code |
| **`40011`** | `FW_VERSION` | `uint16_t` | BCD | R | Firmware Version (e.g. `0x0200` = v2.0.0) |
| **`40012`** | `UPTIME_MSW` | `uint16_t` | Seconds | R | Atomic 32-bit Uptime Counter (MSW) |
| **`40013`** | `UPTIME_LSW` | `uint16_t` | Seconds | R | Atomic 32-bit Uptime Counter (LSW) |
| **`40014`** | `FAULT_CLEAR_CMD` | `uint16_t` | Magic Key | R/W | Dedicated Fault Clear: write `0x00A5` to clear faults |
| **`40015`** | `CMD_RESULT` | `uint16_t` | Enum | R | `0`=None, `1`=Accepted, `2`=Rejected_InvalidState, `3`=Rejected_FaultActive, `4`=Rejected_Limit, `5`=Rejected_Safety, `6`=Rejected_IPC |
| **`40016`** | `CMD_SEQ` | `uint16_t` | Counter | R | Echo of last processed command sequence number |
| **`40017`** | `FSM_STATE` | `uint16_t` | Enum | R | Detailed Internal FSM State ($0-9$) |
| **`40018`** | `LATCHED_FAULT_FLAGS`| `uint16_t` | Bitmap | R | Historical latched fault bitmap (cleared by 40014) |

* **Modbus Exception 0x02 (Illegal Data Address):** Raised if an external client attempts to write to read-only registers ($40002 - 40013, 40015 - 40018$). Direct raw PWM duty cycle writes are strictly prohibited.

---

## 9. Flash Memory Partitioning & Confirmed Boot Architecture

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

* **Slot Symmetry:** Slot A capacity == Slot B capacity = $200\text{ KB}$ ($100\text{ pages}$ each).
* **Power-Loss Safe Metadata & Confirmed Boot:** Bootloader validates SHA-256 and ECDSA signature via on-chip public key. On new update, image boots into `TESTING` state; application must complete safety diagnostics and write `CONFIRM`. If unconfirmed reset occurs $\ge 3$ times, bootloader automatically rolls back to previous confirmed image. Device never stores private signing keys.
