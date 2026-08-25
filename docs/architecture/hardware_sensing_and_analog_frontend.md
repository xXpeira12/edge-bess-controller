# Hardware Sensing Front-End & Analog Topology Specification

**Document:** `docs/architecture/hardware_sensing_and_analog_frontend.md`  
**Related SRS IDs:** `REQ-SENS-001`, `REQ-SENS-002`, `REQ-SENS-003`, `REQ-SAFE-005`

---

## 1. Single Source of Truth: Analog Sensing Parameters

This document is the authoritative **Single Source of Truth** for all analog sensing circuitry, component values, transfer functions, filter parameters, and comparator trip derivations.

```
+===================================================================================================+
|                                    ANALOG FRONT-END ARCHITECTURE                                  |
|                                                                                                   |
|  [ V_BUS 18-24V ] ----> [ 10:1 Resistor Divider ] ----> [ Unity Gain Op-Amp ] ----> [ RC Filter ]|
|                                                               |                             |     |
|                                                               v                             v     |
|                                                        [ COMP2 (Trip) ]             [ ADC2 Channel|
|                                                                                             |     |
|  [ Current Shunt ] ---> [ INA240A1 (Gain 20) ] -------> [ Mid-Rail 1.650V Ref]              |     |
|    (10 mOhm 1%)                  |                            |                             |     |
|                                  +----------------------------+                             |     |
|                                  |                            |                             |     |
|                                  v                            v                             |     |
|                          [ COMP1 Over-I Trip ]         [ RC Filter ]                        |     |
|                          (Internal STM32G4)            (fc = 72.3 kHz)                      |     |
|                                  |                            |                             |     |
|                                  v                            v                             |     |
|                          [ HRTIM/TIM1 BKIN ]           [ ADC1 Channel (50kHz) ] <-----------+     |
+===================================================================================================+
```

---

## 2. Voltage Sensing Conditioning Circuitry & Anti-Aliasing Filter

### 2.1 Resistive Divider Network & Buffering
To measure $V_{bus}$ (max $30.0\text{ V}$) and $V_{bat}$ (max $16.0\text{ V}$) using the MCU's $0.0\text{ V} - 3.3\text{ V}$ ADC range ($V_{ref+} = 3.300\text{ V}$):

$$V_{adc\_in} = V_{bus} \cdot \left( \frac{R_2}{R_1 + R_2} \right)$$

* **Resistor Selection:**
  - $R_1 = 90.0\text{ k}\Omega \pm 0.1\%$ ($25\text{ ppm}/^\circ\text{C}$, 0805 thin-film)
  - $R_2 = 10.0\text{ k}\Omega \pm 0.1\%$ ($25\text{ ppm}/^\circ\text{C}$, 0805 thin-film)
  - Attenuation Ratio: $K_{div} = \frac{10}{90 + 10} = 0.1000$ ($10:1$ attenuation)
  - Nominal $V_{bus} = 24.0\text{ V} \to V_{adc} = 2.400\text{ V}$ ($72.7\%$ of ADC Full Scale)
  - Maximum $V_{bus\_max} = 30.0\text{ V} \to V_{adc} = 3.000\text{ V}$ ($90.9\%$ of ADC Full Scale)

### 2.2 Anti-Aliasing Filter Calculation & Sampling Theory
An operational amplifier buffer isolates the divider from ADC sample capacitor transients. The output passes through a passive RC filter ($R = 1.0\text{ k}\Omega, C = 3.3\text{ nF}$):

$$f_c = \frac{1}{2 \pi R_{filt} C_{filt}} = \frac{1}{2 \pi \times 1000 \times 3.3 \times 10^{-9}} \approx 48.2\text{ kHz}$$

* **Filter Frequency Response:**
  $$|H(f)| = \frac{1}{\sqrt{1 + (f / f_c)^2}}, \quad \theta(f) = -\arctan\left(\frac{f}{f_c}\right)$$
  - **At Nyquist Frequency ($f_{Nyquist} = 25.0\text{ kHz}$):**
    $$|H(25\text{ kHz})| = \frac{1}{\sqrt{1 + (25 / 48.2)^2}} \approx 0.887 \quad (-1.04\text{ dB}), \quad \theta = -27.4^\circ$$
  - **At Switching Frequency ($f_{sw} = 50.0\text{ kHz}$):**
    $$|H(50\text{ kHz})| = \frac{1}{\sqrt{1 + (50 / 48.2)^2}} \approx 0.694 \quad (-3.17\text{ dB}), \quad \theta = -46.0^\circ$$

---

## 3. Current Sensing & Current Sense Amplifier (CSA)

### 3.1 Standardized CSA IC Selection & Transfer Function
* **Shunt Resistor ($R_{shunt}$):** $10.0\text{ m}\Omega \pm 1.0\%$, $3.0\text{ W}$ low-inductance shunt (Bourns CSS2H-2512, TCR $< \pm 50\text{ ppm}/^\circ\text{C}$).
* **Current Sense Amplifier (CSA):** Off-the-shelf **TI INA240A1** (Enhanced PWM Rejection, Gain $G = 20\text{ V/V}$) or **INA180A1**.
* **Reference Bias:** $V_{REF} = 1.650\text{ V}$ precision mid-rail voltage.
* **Sensitivity Factor:**
  $$S = R_{shunt} \times G = 0.010\,\Omega \times 20\,\text{V/V} = 0.200\,\text{V/A}$$
