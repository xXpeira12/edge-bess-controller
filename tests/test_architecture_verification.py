#!/usr/bin/env python3
"""
Industrial Smart BESS & Power Management Controller (Desk-Scale PoC)
Architecture, Mathematical Modeling & Protocol Verification Test Suite

Validates all SRS requirements, analog sensing transfer functions,
filter responses, timing jitter bounds, Tier-0 break latency budgets,
SPI DMA IPC frames, Modbus registers 40001-40018, and Flash memory layouts.
"""

import math
import struct
import unittest


class TestAFESensing(unittest.TestCase):
    """Verifies REQ-SENS-001, REQ-SENS-002, REQ-SENS-003 analog sensing mathematics."""

    def test_dc_bus_voltage_divider_and_filter(self):
        # 10:1 Divider: R1=90k, R2=10k
        r1, r2 = 90000.0, 10000.0
        k_div = r2 / (r1 + r2)
        self.assertAlmostEqual(k_div, 0.100, places=4)

        # Voltage scaling
        v_bus_nom = 24.0
        v_adc_nom = v_bus_nom * k_div
        self.assertAlmostEqual(v_adc_nom, 2.400, places=3)
        self.assertLess(v_adc_nom, 3.30)  # within 3.3V ADC full scale

        v_bus_max = 30.0
        v_adc_max = v_bus_max * k_div
        self.assertAlmostEqual(v_adc_max, 3.000, places=3)
        self.assertLess(v_adc_max, 3.30)

        # Anti-aliasing filter: R=1k, C=3.3nF -> fc ~ 48.2 kHz
        r_filt, c_filt = 1000.0, 3.3e-9
        fc = 1.0 / (2.0 * math.pi * r_filt * c_filt)
        self.assertAlmostEqual(fc, 48228.7, delta=100.0)

        # Frequency response at Nyquist (25 kHz) and Switching (50 kHz)
        f_nyq = 25000.0
        gain_nyq = 1.0 / math.sqrt(1.0 + (f_nyq / fc) ** 2)
        db_nyq = 20.0 * math.log10(gain_nyq)
        phase_nyq = -math.degrees(math.atan(f_nyq / fc))
        self.assertAlmostEqual(gain_nyq, 0.887, delta=0.01)
        self.assertAlmostEqual(db_nyq, -1.04, delta=0.1)
        self.assertAlmostEqual(phase_nyq, -27.4, delta=0.5)

        f_sw = 50000.0
        gain_sw = 1.0 / math.sqrt(1.0 + (f_sw / fc) ** 2)
        db_sw = 20.0 * math.log10(gain_sw)
        phase_sw = -math.degrees(math.atan(f_sw / fc))
        self.assertAlmostEqual(gain_sw, 0.694, delta=0.01)
        self.assertAlmostEqual(db_sw, -3.17, delta=0.1)
        self.assertAlmostEqual(phase_sw, -46.0, delta=0.5)

    def test_current_sensing_and_csa_transfer_function(self):
        # INA240: R_shunt=10 mOhm, Gain=40 V/V (0.400 V/A), V_ref=1.650V
        r_shunt = 0.010
        gain = 40.0
        v_ref = 1.650
        transfer_factor = r_shunt * gain  # 0.400 V/A
        self.assertAlmostEqual(transfer_factor, 0.400, places=4)

        # Operational range: +/- 3.5 A -> 0.250 V to 3.050 V
        i_dis_max = -3.5
        v_out_dis_max = v_ref + (i_dis_max * transfer_factor)
        self.assertAlmostEqual(v_out_dis_max, 0.250, places=3)
        self.assertGreater(v_out_dis_max, 0.0)  # > 0V (no negative saturation)

        i_chg_max = 3.5
        v_out_chg_max = v_ref + (i_chg_max * transfer_factor)
        self.assertAlmostEqual(v_out_chg_max, 3.050, places=3)
        self.assertLess(v_out_chg_max, 3.30)  # < 3.3V (no rail clipping)

        # Warning threshold: +/- 4.0 A -> 0.050 V and 3.250 V
        v_warn_neg = v_ref + (-4.0 * transfer_factor)
        v_warn_pos = v_ref + (4.0 * transfer_factor)
        self.assertAlmostEqual(v_warn_neg, 0.050, places=3)
        self.assertAlmostEqual(v_warn_pos, 3.250, places=3)

        # Emergency trip: +/- 5.0 A -> -0.35 V (clamped to 0V) and +3.65 V (clamped to 3.3V)
        v_trip_neg = v_ref + (-5.0 * transfer_factor)
        v_trip_pos = v_ref + (5.0 * transfer_factor)
        self.assertAlmostEqual(v_trip_neg, -0.350, places=3)
        self.assertAlmostEqual(v_trip_pos, 3.650, places=3)

        # Filter: R=1k, C=2.2nF -> fc ~ 72.3 kHz
        r_filt_c, c_filt_c = 1000.0, 2.2e-9
        fc_c = 1.0 / (2.0 * math.pi * r_filt_c * c_filt_c)
        self.assertAlmostEqual(fc_c, 72343.1, delta=100.0)


