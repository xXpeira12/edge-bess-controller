# Control Loop Timing, Jitter Budget & Verification Methodology

**Document:** `docs/architecture/timing_jitter_and_bench_verification.md`  
**Related SRS IDs:** `REQ-CTRL-001`, `REQ-CTRL-002`, `REQ-CTRL-003`, `NFR-PERF-01`

---

## 1. Real-Time Timing Budget & Determinism Overview

In digital power conversion (Synchronous Buck/Boost topology), phase margin and closed-loop stability depend directly on deterministic execution timing. Any temporal jitter in sampling or duty-cycle update introduces phase noise, degradation of stability margins, and potential subharmonic limit-cycle oscillations.

### 1.1 Core Timing Budget ($50\text{ kHz}$ Control Loop)
* **PWM Switching Frequency ($f_{sw}$):** $50.0\text{ kHz}$ ($\pm 0.05\%$ HSE crystal accuracy)
* **Switching Period ($T_s$):** $20.0\,\mu\text{s}$ ($20,000\text{ ns}$)
* **Primary Core Clock Frequency ($f_{cpu}$):** $170.0\text{ MHz}$ (STM32G474) / $168.0\text{ MHz}$ (STM32F446)
* **Clock Period ($t_{clk}$):** $5.88\text{ ns}$ (@ 170 MHz) / $5.95\text{ ns}$ (@ 168 MHz)
* **Maximum Allowable Total Jitter ($\Delta t_{jitter}$):** $\le \pm 50.0\text{ ns}$ ($\Delta T_{p-p} \le 100\text{ ns}$)
* **Maximum Allowable ISR Execution Duration ($t_{isr}$):** $\le 8.0\,\mu\text{s}$ ($40.0\%$ CPU load limit at 170 MHz)

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

## 2. Disambiguation of the Four Jitter Metrics

To prevent ambiguity between sampling hardware, interrupt servicing, computational variability, and hardware PWM reload, four distinct jitter metrics are formally specified:

```
+===================================================================================================+
|                                    FOUR JITTER METRICS BREAKDOWN                                  |
|                                                                                                   |
|  1. Trigger Jitter (t_trig_jitter):                                                               |
|     Time from internal timer TRGO center-point event to physical ADC sample aperture hold.       |
|     Budget: <= +/- 5.0 ns (Hardware silicon interconnect delay).                                  |
|                                                                                                   |
|  2. Interrupt Latency Jitter (t_irq_jitter):                                                      |
|     Time from ADC End-of-Conversion (EOC) flag to the execution of the first instruction in       |
|     ADC_IRQHandler / HRTIM_Master_IRQHandler.                                                     |
|     Budget: <= +/- 15.0 ns (NVIC hardware stacking and pipeline variance).                        |
|                                                                                                   |
|  3. Execution Time Jitter (t_exec_jitter):                                                        |
|     Variation in total execution time from ISR entry to PID discrete math and saturation done.    |
|     Budget: <= +/- 20.0 ns (Branchless single-precision FPU assembly).                            |
|                                                                                                   |
|  4. Sample-to-Duty-Update Timing Jitter (t_update_jitter):                                        |
|     Total end-to-end delay variation from ADC instantaneous sampling to physical PWM comparator   |
|     (HRTIM_CMP1 / TIM1_CCR1) hardware shadow register reload taking effect in the power stage.   |
|     Overall Control Loop Limit: <= +/- 50.0 ns (Peak-to-Peak <= 100.0 ns).                        |
+===================================================================================================+
```

---

## 3. NVIC Priority Hierarchy & Preemption Policy

To guarantee zero interrupt preemption and minimize `t_irq_jitter`:
* **Priority 0 (Highest):** `HRTIM_Master_IRQHandler` / `ADC_IRQHandler` (Inner Current Loop).
* **Priority 1:** `TIM_BRK_IRQHandler` / `COMP_IRQHandler` (Tier-0 Break Diagnostic Logging).
* **Priority 2:** `DMA1_Channel2_3_IRQHandler` (SPI IPC DMA Transfer Complete).
* **Priority 3:** System Tick / Diagnostics (`SysTick_Handler`).

```
+---------------------------------------------------------------------------------------------------+
| PREEMPTION RULE: No ISR or FreeRTOS critical section may disable interrupts at Priority 0.       |
| ADC/HRTIM control loop execution runs unmasked, ensuring zero preemption jitter.                  |
+---------------------------------------------------------------------------------------------------+
```

---

## 4. Comprehensive Jitter Verification Methodology

