# edge-bess-controller

# Software Requirements Specification (SRS)

**Project:** Industrial Smart BESS & Power Management Controller (Desk-Scale PoC)

**Architecture:** Dual-MCU (Control Core + Gateway Core)

**Standard Compliance:** IEC 60730 Class B (Functional Safety), ISO 21434 (Cybersecurity Concept)

---

### 1. System Overview & Scope

This specification defines the functional, safety, and communication requirements for a desktop-scale prototype of an **Industrial Battery Energy Storage System (BESS) Controller**. The system employs a **Dual-MCU Architecture** separating hard real-time power control and functional safety from high-level communication and industrial telemetry.

```
+-----------------------------------------------------------------------------------+
|                                 DESK-SCALE BESS                                   |
|                                                                                   |
|  +------------------------+      IPC (SPI/UART)     +--------------------------+  |
|  |   Control Core (STM32) | <=====================> |    Gateway Core (ESP32)  |  |
|  |  (Cortex-M4 @ 168MHz)  |                         |   (Dual Xtensa @ 240MHz) |  |
|  +------------------------+                         +--------------------------+  |
|      |               |                                  |               |         |
|   PWM/ADC       IEC 60730                            CAN Bus       Modbus-TCP/IP  |
|      |          Diagnostics                             |               |         |
|      v                                                  v               v         |
| [12V/24V Power Stage]                                [BMS Node]    [SCADA / HMI]  |
+-----------------------------------------------------------------------------------+

```

---

### 2. Hardware Interface & Operational Boundaries

| Parameter | Operational Specification (Desk Scale) |
| --- | --- |
| **Input DC Bus Voltage ($V_{bus}$)** | 18.0 V – 24.0 V DC (Current-limited DC Power Supply) |
| **Battery Terminal Voltage ($V_{bat}$)** | 10.5 V – 14.6 V DC (12V LiFePO4 / 3S Li-ion or Active Dummy Load) |
| **Rated Output Power** | 20 W – 50 W Continuous |
| **Control MCU** | STM32G474RE / STM32F446RE (ARM Cortex-M4 with FPU) |
| **Gateway MCU** | ESP32-WROOM-32 (Dual-Core 240MHz, FreeRTOS) |
| **Inter-Processor Comm (IPC)** | Full-duplex SPI with DMA (Slave: STM32, Master: ESP32) + Hardware Alert Line |
| **Fieldbus Interfaces** | Isolated CAN 2.0B (500 kbps), RS-485 / Modbus-RTU, Ethernet / Wi-Fi (Modbus-TCP) |

---

### 3. Functional Requirements

#### Module 1: Real-Time Power & Closed-Loop Control (`REQ-CTRL`)

* **`REQ-CTRL-001` (PWM Generation):** The Control MCU shall generate complementary PWM signals with a configurable dead-time ($t_{dead} \ge 250\text{ ns}$) using an Advanced Control Timer at a switching frequency of $f_{sw} = 50\text{ kHz}$.
* **`REQ-CTRL-002` (Synchronous ADC Sampling):** ADC conversions for inductor current ($I_L$) and output voltage ($V_{out}$) shall be hardware-triggered at the PWM center-point to eliminate switching noise.
* **`REQ-CTRL-003` (Cascaded Dual-Loop PID):** The firmware shall execute a digital discrete PID algorithm consisting of:
* **Inner Loop (Current Control):** Executes at $50\text{ kHz}$ ($T_s = 20\,\mu\text{s}$) with anti-windup clamping.
* **Outer Loop (Voltage Control):** Executes at $5\text{ kHz}$ ($T_s = 200\,\mu\text{s}$) outputting the current setpoint $I_{ref}$.


* **`REQ-CTRL-004` (Operating Modes):** The system shall support transition between three operational states: **Charge (Buck)**, **Discharge (Boost)**, and **Idle/High-Z**.

---

#### Module 2: Functional Safety Diagnostics — IEC 60730 Class B (`REQ-SAFE`)

* **`REQ-SAFE-001` (CPU Register Test):** At startup (Pre-execution), the Control MCU shall perform destructive read/write pattern tests (`0x55555555`, `0xAAAAAAAA`) across all core registers (R0–R12, LR, PC, PSR) to detect stuck-at faults.
* **`REQ-SAFE-002` (RAM March C- Test):** A periodic, non-destructive March C- algorithm shall scan operational SRAM blocks during runtime within an execution window $\le 100\text{ ms}$.
* **`REQ-SAFE-003` (Flash Integrity Check):** The system shall verify the active firmware integrity via hardware CRC-32 against a pre-compiled golden CRC signature stored in Flash metadata.
* **`REQ-SAFE-004` (Independent Watchdog & Clock Monitor):**
* The internal Independent Watchdog (IWDG) must be refreshed within a fixed window ($50\text{ ms} \pm 10\text{ ms}$).
* Clock Security System (CSS) shall be enabled to trigger a hardware interrupt and immediately switch to internal HSI if the main crystal (HSE) fails.


