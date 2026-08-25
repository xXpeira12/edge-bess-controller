# System Control State Machine Specification

**Document:** `docs/architecture/state_machine.md`  
**Related SRS IDs:** `REQ-CTRL-004`, `REQ-SAFE-005`, `REQ-SAFE-006`, `REQ-COMM-003`

---

## 1. Single Source of Truth: Control State Machine & Transition Ownership

This document is the authoritative **Single Source of Truth** for the Finite State Machine (FSM), state definitions, quantified derating hysteresis bands, transition matrix, and battery recovery checks.

### 1.1 State Authority Principle & Direct Transition Prohibitions
* **STM32 Exclusive Ownership:** The STM32 Control Core FSM is the **sole authoritative owner** of system state transitions.
* **Direct Mode Transition Prohibition:** Direct transitions between `STATE_CHARGE_ACTIVE` and `STATE_DISCHARGE_ACTIVE` are **strictly forbidden**. Any operational mode change must execute a controlled ramp-down to `STATE_IDLE` before entering a new mode.
* **Tier-1 Emergency Ramp Fallback:** If a Level 2 software emergency ramp-down ($100\text{ A/s}$ within $50\text{ ms}$) encounters sensor failure or fails to reduce current below $0.5\text{ A}$, the system triggers an immediate hardware Timer Break trip to `STATE_SAFE_STATE`.

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
|                      |  - Flash Golden CRC-32 verification                 |                      |
|                      |  - ADC & HRTIM fault pin initialization             |                      |
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
|        |              | STATE_DERATING_ACTIVE  | (Reason Bitmap: Temp, SOC, Bus Ripple)           |
|        |              | - Dynamic I_ref Clamp  |                |                                 |
|        |              +------------------------+                |                                 |
|        |                        |                               |                                 |
|        |          [ Temp / SOC Normal Again ]                   |                                 |
|        +------------------------+                               |                                 |
|                                                                 |                                 |
|  [ Level 2 Fault / Emergency Stop: Ramp-Down at 100 A/s ]       |                                 |
|  +------------------------------------------------------+       |                                 |
|  | Decelerates to 0A in <= 50 ms, disables PWM -> IDLE  |       |                                 |
|  | (Fallback: If current doesn't drop -> SAFE_STATE)    |       |                                 |
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
|                       [ FAULT_CLEAR_CMD == 0x00A5 (Accepted ONLY in SAFE_STATE) ]                 |
|                                                 v                                                 |
|                               +------------------------------------+                              |
|                               |        STATE_RECOVERY_CHECK        |                              |
|                               |  - Verify 16V <= Vbus <= 25V       |                              |
|                               |  - Verify Vbat >= 11.0V, |I|<0.2A  |                              |
|                               |  - Verify T < 45C, Break Re-armed  |                              |
|                               +------------------------------------+                              |
|                                                 |                                                 |
|                                    [ Verification Passed ]                                        |
|                                                 v                                                 |
|                                            STATE_IDLE                                             |
|                             (Requires new START command to run)                                   |
+===================================================================================================+
```

---

## 2. Complete State Transition Matrix

| Current State | Target State | Trigger Condition | Guard Condition / Validation | Action Taken |
| :--- | :--- | :--- | :--- | :--- |
| `STATE_POWER_ON` | `STATE_INIT_AND_SELF_TEST` | Reset vector complete | Clocks stable (170 MHz) | Vector table remap |
| `STATE_INIT_AND_SELF_TEST` | `STATE_IDLE` | Startup tests passed | Reg, RAM, Flash CRC OK | PWM in High-Z, relays open |
| `STATE_INIT_AND_SELF_TEST` | `STATE_SAFE_STATE` | Any diagnostic failure | Test fail flag set | Hardware Break trip |
| `STATE_IDLE` | `STATE_CHARGE_RAMP` | `SYS_CONTROL_CMD == 1` | $18\text{V} \le V_{bus} \le 24.5\text{V}$ | Buck PWM soft-start |
| `STATE_IDLE` | `STATE_DISCHARGE_RAMP` | `SYS_CONTROL_CMD == 2` | $V_{bat} \ge 10.5\text{V}$ | Boost PWM soft-start |
| `STATE_CHARGE_RAMP` | `STATE_CHARGE_ACTIVE` | Target current reached | $|I_L - I_{target}| \le 0.1\text{A}$ | Cascaded PID active |
| `STATE_CHARGE_ACTIVE` | `STATE_IDLE` | `SYS_CONTROL_CMD == 0` | Normal stop command | Controlled ramp-down ($2.0\text{ A/s}$) |
| `STATE_CHARGE_ACTIVE` | `STATE_DERATING_ACTIVE` | Warning threshold hit | $T > 55^\circ\text{C}$ or $\text{SOC} > 95\%$ | Throttles current setpoint |
| `STATE_CHARGE_ACTIVE` | `STATE_DISCHARGE_ACTIVE` | Direct switch attempt | **PROHIBITED** | Command rejected (`CMD_RESULT = 2`) |
| `STATE_DERATING_ACTIVE` | `STATE_CHARGE_ACTIVE` | Conditions normalized | $T < 45^\circ\text{C}$ for $> 5\text{s}$ | Restores full current setpoint |
| `* (Any Operating)` | `STATE_IDLE` | Level 2 Software Fault | Soft OC/OT, UVLO, IPC timeout | Emergency ramp-down ($100\text{ A/s}$) |
| `* (Any State)` | `STATE_SAFE_STATE` | Level 3 Critical Fault | Hardware OC/OV, Watchdog | Instant Tier-0 Break Trip |
| `STATE_SAFE_STATE` | `STATE_RECOVERY_CHECK` | `FAULT_CLEAR_CMD == 0x00A5` | Accepted only in `SAFE_STATE` | Re-checks sensors & re-arms break |
| `STATE_RECOVERY_CHECK` | `STATE_IDLE` | All checks passed | $V_{bat} \ge 11\text{V}$, $16\text{V} \le V_{bus} \le 25\text{V}$ | Power conversion remains IDLE |
| `STATE_RECOVERY_CHECK` | `STATE_SAFE_STATE` | Any check failed | Sensor out of safe band | Re-latches fault code |
