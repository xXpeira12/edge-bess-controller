# Hardware Sensing Front-End & Analog Topology Specification

**Document:** `docs/architecture/hardware_sensing_and_analog_frontend.md`  
**Related SRS IDs:** `REQ-SENS-001`, `REQ-SENS-002`, `REQ-SENS-003`, `REQ-SAFE-005`

---

## 1. Single Source of Truth: Analog Sensing Parameters

This document is the authoritative **Single Source of Truth** for all analog sensing circuitry, component values, transfer functions, threshold-crossing models, pin mappings, and comparator trip derivations.

```
+===================================================================================================+
|                                    ANALOG FRONT-END ARCHITECTURE                                  |
|                                                                                                   |
|  [ V_BUS 18-24V ] ----> [ 10:1 Resistor Divider ] ----> [ Unity Gain Op-Amp ] ----> [ RC Filter ]|
|                                                               |                             |     |
|                                                               v                             v     |
|                                                        [ COMP3 (PA0) ]              [ ADC2 Channel|
|                                                                                             |     |
|  [ Current Shunt ] ---> [ INA240A1 (Gain 20) ] -------> [ Mid-Rail 1.650V Ref]              |     |
|    (10 mOhm 1%)                  |                            |                             |     |
|                                  +----------------------------+                             |     |
|                                  |                            |                             |     |
|                                  v                            v                             |     |
|                          [ COMP1/2 Over-I Trip ]       [ RC Filter ]                        |     |
|                          (Internal STM32G4)            (fc = 72.3 kHz)                      |     |
|                                  |                            |                             |     |
|                                  v                            v                             |     |
|                          [ HRTIM1_FLT1/2/3 ]           [ ADC1 Channel (50kHz) ] <-----------+     |
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
  - Nominal $V_{bus} = 24.0\text{ V} \to V_{adc} = 2.400\text{ V}$
  - Over-Voltage Trip $V_{bus} = 26.0\text{ V} \to V_{adc} = 2.600\text{ V}$ ($26.0\text{ V} / 10$)

### 2.2 Anti-Aliasing Filter Calculation & Sampling Theory
$$f_c = \frac{1}{2 \pi R_{filt} C_{filt}} = \frac{1}{2 \pi \times 1000 \times 3.3 \times 10^{-9}} \approx 48.2\text{ kHz}$$
* At $f_{Nyquist} = 25.0\text{ kHz}$: $|H(25\text{ kHz})| \approx 0.887$ ($-1.04\text{ dB}$), $\theta = -27.4^\circ$.
* At $f_{sw} = 50.0\text{ kHz}$: $|H(50\text{ kHz})| \approx 0.694$ ($-3.17\text{ dB}$), $\theta = -46.0^\circ$.

---

## 3. Current Sensing & Threshold-Crossing Latency Model

### 3.1 Standardized CSA IC Selection & Transfer Function
* **Shunt Resistor ($R_{shunt}$):** $10.0\text{ m}\Omega \pm 1.0\%$, $3.0\text{ W}$ low-inductance shunt (Bourns CSS2H-2512).
* **Current Sense Amplifier (CSA):** **TI INA240A1** (Gain $G = 20\text{ V/V}$, sensitivity $0.200\text{ V/A}$, $V_{REF} = 1.650\text{ V}$). *(Note: INA180 may only be considered as a non-recommended BOM alternative).*
* **Authoritative Transfer Function:**
  $$V_{csa\_out} = V_{REF} + (I_L \cdot R_{shunt} \cdot G) = 1.650\text{ V} + (I_L \times 0.200\,\text{V/A})$$

### 3.2 Physical Threshold-Crossing Latency Model
* **INA240A1 Specifications:** Small-signal bandwidth = $400\text{ kHz}$, Slew Rate = $2.0\text{ V/\mu s}$, Full $0.1\%$ Settling Time = $9.6\,\mu\text{s}$.
* **Fault Dynamics:** During a $1.5\text{ A}$ over-current transient step from nominal max ($3.5\text{ A}$) to hard trip ($5.0\text{ A}$):
  $$\Delta V_{out} = \Delta I \times S = 1.5\text{ A} \times 0.200\text{ V/A} = 300\text{ mV}$$
  $$T_{slew} = \frac{0.300\text{ V}}{2.0\text{ V/\mu s}} = 150\text{ ns}$$
  $$T_{CSA\_cross} = T_{prop} + T_{slew} \approx 150\text{ ns} + 150\text{ ns} = \mathbf{300\text{ ns}}$$
* This threshold-crossing time is measurably distinct from the full $9.6\,\mu\text{s}$ settling time, ensuring the comparator trips in sub-microsecond time.

### 3.3 Trip Threshold Tolerance Budget
Accounting for:
* Shunt tolerance: $\pm 1.0\%$
* INA240A1 gain error: $\pm 0.20\%$
* Input offset voltage: $\pm 0.5\text{ mV} \to \pm 0.05\text{ A}$
* DAC reference error: $\pm 1.0\%$
* Comparator offset: $\pm 5.0\text{ mV} \to \pm 0.025\text{ A}$

$$\mathbf{I_{trip,actual} = \pm 5.0\text{ A} \pm 0.15\text{ A} \quad (\pm 4.85\text{ A} \dots \pm 5.15\text{ A})}$$

---

## 4. STM32G474RE Exact Pin & Peripheral Routing Table

| Protection Channel | Comparator | Non-Inverting Input (`COMPx_INP`) | Inverting Input (`COMPx_INM`) | Reference Voltage | Hardware Break Link | Action |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Hard OC+** ($> +5.0\text{ A}$) | `COMP1` | `PA1` (CSA $V_{out}$) | `DAC1_CH1` | $2.650\text{ V}$ | `HRTIM1_FLT1` (internal) | PWM forced LOW ($\le 2.0\,\mu\text{s}$) |
| **Hard OC-** ($< -5.0\text{ A}$) | `COMP2` | `PA7` (CSA $V_{out}$) | `DAC1_CH2` | $0.650\text{ V}$ | `HRTIM1_FLT2` (internal) | PWM forced LOW ($\le 2.0\,\mu\text{s}$) |
| **Hard OV** ($> 26.0\text{ V}$) | `COMP3` | `PA0` ($V_{bus}$ 10:1 AFE) | `DAC2_CH1` | $2.600\text{ V}$ ($26\text{V}/10$) | `HRTIM1_FLT3` (internal) | PWM forced LOW ($\le 2.0\,\mu\text{s}$) |

* **Hardware Invariant:** HRTIM fault digital filters are disabled (`FLTxF = 0000`) for zero-delay asynchronous tripping.
