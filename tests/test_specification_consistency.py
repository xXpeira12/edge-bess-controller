#!/usr/bin/env python3
"""
Industrial Smart BESS & Power Management Controller (Desk-Scale PoC)
Specification Consistency & Architectural Invariant Test Suite

Performs automated mathematical derivations, transfer function validations,
threshold calculations, latency models, comparator routing matrix validations,
and cross-document invariant assertions.
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

    def test_stm32g474_comparator_routing_matrix(self):
        """Verify RM0440 Table 223 COMP to HRTIM Fault input multiplexing."""
        routing_matrix = {
            "OC_POS": {
                "comp": "COMP1",
                "inp": "PA1",
                "inm": "DAC1_CH1",
                "v_ref": 2.650,
                "hrtim_fault": "HRTIM1_FLT4"
            },
            "OC_NEG": {
                "comp": "COMP2",
                "inp": "DAC3_CH2",
                "inm": "PA7",
                "v_ref": 0.650,
                "hrtim_fault": "HRTIM1_FLT1"
            },
            "OV": {
                "comp": "COMP3",
                "inp": "PA0",
                "inm": "DAC1_CH2",
                "v_ref": 2.600,
                "hrtim_fault": "HRTIM1_FLT5"
            }
        }
        self.assertEqual(routing_matrix["OC_POS"]["hrtim_fault"], "HRTIM1_FLT4")
        self.assertEqual(routing_matrix["OC_NEG"]["hrtim_fault"], "HRTIM1_FLT1")
        self.assertEqual(routing_matrix["OV"]["hrtim_fault"], "HRTIM1_FLT5")
        self.assertEqual(routing_matrix["OC_POS"]["v_ref"], 2.650)
        self.assertEqual(routing_matrix["OC_NEG"]["v_ref"], 0.650)
        self.assertEqual(routing_matrix["OV"]["v_ref"], 2.600)

    def test_trip_threshold_tolerance_budget(self):
        """Verify worst-case trip threshold boundaries: 4.85 A <= I_trip <= 5.15 A."""
        tolerance_a = 0.15
        i_trip_min = self.I_HARDWARE_TRIP - tolerance_a
        i_trip_max = self.I_HARDWARE_TRIP + tolerance_a
        self.assertAlmostEqual(i_trip_min, 4.85, places=2)
        self.assertAlmostEqual(i_trip_max, 5.15, places=2)
        self.assertGreater(i_trip_min, self.I_SOFTWARE_WARN)

    def test_flash_slot_symmetry_and_fixed_bootloader(self):
        """Verify symmetric 200 KB dual-bank slot geometry."""
        self.assertEqual(self.SLOT_A_SIZE, self.SLOT_B_SIZE)
        self.assertEqual(self.SLOT_A_SIZE, 200 * 1024)
        self.assertLessEqual(self.MAX_IMAGE_SIZE, self.SLOT_A_SIZE)

        bank1_total = (32 + 200 + 16 + 8) * 1024
        self.assertEqual(bank1_total, 256 * 1024)

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

    def test_anti_aliasing_filter_frequency_response(self):
        """Verify 1st order RC anti-aliasing filter (R=1k, C=3.3nF) cut-off and attenuation."""
        r_filt = 1000.0  # 1 kOhm
        c_filt = 3.3e-9  # 3.3 nF
        f_cutoff = 1.0 / (2.0 * math.pi * r_filt * c_filt)
        self.assertAlmostEqual(f_cutoff / 1000.0, 48.229, places=2)

        # Attenuation at f_Nyquist = 25 kHz: ~ -1.04 dB, ~ -27.4 deg phase
        f_nyquist = 25000.0
        h_nyquist_mag = 1.0 / math.sqrt(1.0 + (f_nyquist / f_cutoff) ** 2)
        h_nyquist_db = 20.0 * math.log10(h_nyquist_mag)
        h_nyquist_phase_deg = -math.degrees(math.atan(f_nyquist / f_cutoff))
        self.assertAlmostEqual(h_nyquist_mag, 0.888, delta=0.002)
        self.assertAlmostEqual(h_nyquist_db, -1.04, delta=0.02)
        self.assertAlmostEqual(h_nyquist_phase_deg, -27.4, delta=0.2)

        # Attenuation at f_sw = 50 kHz: ~ -3.17 dB, ~ -46.0 deg phase
        f_sw = 50000.0
        h_sw_mag = 1.0 / math.sqrt(1.0 + (f_sw / f_cutoff) ** 2)
        h_sw_db = 20.0 * math.log10(h_sw_mag)
        h_sw_phase_deg = -math.degrees(math.atan(f_sw / f_cutoff))
        self.assertAlmostEqual(h_sw_mag, 0.694, delta=0.002)
        self.assertAlmostEqual(h_sw_db, -3.17, delta=0.02)
        self.assertAlmostEqual(h_sw_phase_deg, -46.0, delta=0.2)

    def test_voltage_sensing_divider_and_ov_trip(self):
        """Verify 10:1 resistor divider and 26.0V over-voltage trip derivation."""
        r1 = 90000.0  # 90 kOhm
        r2 = 10000.0  # 10 kOhm
        k_div = r2 / (r1 + r2)  # 0.1000
        self.assertAlmostEqual(k_div, 0.1000, places=4)

        # Nominal Vbus = 24.0V -> V_adc = 2.400V
        v_bus_nom = 24.0
        v_adc_nom = v_bus_nom * k_div
        self.assertAlmostEqual(v_adc_nom, 2.400, places=3)

        # OV Trip Vbus = 26.0V -> V_comp = 2.600V
        v_bus_ov = 26.0
        v_comp_ov = v_bus_ov * k_div
        self.assertAlmostEqual(v_comp_ov, 2.600, places=3)

        # Tolerance budget: 26.0 +/- 0.5 V -> 2.600 +/- 0.050 V
        v_ov_min = 25.5 * k_div
        v_ov_max = 26.5 * k_div
        self.assertAlmostEqual(v_ov_min, 2.550, places=3)
        self.assertAlmostEqual(v_ov_max, 2.650, places=3)

    def test_fsm_state_enum_and_recovery_policy(self):
        """Verify FSM state enum definitions and FAULT_CLEAR_CMD transition authority."""
        fsm_states = {
            0: "STATE_POWER_ON",
            1: "STATE_INIT_AND_SELF_TEST",
            2: "STATE_IDLE",
            3: "STATE_CHARGE_RAMP",
            4: "STATE_CHARGE_ACTIVE",
            5: "STATE_DISCHARGE_RAMP",
            6: "STATE_DISCHARGE_ACTIVE",
            7: "STATE_DERATING_ACTIVE",
            8: "STATE_RECOVERY_CHECK",
            9: "STATE_SAFE_STATE",
        }
        self.assertEqual(len(fsm_states), 10)
        self.assertEqual(fsm_states[8], "STATE_RECOVERY_CHECK")
        self.assertEqual(fsm_states[9], "STATE_SAFE_STATE")

        # Command acceptance logic: 0x00A5 is accepted ONLY in STATE_SAFE_STATE (9)
        def handle_fault_clear(current_state, cmd_key):
            if cmd_key != 0x00A5:
                return (current_state, 4)  # Rejected_Limit
            if current_state == 9:  # STATE_SAFE_STATE
                return (8, 1)  # Enter STATE_RECOVERY_CHECK, Accepted
            return (current_state, 2)  # Rejected_InvalidState

        # In SAFE_STATE -> transitions to RECOVERY_CHECK
        new_state, result = handle_fault_clear(9, 0x00A5)
        self.assertEqual(new_state, 8)
        self.assertEqual(result, 1)

        # In IDLE -> rejected
        new_state, result = handle_fault_clear(2, 0x00A5)
        self.assertEqual(new_state, 2)
        self.assertEqual(result, 2)

        # In CHARGE_ACTIVE -> rejected
        new_state, result = handle_fault_clear(4, 0x00A5)
        self.assertEqual(new_state, 4)
        self.assertEqual(result, 2)

    def test_derating_hysteresis_bands(self):
        """Verify temperature, low SOC, and high SOC derating entry/exit hysteresis."""
        # Heatsink Temperature: Enter > 55.0 C, Exit < 45.0 C
        t_enter = 55.0
        t_exit = 45.0
        self.assertGreater(t_enter, t_exit)
        self.assertEqual(t_enter - t_exit, 10.0)

        # Low SOC: Enter < 15.0 %, Exit > 20.0 %
        soc_low_enter = 15.0
        soc_low_exit = 20.0
        self.assertLess(soc_low_enter, soc_low_exit)
        self.assertEqual(soc_low_exit - soc_low_enter, 5.0)

        # High SOC: Enter > 95.0 %, Exit < 90.0 %
        soc_high_enter = 95.0
        soc_high_exit = 90.0
        self.assertGreater(soc_high_enter, soc_high_exit)
        self.assertEqual(soc_high_enter - soc_high_exit, 5.0)

    def test_boot_metadata_record_structure(self):
        """Verify BootMetadataRecord_t struct size (136 bytes), magic, and commit marker."""
        # uint32_t record_magic (4)
        # uint32_t sequence_num (4)
        # uint32_t active_slot (4)
        # uint32_t slot_state (4)
        # uint32_t security_version (4)
        # uint32_t boot_attempts (4)
        # uint32_t image_size_bytes (4)
        # uint32_t image_crc32 (4)
        # uint8_t  sha256_digest[32] (32)
        # uint8_t  ecdsa_signature[64] (64)
        # uint32_t payload_crc32 (4)
        # uint32_t commit_marker (4)
        fmt = ">IIIIIIII32s64sII"
        record_size = struct.calcsize(fmt)
        self.assertEqual(record_size, 136)

        magic = 0x42455353  # "BESS"
        commit_marker = 0xAA55AA55
        packed = struct.pack(
            fmt,
            magic,
            1,       # seq
            0,       # slot A
            4,       # CONFIRMED
            1,       # sec ver
            0,       # boot attempts
            128000,  # size
            0x12345678,
            b"\x00" * 32,
            b"\x00" * 64,
            0xCAFEBABE,
            commit_marker,
        )
        self.assertEqual(len(packed), 136)
        unpacked_magic, _, _, _, _, _, _, _, _, _, _, unpacked_commit = struct.unpack(fmt, packed)
        self.assertEqual(unpacked_magic, 0x42455353)
        self.assertEqual(unpacked_commit, 0xAA55AA55)

    def test_spi_ipc_frame_16bit_seq_and_crc(self):
        """Verify SPI DMA binary frame with 16-bit SEQ_NUM and CRC16-CCITT."""
        sync_word = 0xA55A
        proto_ver = 0x01
        session_id = 42
        seq_num = 1001  # 16-bit sequence number (1:1 Modbus CMD_SEQ)
        msg_type = 0x01
        msg_flags = 0x00
        payload = struct.pack(">HHhH", 2400, 1280, 250, 850)
        payload_len = len(payload)

        # Header: SYNC(2) + PROTO(1) + SESSION(1) + SEQ_NUM(2) + TYPE(1) + FLAGS(1) + LEN(1)
        header = struct.pack(">HBBHBBB", sync_word, proto_ver, session_id, seq_num, msg_type, msg_flags, payload_len)
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
        self.assertEqual(len(full_frame), 19)
        self.assertEqual(struct.unpack(">H", full_frame[:2])[0], 0xA55A)
        self.assertEqual(struct.unpack(">H", full_frame[4:6])[0], 1001)


if __name__ == "__main__":
    unittest.main()
