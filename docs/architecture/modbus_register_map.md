# SCADA Modbus-TCP / RTU Holding Register Map & Control Policy

**Document:** `docs/architecture/modbus_register_map.md`  
**Related SRS IDs:** `REQ-COMM-003`

---

## 1. Modbus Control Policy & Safety Boundary

### 1.1 Strict Safety Rule
> **CRITICAL SAFETY RESTRICTION:** Direct manipulation or writing of PWM duty cycles, timer period registers, dead-time parameters, or raw inner-loop PID gains via Modbus is **STRICTLY PROHIBITED**.

### 1.2 Architectural Rationale
Modbus is a non-deterministic, unprotected industrial fieldbus protocol susceptible to network latency, packet loss, and unauthenticated client writes. Allowing an external SCADA master or HMI to drive low-level switching registers directly would bypass the control MCU's hardware protection layers, potentially causing power-stage shoot-through, transformer saturation, or battery thermal runaway.

All Modbus client requests are received by the Gateway Core (ESP32), which acts as a supervisory validation gatekeeper:
1. **Command Filtering:** Only high-level operational state commands (`SYS_CONTROL_CMD`) are accepted.
2. **Setpoint Clamping:** Numerical setpoints are clamped against hardware limits defined in immutable firmware headers.
3. **Deterministic Staging:** Validated commands are converted into authenticated IPC frames and transmitted over SPI DMA to the Control MCU (STM32).

---

## 2. Modbus Holding Registers Specification ($40001 - 40013$)

All registers are standard 16-bit Modbus Holding Registers (Function Code `0x03` Read Holding Registers, Function Code `0x06` Write Single Register, Function Code `0x10` Write Multiple Registers).

