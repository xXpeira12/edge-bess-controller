# Industrial Smart BESS & Power Management Controller (Desk-Scale PoC)
## Software Requirements Specification (SRS) & System Architecture Document

**Document Version:** 4.0.0  
**Target Platform:** Dual-MCU Architecture (Real-Time Control Core + Industrial Gateway Core)  
**Primary Control Core MCU (Normative Target):** **STM32G474RE** (ARM Cortex-M4F @ 170 MHz, HRTIM, Fast Internal Comparators, Symmetric Dual-Bank Flash)  
**Secondary / Porting Control Core MCU (Future Target):** **STM32F446RE** (ARM Cortex-M4F @ 168 MHz, TIM1, External Comparator Interconnect)  
**Gateway Core MCU:** **ESP32-WROOM-32** (Dual-Core Xtensa LX6 @ 240 MHz, FreeRTOS Preemptive Kernel)  
**Design Paradigm:** Hard Real-Time Deterministic Control, Multi-Tier Hardware/Software Safety, Non-Blocking Telemetry Isolation  
**PoC Standard Alignment:** IEC 60730 Class B-Oriented Safety Diagnostics & ISO 21434 Cybersecurity Concept  
**Verification Status:** Specification consistency and invariant simulation model verified; hardware physical measurements pending benchtop prototype execution.

---

## 1. Single Source of Truth (SSOT) Architecture Mapping

| Domain | Authoritative SSOT Document | Key SSOT Invariants & Parameters |
| :--- | :--- | :--- |
| **System Overview & Requirements** | `README.md` | Dual-MCU topology, operational envelopes, safety boundaries |
| **Timing, Jitter & Determinism** | `docs/architecture/timing_jitter_and_bench_verification.md` | $f_{sw} = 50\text{ kHz}$, $T_s = 20\,\mu\text{s}$, 4 jitter metrics, DSO vs DWT scope |
| **Analog Front-End & Sensing** | `docs/architecture/hardware_sensing_and_analog_frontend.md` | $R_{shunt}=10\text{ m}\Omega$, INA240A1 ($G=20\text{ V/V}$), $T_{CSA\_cross}=300\text{ns}$, RM0440 pin routing |
| **Safety, Faults & Latency** | `docs/architecture/fault_handling_and_safety.md` | Distinct OC ($491\text{ns}$) & OV ($341\text{ns}$) latency budgets, tolerance budget |
| **Control Finite State Machine** | `docs/architecture/state_machine.md` | STM32 authoritative FSM, `RECOVERY_CHECK`, quantified derating hysteresis |
| **Inter-Processor Comm (IPC)** | `docs/architecture/ipc_protocol.md` | Master-Slave SPI, 16-bit `SEQ_NUM`, `SESSION_ID`, 1:1 Modbus alignment |
| **Modbus SCADA Register Map** | `docs/architecture/modbus_register_map.md` | Registers $40001 - 40018$, mailbox semantics, $0\text{x00A5}$ clear key (SAFE_STATE only) |
| **Flash Memory & Bootloader** | `docs/architecture/flash_memory_partitioning.md` | Fixed base bootloader, symmetric $200\text{ KB}$ slots, power-loss-safe metadata |
| **Specification Consistency** | `tests/test_specification_consistency.py` | Automated cross-document mathematical & invariant test assertions |

---

## 2. Hardware Interfaces, Operational Boundaries & Analog Front-End

### 2.1 Operational Boundaries & Tolerance Budget

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

### 2.2 STM32G474RE Exact Comparator / DAC Routing Matrix (RM0440 / AN5094)

| Protection Channel | Comparator | Non-Inverting Input (`COMPx_INP`) | Inverting Input (`COMPx_INM`) | Internal Reference | HRTIM Fault Link | Action |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Hard OC+** ($> +5.0\text{ A}$) | `COMP1` | `PA1` (CSA $V_{out}$) | `DAC1_CH1` | $2.650\text{ V}$ | `HRTIM1_FLT4` | PWM forced LOW ($\le 2.0\,\mu\text{s}$) |
| **Hard OC-** ($< -5.0\text{ A}$) | `COMP2` | `DAC3_CH2` | `PA7` (CSA $V_{out}$) | $0.650\text{ V}$ | `HRTIM1_FLT1` | PWM forced LOW ($\le 2.0\,\mu\text{s}$) |
| **Hard OV** ($> 26.0\text{ V}$) | `COMP3` | `PA0` ($V_{bus}$ 10:1 AFE) | `DAC1_CH2` | $2.600\text{ V}$ ($26\text{V}/10$) | `HRTIM1_FLT5` | PWM forced LOW ($\le 2.0\,\mu\text{s}$) |

* **Internal HRTIM Fault Mapping (RM0440 Table 223):** `HRTIM1_FLT1 <- COMP2`, `HRTIM1_FLT4 <- COMP1`, `HRTIM1_FLT5 <- COMP3`.
* **Hardware Invariant:** HRTIM fault digital filters are disabled (`FLTxF = 0000`) for zero-delay asynchronous hardware tripping.

---

