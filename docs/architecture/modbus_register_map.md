# SCADA Modbus-TCP / RTU Holding Register Map & Control Policy

**Document:** `docs/architecture/modbus_register_map.md`  
**Related SRS IDs:** `REQ-COMM-003`

---

## 1. Single Source of Truth: Modbus Control Policy & Safety Boundaries

This document is the authoritative **Single Source of Truth** for the SCADA Modbus-TCP / RTU Holding Register Map ($40001 - 40018$), data types, engineering scalings, sentinels, mailbox semantics, command result codes, and access permissions.

### 1.1 Strict Safety Rule
> **CRITICAL SAFETY RESTRICTION:** Direct manipulation or writing of PWM duty cycles, timer period registers, dead-time parameters, or raw inner-loop PID gains via Modbus is **STRICTLY PROHIBITED**.

### 1.2 Mailbox Command Semantics & Double-Buffered Snapshot
1. **Edge-Triggered Mailbox:** `SYS_CONTROL_CMD` (Register `40001`) acts as an edge-triggered command mailbox. Writing a valid value triggers an IPC transaction to the Control MCU.
2. **Dedicated Fault Clear Key (Register `40014`):** Latched faults can only be cleared by writing the magic key `0x00A5` to `FAULT_CLEAR_CMD`. Writing `0x00A5` is **accepted ONLY in `SAFE_STATE`**; issuing it in `IDLE`, `CHARGE`, or `DISCHARGE` returns `CMD_RESULT = 2` (`Rejected_InvalidState`).
3. **Double-Buffered Atomic Snapshot ($\le 20\text{ ms}$ Age):** Upon receipt of Modbus Function Code `0x03` covering registers $40002 - 40018$, the Gateway serves data from an atomic double-buffered shadow memory buffer updated every $\le 20\text{ ms}$, guaranteeing that 32-bit values (such as `UPTIME_MSW`/`LSW`) are read without tear.
4. **Exception Handling:** Writing to any read-only register ($40002 - 40013$, $40015 - 40018$) returns Modbus Exception Code `0x02` (`Illegal Data Address`).

---

## 2. Modbus Holding Registers Specification ($40001 - 40018$)

| Register | Register Name | Data Type | Units / Scaling | Access | Range / Valid Values | Description |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`40001`** | `SYS_CONTROL_CMD` | `uint16_t` | Enum | R/W | `0x0000`, `0x0001`, `0x0002` | `0` = Stop / Transition to IDLE<br>`1` = Start Charge (Buck)<br>`2` = Start Discharge (Boost) |
| **`40002`** | `BUS_VOLTAGE_RAW` | `uint16_t` | $10\text{ mV} / \text{LSB}$ | Read-Only | $0 - 3000$, `0xFFFF` | Filtered DC Bus Voltage ($2400 = 24.00\text{ V}$). Sentinel: `0xFFFF` = Invalid/Uncalibrated. |
| **`40003`** | `BAT_CURRENT_RAW` | `int16_t` | $10\text{ mA} / \text{LSB}$ | Read-Only | $-500 \dots +500$, `0x7FFF` | Battery Current (Signed). $+250 = +2.50\text{ A}$ (Charge), $-250 = -2.50\text{ A}$ (Discharge). Sentinel: `0x7FFF`. |
| **`40004`** | `BAT_SOC` | `uint16_t` | $0.1\% / \text{LSB}$ | Read-Only | $0 - 1000$, `0xFFFF` | Estimated State of Charge ($850 = 85.0\%$). Sentinel: `0xFFFF`. |
| **`40005`** | `ACTIVE_FAULT_FLAGS`| `uint16_t` | Bitfield | Read-Only | `0x0000 - 0xFFFF` | Real-time active warning and fault bitmap. |
| **`40006`** | `VOUT` | `uint16_t` | $10\text{ mV} / \text{LSB}$ | Read-Only | $0 - 2000$, `0xFFFF` | Regulated Battery Terminal Voltage ($1280 = 12.80\text{ V}$). Sentinel: `0xFFFF`. |
| **`40007`** | `IOUT` | `int16_t` | $10\text{ mA} / \text{LSB}$ | Read-Only | $-500 \dots +500$, `0x7FFF` | Filtered Inductor Output Current. Sentinel: `0x7FFF`. |
| **`40008`** | `TEMPERATURE` | `int16_t` | $0.1^\circ\text{C} / \text{LSB}$ | Read-Only | $-200 \dots +1250$, `0x7FFF` | Power Stage Heatsink Temperature ($265 = 26.5^\circ\text{C}$). Sentinel: `0x7FFF`. |
| **`40009`** | `OPERATING_MODE` | `uint16_t` | Enum | Read-Only | `0 - 3` | High-Level Operating Mode:<br>`0` = `IDLE`<br>`1` = `CHARGE`<br>`2` = `DISCHARGE`<br>`3` = `SAFE_STATE` |
| **`40010`** | `FAULT_CODE` | `uint16_t` | Hex Code | Read-Only | `0x0000 - 0xFFFF` | Diagnostic hex code of highest priority active fault. |
| **`40011`** | `FW_VERSION` | `uint16_t` | BCD Format | Read-Only | `0x0000 - 0x9999` | Normative BCD encoding `0xMMmm` (e.g. `0x0130` = v1.3.0). |
| **`40012`** | `UPTIME_MSW` | `uint16_t` | Seconds | Read-Only | $0 - 65535$ | System Uptime 32-bit Counter (MSW). |
| **`40013`** | `UPTIME_LSW` | `uint16_t` | Seconds | Read-Only | $0 - 65535$ | System Uptime 32-bit Counter (LSW). |
| **`40014`** | `FAULT_CLEAR_CMD` | `uint16_t` | Magic Key | R/W | `0x00A5` | Dedicated Fault Clear. Accepted ONLY in `SAFE_STATE`. |
| **`40015`** | `CMD_RESULT` | `uint16_t` | Enum | Read-Only | `0 - 6` | `0` = None<br>`1` = Accepted<br>`2` = Rejected_InvalidState<br>`3` = Rejected_FaultActive<br>`4` = Rejected_Limit<br>`5` = Rejected_Safety<br>`6` = Rejected_IPC |
| **`40016`** | `CMD_SEQ` | `uint16_t` | Counter | Read-Only | $0 - 65535$ | Monotonic sequence number echo of last command (1:1 with SPI SEQ_NUM). |
| **`40017`** | `FSM_STATE` | `uint16_t` | Enum | Read-Only | `0 - 9` | Detailed Internal FSM State ($0-9$). |
| **`40018`** | `LATCHED_FAULT_FLAGS`|`uint16_t`| Bitfield | Read-Only | `0x0000 - 0xFFFF` | Latched historical fault bitmap (cleared by 40014). |

---

## 3. `FSM_STATE` (Register `40017`) Enum Values

* `0`: `STATE_POWER_ON`
* `1`: `STATE_INIT_AND_SELF_TEST`
* `2`: `STATE_IDLE`
* `3`: `STATE_CHARGE_RAMP`
* `4`: `STATE_CHARGE_ACTIVE`
* `5`: `STATE_DISCHARGE_RAMP`
* `6`: `STATE_DISCHARGE_ACTIVE`
* `7`: `STATE_DERATING_ACTIVE`
* `8`: `STATE_RECOVERY_CHECK`
* `9`: `STATE_SAFE_STATE`
