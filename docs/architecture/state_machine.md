# System Control State Machine Specification

**Document:** `docs/architecture/state_machine.md`  
**Related SRS IDs:** `REQ-CTRL-004`, `REQ-SAFE-005`, `REQ-SAFE-006`, `REQ-COMM-003`

---

## 1. State Machine Overview

The Control MCU firmware executes a strictly deterministic Finite State Machine (FSM) synchronized with the $50\text{ kHz}$ inner control interrupt and the $1\text{ kHz}$ system supervisory tick. All transitions between states are guarded by explicit boundary checks and mathematical plausibility constraints.

```
+===================================================================================================+
|                                    CONTROL CORE FINITE STATE MACHINE                              |
|                                                                                                   |
|                      +-----------------------------------------------------+                      |
|                      |                    STATE_POWER_ON                   |                      |
|                      |  - Core reset, vector table remap, basic clocks     |                      |
|                      +-----------------------------------------------------+                      |
|                                                 |                                                 |
|                                                 v                                                 |
|                      +-----------------------------------------------------+                      |
|                      |             STATE_INIT_AND_SELF_TEST                |                      |
|                      |  - IEC 60730 CPU register & RAM March C- tests      |                      |
|                      |  - Flash Golden CRC verification                    |                      |
|                      |  - ADC & Timer Break hardware configuration         |                      |
|                      +-----------------------------------------------------+                      |
|                                 |                               |                                 |
|                       [ Self-Tests Passed ]           [ Any Test Failed / HW Fault ]              |
|                                 v                               |                                 |
|                      +----------------------+                   |                                 |
|        +------------>|      STATE_IDLE      |                   |                                 |
|        |             |  - PWM High-Z / Inact|                   |                                 |
|        |             |  - Sliced Diagnostics|                   |                                 |
|        |             +----------------------+                   |                                 |
|        |                |                |                      |                                 |
|        |     [ SYS_CMD == CHARGE ] [ SYS_CMD == DISCHARGE ]     |                                 |
|        |                v                v                      |                                 |
|        |      +------------------+  +--------------------+      |                                 |
|        |      |STATE_CHARGE_RAMP |  |STATE_DISCHARGE_RAMP|      |                                 |
|        |      | - Pre-check Vbus |  | - Pre-check Vbat   |      |                                 |
|        |      | - Ramp I_ref up  |  | - Ramp I_ref up    |      |                                 |
|        |      +------------------+  +--------------------+      |                                 |
|        |                |                    |                  |                                 |
|        |         [ Ramp Target Met ]  [ Ramp Target Met ]       |                                 |
|        |                v                    v                  |                                 |
|        |      +------------------+  +--------------------+      |                                 |
|        |      |STATE_CHARGE_ACTIV|  |STATE_DISCHARGE_ACT |      |                                 |
|        |      | - 50kHz Buck PID |  | - 50kHz Boost PID  |      |                                 |
|        |      | - Continuous Mon |  | - Continuous Mon   |      |                                 |
|        |      +------------------+  +--------------------+      |                                 |
|        |                |                    |                  |                                 |
|        |         [ Warn Temp/SOC ]    [ Warn Temp/SOC ]         |                                 |
|        |                \                    /                  |                                 |
|        |                 v                  v                   |                                 |
|        |              +------------------------+                |                                 |
|        |              | STATE_DERATING_ACTIVE  |                |                                 |
|        |              | - Dynamic I_ref Clamp  |                |                                 |
|        |              +------------------------+                |                                 |
|        |                        |                               |                                 |
|        |          [ Temp / SOC Normal Again ]                   |                                 |
|        +------------------------+                               |                                 |
|                                                                 |                                 |
|  [ Level 2 Fault / Stop Cmd / Normal Shutdown ]                 |                                 |
|  - Controlled Current Ramp-Down (dI/dt <= 2.0 A/s)              |                                 |
|  - Disable PWM Software Output -> Returns to STATE_IDLE         |                                 |
|                                                                 |                                 |
|  [ Tier-0 Critical Hardware Fault (Over-Current / Over-Voltage / IEC Failure) ]                  |
|  +--------------------------------------------------------------+                                 |
|  |                                                                                                |
|  v                                                                                                |
|  +=============================================================================================+  |
|  |                                     STATE_SAFE_STATE                                        |  |
|  |  - Hardware Timer Break Asserted (PWM forced LOW in <= 2.0 us)                              |  |
|  |  - Isolation Relay Contacts Commanded OPEN                                                  |  |
|  |  - Fault Code Latched in Register 40010; SCADA Alert Broadcast                              |  |
|  |  - Microcontroller Lockout until hard power cycle or authenticated clear command            |  |
|  +=============================================================================================+  |
+===================================================================================================+
```