* **Authoritative Transfer Function:**
  $$V_{csa\_out} = V_{REF} + (I_L \cdot R_{shunt} \cdot G) = 1.650\text{ V} + (I_L \times 0.200\,\text{V/A})$$

### 3.2 Threshold Derivations & Current Mapping Table

Direct derivation: $V = V_{REF} \pm (I \times 0.200\text{ V/A})$

| Operating Level | Inductor Current ($I_L$) | CSA Output ($V_{csa\_out}$) | 12-Bit ADC Code ($3.3\text{V FS}$) | Action & Description |
| :--- | :--- | :--- | :--- | :--- |
| **Linear Negative Saturation** | $-8.25\text{ A}$ | $1.65 - 1.65 = 0.000\text{ V}$ | $0$ ($0\text{x000}$) | ADC lower full-scale limit |
| **Hardware Negative Trip** | $\mathbf{-5.0\text{ A}}$ | $1.65 - 1.00 = \mathbf{0.650\text{ V}}$ | $\mathbf{807}$ ($0\text{x327}$) | **Tier 0:** Hardware Break PWM LOW ($\le 2.0\,\mu\text{s}$) |
| **Software Negative Warning** | $\mathbf{-4.0\text{ A}}$ | $1.65 - 0.80 = \mathbf{0.850\text{ V}}$ | $\mathbf{1055}$ ($0\text{x41F}$) | **Level 2:** Emergency ramp-down at $100\text{ A/s}$ |
| **Normal Max Discharge** | $\mathbf{-3.5\text{ A}}$ | $1.65 - 0.70 = \mathbf{0.950\text{ V}}$ | $\mathbf{1179}$ ($0\text{x49B}$) | Continuous Full-Load Discharge Boundary |
| **Nominal Discharge Point** | $-2.5\text{ A}$ | $1.65 - 0.50 = 1.150\text{ V}$ | $1427$ ($0\text{x593}$) | Nominal Discharge PID Setpoint |
| **Zero Current (Quiescent)** | $\mathbf{0.0\text{ A}}$ | $\mathbf{1.650\text{ V}}$ | $\mathbf{2048}$ ($0\text{x800}$) | Quiescent Mid-Rail Operating Bias |
| **Nominal Charge Point** | $+2.5\text{ A}$ | $1.65 + 0.50 = 2.150\text{ V}$ | $2668$ ($0\text{xA6C}$) | Nominal Charge PID Setpoint |
| **Normal Max Charge** | $\mathbf{+3.5\text{ A}}$ | $1.65 + 0.70 = \mathbf{2.350\text{ V}}$ | $\mathbf{2916}$ ($0\text{xB64}$) | Continuous Full-Load Charge Boundary |
| **Software Positive Warning** | $\mathbf{+4.0\text{ A}}$ | $1.65 + 0.80 = \mathbf{2.450\text{ V}}$ | $\mathbf{3041}$ ($0\text{xBE1}$) | **Level 2:** Emergency ramp-down at $100\text{ A/s}$ |
| **Hardware Positive Trip** | $\mathbf{+5.0\text{ A}}$ | $1.65 + 1.00 = \mathbf{2.650\text{ V}}$ | $\mathbf{3289}$ ($0\text{xCD9}$) | **Tier 0:** Hardware Break PWM LOW ($\le 2.0\,\mu\text{s}$) |
| **Linear Positive Saturation** | $+8.25\text{ A}$ | $1.65 + 1.65 = 3.300\text{ V}$ | $4095$ ($0\text{xFFF}$) | ADC upper full-scale limit |

---

## 4. Dual-Path Split & Primary Comparator Selection

* **Primary Path (STM32G474 Internal Comparators `COMP1` / `COMP2`):**
  - Integrated fast rail-to-rail analog comparators ($25\text{ ns}$ maximum delay in high-speed mode).
  - Reference voltages configured via internal $12\text{ bit}$ DACs:
    - $V_{comp\_high} = 2.650\text{ V}$ ($+5.0\text{ A}$ Hardware Over-Current Trip)
    - $V_{comp\_low} = 0.650\text{ V}$ ($-5.0\text{ A}$ Hardware Over-Current Trip)
  - Direct silicon routing to `HRTIM_FAULT1` / `TIM1_BKIN`.
* **Antialiasing Filter Calculation ($R = 1.0\text{ k}\Omega, C = 2.2\text{ nF}, f_c = 72.3\text{ kHz}$):**
  - At $f_{Nyquist} = 25.0\text{ kHz}$: $|H(25\text{k})| = 0.945$ ($-0.49\text{ dB}$), $\theta = -19.1^\circ$.
  - At $f_{sw} = 50.0\text{ kHz}$: $|H(50\text{k})| = 0.822$ ($-1.70\text{ dB}$), $\theta = -34.7^\circ$.
