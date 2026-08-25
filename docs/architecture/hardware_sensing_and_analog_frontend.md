# Hardware Sensing Front-End & Analog Topology Specification

**Document:** `docs/architecture/hardware_sensing_and_analog_frontend.md`  
**Related SRS IDs:** `REQ-SENS-001`, `REQ-SENS-002`, `REQ-SENS-003`, `REQ-SAFE-005`

---

## 1. Analog Front-End (AFE) Overview

The Desk-Scale BESS Controller requires high-speed, noise-immune, and low-drift analog signal conditioning for four primary feedback signals:
1. **DC Bus Voltage ($V_{bus}$):** $18.0\text{ V} - 24.0\text{ V}$ nominal ($26.0\text{ V}$ maximum, $30.0\text{ V}$ absolute maximum transient).
2. **Battery Terminal Voltage ($V_{bat}$):** $10.0\text{ V} - 14.6\text{ V}$ nominal ($16.0\text{ V}$ maximum).
3. **Inductor / Battery Current ($I_L$):** Bi-directional $-3.5\text{ A}$ (Discharge) to $+3.5\text{ A}$ (Charge), warning threshold at $\pm 4.0\text{ A}$, hard trip at $\pm 5.0\text{ A}$.
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
|  [ Current Shunt ] ---> [ INA240 CSA (Gain 40) ] -----> [ Mid-Rail 1.65V Ref]               |     |
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
To measure $V_{bus}$ (max $30.0\text{ V}$) and $V_{bat}$ (max $16.0\text{ V}$) using the MCU's $0.0\text{ V} - 3.3\text{ V}$ ADC range ($V_{ref+} = 3.30\text{ V}$), a precision voltage divider is utilized:

$$V_{adc\_in} = V_{bus} \cdot \left( \frac{R_2}{R_1 + R_2} \right)$$

* **Resistor Selection:**
  - $R_1 = 90.0\text{ k}\Omega \pm 0.1\%$ ($25\text{ ppm}/^\circ\text{C}$, 0805 thin-film)
  - $R_2 = 10.0\text{ k}\Omega \pm 0.1\%$ ($25\text{ ppm}/^\circ\text{C}$, 0805 thin-film)
  - Attenuation Ratio: $K_{div} = \frac{10}{90 + 10} = 0.1000$ ($10:1$ attenuation)
  - Nominal $V_{bus} = 24.0\text{ V} \to V_{adc} = 2.400\text{ V}$ ($72.7\%$ of ADC Full Scale)
  - Maximum $V_{bus\_max} = 30.0\text{ V} \to V_{adc} = 3.000\text{ V}$ ($90.9\%$ of ADC Full Scale)

### 2.2 Anti-Aliasing Filter Calculation & Sampling Theory
An operational amplifier buffer (MCP6002 / OPA2340) isolates the divider from ADC sample capacitor transients. The output passes through a passive RC filter ($R = 1.0\text{ k}\Omega, C = 3.3\text{ nF}$):

$$f_c = \frac{1}{2 \pi R_{filt} C_{filt}} = \frac{1}{2 \pi \times 1000 \times 3.3 \times 10^{-9}} \approx 48.2\text{ kHz}$$

* **Filter Frequency Response:**
  $$|H(f)| = \frac{1}{\sqrt{1 + (f / f_c)^2}}, \quad \theta(f) = -\arctan\left(\frac{f}{f_c}\right)$$
  - **At Nyquist Frequency ($f_{Nyquist} = 25.0\text{ kHz}$):**
    $$|H(25\text{ kHz})| = \frac{1}{\sqrt{1 + (25 / 48.2)^2}} \approx 0.887 \quad (-1.04\text{ dB}), \quad \theta = -27.4^\circ$$
  - **At Switching Frequency ($f_{sw} = 50.0\text{ kHz}$):**
    $$|H(50\text{ kHz})| = \frac{1}{\sqrt{1 + (50 / 48.2)^2}} \approx 0.694 \quad (-3.17\text{ dB}), \quad \theta = -46.0^\circ$$
* Phase lag $\theta$ at $50\text{ kHz}$ is explicitly factored into discrete PID derivative and phase-lead compensator coefficients.

---

## 3. Current Sensing & Current Sense Amplifier (CSA)

### 3.1 Shunt Resistor & Transfer Function
* **Shunt Resistor ($R_{shunt}$):** $10.0\text{ m}\Omega \pm 1.0\%$, $3.0\text{ W}$ low-inductance shunt (Bourns CSS2H-2512, TCR $< \pm 50\text{ ppm}/^\circ\text{C}$).
* **Current Sense Amplifier (CSA):** **TI INA240A1** (Enhanced PWM Rejection, Gain $G = 40\text{ V/V}$) or **INA180A1**.
* **Reference Bias:** $V_{REF} = 1.650\text{ V}$ precision mid-rail voltage.
* **Transfer Function:**
  $$V_{csa\_out} = V_{REF} + (I_L \cdot R_{shunt} \cdot G) = 1.650\text{ V} + (I_L \times 0.010\,\Omega \times 40\,\text{V/V}) = 1.650\text{ V} + (I_L \times 0.400\,\text{V/A})$$

