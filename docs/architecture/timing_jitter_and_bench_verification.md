# Control Loop Timing, Jitter Budget & Verification Methodology

**Document:** `docs/architecture/timing_jitter_and_bench_verification.md`  
**Related SRS IDs:** `REQ-CTRL-001`, `REQ-CTRL-002`, `REQ-CTRL-003`, `NFR-PERF-01`

---

## 1. Single Source of Truth: Timing Budget & Determinism

This document is the authoritative **Single Source of Truth** for the $50.0\text{ kHz}$ control loop timing budget, execution schedule, WCET analysis, 4 jitter metric definitions, NVIC priority assignments, and bench verification methodologies.

### 1.1 Core Timing Budget & WCET Schedule ($50\text{ kHz}$ Loop)
* **PWM Switching Frequency ($f_{sw}$):** $50.0\text{ kHz}$ ($\pm 0.05\%$ HSE crystal accuracy)
* **Switching Period ($T_s$):** $20.0\,\mu\text{s}$ ($20,000\text{ ns}$)
* **Primary Core Clock Frequency ($f_{cpu}$):** $170.0\text{ MHz}$ (STM32G474RE, $t_{clk} = 5.88\text{ ns}$)

```
+---------------------------------------------------------------------------------------------------+
| STAGE-BY-STAGE EXECUTION TIMELINE (Ts = 20.0 microseconds)                                        |
|                                                                                                   |
|  0.0 us      1.0 us      1.2 us                  4.8 us     5.0 us                      20.0 us   |
|  +-----------+-----------+-----------------------+----------+---------------------------+         |
|  | ADC Conv  | DMA / IRQ | Cascaded PID Loop     | CCR/CMP  | Background Tasks & Slack  |         |
|  | Dual-Mode | Stacking  | Current + Voltage Calc| Reload   | (75% CPU Headroom)        |         |
|  +-----------+-----------+-----------------------+----------+---------------------------+         |
|  |<-------- Worst-Case Execution Time (WCET) = 5.0 us ------>|<---- Slack = 15.0 us ----->|         |
|  |<------------------- Maximum Allowable ISR Budget = 8.0 us (40% Load) ----------------->|         |
+---------------------------------------------------------------------------------------------------+
```

| Execution Stage | Duration | CPU Cycles (@ 170 MHz) | Description |
| :--- | :--- | :--- | :--- |
| **ADC Simultaneous Sampling & Conversion** | $1.00\,\mu\text{s}$ | $170\text{ cycles}$ | Dual ADC1/ADC2 hardware conversion triggered on TRGO |
| **NVIC IRQ Entry & Context Stacking** | $0.20\,\mu\text{s}$ | $34\text{ cycles}$ | Hardware stacking and branch to `ADC_IRQHandler` |
| **Cascaded Discrete PID Execution** | $3.60\,\mu\text{s}$ | $612\text{ cycles}$ | Inner current + outer voltage loop, clamping, anti-windup |
| **HRTIM Compare Shadow Register Reload** | $0.20\,\mu\text{s}$ | $34\text{ cycles}$ | Writing updated compare value to shadow register |
| **TOTAL WORST-CASE EXECUTION TIME (WCET)** | $\mathbf{5.00\,\mu\text{s}}$ | $\mathbf{850\text{ cycles}}$ | **$25.0\%$ CPU Load (Well below $8.0\,\mu\text{s}$ / $40\%$ budget)** |

### 1.2 Asynchronous Background SPI DMA Telemetry Timing
* A full 76-byte telemetry frame transfer over $10\text{ MHz}$ SPI requires:
  $$T_{spi} = \frac{76\text{ bytes} \times 8\text{ bits}}{10\times 10^6\text{ bps}} = 60.8\,\mu\text{s}$$
* **Zero Loop Blocking:** SPI DMA transfers execute autonomously in background silicon memory channels without CPU intervention, operating asynchronously across multiple $20\,\mu\text{s}$ PWM cycles without introducing jitter to the Priority 0 control loop.

---

## 2. Disambiguation of the Four Jitter Metrics

* **Trigger Jitter ($t_{trig\_jitter}$):** $\le \pm 5.0\text{ ns}$ (TRGO to ADC aperture). *Requires DSO measurement.*
* **Interrupt Latency Jitter ($t_{irq\_jitter}$):** $\le \pm 15.0\text{ ns}$ (EOC to ISR entry). *Requires DSO measurement.*
* **Execution Time Jitter ($t_{exec\_jitter}$):** $\le \pm 20.0\text{ ns}$ (ISR compute duration). *Tracked in-firmware via Cortex-M4 DWT.*
* **Sample-to-Duty-Update Jitter ($t_{update\_jitter}$):** $\le \pm 50.0\text{ ns}$ (ADC sample to physical PWM reload). *Requires DSO measurement.*
* **Verification Status:** Specification consistency and invariant simulation model verified; hardware physical measurements pending benchtop prototype execution.
* **Preemption Policy:** No intentional software ISR preemption is permitted during control loop execution.