| Register Address | Register Name | Data Type | Units / Scaling | Access | Range / Valid Values | Description |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`40001`** | `SYS_CONTROL_CMD` | `uint16_t` | Enum | R/W | `0x0000`, `0x0001`, `0x0002`, `0x00FF` | System command register.<br>`0x00` = Stop / Transition to IDLE<br>`0x01` = Start Charge (Buck)<br>`0x02` = Start Discharge (Boost)<br>`0xFF` = Clear Latched Faults |
| **`40002`** | `BUS_VOLTAGE_RAW` | `uint16_t` | $10\text{ mV} / \text{LSB}$ | Read-Only | $0 - 3000$ ($0.00\text{ V} - 30.00\text{ V}$) | Filtered DC Bus Voltage. Multiplier: $0.01\text{ V}$. Example: $2400 = 24.00\text{ V}$. |
| **`40003`** | `BAT_CURRENT_RAW` | `int16_t` | $10\text{ mA} / \text{LSB}$ | Read-Only | $-500 \dots +500$ ($-5.00\text{ A} \dots +5.00\text{ A}$) | Battery Inductor Current (Signed two's complement). Positive = Charge, Negative = Discharge. Example: $+250 = +2.50\text{ A}$. |
| **`40004`** | `BAT_SOC` | `uint16_t` | $0.1\% / \text{LSB}$ | Read-Only | $0 - 1000$ ($0.0\% - 100.0\%$) | Estimated State of Charge. Example: $855 = 85.5\%$. |
| **`40005`** | `FAULT_STATUS_FLAGS` | `uint16_t` | Bitfield | Read-Only | `0x0000 - 0xFFFF` | Active Warning and Fault Flag Bitmap (see Section 3). |
| **`40006`** | `VOUT` | `uint16_t` | $10\text{ mV} / \text{LSB}$ | Read-Only | $0 - 2000$ ($0.00\text{ V} - 20.00\text{ V}$) | Regulated Battery Output Terminal Voltage. Example: $1280 = 12.80\text{ V}$. |
| **`40007`** | `IOUT` | `int16_t` | $10\text{ mA} / \text{LSB}$ | Read-Only | $-500 \dots +500$ | Filtered Inductor Output Current. |
| **`40008`** | `TEMPERATURE` | `int16_t` | $0.1^\circ\text{C} / \text{LSB}$ | Read-Only | $-200 \dots +1250$ ($-20.0^\circ\text{C} \dots +125.0^\circ\text{C}$) | Heatsink NTC Temperature. Example: $265 = 26.5^\circ\text{C}$. |
| **`40009`** | `CONTROL_STATUS` | `uint16_t` | Enum | Read-Only | `0 - 5` | Control FSM State:<br>`0` = `INIT`<br>`1` = `IDLE`<br>`2` = `CHARGE`<br>`3` = `DISCHARGE`<br>`4` = `DERATING`<br>`5` = `SAFE_STATE` |
| **`40010`** | `FAULT_CODE` | `uint16_t` | Hex Code | Read-Only | `0x0000 - 0xFFFF` | Hexadecimal diagnostic fault code of active/latched event (see Section 4). |
| **`40011`** | `FW_VERSION` | `uint16_t` | BCD Format | Read-Only | `0x0000 - 0x9999` | Firmware version in BCD. Example: `0x0120` corresponds to Firmware v1.2.0. |
| **`40012`** | `SYSTEM_UPTIME_MSW`| `uint16_t` | Seconds | Read-Only | $0 - 65535$ | System Uptime 32-bit Counter: Most-Significant 16 bits. |
| **`40013`** | `SYSTEM_UPTIME_LSW`| `uint16_t` | Seconds | Read-Only | $0 - 65535$ | System Uptime 32-bit Counter: Least-Significant 16 bits. |

---

## 3. `FAULT_STATUS_FLAGS` (Register `40005`) Bitfield Definitions

```
 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+
|      RESERVED         |B8|B7|B6|B5|B4|B3|B2|B1|B0|
+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+
```

| Bit | Name | Trigger Condition | Severity Level |
| :--- | :--- | :--- | :--- |
| **`Bit 0`** | `FLAG_OVER_VOLTAGE` | $V_{bus} > 25.0\text{ V}$ (Soft) or $> 26.0\text{ V}$ (Hard) | WARNING / CRITICAL |
| **`Bit 1`** | `FLAG_OVER_CURRENT` | $I > 4.2\text{ A}$ (Soft) or $> 5.0\text{ A}$ (Hard) | WARNING / CRITICAL |
| **`Bit 2`** | `FLAG_OVER_TEMP` | Heatsink Temperature $T > 65.0^\circ\text{C}$ | WARNING / FAULT |
| **`Bit 3`** | `FLAG_UNDER_VOLTAGE` | Battery Voltage $V_{bat} < 10.0\text{ V}$ | WARNING / FAULT |
| **`Bit 4`** | `FLAG_IPC_COMM_LOST` | Gateway-to-Control SPI heartbeat lost $> 500\text{ ms}$ | FAULT |
| **`Bit 5`** | `FLAG_IEC_SELFTEST_FAIL`| Startup or runtime IEC 60730 test anomaly | CRITICAL |
| **`Bit 6`** | `FLAG_WATCHDOG_CSS_FAIL`| Window Watchdog violation or Crystal Clock fail | CRITICAL |
| **`Bit 7`** | `FLAG_HW_BREAK_TRIP` | Hardware Comparator triggered `TIM1_BKIN` | CRITICAL |
| **`Bit 8`** | `FLAG_BMS_CAN_LOST` | CAN telemetry from external BMS node timed out | WARNING |
| **`Bits 9–15`**| `RESERVED` | Reserved for future expansion (always 0) | N/A |

---

## 4. `FAULT_CODE` (Register `40010`) Diagnostic Hex Codes

| Hex Code | Symbol | Description | Required Clearing Action |
| :--- | :--- | :--- | :--- |
| `0x0000` | `NO_FAULT` | System operating normally within nominal boundaries | None |
| `0xE001` | `ERR_HW_BREAK_OC` | Tier-0 Hardware Break triggered by over-current comparator ($> 5.0\text{ A}$) | Verify circuit; write `0xFF` to `40001` |
| `0xE002` | `ERR_HW_BREAK_OV` | Tier-0 Hardware Break triggered by over-voltage comparator ($> 26.0\text{ V}$) | Verify supply; write `0xFF` to `40001` |
| `0xE010` | `ERR_IEC_CPU_REG` | IEC 60730 pre-execution CPU register pattern test failure | Cold Power Cycle Reboot |
| `0xE011` | `ERR_IEC_RAM_MARCHC`| IEC 60730 runtime sliced March C- SRAM check failure | Cold Power Cycle Reboot |
| `0xE012` | `ERR_IEC_FLASH_CRC` | Active application Flash CRC mismatch against golden header | Reflash valid signed firmware |
| `0xE020` | `ERR_IPC_TIMEOUT` | SPI DMA IPC continuous packet drop / timeout ($> 500\text{ ms}$) | Re-establish link; write `0xFF` to `40001` |
| `0xE030` | `ERR_THERMAL_OVERTEMP`| Power stage heatsink temperature exceeded $65^\circ\text{C}$ | Cool down $< 45^\circ\text{C}$; write `0xFF` |
| `0xE040` | `ERR_UNDER_VOLT_LOCK` | Battery terminal voltage dropped below UVLO threshold ($< 9.5\text{ V}$) | Charge battery; write `0xFF` |