---

## 2. Detailed State Table & Actions

### 2.1 State 0: `STATE_POWER_ON`
* **Entry:** Microcontroller power applied or hardware reset line released.
* **Actions:**
  - Setup core clock trees (HSE $8\text{ MHz} \to \text{PLL} \to 168/170\text{ MHz}$).
  - Remap interrupt vector table to active Flash base address.
  - Initialize basic internal GPIO pins to safe default states.
* **Exit Criteria:** Unconditional transition to `STATE_INIT_AND_SELF_TEST`.

---

### 2.2 State 1: `STATE_INIT_AND_SELF_TEST`
* **Entry:** Boot initialization complete.
* **Actions:**
  - Execute destructive CPU core register pattern tests (`0x55555555` / `0xAAAAAAAA`).
  - Execute destructive startup SRAM March C- scan.
  - Calculate active application Flash CRC-32 and match against image golden header.
  - Configure TIM1/HRTIM complementary PWM outputs with hardware dead-time ($350\text{ ns}$).
  - Configure internal/external analog comparators and map to `BKIN` break inputs.
  - Perform multi-point ADC zero-offset self-calibration.
* **Exit Criteria:**
  - **Pass:** All self-tests return `SUCCESS` $\to$ Transition to `STATE_IDLE`.
  - **Fail:** Any diagnostic error $\to$ Latch `FLT_IEC_*` fault code and transition to `STATE_SAFE_STATE`.

---

### 2.3 State 2: `STATE_IDLE`
* **Entry:** Successful initialization, normal soft-stop completion, or cleared soft fault.
* **Actions:**
  - PWM outputs forced to High-Z / Inactive LOW.
  - Continuous execution of non-destructive sliced March C- SRAM check ($\le 100\text{ ms}$ interval).
  - Refresh Window Watchdog (IWDG) every $50\text{ ms} \pm 10\text{ ms}$.
  - Monitor DC bus and battery voltages to ensure stability.
* **Exit Criteria:**
  - Command `SYS_CONTROL_CMD == 1` AND $18.0\text{ V} \le V_{bus} \le 24.5\text{ V}$ $\to$ Transition to `STATE_CHARGE_RAMP`.
  - Command `SYS_CONTROL_CMD == 2` AND $V_{bat} \ge 10.5\text{ V}$ $\to$ Transition to `STATE_DISCHARGE_RAMP`.
  - Any Critical Hardware Trip $\to$ Transition to `STATE_SAFE_STATE`.

---

### 2.4 State 3: `STATE_CHARGE_RAMP`
* **Entry:** Charge command received in `STATE_IDLE`.
* **Actions:**
  - Enable High-Side Buck complementary PWM switching.
  - Ramp current reference setpoint $I_{ref}$ from $0.0\text{ A}$ to target setpoint (e.g. $+2.5\text{ A}$) at a rate of $dI/dt = 2.0\text{ A/s}$ ($1.0\text{ mA}$ per $500\,\mu\text{s}$ tick).
  - Monitor for initial inrush transients or switch ringing.
* **Exit Criteria:**
  - Target current reached ($|I_{actual} - I_{target}| \le 0.1\text{ A}$) $\to$ Transition to `STATE_CHARGE_ACTIVE`.
  - Ramp timeout ($> 3.0\text{ s}$) or soft fault $\to$ Ramp down to `STATE_IDLE`.
  - Critical fault $\to$ Transition to `STATE_SAFE_STATE`.

---

