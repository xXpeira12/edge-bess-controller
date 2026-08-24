# Hardware Sensing Front-End & Analog Topology Specification

**Document:** `docs/architecture/hardware_sensing_and_analog_frontend.md`  
**Related SRS IDs:** `REQ-SENS-001`, `REQ-SENS-002`, `REQ-SENS-003`, `REQ-SAFE-005`

---

## 1. Analog Front-End (AFE) Overview

The Desk-Scale BESS Controller requires high-speed, noise-immune, and low-drift analog signal conditioning for four primary feedback signals:
1. **DC Bus Voltage ($V_{bus}$):** $18.0\text{ V} - 24.0\text{ V}$ nominal ($30.0\text{ V}$ absolute maximum).
2. **Battery Terminal Voltage ($V_{bat}$):** $10.0\text{ V} - 14.6\text{ V}$ nominal ($16.0\text{ V}$ absolute maximum).
3. **Inductor / Battery Current ($I_L$):** Bi-directional $-3.5\text{ A}$ (Discharge) to $+3.5\text{ A}$ (Charge), peak trip at $\pm 5.0\text{ A}$.
4. **Power Stage Heatsink Temperature ($T_{sink}$):** $-20^\circ\text{C}$ to $+100^\circ\text{C}$ (NTC Thermistor).

```
+===================================================================================================+
|                                    ANALOG FRONT-END ARCHITECTURE                                  |
|                                                                                                   |
|  [ V_BUS 18-24V ] ----> [ 10:1 Resistor Divider ] ----> [ Unity Gain Op-Amp ] ----> [ RC Filter ]|
|                                                               |                             |     |
|                                                               v                             v     |
|                                                        [ COMP2 (Trip) ]             [ ADC2 Channel|
|                                                                                             |     |
|  [ Current Shunt ] ---> [ INA240 CSA (Gain 50) ] -----> [ Mid-Rail 1.65V Ref]               |     |
|    (10 mOhm 1%)                  |                            |                             |     |
|                                  +----------------------------+                             |     |
|                                  |                            |                             |     |
|                                  v                            v                             |     |
|                          [ COMP1 Over-I Trip ]         [ RC Filter ]                        |     |
|                                  |                            |                             |     |
|                                  v                            v                             |     |
|                          [ TIM1_BKIN Break ]           [ ADC1 Channel (50kHz) ] <-----------+     |
+===================================================================================================+
```

---

## 2. Voltage Sensing Conditioning Circuitry

### 2.1 Resistive Divider Network & Buffering

To measure $V_{bus}$ (max $30.0\text{ V}$) and $V_{bat}$ (max $16.0\text{ V}$) using the MCU's $0.0\text{ V} - 3.3\text{ V}$ ADC range ($V_{ref+} = 3.30\text{ V}$), a precision voltage divider is utilized:

$$V_{adc\_in} = V_{bus} \cdot \left( \frac{R_2}{R_1 + R_2} \right)$$

* **Resistor Selection:**
  - $R_1 = 90.0\text{ k}\Omega \pm 0.1\%$ ($25\text{ ppm}/^\circ\text{C}$, 0805 thin-film)
  - $R_2 = 10.0\text{ k}\Omega \pm 0.1\%$ ($25\text{ ppm}/^\circ\text{C}$, 0805 thin-film)
  - Division Ratio: $K_{div} = \frac{10}{90 + 10} = 0.1000$ ($10:1$ attenuation)
  - Maximum Nominal Input at $V_{bus} = 24.0\text{ V}$: $V_{adc} = 2.400\text{ V}$ ($72.7\%$ of ADC Full Scale)
  - Maximum Input at $V_{bus\_max} = 30.0\text{ V}$: $V_{adc} = 3.000\text{ V}$ ($90.9\%$ of ADC Full Scale)

### 2.2 Op-Amp Buffer & Antialiasing Filter

To isolate the high-impedance divider network from ADC sample-and-hold capacitor switching currents:
* **Operational Amplifier:** Rail-to-rail precision op-amp (e.g. MCP6002 or OPA2340) in unity-gain buffer configuration.
* **Low-Pass Filter:** First-order passive RC filter at buffer output:
  - $R_{filt} = 1.0\text{ k}\Omega \pm 1\%$
  - $C_{filt} = 3.3\text{ nF}$ (C0G/NP0 dielectric for zero voltage coefficient)
  - Cutoff Frequency ($f_c$):
    $$f_c = \frac{1}{2 \pi R_{filt} C_{filt}} = \frac{1}{2 \pi \times 1000 \times 3.3 \times 10^{-9}} \approx 48.2\text{ kHz}$$
  - Phase delay at $50\text{ kHz}$ is compensated deterministically within digital PID loop coefficients.

