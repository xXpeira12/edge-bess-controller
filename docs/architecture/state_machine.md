# System Control State Machine Specification

**Document:** `docs/architecture/state_machine.md`  
**Related SRS IDs:** `REQ-CTRL-004`, `REQ-SAFE-005`, `REQ-SAFE-006`, `REQ-COMM-003`

---

## 1. Unified Control Loop & Supervisory Timing Hierarchy

The Control MCU firmware executes a hierarchical timing architecture:
1. **$50.0\text{ kHz}$ Fast Inner Loop ($T_s = 20.0\,\mu\text{s}$):** Synchronous current sampling, cycle-by-cycle PID execution, anti-windup clamping, and PWM register updates.
2. **$5.0\text{ kHz}$ Slow Outer Loop ($T_s = 200.0\,\mu\text{s}$):** Voltage loop regulation generating dynamic current setpoint $I_{ref}$.
3. **$1.0\text{ kHz}$ Supervisory FSM Loop ($T_s = 1.0\text{ ms}$):** Finite state machine transitions, normal current ramping ($2.0\text{ mA/ms} = 2.0\text{ A/s}$), emergency current ramp-down ($100\text{ mA/ms} = 100.0\text{ A/s}$), and diagnostic checks.

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
|        |      | (2.0 A/s Ramp)   |  | (2.0 A/s Ramp)     |      |                                 |
|        |      +------------------+  +--------------------+      |                                 |
|        |                |                    |                  |                                 |
|        |         [ Target Current Met] [ Target Current Met]    |                                 |
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
|  [ Level 2 Fault / Emergency Stop: Ramp-Down at 100 A/s ]       |                                 |
|  +------------------------------------------------------+       |                                 |
|  | Decelerates to 0A in <= 50 ms, disables PWM -> IDLE  |       |                                 |
|                                                                 |                                 |
|  [ Level 3 Critical Hardware Fault (Tier-0 Break Trip <= 2.0 us) ]                                |
|  +--------------------------------------------------------------+                                 |
|  |                                                                                                |
|  v                                                                                                |
|  +=============================================================================================+  |
|  |                                     STATE_SAFE_STATE                                        |  |
|  |  - Hardware Timer Break Asserted (PWM forced LOW in <= 2.0 us)                              |  |
|  |  - Isolation Relay Contacts Commanded OPEN                                                  |  |
|  |  - Fault Code Latched in Register 40010; SCADA Alert Broadcast                              |  |
|  +=============================================================================================+  |
|                                                 |                                                 |
|                                [ Write 0x00A5 to Register 40014 ]                                 |
|                                                 v                                                 |
|                               +------------------------------------+                              |
|                               |        STATE_RECOVERY_CHECK        |                              |
|                               |  - Verify sensors within band      |                              |
|                               |  - Verify hardware break cleared   |                              |
|                               +------------------------------------+                              |
|                                                 |                                                 |
|                                    [ Verification Passed ]                                        |
|                                                 v                                                 |
|                                            STATE_IDLE                                             |
|                             (Requires new START command to run)                                   |
+===================================================================================================+
```

---

## 2. Detailed State Descriptions & Transition Guard Conditions

### 2.1 State 0: `STATE_POWER_ON`
* **Entry:** Microcontroller reset vector execution.
* **Actions:** Clock configuration (HSE $8\text{ MHz} \to \text{PLL} \to 170\text{ MHz}$), vector table relocation.
* **Exit:** Unconditional transition to `STATE_INIT_AND_SELF_TEST`.

### 2.2 State 1: `STATE_INIT_AND_SELF_TEST`
* **Actions:**
  - IEC 60730 CPU register pattern tests (R0-R12, SP, LR, APSR flags).
  - Destructive SRAM March C- scan on unallocated memory.
  - Flash CRC-32 golden signature validation.
  - HRTIM/TIM1 dead-time and internal analog comparator configuration.
* **Exit:**
  - **Pass:** Transitions to `STATE_IDLE`.
  - **Fail:** Latches fault and transitions to `STATE_SAFE_STATE`.

### 2.3 State 2: `STATE_IDLE`
* **Actions:**
  - PWM outputs inactive High-Z; power relays open.
  - Sliced runtime March C- SRAM testing ($\le 100\text{ ms}$ window).
  - Refresh IWDG ($50\text{ ms} \pm 10\text{ ms}$).
* **Exit:**
  - `SYS_CONTROL_CMD == 1` (Start Charge) AND $18.0\text{ V} \le V_{bus} \le 24.5\text{ V}$ $\to$ `STATE_CHARGE_RAMP`.
  - `SYS_CONTROL_CMD == 2` (Start Discharge) AND $V_{bat} \ge 10.5\text{ V}$ $\to$ `STATE_DISCHARGE_RAMP`.
  - Level 3 Critical Fault $\to$ `STATE_SAFE_STATE`.

### 2.4 State 3: `STATE_CHARGE_RAMP` & State 5: `STATE_DISCHARGE_RAMP`
* **Ramping Rate:** $2.0\text{ A/s}$ ($2.0\text{ mA}$ increment per $1.0\text{ ms}$ supervisory tick).
* **Exit:** Target current reached $\to$ `STATE_CHARGE_ACTIVE` / `STATE_DISCHARGE_ACTIVE`.

### 2.5 State 4: `STATE_CHARGE_ACTIVE` & State 6: `STATE_DISCHARGE_ACTIVE`
* **Actions:** Dual-loop cascaded PID executing at $50\text{ kHz}$ inner / $5\text{ kHz}$ outer.
* **Exit:**
  - Thermal / SOC Warning $\to$ `STATE_DERATING_ACTIVE`.
  - Stop Command / Level 2 Fault $\to$ Emergency ramp-down ($100\text{ A/s}$) to `STATE_IDLE`.
  - Level 3 Critical Fault $\to$ Instant Tier-0 Break Trip to `STATE_SAFE_STATE`.

### 2.6 State 7: `STATE_DERATING_ACTIVE`
* **Actions:** Clamps active current setpoint $I_{ref}$ to derated envelope ($20\% - 50\%$ nominal).
* **Exit:** Temperature $< 50^\circ\text{C}$ for $> 5.0\text{ s}$ $\to$ Returns to Active State.

### 2.7 State 8: `STATE_SAFE_STATE`
* **Actions:** Hardware Break forces PWM `LOW` $\le 2.0\,\mu\text{s}$. Latches `FAULT_CODE` in register `40010`.
* **Exit:** Receives authenticated fault clear command `FAULT_CLEAR_CMD = 0x00A5` $\to$ Transitions to `STATE_RECOVERY_CHECK`.

### 2.8 State 9: `STATE_RECOVERY_CHECK`
* **Entry:** Fault clear request received in `STATE_SAFE_STATE`.
* **Actions:**
  - Confirms DC bus voltage is within safe band ($16.0\text{ V} \le V_{bus} \le 25.0\text{ V}$).
  - Confirms inductor current is quiescent ($|I_L| < 0.2\text{ A}$).
  - Confirms temperature has normalized ($T < 45^\circ\text{C}$).
  - Re-arms hardware Timer Break inputs (`HRTIM_CR2_SWFLTR` / `TIM_BDTR_MOE`).
* **Exit:**
  - If all checks pass $\to$ Transitions to `STATE_IDLE`. (Power conversion remains STOPPED until a new explicit `START` command is issued).
  - If any check fails $\to$ Re-latches fault and returns to `STATE_SAFE_STATE`.
