# Industrial Smart BESS & Power Management Controller (Desk-Scale PoC)
## Software Requirements Specification (SRS) & System Architecture Document

**Document Version:** 3.0.0  
**Target Platform:** Dual-MCU Architecture (Real-Time Control Core + Industrial Gateway Core)  
**Primary Control Core MCU:** **STM32G474RE** (ARM Cortex-M4F @ 170 MHz, HRTIM, Fast Internal Comparators, Symmetric Dual-Bank Flash)  
**Secondary / Porting Control Core MCU:** **STM32F446RE** (ARM Cortex-M4F @ 168 MHz, TIM1, External Comparator Interconnect)  
**Gateway Core MCU:** **ESP32-WROOM-32** (Dual-Core Xtensa LX6 @ 240 MHz, FreeRTOS Preemptive Kernel)  
**Design Paradigm:** Hard Real-Time Deterministic Control, Multi-Tier Hardware/Software Safety, Non-Blocking Telemetry Isolation  
**PoC Standard Alignment:** IEC 60730 Class B-Oriented Safety Diagnostics & ISO 21434 Cybersecurity Concept  

---

## 1. Single Source of Truth (SSOT) Architecture Mapping

| Domain | Authoritative SSOT Document | Key SSOT Invariants & Parameters |
| :--- | :--- | :--- |
| **System Overview & Requirements** | `README.md` | Dual-MCU topology, operational envelopes, safety boundaries |
| **Timing, Jitter & Determinism** | `docs/architecture/timing_jitter_and_bench_verification.md` | $f_{sw} = 50\text{ kHz}$, $T_s = 20\,\mu\text{s}$, 4 jitter metrics, DSO vs DWT scope |
| **Analog Front-End & Sensing** | `docs/architecture/hardware_sensing_and_analog_frontend.md` | $R_{shunt}=10\text{ m}\Omega$, INA240A1 ($G=20\text{ V/V}$), $T_{CSA\_cross}=300\text{ns}$, pin routing |
| **Safety, Faults & Latency** | `docs/architecture/fault_handling_and_safety.md` | Distinct OC ($491\text{ns}$) & OV ($341\text{ns}$) latency budgets, tolerance budget |
| **Control Finite State Machine** | `docs/architecture/state_machine.md` | STM32 authoritative FSM, `RECOVERY_CHECK`, quantified derating hysteresis |
| **Inter-Processor Comm (IPC)** | `docs/architecture/ipc_protocol.md` | Master-Slave SPI, `SESSION_ID`, sequence wraparound, transaction idempotency |
| **Modbus SCADA Register Map** | `docs/architecture/modbus_register_map.md` | Registers $40001 - 40018$, mailbox semantics, $0\text{x00A5}$ clear key (SAFE_STATE only) |
| **Flash Memory & Bootloader** | `docs/architecture/flash_memory_partitioning.md` | Fixed base bootloader, symmetric $200\text{ KB}$ slots, power-loss-safe metadata |
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
|  |  - Fixed Bootloader + 200KB Slots   |   (Robust ARQ)    |  - OTA Image Staging & Verifier   |  |
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

---

## 3. Hardware Interfaces, Operational Boundaries & Analog Front-End

### 3.1 Operational Boundaries & Tolerance Budget

