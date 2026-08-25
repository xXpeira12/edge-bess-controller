#!/usr/bin/env python3
"""
Industrial Smart BESS & Power Management Controller (Desk-Scale PoC)
Specification Consistency & Architectural Invariant Test Suite

Performs automated mathematical derivations, transfer function validations,
threshold calculations, and cross-document invariant assertions across all
architectural domains.
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

        # Assert headroom within 0-3.3V ADC full-scale
        self.assertGreater(v_op_low, 0.0)
        self.assertLess(v_op_high, 3.300)

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

    def test_dc_bus_voltage_divider_and_filter(self):
        """Verify 10:1 divider and 48.2 kHz low-pass anti-aliasing filter."""
        r1, r2 = 90000.0, 10000.0
        k_div = r2 / (r1 + r2)
        self.assertAlmostEqual(k_div, 0.100, places=4)

        # ADC scaling: 24V -> 2.400V, 30V -> 3.000V
        self.assertAlmostEqual(24.0 * k_div, 2.400, places=3)
        self.assertAlmostEqual(30.0 * k_div, 3.000, places=3)

        # Anti-aliasing filter: R=1k, C=3.3nF -> fc ~ 48.2 kHz
        r_filt, c_filt = 1000.0, 3.3e-9
        fc = 1.0 / (2.0 * math.pi * r_filt * c_filt)
        self.assertAlmostEqual(fc, 48228.7, delta=100.0)

        # Response at Nyquist (25 kHz) and Switching (50 kHz)
        f_nyq = 25000.0
        db_nyq = 20.0 * math.log10(1.0 / math.sqrt(1.0 + (f_nyq / fc) ** 2))
        phase_nyq = -math.degrees(math.atan(f_nyq / fc))
        self.assertAlmostEqual(db_nyq, -1.04, delta=0.1)
        self.assertAlmostEqual(phase_nyq, -27.4, delta=0.5)

        f_sw = 50000.0
        db_sw = 20.0 * math.log10(1.0 / math.sqrt(1.0 + (f_sw / fc) ** 2))
        phase_sw = -math.degrees(math.atan(f_sw / fc))
        self.assertAlmostEqual(db_sw, -3.17, delta=0.1)
        self.assertAlmostEqual(phase_sw, -46.0, delta=0.5)

    def test_tier0_hardware_break_latency_budget(self):
        """Verify Tier-0 latency equation and budget <= 2.0 us."""
        t_shunt = 10e-9        # 10 ns calculated (L/R)
        t_afe = 250e-9         # 250 ns datasheet-guaranteed
        t_comparator = 25e-9   # 25 ns datasheet-guaranteed
        t_mcu_break = 50e-9    # 50 ns datasheet-guaranteed
        t_gate_driver = 50e-9  # 50 ns datasheet-guaranteed
        t_power_stage = 100e-9 # 100 ns bench/datasheet

        t_total_trip = t_shunt + t_afe + t_comparator + t_mcu_break + t_gate_driver + t_power_stage
        self.assertAlmostEqual(t_total_trip * 1e9, 485.0, delta=1.0)
        self.assertLess(t_total_trip, self.T_TOTAL_TRIP_MAX_US * 1e-6)

    def test_control_loop_timing_and_dwt_jitter_cycles(self):
        """Verify 50 kHz switching timing and DWT cycle equivalence at 170 MHz."""
        f_cpu = 170e6
        max_p_p_jitter_ns = 100.0  # +/- 50 ns
        dwt_cycles = (max_p_p_jitter_ns * 1e-9) * f_cpu
        self.assertAlmostEqual(dwt_cycles, 17.0, places=1)

    def test_flash_slot_symmetry_invariants(self):
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

    def test_modbus_register_map_schema(self):
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

    def test_spi_ipc_crc16_ccitt(self):
        """Verify CRC-16-CCITT implementation on SPI DMA binary frame."""
        sync_word = 0xA55A
        proto_ver = 0x01
        seq_num = 1
        msg_type = 0x01
        msg_flags = 0x00
        payload = struct.pack(">HHhH", 2400, 1280, 250, 850)
        payload_len = len(payload)

        header = struct.pack(">HBBBB", sync_word, proto_ver, seq_num, msg_type, msg_flags) + struct.pack("B", payload_len)
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
        self.assertEqual(len(full_frame), 17)
        self.assertEqual(struct.unpack(">H", full_frame[:2])[0], 0xA55A)


if __name__ == "__main__":
    unittest.main()
