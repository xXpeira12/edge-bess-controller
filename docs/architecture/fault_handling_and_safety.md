# Multi-Tier Fault Handling & Functional Safety Architecture

**Document:** `docs/architecture/fault_handling_and_safety.md`  
**Related SRS IDs:** `REQ-SAFE-001` through `REQ-SAFE-006`, `REQ-SEC-001` through `REQ-SEC-003`

---

## 1. Single Source of Truth: Protection Tiers & Safety Invariants

This document is the authoritative **Single Source of Truth** for the multi-tier protection framework, distinct Over-Current and Over-Voltage Tier-0 hardware latency models, itemized tolerance budgets, and fault recovery invariants.

```
+===================================================================================================+
|                                    SAFETY & PROTECTION LAYERS                                     |
|                                                                                                   |
|  +---------------------------------------------------------------------------------------------+  |
|  | TIER 0: SILICON HARDWARE BREAK (Autonomous, <= 2.0 microseconds total path)                 |  |
|  | - Over-Current: |I| > 5.0A (0.650V / 2.650V) -> T_trip,OC = 491 ns (bench) / 691 ns (max)       |  |
|  | - Over-Voltage: V_bus > 26.0V (2.600V)       -> T_trip,OV = 241 ns (preliminary model)         |  |
|  | - Internal COMP1/2/3 -> HRTIM1_FLT4/1/5 -> Hardware PWM Disable. Latched in Silicon.        |  |
|  +---------------------------------------------------------------------------------------------+  |
|                                                |                                                  |
|                                                v                                                  |
|  +---------------------------------------------------------------------------------------------+  |
|  | TIER 1: SOFTWARE EMERGENCY SUPERVISOR (Emergency Ramp-Down at 100 A/s)                      |  |
|  | - Soft Limits (|I| > 4.0A, T > 65C, UVLO < 9.5V, IPC Timeout > 500ms)                       |  |
|  | - Controlled current ramp-down to 0A in <= 50 ms (100 A/s deceleration rate)                |  |
|  | - If emergency ramp fails (ADC error / current does not drop) -> Immediate Break to SAFE   |  |
|  +---------------------------------------------------------------------------------------------+  |
|                                                |                                                  |
|                                                v                                                  |
|  +---------------------------------------------------------------------------------------------+  |
|  | TIER 2: NORMAL OPERATION RAMPING (Commanded Setpoints, 2.0 A/s Slew Rate)                    |  |
|  | - Normal start/stop and setpoint tracking (2 mA per 1 ms FSM supervisory tick)               |  |
|  +---------------------------------------------------------------------------------------------+  |
+===================================================================================================+
```

---

## 2. Distinct Latency Models for Over-Current (OC) and Over-Voltage (OV)

Using the STM32G474RE datasheet parameter: $T_{COMP\_HRTIM} \le 31\text{ ns}$ (internal comparator input to HRTIM output disable in high-speed mode).

### 2.1 Over-Current (OC) Hardware Break Latency Breakdown
$$T_{trip,OC} = T_{shunt} + T_{CSA\_cross} + T_{COMP\_HRTIM} + T_{gate\_driver} + T_{power\_stage}$$

| Component Stage | Parameter Symbol | Typical Delay | Worst-Case Delay | Source / Categorization | Remarks |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Shunt Parasitics** | $T_{shunt}$ | $5\text{ ns}$ | $10\text{ ns}$ | **Calculated** | Low-inductance 2512 SMD shunt ($< 0.1\text{ nH}$) |
| **CSA Crossing Delay** | $T_{CSA\_cross}$ | $250\text{ ns}$ | $300\text{ ns} / 500\text{ ns}$| **Characterized / Datasheet**| INA240A1 slew ($2.0\text{V/\mu s}$): $300\text{ns}$ ($1.5\text{A}$ step) / $500\text{ns}$ ($5\text{A}$ step) |
| **Internal Comparator to HRTIM**| $T_{COMP\_HRTIM}$| $20\text{ ns}$ | $31\text{ ns}$ | **Datasheet-Guaranteed** | STM32G474 COMP1/2 high-speed mode to HRTIM kill |
| **Gate Driver Propagation** | $T_{gate\_driver}$ | $30\text{ ns}$ | $50\text{ ns}$ | **Datasheet-Guaranteed** | UCC27211 propagation delay ($t_{pHL}$) |
| **Power Stage MOSFET** | $T_{power\_stage}$| $60\text{ ns}$ | $100\text{ ns}$ | **Bench-Measured / Prelim** | $t_{d(off)} + t_f$ with $10\,\Omega$ gate pull-down |
| **TOTAL OC TRIP LATENCY** | $\mathbf{T_{trip,OC}}$ | $\mathbf{365\text{ ns}}$ | $\mathbf{491\text{ ns} / 691\text{ ns}}$| **Combined Model** | **$\ll 2.0\,\mu\text{s}$ Maximum Requirement** |

