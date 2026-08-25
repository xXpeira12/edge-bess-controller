# Control Loop Timing, Jitter Budget & Verification Methodology

**Document:** `docs/architecture/timing_jitter_and_bench_verification.md`  
**Related SRS IDs:** `REQ-CTRL-001`, `REQ-CTRL-002`, `REQ-CTRL-003`, `NFR-PERF-01`

---

## 1. Single Source of Truth: Timing Budget & Determinism

This document is the authoritative **Single Source of Truth** for the $50.0\text{ kHz}$ control loop timing budget, the 4 jitter metric definitions, NVIC priority assignments, and bench verification methodologies.

### 1.1 Core Timing Budget ($50\text{ kHz}$ Control Loop)
* **PWM Switching Frequency ($f_{sw}$):** $50.0\text{ kHz}$ ($\pm 0.05\%$ HSE crystal accuracy)
* **Switching Period ($T_s$):** $20.0\,\mu\text{s}$ ($20,000\text{ ns}$)
* **Primary Core Clock Frequency ($f_{cpu}$):** $170.0\text{ MHz}$ (STM32G474RE)
* **Clock Period ($t_{clk}$):** $5.88\text{ ns}$ (@ 170 MHz)
* **Maximum Allowable Total Jitter ($\Delta t_{jitter}$):** $\le \pm 50.0\text{ ns}$ ($\Delta T_{p-p} \le 100\text{ ns}$)
* **Maximum Allowable ISR Execution Duration ($t_{isr}$):** $\le 8.0\,\mu\text{s}$ ($40.0\%$ CPU load limit at 170 MHz)

---

## 2. Disambiguation of the Four Jitter Metrics

```
+===================================================================================================+
|                                    FOUR JITTER METRICS BREAKDOWN                                  |
|                                                                                                   |
|  1. Trigger Jitter (t_trig_jitter):                                                               |
|     Time from internal timer TRGO center-point event to physical ADC sample aperture hold.       |
|     Budget: <= +/- 5.0 ns (Hardware silicon interconnect delay). Requires DSO measurement.        |
|                                                                                                   |
|  2. Interrupt Latency Jitter (t_irq_jitter):                                                      |
|     Time from ADC End-of-Conversion (EOC) pulse to first instruction in ADC_IRQHandler.          |
|     Budget: <= +/- 15.0 ns (NVIC hardware stacking variance). Requires DSO measurement.          |
|                                                                                                   |
|  3. Execution Time Jitter (t_exec_jitter):                                                        |
|     Variation in software execution time from ISR entry to PID discrete math and saturation done. |
|     Budget: <= +/- 20.0 ns. Measurable in firmware via Cortex-M4 DWT cycle counter.               |
|                                                                                                   |
|  4. Sample-to-Duty-Update Timing Jitter (t_update_jitter):                                        |
|     Total end-to-end delay variation from ADC instantaneous sampling to physical PWM comparator   |
|     (HRTIM_CMP1 / TIM1_CCR1) hardware shadow register reload taking effect in the power stage.   |
|     Overall Control Loop Limit: <= +/- 50.0 ns (Peak-to-Peak <= 100.0 ns). Requires DSO.          |
+===================================================================================================+
```

---

## 3. NVIC Priority Hierarchy & Preemption Policy

* **Priority 0 (Highest):** `HRTIM_Master_IRQHandler` / `ADC_IRQHandler` (Inner Current Loop).
* **Priority 1:** `HRTIM_FLT_IRQHandler` / `COMP_IRQHandler` (Tier-0 Break Diagnostic Logging).
* **Priority 2:** `DMA1_Channel2_3_IRQHandler` (SPI IPC DMA Transfer Complete).
* **Priority 3:** System Tick / Diagnostics (`SysTick_Handler`).

```
+---------------------------------------------------------------------------------------------------+
| PREEMPTION POLICY: No intentional software ISR preemption is permitted during the control loop.   |
| Inner loop execution runs at Priority 0, unmasked by any FreeRTOS critical sections.             |
+---------------------------------------------------------------------------------------------------+
```

---

## 4. Verification Protocols: Bench DSO vs In-Firmware DWT

```
+===================================================================================================+
|                                    VERIFICATION TOOL RESPONSIBILITIES                             |
|                                                                                                   |
|  CORTEX-M4 DWT CYCLE COUNTER (In-Firmware Telemetry):                                             |
|  - Measures ONLY internal software execution cycles (t_exec).                                     |
|  - Tracks min/max/average PID compute duration at 5.88 ns resolution (170 MHz).                   |
|  - Reports execution jitter over telemetry every 100 ms.                                          |
|                                                                                                   |
|  DIGITAL STORAGE OSCILLOSCOPE (DSO >= 100 MHz, >= 1 GSa/s, Benchtop Physical Verification):       |
|  - Measures physical trigger jitter (CH1: TRGO, CH2: ADC sample testpoint).                       |
|  - Measures physical interrupt latency jitter (CH1: TRGO, CH2: Fast GPIO ISR marker).            |
|  - Measures physical sample-to-duty update jitter (CH1: TRGO, CH2: PWM switching edge).          |
|  - Infinite persistence + horizontal histogram over N >= 100,000 cycles (>= 2.0 s runtime).       |
+===================================================================================================+
```