| Parameter | Minimum | Nominal | Maximum | Unit | Remarks |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Input Bus Voltage ($V_{bus}$)** | $16.0$ | $24.0$ | $26.0$ | $\text{V}$ | Current-limited benchtop DC supply |
| **Battery Port Voltage ($V_{bat}$)** | $10.0$ | $12.8$ | $14.6$ | $\text{V}$ | 4S LiFePO4 / 3S Li-ion or programmable load |
| **Continuous Power Rating** | $-$ | $30.0$ | $50.0$ | $\text{W}$ | Convection cooled bench scale |
| **Normal Operating Current ($I_{op}$)** | $-3.5$ | $\pm 2.5$ | $+3.5$ | $\text{A}$ | Continuous operational envelope ($0.950\text{ V} \dots 2.350\text{ V}$) |
| **Software Warning Threshold ($I_{warn}$)** | $-4.0$ | $-$ | $+4.0$ | $\text{A}$ | Triggers soft derating / emergency ramp-down ($0.850\text{ V} / 2.450\text{ V}$) |
| **Hardware Emergency Trip ($I_{trip}$)** | $\pm 4.85$ | $\pm 5.0$ | $\pm 5.15$ | $\text{A}$ | Tolerance budget: $\pm 0.15\text{ A}$ ($\pm 3\%$) worst-case |
| **Linear ADC Saturation Limit** | $-8.25$ | $-$ | $+8.25$ | $\text{A}$ | Full scale $0.0\text{ V} \dots 3.3\text{ V}$ ADC range |
| **Hardware Over-Voltage Trip ($V_{trip}$)** | $25.5$ | $26.0$ | $26.5$ | $\text{V}$ | Tier-0 Hardware Break to PWM LOW ($2.600\text{ V}$ threshold) |
| **PWM Switching Frequency ($f_{sw}$)** | $-$ | $50.0$ | $50.0$ | $\text{kHz}$ | Complementary with dead-time |
| **Dead-Time Insertion ($t_{dead}$)** | $250$ | $350$ | $500$ | $\text{ns}$ | Hardware dead-time in HRTIM/TIM1 |

### 3.2 Analog Front-End & Threshold-Crossing Latency Model
* **Current Sensing Transfer Function:** Current is sensed via a $10\text{ m}\Omega$ precision shunt ($1\%$) and an off-the-shelf **TI INA240A1** (Gain $G = 20\text{ V/V}$, sensitivity $0.200\text{ V/A}$, midpoint $V_{REF} = 1.650\text{ V}$):
  $$V_{csa\_out} = 1.650\text{ V} + (I_L \times 0.200\,\text{V/A})$$
* **Threshold Crossing Model:** For a $1.5\text{ A}$ over-current step ($300\text{ mV}$ output delta), the INA240A1 ($2.0\text{ V/\mu s}$ slew rate) crosses comparator trip thresholds in $T_{CSA\_cross} \approx 300\text{ ns}$ (measurably distinct from the $9.6\,\mu\text{s}$ full $0.1\%$ settling time).
* **STM32G474RE Pin & Peripheral Routing:**
  - `COMP1`: Non-inverting `PA1` (CSA $V_{out}$), Inverting `DAC1_CH1` ($2.650\text{ V}$), internal asynchronous link to `HRTIM1_FLT1` (Hard OC+).
  - `COMP2`: Non-inverting `PA7` (CSA $V_{out}$), Inverting `DAC1_CH2` ($0.650\text{ V}$), internal asynchronous link to `HRTIM1_FLT2` (Hard OC-).
  - `COMP3`: Non-inverting `PA0` ($V_{bus}$ 10:1 AFE), Inverting `DAC2_CH1` ($2.600\text{ V}$), internal asynchronous link to `HRTIM1_FLT3` (Hard OV).
  - HRTIM fault digital filters disabled (`FLTxF = 0000`) for zero-delay hardware trip.

---

## 4. Multi-Tier Protection Latency Models

```
+===================================================================================================+
|                                DISTINCT TRIP LATENCY BREAKDOWNS                                   |
|                                                                                                   |
|  OVER-CURRENT (OC) HARDWARE TRIP PATH (Worst-Case Budget: 491 ns << 2.0 us)                       |
|  T_trip,OC = T_shunt(10ns) + T_CSA_cross(300ns) + T_COMP_HRTIM(31ns) + T_driver(50ns)             |
|              + T_power_stage(100ns) = 491 ns                                                      |
|                                                                                                   |
|  OVER-VOLTAGE (OV) HARDWARE TRIP PATH (Worst-Case Budget: 341 ns << 2.0 us)                       |
|  T_trip,OV = T_divider(10ns) + T_buffer_filter(150ns) + T_COMP_HRTIM(31ns) + T_driver(50ns)       |
|              + T_power_stage(100ns) = 341 ns                                                      |
+===================================================================================================+
```

---

