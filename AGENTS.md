# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

## System Architecture & SRS
- The primary system specification is in `README.md`.
- Deep-dive architectural topics are modularized under `docs/architecture/`:
  - `timing_jitter_and_bench_verification.md`: 50 kHz control loop timing budget, <= +/-50ns jitter verification via DSO and DWT.
  - `hardware_sensing_and_analog_frontend.md`: Voltage dividers, INA240 current sense amp, dual-path feedback/trip split.
  - `fault_handling_and_safety.md`: Multi-tier fault handling (Warning, Fault, Critical Tier-0 Break Trip), IEC 60730 Class B-oriented self-tests, ISO 21434 concepts.
  - `state_machine.md`: Control MCU FSM from `POWER_ON` through `SAFE_STATE`.
  - `ipc_protocol.md`: FreeRTOS task isolation, SPI DMA frame format (sync 0xA55A, CRC16-CCITT, ARQ state machine).
  - `modbus_register_map.md`: SCADA registers 40001-40013, strict restriction against raw PWM duty cycle writes.
  - `flash_memory_partitioning.md`: Dual-Bank STM32G474 vs Asymmetric STM32F446 Flash layout (`TODO [Hardware Selection Pending]`).

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