---

## 3. Current Sensing & Current Sense Amplifier (CSA)

### 3.1 Shunt Resistor & CSA Topology

* **Shunt Resistor ($R_{shunt}$):**
  - Value: $10.0\text{ m}\Omega$
  - Tolerance: $\pm 1.0\%$
  - Power Rating: $3.0\text{ W}$ (Bourns CSS2H-2512 series)
  - Temperature Coefficient: $< \pm 50\text{ ppm}/^\circ\text{C}$
  - Power Dissipation at $I_{max} = 5.0\text{ A}$: $P = I^2 R = (5.0)^2 \times 0.010 = 0.25\text{ W}$ (operated at $<10\%$ of rated power to eliminate self-heating drift).

* **Current Sense Amplifier (CSA):**
  - Recommended IC: **TI INA240A2** (Enhanced PWM Rejection, Gain $G = 50\text{ V/V}$) or **INA180A2**.
  - PWM Rejection: $> 90\text{ dB}$ CMRR at $50\text{ kHz}$ switching edge transitions ($dV/dt > 10\text{ V/ns}$).
  - Reference Voltage ($V_{REF}$): Biased at $V_{REF} = 1.650\text{ V}$ using a precision voltage reference (e.g. LM4040-1.65) to permit bi-directional current measurement:
    $$V_{csa\_out} = V_{REF} + (I_L \cdot R_{shunt} \cdot G)$$
    $$V_{csa\_out} = 1.65\text{ V} + (I_L \times 0.010\,\Omega \times 50\,\text{V/V}) = 1.65\text{ V} + (I_L \times 0.500\,\text{V/A})$$

| Current ($I_L$) | CSA Output ($V_{csa\_out}$) | 12-Bit ADC Raw (3.3V FS) | Status / State |
| :--- | :--- | :--- | :--- |
| **$-5.0\text{ A}$ (Discharge Peak)** | $1.65 - 2.50 = -0.85\text{ V}$ (Clamped to $0.0\text{ V}$) | $0$ | Hard Break Negative OC Trip |
| **$-3.5\text{ A}$ (Discharge Full)** | $1.65 - 1.75 = 0.00\text{ V}$ (Margin offset: $0.15\text{ V}$) | $\approx 186$ | Maximum Discharge Operating Boundary |
| **$0.0\text{ A}$ (Zero Current / Idle)**| $1.650\text{ V}$ | $2048$ ($0\text{x800}$) | Quiescent Mid-Rail |
| **$+3.5\text{ A}$ (Charge Full)** | $1.65 + 1.75 = 3.150\text{ V}$ | $\approx 3910$ | Maximum Charge Operating Boundary |
| **$+5.0\text{ A}$ (Charge Peak)** | $1.65 + 2.50 = 4.15\text{ V}$ (Clamped to $3.3\text{ V}$) | $4095$ ($0\text{xFFF}$) | Hard Break Positive OC Trip |

### 3.2 Dual-Path Trip / Feedback Configuration

```
                          CSA OUTPUT SPLIT CIRCUIT
                          
                       +-----------------------------+
                       |       INA240 Output         |
                       | V_out = 1.65V +/- 0.5V/A    |
                       +-----------------------------+
                                      |
                 +--------------------+--------------------+
                 |                                         |
                 v                                         v
        [ Filter: 1k / 2.2nF ]                     [ Fast Analog Comparator ]
         fc = 72.3 kHz                              (COMP1 / External TLV3501)
                 |                                         |
                 v                                         v
        MCU ADC1 Channel 1                         Compare with V_Trip_High (3.15V)
       (Synchronous Center Sample)                 and V_Trip_Low (0.15V)
                 |                                         |
                 v                                         v
       Discrete PID Algorithm                     Timer Break Input (BKIN)
       (inner current loop @ 50kHz)               (Hardware PWM Kill <= 2.0us)
```

1. **Digital Feedback Path:** Passed through an antialiasing filter ($R = 1.0\text{ k}\Omega$, $C = 2.2\text{ nF}$, $f_c = 72.3\text{ kHz}$) to the MCU ADC channel for synchronous sampling at the PWM center-point.
2. **Hardware Protection Path:** Directly connected without RC delay to internal comparator `COMP1` and `COMP2` configured as a window comparator. If the voltage breaches the $0.15\text{ V} - 3.15\text{ V}$ window ($\pm 3.0\text{ A}$ nominal, hard trip $\pm 5.0\text{ A}$ with hysteresis), `COMP1_OUT` asserts `HIGH`, driving the timer `BKIN` circuit asynchronously.