* **`REQ-SAFE-005` (Hardware Safe-State Transition):** Upon detection of over-current ($I > 5.0\text{ A}$), over-voltage ($V > 26.0\text{ V}$), or any safety diagnostic failure, the hardware Timer Break input shall force all PWM outputs to `LOW` within $\le 2.0\,\mu\text{s}$.

---

#### Module 3: Gateway, Networking & SCADA (`REQ-COMM`)

* **`REQ-COMM-001` (Inter-Processor Communication):** The IPC protocol between STM32 and ESP32 shall use a structured frame with a 2-byte header, payload length, payload, and a 16-bit CRC (CRC-CCITT). Corrupted frames shall trigger an automatic retransmission request (ARQ).
* **`REQ-COMM-002` (BMS CAN Telemetry):** The Gateway MCU shall poll/receive battery pack metrics over CAN 2.0B (Standard/Extended IDs at $500\text{ kbps}$) every $100\text{ ms}$, including Cell Voltages, Pack SOC, and Temperature.
* **`REQ-COMM-003` (Modbus-TCP/RTU Server):** The Gateway MCU shall implement standard Modbus holding registers for telemetry and control:

| Register Address | Name | Data Type | Access | Description |
| --- | --- | --- | --- | --- |
| **`40001`** | `SYS_CONTROL_STATE` | `uint16_t` | R/W | `0` = Stop, `1` = Charge, `2` = Discharge |
| **`40002`** | `BUS_VOLTAGE_RAW` | `uint16_t` | R | Scaled DC Bus Voltage ($10\text{ mV}/\text{LSB}$) |
| **`40003`** | `BAT_CURRENT_RAW` | `int16_t` | R | Battery Current ($10\text{ mA}/\text{LSB}$, +/-) |
| **`40004`** | `BAT_SOC` | `uint16_t` | R | State of Charge ($0.1\%/\text{LSB}$) |
| **`40005`** | `FAULT_STATUS_FLAGS` | `uint16_t` | R | IEC 60730 & Over-limit Error Bitmap |

* **`REQ-COMM-004` (FreeRTOS Task Separation):** The Gateway shall run dedicated FreeRTOS tasks with priority queuing:
* Task 1 (`Priority: High`): IPC Handler (SPI/DMA)
* Task 2 (`Priority: Medium`): CAN Bus Ingestion
* Task 3 (`Priority: Normal`): Modbus Server / TCP Sockets
* Task 4 (`Priority: Low`): MQTT Telemetry Publisher (1 Hz)



---

#### Module 4: Secure Bootloader & Image Management — ISO 21434 (`REQ-SEC`)

* **`REQ-SEC-001` (Dual-Bank Memory Partitioning):** The Control MCU Flash memory shall be mapped to support In-Application Programming (IAP) with rollback capability:
* **Sector 0 (32 KB):** Primary Secure Bootloader (Immutable)
* **Sector 1–3 (128 KB):** Application Slot A (Active Image)
* **Sector 4–6 (128 KB):** Application Slot B (Staging Image)
* **Sector 7 (32 KB):** NVRAM Config & Cryptographic Public Keys


* **`REQ-SEC-002` (Cryptographic Verification):** The Bootloader shall verify the firmware payload using SHA-256 hashing and ECDSA (secp256r1) digital signature before boot execution.
* **`REQ-SEC-003` (Anti-Rollback & Secure Downgrade Prevention):** The Bootloader shall reject images containing a Security Version Counter lower than the currently installed monotonic version.

---

### 4. Non-Functional & Quality Requirements

* **`NFR-PERF-01` (Deterministic Latency):** Control loop interrupt jitter on the STM32 shall not exceed $\pm 50\text{ ns}$.
* **`NFR-CODE-01` (Coding Standards):** Core firmware drivers and safety modules shall comply with MISRA-C:2012 Mandatory and Required guidelines.
* **`NFR-TEST-01` (Automated Verification):** All algorithmic modules (PID, CRC, Frame Parsers) shall have $>90\%$ code coverage via unit test suites (Unity/CMock) executed on a CI/CD pipeline.