## 3. Real-Time Determinism & Jitter Verification Protocols

### 3.1 Four Jitter Metrics Disambiguation (`NFR-PERF-01`)
* **Trigger Jitter ($t_{trig\_jitter}$):** $\le \pm 5.0\text{ ns}$ (TRGO to ADC aperture). *Requires DSO measurement.*
* **Interrupt Latency Jitter ($t_{irq\_jitter}$):** $\le \pm 15.0\text{ ns}$ (EOC to ISR entry). *Requires DSO measurement.*
* **Execution Time Jitter ($t_{exec\_jitter}$):** $\le \pm 20.0\text{ ns}$ (ISR compute duration). *Tracked in-firmware via Cortex-M4 DWT.*
* **Sample-to-Duty-Update Jitter ($t_{update\_jitter}$):** $\le \pm 50.0\text{ ns}$ (ADC sample to physical PWM reload). *Requires DSO measurement.*
* **Verification Status:** Specification consistency and invariant simulation model verified; hardware measurements pending physical benchtop prototype.
* **Preemption Policy:** No intentional software ISR preemption is permitted during control loop execution.

---

## 4. Multi-Tier Protection Latency Models

```
+===================================================================================================+
|                                DISTINCT TRIP LATENCY BREAKDOWNS                                   |
|                                                                                                   |
|  OVER-CURRENT (OC) HARDWARE TRIP PATH (Preliminary Model: 491 ns << 2.0 us Budget)                |
|  T_trip,OC = T_shunt(10ns) + T_CSA_cross(300ns) + T_COMP_HRTIM(31ns) + T_driver(50ns)             |
|              + T_power_stage(100ns) = 491 ns                                                      |
|                                                                                                   |
|  OVER-VOLTAGE (OV) HARDWARE TRIP PATH (Preliminary Model: 341 ns << 2.0 us Budget)                |
|  T_trip,OV = T_divider(10ns) + T_buffer_filter(150ns) + T_COMP_HRTIM(31ns) + T_driver(50ns)       |
|              + T_power_stage(100ns) = 341 ns                                                      |
+===================================================================================================+
```

---

## 5. Gateway Architecture & Resilient Master-Slave IPC

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|       SYNC_WORD (0xA55A)      |   PROTO_VER   |  SESSION_ID   |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|          SEQ_NUM (uint16_t: 0 - 65535, 1:1 Modbus)            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|   MSG_TYPE    |   MSG_FLAGS   |  PAYLOAD_LEN  |  PAYLOAD...   |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
| ... PAYLOAD (0 to 64 bytes) ...               |     CRC16     |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

* **16-bit Sequence Number Alignment:** SPI frame `SEQ_NUM` is a `uint16_t` ($0 - 65535$), aligning 1:1 with Modbus `CMD_SEQ` (Register `40016`) without truncation.
* **Session Handshake:** `SESSION_ID` increments upon MCU reset; microcontrollers exchange an initial handshake to reset `SEQ_NUM` to `0`.

---

## 6. Industrial Modbus Holding Registers Map ($40001 - 40018$)

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
| **`40011`** | `FW_VERSION` | `uint16_t` | BCD | R | Firmware Version (e.g. `0x0400` = v4.0.0) |
| **`40012`** | `UPTIME_MSW` | `uint16_t` | Seconds | R | Atomic 32-bit Uptime Counter (MSW) |
| **`40013`** | `UPTIME_LSW` | `uint16_t` | Seconds | R | Atomic 32-bit Uptime Counter (LSW) |
| **`40014`** | `FAULT_CLEAR_CMD` | `uint16_t` | Magic Key | R/W | Dedicated Fault Clear: write `0x00A5` (Accepted only in `SAFE_STATE`) |
| **`40015`** | `CMD_RESULT` | `uint16_t` | Enum | R | `0`=None, `1`=Accepted, `2`=Rejected_InvalidState, `3`=Rejected_FaultActive, `4`=Rejected_Limit, `5`=Rejected_Safety, `6`=Rejected_IPC |
| **`40016`** | `CMD_SEQ` | `uint16_t` | Counter | R | Echo of last processed command sequence number (1:1 with SPI SEQ_NUM) |
| **`40017`** | `FSM_STATE` | `uint16_t` | Enum | R | Detailed Internal FSM State ($0-9$) |
| **`40018`** | `LATCHED_FAULT_FLAGS`| `uint16_t` | Bitmap | R | Historical latched fault bitmap (cleared by 40014) |

---

## 7. Fixed Bootloader & Confirmed Boot Architecture

* **Fixed Base Bootloader:** Bootloader resides at immutable fixed base address `0x0800_0000` ($32\text{ KB}$), reads metadata table, validates SHA-256 + ECDSA signature via on-chip public key, selects confirmed slot, and jumps.
* **Symmetric Slots:** Slot A capacity == Slot B capacity = $200\text{ KB}$ ($100\text{ pages}$ each).
* **Confirmed Boot Rollback:** Maximum 3 application boot attempts permitted ($1 \to 2 \to 3$); automatic rollback occurs before the 4th boot attempt.
