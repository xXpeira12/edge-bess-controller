# System Control State Machine Specification

**Document:** `docs/architecture/state_machine.md`  
**Related SRS IDs:** `REQ-CTRL-004`, `REQ-SAFE-005`, `REQ-SAFE-006`, `REQ-COMM-003`

---

## 1. Single Source of Truth: Control State Machine & Transition Ownership

This document is the authoritative **Single Source of Truth** for the Finite State Machine (FSM), state definitions, quantified derating hysteresis bands, battery recovery checks, and transition authority.

### 1.1 State Authority Principle
* **STM32 Exclusive Ownership:** The STM32 Control Core FSM is the **sole authoritative owner** of system state transitions.
* **Supervisory Requests:** External Modbus and IPC commands are transition requests. If a request violates state transition guard conditions, the STM32 rejects the command and sets `CMD_RESULT = 2` (`Rejected_InvalidState`).

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

## 2. Quantified Derating Triggers & Hysteresis

| Trigger Source | Entry Threshold | Exit Threshold | Action in `STATE_DERATING_ACTIVE` |
| :--- | :--- | :--- | :--- |
| **Heatsink Temperature** | $T > 55.0^\circ\text{C}$ | $T < 45.0^\circ\text{C}$ | Clamps $I_{ref}$ linearly ($100\%$ at $55^\circ\text{C} \to 50\%$ at $65^\circ\text{C}$). |
| **Low Battery SOC** | $\text{SOC} < 15.0\%$ | $\text{SOC} > 20.0\%$ | Discharge current setpoint clamped to $1.0\text{ A}$ maximum. |
| **High Battery SOC** | $\text{SOC} > 95.0\%$ | $\text{SOC} < 90.0\%$ | Charge current setpoint clamped to $0.5\text{ A}$ taper current. |

---

## 3. Detailed State Table & Actions

### 3.1 State 8: `STATE_RECOVERY_CHECK`
* **Entry:** `FAULT_CLEAR_CMD = 0x00A5` received in `STATE_SAFE_STATE`.
* **Battery & Bus Verification:**
  - $V_{bat} \ge 11.0\text{ V}$ (Battery present and above deep discharge).
  - $16.0\text{ V} \le V_{bus} \le 25.0\text{ V}$ (DC bus stable).
  - $|I_L| < 0.20\text{ A}$ (Zero current).
  - $T_{sink} < 45.0^\circ\text{C}$ (Thermal recovery).
* **Exit:** If passed $\to$ `STATE_IDLE`; if failed $\to$ `STATE_SAFE_STATE`.

### 3.2 State 9: `STATE_SAFE_STATE`
* **Actions:** Hardware Break forces PWM `LOW` $\le 2.0\,\mu\text{s}$. Latches `FAULT_CODE` in register `40010`.
* **Exit:** Accepts `FAULT_CLEAR_CMD = 0x00A5` to transition to `STATE_RECOVERY_CHECK`.