### 2.5 State 4: `STATE_CHARGE_ACTIVE`
* **Entry:** Charge ramp successfully completed.
* **Actions:**
  - Execute cascaded dual-loop PID in Buck mode ($50\text{ kHz}$ inner current loop, $5\text{ kHz}$ outer voltage loop).
  - Continuous CC-CV regulation (Constant Current charging up to $14.4\text{ V}$, Constant Voltage taper).
  - Stream fast telemetry frames over SPI DMA every $20\text{ ms}$.
* **Exit Criteria:**
  - Heatsink temp $55^\circ\text{C} \le T \le 65^\circ\text{C}$ $\to$ Transition to `STATE_DERATING_ACTIVE`.
  - Battery full ($V_{bat} \ge 14.4\text{ V}$ and $I < 0.2\text{ A}$) or Stop Command received $\to$ Execute soft ramp-down to `STATE_IDLE`.
  - Level 2 Soft Fault $\to$ Soft ramp-down to `STATE_IDLE`.
  - Level 3 Critical Fault $\to$ Transition to `STATE_SAFE_STATE`.

---

### 2.6 State 5: `STATE_DISCHARGE_RAMP`
* **Entry:** Discharge command received in `STATE_IDLE`.
* **Actions:**
  - Enable Low-Side Boost complementary PWM switching.
  - Ramp discharge current setpoint from $0.0\text{ A}$ to target negative current (e.g. $-2.5\text{ A}$) at $dI/dt = 2.0\text{ A/s}$.
* **Exit Criteria:**
  - Target discharge current reached $\to$ Transition to `STATE_DISCHARGE_ACTIVE`.
  - Ramp timeout or soft fault $\to$ Ramp down to `STATE_IDLE`.
  - Critical fault $\to$ Transition to `STATE_SAFE_STATE`.

---

### 2.7 State 6: `STATE_DISCHARGE_ACTIVE`
* **Entry:** Discharge ramp successfully completed.
* **Actions:**
  - Execute cascaded dual-loop PID in Boost mode supplying power to the DC bus load.
  - Regulate bus voltage ($24.0\text{ V}$) while clamping maximum discharge current.
* **Exit Criteria:**
  - Warning condition (Low SOC $10-15\%$ or Temp $55-65^\circ\text{C}$) $\to$ Transition to `STATE_DERATING_ACTIVE`.
  - Battery empty ($V_{bat} \le 10.0\text{ V}$) or Stop Command received $\to$ Soft ramp-down to `STATE_IDLE`.
  - Critical fault $\to$ Transition to `STATE_SAFE_STATE`.

---

### 2.8 State 7: `STATE_DERATING_ACTIVE`
* **Entry:** Thermal warning ($55^\circ\text{C} \le T \le 65^\circ\text{C}$) or low battery state of charge.
* **Actions:**
  - Apply linear current derating factor $K_{derate} \in [0.2, 0.8]$ to the PID reference setpoint $I_{ref}$.
  - Assert warning flag `FLT_TEMP_WARN` / `FLT_SOC_LOW` in register `40005`.
* **Exit Criteria:**
  - Temperature drops $< 50^\circ\text{C}$ for $> 5.0\text{ s}$ $\to$ Return to active operating state (`CHARGE_ACTIVE` or `DISCHARGE_ACTIVE`).
  - Temperature exceeds $65.0^\circ\text{C}$ $\to$ Soft ramp-down to `STATE_IDLE`.
  - Critical fault $\to$ Transition to `STATE_SAFE_STATE`.

---

### 2.9 State 8: `STATE_SAFE_STATE`
* **Entry:** Hardware Over-Current ($I > 5.0\text{ A}$), Hardware Over-Voltage ($V > 26.0\text{ V}$), Watchdog failure, or IEC 60730 self-test failure.
* **Actions:**
  - Hardware Break circuit drives all PWM outputs `LOW` within $\le 2.0\,\mu\text{s}$.
  - Main power relays opened.
  - Latches active fault code in Modbus register `40010`.
  - LED fault blink code output active.
* **Exit Criteria:**
  - Requires physical power-cycle or authenticated supervisory reset command `SYS_CONTROL_CMD = 0xFF` after diagnostic verification.
