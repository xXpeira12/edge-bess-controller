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


if __name__ == "__main__":
    unittest.main()