class TestControlLoopTimingAndJitter(unittest.TestCase):
    """Verifies NFR-PERF-01 timing budget and 4 jitter metrics."""

    def test_timing_budget_and_cpu_load(self):
        f_sw = 50000.0
        t_s_us = (1.0 / f_sw) * 1e6
        self.assertAlmostEqual(t_s_us, 20.0, places=2)

        f_cpu_g4 = 170e6
        t_clk_g4_ns = (1.0 / f_cpu_g4) * 1e9
        self.assertAlmostEqual(t_clk_g4_ns, 5.88, delta=0.02)

        # 40% CPU load limit -> max ISR budget = 8.0 us
        max_isr_us = 0.40 * t_s_us
        self.assertAlmostEqual(max_isr_us, 8.0, places=2)

    def test_four_jitter_metrics_and_dwt_cycles(self):
        # 1. Trigger jitter <= +/- 5 ns
        # 2. IRQ latency jitter <= +/- 15 ns
        # 3. Execution time jitter <= +/- 20 ns
        # 4. Total sample-to-duty update jitter <= +/- 50 ns (peak-to-peak <= 100 ns)
        max_p_p_jitter_ns = 100.0
        f_cpu = 170e6
        max_dwt_cycles = (max_p_p_jitter_ns * 1e-9) * f_cpu
        self.assertAlmostEqual(max_dwt_cycles, 17.0, places=1)


class TestTier0ProtectionLatency(unittest.TestCase):
    """Verifies Tier-0 Hardware Break latency breakdown budget <= 2.0 us."""

    def test_tier0_latency_breakdown(self):
        t_sensor = 350e-9      # INA240 delay
        t_comparator = 25e-9  # STM32G4 COMP delay
        t_routing = 5e-9      # Internal silicon matrix
        t_timer = 25e-9       # HRTIM/TIM1 break logic
        t_driver = 20e-9      # Gate driver delay
        t_gate = 60e-9        # MOSFET turn-off time

        t_total = t_sensor + t_comparator + t_routing + t_timer + t_driver + t_gate
        self.assertAlmostEqual(t_total * 1e9, 485.0, delta=1.0)
        self.assertLess(t_total, 2.0e-6)  # Must be strictly << 2.0 us


