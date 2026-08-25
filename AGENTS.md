# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

## System Architecture & SRS
- The primary system specification is in `README.md` (Primary Target: STM32G474RE, Secondary: STM32F446RE).
- Deep-dive architectural topics are modularized under `docs/architecture/`:
  - `timing_jitter_and_bench_verification.md`: 50 kHz control loop timing budget, 4 jitter metrics disambiguation, <= +/-50ns jitter verification via DSO and DWT.
  - `hardware_sensing_and_analog_frontend.md`: Voltage dividers, INA240 current sense amp (Gain 40, 0.4V/A, +/-3.5A nominal, +/-4.0A warning, +/-5.0A trip), dual-path feedback/trip split.
  - `fault_handling_and_safety.md`: Multi-tier fault handling (Warning, Fault with 100A/s ramp-down, Critical Tier-0 Break Trip <= 2.0us), IEC 60730 Class B-oriented self-tests, ISO 21434 concepts.
  - `state_machine.md`: Control MCU FSM from `POWER_ON` through `RECOVERY_CHECK` and `SAFE_STATE`.
  - `ipc_protocol.md`: Master-Slave SPI (ESP32 Master, STM32 Slave with `ALERT_OUT` line), FreeRTOS task isolation, SPI DMA frame format (sync 0xA55A, CRC16-CCITT, ARQ state machine).
  - `modbus_register_map.md`: SCADA registers 40001-40018 (including dedicated `FAULT_CLEAR_CMD` 40014), strict restriction against raw PWM duty cycle writes.
  - `flash_memory_partitioning.md`: Symmetric 200KB Dual-Bank STM32G474 vs Asymmetric STM32F446 Flash layout, confirmed boot rollback.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