```
+===================================================================================================+
|                                    JITTER TESTBENCH TOPOLOGY                                      |
|                                                                                                   |
|  +-------------------------------------+                                                          |
|  | TARGET CONTROL MCU (STM32G474)      |                                                          |
|  |                                     |                                                          |
|  |  [ HRTIM/TIM1 TRGO Sync Pulse Pin ] |=======> CH1: DSO Reference Trigger                       |
|  |  (Center-Point Hardware Marker)     |                                                          |
|  |                                     |                                                          |
|  |  [ Fast Debug GPIO Pin ] ----------->|=======> CH2: DSO ISR Latency Monitor                     |
|  |  (Toggled in ADC ISR Entry/Exit)    |                                                          |
|  |                                     |                                                          |
|  |  [ Cortex-M4 DWT Unit ]             |                                                          |
|  |  (In-firmware Cycle Logging)        |                                                          |
|  +-------------------------------------+                                                          |
|                                                                                                   |
|  +---------------------------------------------------------------------------------------------+  |
|  | DIGITAL STORAGE OSCILLOSCOPE (DSO) CONFIGURATION                                            |  |
|  |  - Bandwidth: >= 100 MHz (Sample Rate >= 1.0 GSa/s, 1 ns resolution per point)              |  |
|  |  - Probes: Low-capacitance active probes with ground-spring connection                       |  |
|  |  - Trigger: CH1 Rising Edge (TRGO center point)                                             |  |
|  |  - Measurement: Delta-T between CH1 Rising Edge and CH2 Rising Edge                         |  |
|  |  - Persistence Mode: Infinite Persistence Enabled                                           |  |
|  |  - Histogram Mode: Horizontal time histogram over CH2 rising edge                           |  |
|  |  - Acquisition Population: N >= 100,000 continuous switching cycles (>= 2.0 seconds run)    |  |
|  |  - Acceptance Gate: Delta-T_max - Delta-T_min <= 100.0 ns (Jitter <= +/- 50.0 ns)           |  |
|  +---------------------------------------------------------------------------------------------+  |
+===================================================================================================+
```

### 4.1 Method 1: Hardware Fast GPIO Toggle Protocol
A high-speed push-pull GPIO pin (`DEBUG_ISR_PIN`, speed set to `VERY_HIGH`) toggles via single-cycle BSRR register writes:

```c
void ADC_IRQHandler(void)
{
    /* 1. Fast GPIO Set: Entry timestamp marker (1 CPU cycle = 5.88 ns) */
    DEBUG_PORT->BSRR = DEBUG_PIN_MASK;

    /* 2. Clear conversion complete flag */
    ADC1->ISR = ADC_ISR_EOC;

    /* 3. Read synchronous conversion registers */
    uint32_t raw_current = ADC1->DR;
    uint32_t raw_voltage = ADC2->DR;

    /* 4. Branchless Discrete PID Math */
    Control_ExecuteFastLoop(raw_current, raw_voltage);

    /* 5. Fast GPIO Reset: Exit timestamp marker (1 CPU cycle) */
    DEBUG_PORT->BSRR = (uint32_t)DEBUG_PIN_MASK << 16U;
}
```

### 4.2 Method 2: DSO Infinite Persistence & Statistical Histogram Analysis
* **Protocol Steps:**
  1. Attach CH1 to `TRGO` pulse and CH2 to `DEBUG_PIN`.
  2. Set trigger to CH1 rising edge at $50\%$ threshold.
  3. Configure DSO timebase to $10\text{ ns/div}$ centered on the CH2 rising edge.
  4. Enable **Infinite Persistence** and **Horizontal Measurement Histogram**.
  5. Accumulate $\ge 100,000$ consecutive trigger events.
* **Pass Criteria:**
  $$\Delta t_{jitter\_p-p} = t_{edge\_max} - t_{edge\_min} \le 100.0\text{ ns} \quad (\le \pm 50.0\text{ ns})$$
  $$\sigma_{jitter} \le 12.5\text{ ns} \quad (4\sigma \le 50.0\text{ ns})$$

### 4.3 Method 3: Cortex-M4 DWT Cycle Counter Telemetry
`DWT->CYCCNT` captures cycle-accurate execution duration inside firmware:

```c
void DWT_Init(void)
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    DWT->CYCCNT = 0U;
}

static volatile uint32_t s_isr_min_cycles = 0xFFFFFFFFU;
static volatile uint32_t s_isr_max_cycles = 0U;
static volatile uint32_t s_jitter_violations = 0U;

void ADC_IRQHandler_Monitored(void)
{
    uint32_t t_start = DWT->CYCCNT;
    
    // ... Inner Loop PID Computation ...

    uint32_t t_cycles = DWT->CYCCNT - t_start;
    if (t_cycles < s_isr_min_cycles) s_isr_min_cycles = t_cycles;
    if (t_cycles > s_isr_max_cycles) s_isr_max_cycles = t_cycles;

    /* Max allowed jitter cycles = 100 ns * 170 MHz = 17 cycles */
    if ((s_isr_max_cycles - s_isr_min_cycles) > 17U) {
        s_jitter_violations++;
    }
}
```
Min/max cycle telemetry is transmitted over IPC every $100\text{ ms}$ for real-time SCADA diagnostics.