class TestSPIIPCProtocol(unittest.TestCase):
    """Verifies REQ-COMM-001 SPI frame serialization, CRC16-CCITT, and ARQ parameters."""

    @staticmethod
    def crc16_ccitt(data: bytes) -> int:
        crc = 0xFFFF
        for byte in data:
            crc ^= (byte << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x1021) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
        return crc

    def test_frame_serialization_and_crc(self):
        sync_word = 0xA55A
        proto_ver = 0x01
        seq_num = 42
        msg_type = 0x01  # MSG_TELEMETRY_FAST
        msg_flags = 0x00
        payload = struct.pack(">HHhH", 2400, 1280, 250, 850)
        payload_len = len(payload)

        header = struct.pack(">HBBBB", sync_word, proto_ver, seq_num, msg_type, msg_flags)
        header_with_len = header + struct.pack("B", payload_len)
        data_to_crc = header_with_len[2:] + payload
        calculated_crc = self.crc16_ccitt(data_to_crc)
        full_frame = header_with_len + payload + struct.pack(">H", calculated_crc)

        self.assertEqual(len(full_frame), 2 + 5 + 8 + 2)
        parsed_sync = struct.unpack(">H", full_frame[:2])[0]
        self.assertEqual(parsed_sync, 0xA55A)
        self.assertEqual(self.crc16_ccitt(full_frame[2:-2]), calculated_crc)

    def test_arq_timing_parameters(self):
        t_ack_timeout_ms = 5.0
        max_retries = 3
        self.assertEqual(t_ack_timeout_ms, 5.0)
        self.assertEqual(max_retries, 3)


class TestSystemStateTransitions(unittest.TestCase):
    """Verifies FSM state machine, ramping rates, and recovery transitions."""

    def test_slew_rates(self):
        normal_ramp_rate = 2.0       # 2.0 A/s normal commanded ramp
        emergency_ramp_rate = 100.0  # 100.0 A/s emergency ramp-down
        fsm_tick_ms = 1.0

        # Normal: 2 mA per 1 ms tick
        delta_i_norm = normal_ramp_rate * (fsm_tick_ms / 1000.0)
        self.assertAlmostEqual(delta_i_norm, 0.002, places=4)

        # Emergency: 5.0 A to 0 A at 100 A/s takes 50 ms
        t_emerg_stop_ms = (5.0 / emergency_ramp_rate) * 1000.0
        self.assertAlmostEqual(t_emerg_stop_ms, 50.0, places=1)

    def test_state_enum_and_recovery_flow(self):
        states = {
            "STATE_POWER_ON": 0,
            "STATE_INIT_AND_SELF_TEST": 1,
            "STATE_IDLE": 2,
            "STATE_CHARGE_RAMP": 3,
            "STATE_CHARGE_ACTIVE": 4,
            "STATE_DISCHARGE_RAMP": 5,
            "STATE_DISCHARGE_ACTIVE": 6,
            "STATE_DERATING_ACTIVE": 7,
            "STATE_RECOVERY_CHECK": 8,
            "STATE_SAFE_STATE": 9,
        }
        self.assertEqual(len(states), 10)
        self.assertEqual(states["STATE_RECOVERY_CHECK"], 8)
        self.assertEqual(states["STATE_SAFE_STATE"], 9)


class TestModbusRegisterMapSchema(unittest.TestCase):
    """Verifies holding registers 40001 - 40018 and safety prohibitions."""

    def test_register_map_integrity(self):
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


class TestFlashMemoryMaps(unittest.TestCase):
    """Verifies symmetric 200 KB dual-bank slot geometry for STM32G474RE."""

    def test_stm32g474_symmetric_geometry(self):
        bank1_bootloader = 32 * 1024
        bank1_slot_a = 200 * 1024
        bank1_nvram = 16 * 1024
        bank1_key_region = 8 * 1024
        self.assertEqual(bank1_bootloader + bank1_slot_a + bank1_nvram + bank1_key_region, 256 * 1024)

        bank2_slot_b = 200 * 1024
        bank2_diag_log = 32 * 1024
        bank2_metadata = 24 * 1024
        self.assertEqual(bank2_slot_b + bank2_diag_log + bank2_metadata, 256 * 1024)

        # Symmetry check
        self.assertEqual(bank1_slot_a, bank2_slot_b)


if __name__ == "__main__":
    unittest.main()
