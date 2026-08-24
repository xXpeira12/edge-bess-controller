# Control Loop Timing, Jitter Budget & Verification Methodology

**Document:** `docs/architecture/timing_jitter_and_bench_verification.md`  
**Related SRS IDs:** `REQ-CTRL-001`, `REQ-CTRL-002`, `REQ-CTRL-003`, `NFR-PERF-01`

---

## 1. Real-Time Timing Budget & Determinism Overview

In digital power conversion (Synchronous Buck/Boost topology), phase margin and loop stability depend directly on deterministic execution timing. Any temporal jitter in sampling or duty-cycle update introduces phase noise and can lead to limit-cycle oscillations or catastrophic subharmonic instability.

### 1.1 Timing Parameters
* **PWM Switching Frequency ($f_{sw}$):** $50.0\text{ kHz}$ ($\pm 0.05\%$ HSE crystal accuracy)
* **Switching Period ($T_s$):** $20.0\,\mu\text{s}$ ($20,000\text{ ns}$)
* **Core Clock Frequency ($f_{cpu}$):** $168.0\text{ MHz}$ (STM32F446) / $170.0\text{ MHz}$ (STM32G474)
* **Clock Period ($t_{clk}$):** $5.95\text{ ns}$ (@ 168 MHz) / $5.88\text{ ns}$ (@ 170 MHz)
* **Allowed Interrupt Jitter ($\Delta t_{jitter}$):** $\le \pm 50.0\text{ ns}$ ($\approx \pm 8.4$ clock cycles)
* **Maximum Allowable ISR Execution Duration ($t_{isr}$):** $\le 8.0\,\mu\text{s}$ ($40.0\%$ CPU load limit)

```
0 us                       10 us                      20 us (Ts)
+--------------------------+--------------------------+
| PWM Counter Up-Counting  | PWM Counter Down-Counting| (Center-Aligned Mode)
|                          |                          |
|                          * TRGO Event (Center Point)|
|                          |                          |
|                          +-> ADC Conversion (1.2us) |
|                              +-> EOC Interrupt ISR  |
|                                  [ PID Calculation ]|
|                                  [ Clamping & Satur]|
|                                  [ Timer Duty Update|
|                                  <---- <= 8.0 us -->|
+--------------------------+--------------------------+
```

---

## 2. Hardware Triggering & Synchronization Architecture

1. **Timer Configuration:**
   - TIM1 (or HRTIM Master) is configured in **Center-Aligned Mode** (Up-Down counting).
   - An internal Trigger Output (`TRGO`) is generated exactly at the timer counter reload point (`CTR = PERIOD` or `CTR = 0`), which aligns with the midpoint of the inductor current waveform where $I_L(t) = I_{L,avg}$.
2. **Synchronous ADC Trigger:**
   - The ADC hardware trigger is mapped directly to `TIM1_TRGO` via internal MCU interconnects (no software or GPIO delay).
   - Hardware sampling starts simultaneously on ADC1 (Inductor Current $I_L$) and ADC2 (Output Voltage $V_{out}$) using dual-ADC simultaneous mode.
3. **Interrupt Service Routine (ISR) Servicing:**
   - Upon ADC End-of-Conversion (EOC), `ADC_IRQHandler` (or `HRTIM_Master_IRQHandler`) is invoked.
   - The interrupt priority is assigned to `NVIC Priority 0` (Highest Priority), guaranteeing zero preemption by any FreeRTOS kernel, communication, or diagnostic interrupt.

---

## 3. Comprehensive Jitter Verification Methodology

To verify the jitter requirement ($\le \pm 50\text{ ns}$) empirically, a 3-part verification methodology is mandatory on the test bench:

```
+===================================================================================================+
|                                    JITTER TESTBENCH TOPOLOGY                                      |
|                                                                                                   |
|  +-------------------------------------+                                                          |
|  | TARGET CONTROL MCU                  |                                                          |
|  |                                     |                                                          |
|  |  [ TIM1 TRGO Output Pin ] --------->|=======> CH1: DSO Reference (Trigger)                     |
|  |  (Center-Point Sync Pulse)          |                                                          |
|  |                                     |                                                          |
|  |  [ Fast Debug GPIO Pin ] ---------->|=======> CH2: DSO ISR Latency Monitor                     |
|  |  (Toggled in ADC ISR Entry/Exit)    |                                                          |
|  |                                     |                                                          |
|  |  [ Cortex-M4 DWT Unit ]             |                                                          |
|  |  (Cycle Counter Logging)            |                                                          |
|  +-------------------------------------+                                                          |
|                                                                                                   |
|  +---------------------------------------------------------------------------------------------+  |
|  | DIGITAL STORAGE OSCILLOSCOPE (DSO) CONFIGURATION                                            |  |
|  |  - Bandwidth: >= 100 MHz (e.g. Rigol DS1054Z/DS2000, Keysight DSOX, or Tektronix)           |  |
|  |  - Sample Rate: >= 1.0 GSa/s (1 sample per 1 ns resolution)                                 |  |
|  |  - Trigger Mode: CH1 Rising Edge, DC Coupled, 50-ohm / 1M-ohm 10x Probe                     |  |
|  |  - Measurement: Delta-T between CH1 Rising Edge and CH2 Rising Edge                         |  |
|  |  - Persistence Mode: Infinite Persistence ON                                                |  |
|  |  - Histogram Mode: Enable horizontal time histogram across Delta-T measurement cursor       |  |
|  |  - Population: >= 100,000 cycles (continuous 2.0 second run)                                |  |
|  |  - Pass Criterion: Peak-to-peak distribution width (Delta-T_max - Delta-T_min) <= 100 ns      |  |
|  +---------------------------------------------------------------------------------------------+  |
+===================================================================================================+
```

### 3.1 Method 1: Hardware Fast GPIO Toggle

A dedicated high-speed GPIO (configured with `GPIO_SPEED_FREQ_VERY_HIGH`) is toggled at the entry and exit of the control interrupt:

```c
void ADC_IRQHandler(void)
{
    /* 1. Fast GPIO Set (Direct Register Write, 1 CPU cycle) */
    DEBUG_PORT->BSRR = DEBUG_PIN_MASK;

    /* 2. Clear ADC Flag */
    ADC1->SR = ~ADC_SR_EOC;

    /* 3. Read conversion results from dual ADC registers */
    uint32_t raw_current = ADC1->DR;
    uint32_t raw_voltage = ADC2->DR;

    /* 4. Execute Discrete PID Algorithm */
    Control_ExecuteLoop(raw_current, raw_voltage);

    /* 5. Fast GPIO Reset (1 CPU cycle) */
    DEBUG_PORT->BSRR = (uint32_t)DEBUG_PIN_MASK << 16U;
}
```

### 3.2 Method 2: DSO Infinite Persistence & Histogram Analysis

* **Setup:**
  1. Connect DSO Probe 1 (CH1) to the timer sync testpoint (`TIM1_TRGO`).
  2. Connect DSO Probe 2 (CH2) to the `DEBUG_PIN`.
  3. Ground leads connected using short low-inductance ground springs.
* **Execution:**
  1. Trigger on CH1 rising edge.
  2. Adjust timebase to $20\text{ ns/div}$ centered on the CH2 rising edge.
  3. Enable **Infinite Persistence** and accumulate waveforms for $\ge 100,000$ triggers.
  4. Enable the **Horizontal Measurement Histogram** over the CH2 edge.
* **Criterion:**
  $$\text{Jitter}_{p-p} = t_{edge, max} - t_{edge, min} \le 100\text{ ns} \quad (\le \pm 50\text{ ns})$$
  Standard deviation ($\sigma$) must be $\le 12.5\text{ ns}$.

### 3.3 Method 3: Cortex-M4 DWT Cycle Counter Telemetry

The ARM Cortex-M4 Data Watchpoint and Trace (DWT) cycle counter (`DWT->CYCCNT`) provides non-intrusive, cycle-accurate in-firmware telemetry:

```c
/* Initialization */
void DWT_Init(void)
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    DWT->CYCCNT = 0U;
}

/* ISR Execution Monitor */
static volatile uint32_t s_isr_entry_cycles = 0;
static volatile uint32_t s_isr_min_cycles   = 0xFFFFFFFFU;
static volatile uint32_t s_isr_max_cycles   = 0;
static volatile uint32_t s_jitter_violations = 0;

void ADC_IRQHandler_Monitored(void)
{
    uint32_t t_entry = DWT->CYCCNT;
    
    // ... Power control logic ...

    uint32_t t_exec = DWT->CYCCNT - t_entry;
    if (t_exec < s_isr_min_cycles) s_isr_min_cycles = t_exec;
    if (t_exec > s_isr_max_cycles) s_isr_max_cycles = t_exec;

    /* Check for jitter / overrun breach */
    if ((s_isr_max_cycles - s_isr_min_cycles) > MAX_ALLOWED_JITTER_CYCLES) {
        s_jitter_violations++;
    }
}
```

Telemetry containing `s_isr_min_cycles`, `s_isr_max_cycles`, and `s_jitter_violations` is packaged into `MSG_TELEMETRY_SLOW` and forwarded to the Gateway MCU for continuous SCADA monitoring.