### 3.2 Current Levels & ADC / Trip Mapping Table

| Operating Level | Inductor Current ($I_L$) | CSA Output ($V_{csa\_out}$) | 12-Bit ADC Code ($3.3\text{V FS}$) | System State & Action |
| :--- | :--- | :--- | :--- | :--- |
| **Hardware Negative Trip** | $-5.0\text{ A}$ (Discharge) | $1.65 - 2.00 = -0.35\text{ V}$ (Clamped $0.0\text{V}$) | $0$ | **Tier 0:** Hardware Break PWM LOW ($\le 2.0\,\mu\text{s}$) |
| **Software Negative Warning** | $-4.0\text{ A}$ (Discharge) | $1.65 - 1.60 = 0.050\text{ V}$ | $62$ | **Level 2:** Emergency ramp-down at $100\text{ A/s}$ |
| **Normal Max Discharge** | $-3.5\text{ A}$ (Discharge) | $1.65 - 1.40 = 0.250\text{ V}$ | $310$ | Continuous Full-Load Discharge Boundary |
| **Nominal Operating Point** | $\pm 2.5\text{ A}$ | $0.650\text{ V} \dots 2.650\text{ V}$ | $807 \dots 3289$ | Normal PID Closed-Loop Regulation |
| **Zero Current (Quiescent)** | $0.0\text{ A}$ (Idle) | $1.650\text{ V}$ | $2048$ ($0\text{x800}$) | Quiescent Mid-Rail Operating Bias |
| **Normal Max Charge** | $+3.5\text{ A}$ (Charge) | $1.65 + 1.40 = 3.050\text{ V}$ | $3785$ | Continuous Full-Load Charge Boundary |
| **Software Positive Warning** | $+4.0\text{ A}$ (Charge) | $1.65 + 1.60 = 3.250\text{ V}$ | $4033$ | **Level 2:** Emergency ramp-down at $100\text{ A/s}$ |
| **Hardware Positive Trip** | $+5.0\text{ A}$ (Charge) | $1.65 + 2.00 = 3.65\text{ V}$ (Clamped $3.3\text{V}$) | $4095$ ($0\text{xFFF}$) | **Tier 0:** Hardware Break PWM LOW ($\le 2.0\,\mu\text{s}$) |

### 3.3 Separation of the Three Current Thresholds
1. **Normal Operating Envelope ($\pm 3.5\text{ A}$):** Fully within $0.250\text{ V} \dots 3.050\text{ V}$ ($250\text{ mV}$ margin from rails, preventing ADC non-linear clipping).
2. **Software Warning / Throttling ($\pm 4.0\text{ A}$):** Monitored in real-time software loop; initiates emergency current ramp-down ($100\text{ A/s}$) to prevent tripping hardware protection.
3. **Hardware Emergency Break Trip ($\pm 5.0\text{ A}$):** Autonomous silicon protection tripping Timer Break Input asynchronously.

---

## 4. Dual-Path Split & Primary Comparator Selection

```
                          CSA OUTPUT SPLIT CIRCUIT
                          
                       +-----------------------------+
                       |       INA240 Output         |
                       | V_out = 1.65V +/- 0.4V/A    |
                       +-----------------------------+
                                      |
                 +--------------------+--------------------+
                 |                                         |
                 v                                         v
        [ Filter: 1k / 2.2nF ]                     [ Fast Analog Comparator ]
         fc = 72.3 kHz                              (PRIMARY: Internal COMP1/COMP2)
                 |                                  (SECONDARY: External TLV3501)
                 v                                         |
        MCU ADC1 Channel 1                                 v
       (Synchronous 50 kHz Center)                 Compare against V_Trip_High (3.25V)
                 |                                 and V_Trip_Low (0.05V)
                 v                                         |
       Discrete PID Algorithm                              v
       (inner current loop @ 50kHz)                HRTIM / TIM1 Break (BKIN)
                                                   (PWM Hardware Kill <= 2.0us)
```

* **Primary Path (STM32G474 Internal Comparators `COMP1` / `COMP2`):**
  - Integrated ultra-fast rail-to-rail analog comparators ($16\text{ ns}$ propagation delay in high-speed mode).
  - Reference voltages set dynamically via internal $12\text{ bit}$ DACs (`DAC1_CH1 = 3.250V`, `DAC1_CH2 = 0.050V`).
  - Internal silicon routing directly to `HRTIM_FAULT1` / `TIM1_BKIN` (zero external PCB trace delay).
* **Secondary / Porting Option (External TLV3501):**
  - Ultra-fast discrete comparator ($4.5\text{ ns}$ delay) used for legacy boards (e.g. STM32F446).
* **Antialiasing Filter Calculation ($R = 1.0\text{ k}\Omega, C = 2.2\text{ nF}, f_c = 72.3\text{ kHz}$):**
  - At $f_{Nyquist} = 25.0\text{ kHz}$: $|H(25\text{k})| = 0.945$ ($-0.49\text{ dB}$), $\theta = -19.1^\circ$.
  - At $f_{sw} = 50.0\text{ kHz}$: $|H(50\text{k})| = 0.822$ ($-1.70\text{ dB}$), $\theta = -34.7^\circ$.