### 2.2 Over-Voltage (OV) Hardware Break Latency Breakdown
Because `COMP3` is tapped directly after the buffer amplifier **before** the RC filter:
$$T_{trip,OV} = T_{divider} + T_{buffer} + T_{COMP\_HRTIM} + T_{gate\_driver} + T_{power\_stage}$$

| Component Stage | Parameter Symbol | Typical Delay | Worst-Case Delay | Source / Categorization | Remarks |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Divider Propagation** | $T_{divider}$ | $5\text{ ns}$ | $10\text{ ns}$ | **Calculated** | Pure resistive divider propagation |
| **Buffer Amplifier Delay**| $T_{buffer}$ | $30\text{ ns}$ | $50\text{ ns}$ | **Datasheet Slew** | Op-amp buffer slew rate ($10\text{ V/\mu s}$) |
| **Internal Comparator to HRTIM**| $T_{COMP\_HRTIM}$| $20\text{ ns}$ | $31\text{ ns}$ | **Datasheet-Guaranteed** | STM32G474 COMP3 high-speed mode to HRTIM kill |
| **Gate Driver Propagation** | $T_{gate\_driver}$ | $30\text{ ns}$ | $50\text{ ns}$ | **Datasheet-Guaranteed** | UCC27211 propagation delay ($t_{pHL}$) |
| **Power Stage MOSFET** | $T_{power\_stage}$| $60\text{ ns}$ | $100\text{ ns}$ | **Bench-Measured / Prelim** | MOSFET turn-off time |
| **TOTAL OV TRIP LATENCY** | $\mathbf{T_{trip,OV}}$ | $\mathbf{145\text{ ns}}$ | $\mathbf{241\text{ ns}}$ | **Combined Model** | **$\ll 2.0\,\mu\text{s}$ Maximum Requirement** |

---

## 3. Trip Threshold Tolerance Budget

$$\mathbf{I_{trip,actual} = \pm 5.0\text{ A} \pm 0.15\text{ A} \quad (\pm 4.85\text{ A} \dots \pm 5.15\text{ A})}$$
$$\mathbf{V_{trip,actual} = 26.0\text{ V} \pm 0.5\text{ V} \quad (25.5\text{ V} \dots 26.5\text{ V})}$$

---

## 4. Multi-Level Fault Matrix & Recovery Policy

* **Invariant:** Dedicated fault clear command (`FAULT_CLEAR_CMD = 0x00A5`) is accepted **ONLY in `SAFE_STATE`**.
* **Tier-1 Emergency Ramp Fallback:** If a Level 2 software emergency ramp-down ($100\text{ A/s}$ within $50\text{ ms}$) fails (e.g. sensor timeout or current does not drop $< 0.5\text{ A}$), the system executes an immediate hardware break trip to `STATE_SAFE_STATE`.
* **Recovery Sequence:** `SAFE_STATE` $\to$ `STATE_RECOVERY_CHECK` (verifies $V_{bat} \ge 11.0\text{ V}$, $16.0\text{ V} \le V_{bus} \le 25.0\text{ V}$, $|I_L| < 0.2\text{ A}$, $T < 45^\circ\text{C}$) $\to$ `STATE_IDLE`. Requires an explicit new `START` command to resume power flow.