## 5. System Control State Machine & Derating Hysteresis

* **State Authority:** STM32 Control Core FSM is the **exclusive, authoritative owner** of system state.
* **Quantified Derating Triggers (Hysteresis Bands):**
  - Heatsink Temperature: Entry at $T > 55.0^\circ\text{C}$, Exit at $T < 45.0^\circ\text{C}$.
  - Low SOC: Entry at $\text{SOC} < 15.0\%$, Exit at $\text{SOC} > 20.0\%$.
  - High SOC: Entry at $\text{SOC} > 95.0\%$, Exit at $\text{SOC} < 90.0\%$.
* **Safe Recovery Policy:** Clearing a fault (via `FAULT_CLEAR_CMD = 0x00A5`, accepted only in `SAFE_STATE`) transitions to `STATE_RECOVERY_CHECK`. Recovery requires $V_{bat} \ge 11.0\text{ V}$, $16.0\text{ V} \le V_{bus} \le 25.0\text{ V}$, and $|I_L| < 0.2\text{ A}$. Transitions to `STATE_IDLE` and requires an explicit new `START` command (`SYS_CONTROL_CMD = 1` or `2`) to resume power flow.

---

## 6. Gateway Architecture & Resilient Master-Slave IPC

* **Master-Slave SPI Model:** ESP32 is SPI Master; STM32 is SPI Slave with hardware `ALERT_OUT` line (`ACTIVE HIGH`).
* **Session ID & Sequence Wraparound:** `SESSION_ID` in frame header tracks MCU boots. Sequence numbers ($0\text{xFF} \to 0\text{x00}$) are re-synchronized upon reset. Duplicate packets return cached results without re-executing commands.
* **Communication Loss Fail-Safe:** Silence $> 500\text{ ms}$ triggers emergency software ramp-down at $100\text{ A/s}$ to `STATE_IDLE`.

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
| **`40011`** | `FW_VERSION` | `uint16_t` | BCD | R | Firmware Version (e.g. `0x0300` = v3.0.0) |
| **`40012`** | `UPTIME_MSW` | `uint16_t` | Seconds | R | Atomic 32-bit Uptime Counter (MSW) |
| **`40013`** | `UPTIME_LSW` | `uint16_t` | Seconds | R | Atomic 32-bit Uptime Counter (LSW) |
| **`40014`** | `FAULT_CLEAR_CMD` | `uint16_t` | Magic Key | R/W | Dedicated Fault Clear: write `0x00A5` (Accepted only in `SAFE_STATE`) |
| **`40015`** | `CMD_RESULT` | `uint16_t` | Enum | R | `0`=None, `1`=Accepted, `2`=Rejected_InvalidState, `3`=Rejected_FaultActive, `4`=Rejected_Limit, `5`=Rejected_Safety, `6`=Rejected_IPC |
| **`40016`** | `CMD_SEQ` | `uint16_t` | Counter | R | Echo of last processed command sequence number |
| **`40017`** | `FSM_STATE` | `uint16_t` | Enum | R | Detailed Internal FSM State ($0-9$) |
| **`40018`** | `LATCHED_FAULT_FLAGS`| `uint16_t` | Bitmap | R | Historical latched fault bitmap (cleared by 40014) |

* Writing to read-only registers returns Modbus Exception `0x02` (`Illegal Data Address`).
* Direct raw PWM duty cycle writes are strictly prohibited.

---

## 8. Fixed Bootloader & Confirmed Boot Architecture

* **Fixed Base Bootloader:** Immutable $32\text{ KB}$ bootloader resides at fixed base address `0x0800_0000`, reads metadata table, verifies SHA-256 + ECDSA signature via on-chip public key, selects confirmed slot, and jumps.
* **Symmetric Slots:** Slot A capacity == Slot B capacity = $200\text{ KB}$ ($100\text{ pages}$ each).
* **Confirmed Boot Rollback:** Bootloader enforces 3 testing boots ($0 \to 1 \to 2 \to 3 \to \text{rollback}$). Application must pass safety initialization and write `CONFIRM` to metadata table.
