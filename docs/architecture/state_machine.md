# System Control State Machine Specification

**Document:** `docs/architecture/state_machine.md`  
**Related SRS IDs:** `REQ-CTRL-004`, `REQ-SAFE-005`, `REQ-SAFE-006`, `REQ-COMM-003`

---

## 1. Single Source of Truth: Control State Machine & Transition Ownership

This document is the authoritative **Single Source of Truth** for the Finite State Machine (FSM), state definitions, transition guard conditions, ramping rates, and transition authority.

### 1.1 State Authority Principle
* **STM32 Exclusive Ownership:** The STM32 Control Core FSM is the **sole authoritative owner** of system state transitions.
* **Supervisory Commands as Requests:** All Modbus and IPC commands are treated strictly as transition requests. If a request violates state transition guard conditions, the STM32 rejects the command and sets `CMD_RESULT = 2` (`Rejected_InvalidState`).

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

## 2. Detailed State Table & Actions

### 2.1 State 0: `STATE_POWER_ON`
* **Entry:** Microcontroller reset vector execution.
* **Exit:** Unconditional transition to `STATE_INIT_AND_SELF_TEST`.

### 2.2 State 1: `STATE_INIT_AND_SELF_TEST`
* **Actions:** IEC 60730 CPU register pattern tests, destructive SRAM March C- scan, Flash CRC-32 golden signature validation.
* **Exit:** If passed $\to$ `STATE_IDLE`; if failed $\to$ `STATE_SAFE_STATE`.

### 2.3 State 2: `STATE_IDLE`
* **Actions:** PWM outputs inactive High-Z; power relays open; sliced runtime March C- SRAM check ($\le 100\text{ ms}$); IWDG refresh ($50\text{ ms} \pm 10\text{ ms}$).
* **Exit:**
  - `SYS_CONTROL_CMD == 1` $\to$ `STATE_CHARGE_RAMP`.
  - `SYS_CONTROL_CMD == 2` $\to$ `STATE_DISCHARGE_RAMP`.
  - Level 3 Critical Fault $\to$ `STATE_SAFE_STATE`.

### 2.4 State 3: `STATE_CHARGE_RAMP` & State 5: `STATE_DISCHARGE_RAMP`
* **Ramping Rate:** $2.0\text{ A/s}$ ($2.0\text{ mA}$ per $1.0\text{ ms}$ supervisory tick).
* **Exit:** Target current reached $\to$ `STATE_CHARGE_ACTIVE` / `STATE_DISCHARGE_ACTIVE`.

### 2.5 State 4: `STATE_CHARGE_ACTIVE` & State 6: `STATE_DISCHARGE_ACTIVE`
* **Actions:** Cascaded dual-loop PID ($50\text{ kHz}$ inner current / $5\text{ kHz}$ outer voltage).
* **Exit:**
  - Warning threshold $\to$ `STATE_DERATING_ACTIVE`.
  - Stop Command / Level 2 Fault $\to$ Emergency ramp-down ($100\text{ A/s}$) to `STATE_IDLE`.
  - Level 3 Critical Fault $\to$ Instant Tier-0 Break Trip to `STATE_SAFE_STATE`.

### 2.6 State 7: `STATE_DERATING_ACTIVE`
* **Reason Bitmap:** Over-temperature warning, low/high battery SOC, bus voltage ripple.
* **Actions:** Clamps active current setpoint $I_{ref}$ to derated envelope ($20\% - 50\%$ nominal).
* **Exit:** Derating conditions clear for $> 5.0\text{ s}$ $\to$ Returns to Active Operating State.

### 2.7 State 8: `STATE_RECOVERY_CHECK`
* **Entry:** Fault clear command `FAULT_CLEAR_CMD = 0x00A5` received in `STATE_SAFE_STATE`.
* **Actions:** Validates voltages within nominal band ($16.0\text{ V} \le V_{bus} \le 25.0\text{ V}$), $|I_L| < 0.2\text{ A}$, $T < 45^\circ\text{C}$, and re-arms hardware break inputs.
* **Exit:** If passed $\to$ `STATE_IDLE` (requires explicit `START` command to run); if failed $\to$ `STATE_SAFE_STATE`.

### 2.8 State 9: `STATE_SAFE_STATE`
* **Actions:** Hardware Break forces PWM `LOW` $\le 2.0\,\mu\text{s}$. Latches `FAULT_CODE` in register `40010`.
* **Exit:** Receives `FAULT_CLEAR_CMD = 0x00A5` $\to$ `STATE_RECOVERY_CHECK`.
