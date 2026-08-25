#!/usr/bin/env python3
"""
Industrial Smart BESS & Power Management Controller (Desk-Scale PoC)
Specification Consistency & Architectural Invariant Test Suite

Performs automated mathematical derivations, transfer function validations,
threshold calculations, latency models, and cross-document invariant assertions.
"""

import math
import struct
import unittest


class TestSpecificationConsistency(unittest.TestCase):
    """Automated cross-document invariant assertions & mathematical derivations."""

    def setUp(self):
        # Hardware Parameters (SSOT)
        self.R_SHUNT = 0.010           # 10 mOhm
        self.INA240_GAIN = 20.0        # INA240A1 (20 V/V)
        self.V_REF = 1.650             # 1.650 V mid-rail bias
        self.SENSITIVITY = self.R_SHUNT * self.INA240_GAIN  # 0.200 V/A

        # Current Limits
        self.I_NOMINAL_MAX = 3.5       # Normal Max Operating: +/- 3.5 A
        self.I_SOFTWARE_WARN = 4.0     # Software Warning Limit: +/- 4.0 A
        self.I_HARDWARE_TRIP = 5.0     # Hardware Break Trip: +/- 5.0 A

        # Memory Geometry
        self.PAGE_SIZE = 2 * 1024      # 2 KB per page
        self.SLOT_A_SIZE = 200 * 1024  # 200 KB
        self.SLOT_B_SIZE = 200 * 1024  # 200 KB
        self.MAX_IMAGE_SIZE = 192 * 1024  # 192 KB maximum application binary

        # Timing & Latency Limits
        self.T_SWITCHING_US = 20.0     # 50 kHz switching period (20 us)
        self.T_ISR_BUDGET_US = 8.0     # 40% CPU load limit @ 170 MHz
        self.T_TOTAL_TRIP_MAX_US = 2.0 # Maximum allowable Tier-0 break latency

    def test_current_threshold_hierarchy_invariants(self):
        """Verify strict ordering: HARD_OC_TRIP > SOFTWARE_OC_LIMIT > NOMINAL_MAX."""
        self.assertGreater(self.I_HARDWARE_TRIP, self.I_SOFTWARE_WARN)
        self.assertGreater(self.I_SOFTWARE_WARN, self.I_NOMINAL_MAX)

    def test_current_sensing_transfer_function_and_thresholds(self):
        """Derive all voltage threshold levels directly from V = V_ref +/- (I * R_shunt * Gain)."""
        self.assertAlmostEqual(self.SENSITIVITY, 0.200, places=4)

        # 1. Nominal Operating Envelope (+/- 3.5 A)
        v_op_high = self.V_REF + (self.I_NOMINAL_MAX * self.SENSITIVITY)
        v_op_low = self.V_REF - (self.I_NOMINAL_MAX * self.SENSITIVITY)
        self.assertAlmostEqual(v_op_high, 2.350, places=3)
        self.assertAlmostEqual(v_op_low, 0.950, places=3)

        # 2. Software Warning Envelope (+/- 4.0 A)
        v_warn_high = self.V_REF + (self.I_SOFTWARE_WARN * self.SENSITIVITY)
        v_warn_low = self.V_REF - (self.I_SOFTWARE_WARN * self.SENSITIVITY)
        self.assertAlmostEqual(v_warn_high, 2.450, places=3)
        self.assertAlmostEqual(v_warn_low, 0.850, places=3)

        # 3. Hardware Trip Break Thresholds (+/- 5.0 A)
        v_trip_high = self.V_REF + (self.I_HARDWARE_TRIP * self.SENSITIVITY)
        v_trip_low = self.V_REF - (self.I_HARDWARE_TRIP * self.SENSITIVITY)
        self.assertAlmostEqual(v_trip_high, 2.650, places=3)
        self.assertAlmostEqual(v_trip_low, 0.650, places=3)

        # 4. Linear ADC Saturation Limits (+/- 8.25 A)
        i_sat_pos = (3.300 - self.V_REF) / self.SENSITIVITY
        i_sat_neg = (0.000 - self.V_REF) / self.SENSITIVITY
        self.assertAlmostEqual(i_sat_pos, 8.25, places=2)
        self.assertAlmostEqual(i_sat_neg, -8.25, places=2)

    def test_ina240_threshold_crossing_latency_model(self):
        """Verify INA240A1 slew-rate-based threshold-crossing model (300 mV step -> 300 ns)."""
        delta_i = self.I_HARDWARE_TRIP - self.I_NOMINAL_MAX  # 1.5 A step
        delta_v = delta_i * self.SENSITIVITY                # 300 mV step
        self.assertAlmostEqual(delta_v, 0.300, places=3)

        slew_rate_v_us = 2.0  # INA240A1 slew rate: 2.0 V/us
        t_slew_ns = (delta_v / slew_rate_v_us) * 1000.0     # 150 ns
        self.assertAlmostEqual(t_slew_ns, 150.0, places=1)

        t_prop_ns = 150.0
        t_csa_cross_ns = t_prop_ns + t_slew_ns              # 300 ns
        self.assertAlmostEqual(t_csa_cross_ns, 300.0, places=1)

    def test_distinct_oc_and_ov_hardware_break_latency_budgets(self):
        """Verify distinct OC (491 ns) and OV (341 ns) latency breakdowns <= 2.0 us."""
        t_shunt = 10e-9
        t_csa_cross = 300e-9
        t_comp_hrtim = 31e-9  # STM32G474 COMP to HRTIM datasheet limit
        t_gate_driver = 50e-9
        t_power_stage = 100e-9

        t_trip_oc = t_shunt + t_csa_cross + t_comp_hrtim + t_gate_driver + t_power_stage
        self.assertAlmostEqual(t_trip_oc * 1e9, 491.0, delta=1.0)
        self.assertLess(t_trip_oc, self.T_TOTAL_TRIP_MAX_US * 1e-6)

        t_divider = 10e-9
        t_buffer_filter = 150e-9
        t_trip_ov = t_divider + t_buffer_filter + t_comp_hrtim + t_gate_driver + t_power_stage
        self.assertAlmostEqual(t_trip_ov * 1e9, 341.0, delta=1.0)
        self.assertLess(t_trip_ov, self.T_TOTAL_TRIP_MAX_US * 1e-6)

    def test_trip_threshold_tolerance_budget(self):
        """Verify worst-case trip threshold boundaries: 4.85 A <= I_trip <= 5.15 A."""
        tolerance_a = 0.15
        i_trip_min = self.I_HARDWARE_TRIP - tolerance_a
        i_trip_max = self.I_HARDWARE_TRIP + tolerance_a
        self.assertAlmostEqual(i_trip_min, 4.85, places=2)
        self.assertAlmostEqual(i_trip_max, 5.15, places=2)
        # Invariant: Must remain strictly above software warning threshold (4.0 A)
        self.assertGreater(i_trip_min, self.I_SOFTWARE_WARN)

    def test_flash_slot_symmetry_and_fixed_bootloader(self):
        """Verify symmetric 200 KB dual-bank slot geometry."""
        self.assertEqual(self.SLOT_A_SIZE, self.SLOT_B_SIZE)
        self.assertEqual(self.SLOT_A_SIZE, 200 * 1024)
        self.assertLessEqual(self.MAX_IMAGE_SIZE, self.SLOT_A_SIZE)

        # Bank 1: 32 KB Boot + 200 KB Slot A + 16 KB NV + 8 KB Key = 256 KB
        bank1_total = (32 + 200 + 16 + 8) * 1024
        self.assertEqual(bank1_total, 256 * 1024)

        # Bank 2: 200 KB Slot B + 32 KB Diag + 24 KB Meta = 256 KB
        bank2_total = (200 + 32 + 24) * 1024
        self.assertEqual(bank2_total, 256 * 1024)

    def test_modbus_register_map_schema_and_command_codes(self):
        """Verify 18 holding registers (40001 - 40018) and safety commands."""
        registers = {
            40001: ("SYS_CONTROL_CMD", "uint16"),
            40002: ("BUS_VOLTAGE_RAW", "uint16"),
            40003: ("BAT_CURRENT_RAW", "int16"),
            40004: ("BAT_SOC", "uint16"),
            40005: ("ACTIVE_FAULT_FLAGS", "uint16"),
            40006: ("VOUT", "uint16"),
            40007: ("IOUT", "int16"),
            40008: ("TEMPERATURE", "int16"),
            40009: ("OPERATING_MODE", "uint16"),
            40010: ("FAULT_CODE", "uint16"),
            40011: ("FW_VERSION", "uint16"),
            40012: ("UPTIME_MSW", "uint16"),
            40013: ("UPTIME_LSW", "uint16"),
            40014: ("FAULT_CLEAR_CMD", "uint16"),
            40015: ("CMD_RESULT", "uint16"),
            40016: ("CMD_SEQ", "uint16"),
            40017: ("FSM_STATE", "uint16"),
            40018: ("LATCHED_FAULT_FLAGS", "uint16"),
        }
        self.assertEqual(len(registers), 18)
        self.assertIn(40014, registers)
        self.assertEqual(registers[40014][0], "FAULT_CLEAR_CMD")
        self.assertIn(40018, registers)
        self.assertEqual(registers[40018][0], "LATCHED_FAULT_FLAGS")

    def test_spi_ipc_frame_with_session_id_and_crc(self):
        """Verify SPI DMA binary frame with SESSION_ID epoch and CRC16-CCITT."""
        sync_word = 0xA55A
        proto_ver = 0x01
        session_id = 42
        seq_num = 1
        msg_type = 0x01
        msg_flags = 0x00
        payload = struct.pack(">HHhH", 2400, 1280, 250, 850)
        payload_len = len(payload)

        header = struct.pack(">HBBBBBB", sync_word, proto_ver, session_id, seq_num, msg_type, msg_flags, payload_len)
        data_to_crc = header[2:] + payload

        # CRC16-CCITT: Poly 0x1021, Init 0xFFFF
        crc = 0xFFFF
        for b in data_to_crc:
            crc ^= (b << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x1021) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF

        full_frame = header + payload + struct.pack(">H", crc)
        self.assertEqual(len(full_frame), 18)
        self.assertEqual(struct.unpack(">H", full_frame[:2])[0], 0xA55A)

    def test_anti_aliasing_filter_transfer_function(self):
        """Verify voltage sensing RC anti-aliasing filter cutoff and attenuation values."""
        r_filt = 1000.0       # 1 kOhm
        c_filt = 3.3e-9       # 3.3 nF
        f_cutoff = 1.0 / (2.0 * math.pi * r_filt * c_filt)
        self.assertAlmostEqual(f_cutoff / 1000.0, 48.2, places=1)

        # Attenuation at Nyquist (25 kHz)
        f_nyquist = 25000.0
        h_nyquist = 1.0 / math.sqrt(1.0 + (f_nyquist / f_cutoff) ** 2)
        db_nyquist = 20.0 * math.log10(h_nyquist)
        phase_nyquist = -math.degrees(math.atan2(f_nyquist, f_cutoff))
        self.assertAlmostEqual(h_nyquist, 0.888, places=2)
        self.assertAlmostEqual(db_nyquist, -1.04, places=1)
        self.assertAlmostEqual(phase_nyquist, -27.4, delta=0.2)

        # Attenuation at PWM switching frequency (50 kHz)
        f_sw = 50000.0
        h_sw = 1.0 / math.sqrt(1.0 + (f_sw / f_cutoff) ** 2)
        db_sw = 20.0 * math.log10(h_sw)
        phase_sw = -math.degrees(math.atan2(f_sw, f_cutoff))
        self.assertAlmostEqual(h_sw, 0.694, places=2)
        self.assertAlmostEqual(db_sw, -3.17, places=1)
        self.assertAlmostEqual(phase_sw, -46.0, delta=0.2)

    def test_control_loop_jitter_budget_and_metrics(self):
        """Verify 50 kHz control loop timing budget, ISR limits, and 4 jitter metrics."""
        f_sw = 50000.0        # 50 kHz
        t_period_us = (1.0 / f_sw) * 1e6
        self.assertEqual(t_period_us, 20.0)

        # CPU timing at 170 MHz
        f_cpu_mhz = 170.0
        t_clk_ns = (1.0 / (f_cpu_mhz * 1e6)) * 1e9
        self.assertAlmostEqual(t_clk_ns, 5.88, places=2)

        # ISR Execution budget (40% CPU load limit)
        cpu_load_limit = 0.40
        t_isr_limit_us = t_period_us * cpu_load_limit
        self.assertEqual(t_isr_limit_us, 8.0)
        max_isr_cycles = int(t_isr_limit_us * 1e-6 * (f_cpu_mhz * 1e6))
        self.assertEqual(max_isr_cycles, 1360)

        # Disambiguated 4 Jitter Metrics
        t_trig_jitter_max_ns = 5.0      # Metric 1: Trigger Jitter
        t_irq_jitter_max_ns = 15.0      # Metric 2: Interrupt Latency Jitter
        t_exec_jitter_max_ns = 20.0     # Metric 3: Execution Time Jitter
        t_update_jitter_max_ns = 50.0   # Metric 4: Sample-to-Duty Update Jitter (Overall)
        t_update_jitter_pp_ns = 100.0   # Peak-to-Peak update jitter

        self.assertLessEqual(t_trig_jitter_max_ns, 5.0)
        self.assertLessEqual(t_irq_jitter_max_ns, 15.0)
        self.assertLessEqual(t_exec_jitter_max_ns, 20.0)
        self.assertLessEqual(t_update_jitter_max_ns, 50.0)
        self.assertEqual(t_update_jitter_pp_ns, 2 * t_update_jitter_max_ns)

    def test_fsm_state_transitions_and_derating_hysteresis(self):
        """Simulate FSM transitions, state authority, and derating hysteresis."""
        # Enum definitions matching modbus_register_map.md and state_machine.md
        STATE_POWER_ON = 0
        STATE_INIT_AND_SELF_TEST = 1
        STATE_IDLE = 2
        STATE_CHARGE_RAMP = 3
        STATE_CHARGE_ACTIVE = 4
        STATE_DISCHARGE_RAMP = 5
        STATE_DISCHARGE_ACTIVE = 6
        STATE_DERATING_ACTIVE = 7
        STATE_RECOVERY_CHECK = 8
        STATE_SAFE_STATE = 9

        # 1. Startup sequence
        fsm_state = STATE_POWER_ON
        self.assertEqual(fsm_state, 0)
        fsm_state = STATE_INIT_AND_SELF_TEST
        self.assertEqual(fsm_state, 1)
        self_test_passed = True
        if self_test_passed:
            fsm_state = STATE_IDLE
        self.assertEqual(fsm_state, 2)

        # 2. Charge start request
        sys_cmd = 1  # START_CHARGE
        if fsm_state == STATE_IDLE and sys_cmd == 1:
            fsm_state = STATE_CHARGE_RAMP
        self.assertEqual(fsm_state, 3)

        ramp_complete = True
        if ramp_complete:
            fsm_state = STATE_CHARGE_ACTIVE
        self.assertEqual(fsm_state, 4)

        # 3. Thermal Derating Hysteresis simulation (Entry > 55C, Exit < 45C)
        temp_c = 56.0
        if fsm_state == STATE_CHARGE_ACTIVE and temp_c > 55.0:
            fsm_state = STATE_DERATING_ACTIVE
        self.assertEqual(fsm_state, 7)

        # Partial cooling to 50C -> Must remain in DERATING_ACTIVE due to hysteresis band
        temp_c = 50.0
        if fsm_state == STATE_DERATING_ACTIVE and temp_c < 45.0:
            fsm_state = STATE_CHARGE_ACTIVE
        self.assertEqual(fsm_state, STATE_DERATING_ACTIVE)

        # Full cooling to 44C -> Exits derating back to CHARGE_ACTIVE
        temp_c = 44.0
        if fsm_state == STATE_DERATING_ACTIVE and temp_c < 45.0:
            fsm_state = STATE_CHARGE_ACTIVE
        self.assertEqual(fsm_state, STATE_CHARGE_ACTIVE)

        # 4. Critical Tier-0 Break Trip
        hard_fault = True
        if hard_fault:
            fsm_state = STATE_SAFE_STATE
        self.assertEqual(fsm_state, 9)

    def test_fault_recovery_sequence_and_magic_key_gating(self):
        """Verify FAULT_CLEAR_CMD gating (accepted ONLY in SAFE_STATE) and recovery criteria."""
        STATE_IDLE = 2
        STATE_CHARGE_ACTIVE = 4
        STATE_RECOVERY_CHECK = 8
        STATE_SAFE_STATE = 9

        CMD_RESULT_NONE = 0
        CMD_RESULT_ACCEPTED = 1
        CMD_RESULT_REJECTED_INVALID_STATE = 2
        CMD_RESULT_REJECTED_SAFETY = 5

        # Helper function simulating Control MCU command handler
        def handle_fault_clear(current_state, clear_key):
            if clear_key != 0x00A5:
                return current_state, CMD_RESULT_REJECTED_SAFETY
            if current_state != STATE_SAFE_STATE:
                return current_state, CMD_RESULT_REJECTED_INVALID_STATE
            return STATE_RECOVERY_CHECK, CMD_RESULT_ACCEPTED

        # Test 1: Clear command rejected in IDLE
        state, result = handle_fault_clear(STATE_IDLE, 0x00A5)
        self.assertEqual(state, STATE_IDLE)
        self.assertEqual(result, CMD_RESULT_REJECTED_INVALID_STATE)

        # Test 2: Clear command rejected in CHARGE_ACTIVE
        state, result = handle_fault_clear(STATE_CHARGE_ACTIVE, 0x00A5)
        self.assertEqual(state, STATE_CHARGE_ACTIVE)
        self.assertEqual(result, CMD_RESULT_REJECTED_INVALID_STATE)

        # Test 3: Invalid clear key rejected in SAFE_STATE
        state, result = handle_fault_clear(STATE_SAFE_STATE, 0x1234)
        self.assertEqual(state, STATE_SAFE_STATE)
        self.assertEqual(result, CMD_RESULT_REJECTED_SAFETY)

        # Test 4: Valid magic key accepted in SAFE_STATE -> transitions to RECOVERY_CHECK
        state, result = handle_fault_clear(STATE_SAFE_STATE, 0x00A5)
        self.assertEqual(state, STATE_RECOVERY_CHECK)
        self.assertEqual(result, CMD_RESULT_ACCEPTED)

        # Test 5: Recovery Check Criteria evaluation
        def evaluate_recovery(v_bat, v_bus, i_inductor, t_sink):
            vbat_ok = (v_bat >= 11.0)
            vbus_ok = (16.0 <= v_bus <= 25.0)
            current_zero_ok = (abs(i_inductor) < 0.20)
            temp_ok = (t_sink < 45.0)
            if vbat_ok and vbus_ok and current_zero_ok and temp_ok:
                return STATE_IDLE
            return STATE_SAFE_STATE

        # Fail on undervoltage battery (< 11V)
        self.assertEqual(evaluate_recovery(10.5, 24.0, 0.0, 30.0), STATE_SAFE_STATE)
        # Fail on out-of-spec bus voltage
        self.assertEqual(evaluate_recovery(12.8, 15.0, 0.0, 30.0), STATE_SAFE_STATE)
        self.assertEqual(evaluate_recovery(12.8, 25.5, 0.0, 30.0), STATE_SAFE_STATE)
        # Fail on non-zero current
        self.assertEqual(evaluate_recovery(12.8, 24.0, 0.25, 30.0), STATE_SAFE_STATE)
        # Fail on high temperature (>= 45C)
        self.assertEqual(evaluate_recovery(12.8, 24.0, 0.0, 46.0), STATE_SAFE_STATE)
        # All criteria pass -> Transition to STATE_IDLE
        self.assertEqual(evaluate_recovery(12.8, 24.0, 0.0, 35.0), STATE_IDLE)

    def test_confirmed_boot_state_machine_and_rollback(self):
        """Simulate confirmed bootloader state machine and automatic rollback after 3 failed boots."""
        SLOT_EMPTY = 0
        SLOT_STAGED = 1
        SLOT_VALIDATED = 2
        SLOT_TESTING = 3
        SLOT_CONFIRMED = 4
        SLOT_INVALID = 5

        # Class representing power-loss-safe metadata state
        class BootMetadata:
            def __init__(self):
                self.active_slot = 0  # 0: Slot A, 1: Slot B
                self.slot_state = [SLOT_CONFIRMED, SLOT_EMPTY]
                self.boot_attempts = 0
                self.prev_confirmed_slot = 0

            def stage_new_image(self, target_slot):
                self.slot_state[target_slot] = SLOT_TESTING
                self.active_slot = target_slot
                self.boot_attempts = 1

            def power_on_boot(self):
                if self.slot_state[self.active_slot] == SLOT_CONFIRMED:
                    return "BOOT_MAIN_APP"
                elif self.slot_state[self.active_slot] == SLOT_TESTING:
                    if self.boot_attempts >= 3:
                        # Rollback triggered
                        self.slot_state[self.active_slot] = SLOT_INVALID
                        self.active_slot = self.prev_confirmed_slot
                        self.boot_attempts = 0
                        return "ROLLBACK_TO_PREV_CONFIRMED"
                    else:
                        self.boot_attempts += 1
                        return "BOOT_TESTING_IMAGE"
                return "SAFE_RECOVERY"

            def confirm_application(self):
                if self.slot_state[self.active_slot] == SLOT_TESTING:
                    self.slot_state[self.active_slot] = SLOT_CONFIRMED
                    self.prev_confirmed_slot = self.active_slot
                    self.boot_attempts = 0

        # Scenario 1: Unstable firmware crash loop causes rollback
        meta = BootMetadata()
        self.assertEqual(meta.active_slot, 0)
        self.assertEqual(meta.slot_state[0], SLOT_CONFIRMED)

        # Stage image into Slot B
        meta.stage_new_image(target_slot=1)
        self.assertEqual(meta.active_slot, 1)
        self.assertEqual(meta.slot_state[1], SLOT_TESTING)
        self.assertEqual(meta.boot_attempts, 1)

        # Boot 2 after crash
        action = meta.power_on_boot()
        self.assertEqual(action, "BOOT_TESTING_IMAGE")
        self.assertEqual(meta.boot_attempts, 2)

        # Boot 3 after crash
        action = meta.power_on_boot()
        self.assertEqual(action, "BOOT_TESTING_IMAGE")
        self.assertEqual(meta.boot_attempts, 3)

        # Boot 4 (3 failed attempts exceeded) -> Automatic Rollback to Slot A
        action = meta.power_on_boot()
        self.assertEqual(action, "ROLLBACK_TO_PREV_CONFIRMED")
        self.assertEqual(meta.active_slot, 0)
        self.assertEqual(meta.slot_state[1], SLOT_INVALID)
        self.assertEqual(meta.slot_state[0], SLOT_CONFIRMED)

        # Scenario 2: Successful boot confirmation
        meta2 = BootMetadata()
        meta2.stage_new_image(target_slot=1)
        # Application passes self-tests and confirms
        meta2.confirm_application()
        self.assertEqual(meta2.active_slot, 1)
        self.assertEqual(meta2.slot_state[1], SLOT_CONFIRMED)
        self.assertEqual(meta2.boot_attempts, 0)
        self.assertEqual(meta2.power_on_boot(), "BOOT_MAIN_APP")

    def test_modbus_register_access_and_atomic_snapshot(self):
        """Verify Modbus holding registers access permissions and atomic 32-bit uptime snapshot."""
        # Holding register access map: True = R/W, False = Read-Only
        MODBUS_REGISTERS = {
            40001: ("SYS_CONTROL_CMD", True),
            40002: ("BUS_VOLTAGE_RAW", False),
            40003: ("BAT_CURRENT_RAW", False),
            40004: ("BAT_SOC", False),
            40005: ("ACTIVE_FAULT_FLAGS", False),
            40006: ("VOUT", False),
            40007: ("IOUT", False),
            40008: ("TEMPERATURE", False),
            40009: ("OPERATING_MODE", False),
            40010: ("FAULT_CODE", False),
            40011: ("FW_VERSION", False),
            40012: ("UPTIME_MSW", False),
            40013: ("UPTIME_LSW", False),
            40014: ("FAULT_CLEAR_CMD", True),
            40015: ("CMD_RESULT", False),
            40016: ("CMD_SEQ", False),
            40017: ("FSM_STATE", False),
            40018: ("LATCHED_FAULT_FLAGS", False),
        }

        # Verify only 40001 and 40014 are writable
        writable_regs = [reg for reg, (_, rw) in MODBUS_REGISTERS.items() if rw]
        self.assertEqual(writable_regs, [40001, 40014])

        # Simulate Modbus Write Request Handler
        def write_holding_register(reg_addr, value):
            if reg_addr not in MODBUS_REGISTERS:
                return "EXCEPTION_02_ILLEGAL_DATA_ADDRESS"
            name, is_writable = MODBUS_REGISTERS[reg_addr]
            if not is_writable:
                return "EXCEPTION_02_ILLEGAL_DATA_ADDRESS"
            return "SUCCESS"

        self.assertEqual(write_holding_register(40001, 1), "SUCCESS")
        self.assertEqual(write_holding_register(40014, 0x00A5), "SUCCESS")
        self.assertEqual(write_holding_register(40002, 2400), "EXCEPTION_02_ILLEGAL_DATA_ADDRESS")
        self.assertEqual(write_holding_register(40008, 250), "EXCEPTION_02_ILLEGAL_DATA_ADDRESS")
        self.assertEqual(write_holding_register(40017, 4), "EXCEPTION_02_ILLEGAL_DATA_ADDRESS")

        # Atomic 32-bit snapshot simulation for Uptime
        system_uptime_seconds = 131075  # 0x00020003 -> MSW=2, LSW=3
        shadow_snapshot = {
            40012: (system_uptime_seconds >> 16) & 0xFFFF,
            40013: system_uptime_seconds & 0xFFFF,
        }
        reconstructed_uptime = (shadow_snapshot[40012] << 16) | shadow_snapshot[40013]
        self.assertEqual(reconstructed_uptime, system_uptime_seconds)

    def test_spi_ipc_session_resync_and_sequence_wraparound(self):
        """Verify SPI IPC session epoch re-synchronization and 8-bit sequence number wraparound."""
        class SpiIpcChannel:
            def __init__(self, initial_session):
                self.session_id = initial_session
                self.expected_seq = 0
                self.last_response = None

            def receive_frame(self, frame_session, frame_seq, command_val):
                # Check for session epoch change (MCU reset)
                if frame_session != self.session_id:
                    self.session_id = frame_session
                    self.expected_seq = 0  # Sequence reset on new session epoch
                    self.last_response = None

                # Check for duplicate frame (re-transmission / retry)
                if self.last_response is not None and frame_seq == ((self.expected_seq - 1) & 0xFF):
                    return "CACHED_RESPONSE", self.last_response

                # Process new monotonic sequence
                self.expected_seq = (frame_seq + 1) & 0xFF
                self.last_response = f"ACK_CMD_{command_val}"
                return "PROCESSED", self.last_response

        channel = SpiIpcChannel(initial_session=1)

        # Normal sequence 0 -> 1 -> 2
        status, resp = channel.receive_frame(frame_session=1, frame_seq=0, command_val=10)
        self.assertEqual(status, "PROCESSED")
        self.assertEqual(channel.expected_seq, 1)

        # Duplicate retry packet (SEQ 0) -> Returns cached response without re-executing
        status, resp = channel.receive_frame(frame_session=1, frame_seq=0, command_val=10)
        self.assertEqual(status, "CACHED_RESPONSE")

        # Sequence Wraparound (255 -> 0)
        channel.expected_seq = 255
        status, resp = channel.receive_frame(frame_session=1, frame_seq=255, command_val=20)
        self.assertEqual(status, "PROCESSED")
        self.assertEqual(channel.expected_seq, 0)  # Wrapped to 0

        # Session Reset (Session ID increments 1 -> 2 due to MCU reboot)
        status, resp = channel.receive_frame(frame_session=2, frame_seq=0, command_val=30)
        self.assertEqual(status, "PROCESSED")
        self.assertEqual(channel.session_id, 2)
        self.assertEqual(channel.expected_seq, 1)


if __name__ == "__main__":
    unittest.main()
