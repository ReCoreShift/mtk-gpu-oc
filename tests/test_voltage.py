import pytest
import struct

from mtk_gpu_oc.opp import OppEntry, OppTable, OPP_ENTRY_SIZE, VSRAM_FLOOR, PMIC_STEP, OPP_VOLT_MIN, OPP_VOLT_MAX
from mtk_gpu_oc.voltage import estimate_voltage, quantize_volt


def _make_table(entries: list[tuple[int, int]]) -> OppTable:
    opps = []
    for freq, volt in entries:
        opps.append(OppEntry(
            freq_khz=freq,
            volt=volt,
            vsram=max(volt, VSRAM_FLOOR),
            u3=1 if freq >= 948000 else 2,
            u4=1875 if freq >= 835000 else 1250 if freq >= 596000 else 625,
        ))
    return OppTable(entries=opps, file_offset=0)


class TestQuantizeVolt:
    def test_exact_step(self):
        assert quantize_volt(90000) == 90000

    def test_rounds_down(self):
        assert quantize_volt(90100) == 90000  # 90100/625 = 144.16 -> 144

    def test_rounds_up(self):
        # 90469/625 = 144.7504 -> round = 145 -> 90625
        assert quantize_volt(90469) == 90625

    def test_midpoint(self):
        # 90312.5/625 = 144.5 -> banker's round = 144 -> 90000
        assert quantize_volt(90312) == 90000

    def test_zero(self):
        assert quantize_volt(0) == 0

    def test_large_value(self):
        assert quantize_volt(100000) == 100000  # 100000/625 = 160


class TestEstimateVoltageExplicit:
    def test_explicit_override(self):
        table = _make_table([(1100000, 90000), (390000, 67500)])
        ve = estimate_voltage(table, 1200000, explicit_volt_uv=95000)
        assert ve.model == 'explicit'
        assert ve.estimated_raw_uv == 95000
        assert ve.quantized_uv == 95000
        assert ve.is_explicit

    def test_explicit_not_step_aligned(self):
        table = _make_table([(1100000, 90000), (390000, 67500)])
        ve = estimate_voltage(table, 1200000, explicit_volt_uv=95100)
        assert ve.model == 'explicit'
        assert ve.quantized_uv != 95100  # gets quantized
        assert ve.quantized_uv % PMIC_STEP == 0


class TestEstimateVoltageTopTwo:
    def test_exact_stock_max(self):
        table = _make_table([(1100000, 90000), (1086000, 89375), (1072000, 88750)])
        ve = estimate_voltage(table, 1100000)
        assert ve.model == 'top-two'
        assert ve.estimated_raw_uv == 90000
        assert ve.quantized_uv == 90000

    def test_exact_stock_min(self):
        table = _make_table([(1100000, 90000), (390000, 67500)])
        ve = estimate_voltage(table, 390000)
        assert ve.quantized_uv == 67500

    def test_between_opps(self):
        table = _make_table([(1100000, 90000), (390000, 67500)])
        ve = estimate_voltage(table, 700000)
        # Should interpolate between min and max
        ratio = (700000 - 390000) / (1100000 - 390000)
        expected = 67500 + ratio * (90000 - 67500)
        assert abs(ve.estimated_raw_uv - expected) < 100

    def test_above_stock_max(self):
        table = _make_table([(1100000, 90000), (1086000, 89375)])
        ve = estimate_voltage(table, 1150000)
        # Top-two slope = (90000-89375)/(1100000-1086000)*1000 = 44.6 uV/MHz
        expected = 90000 + (1150000 - 1100000) * 44.6 / 1000
        assert abs(ve.estimated_raw_uv - expected) < 10
        assert ve.extrapolation_mhz == 50
        assert ve.is_extrapolated

    def test_substantially_above_stock(self):
        table = _make_table([(1100000, 90000), (1086000, 89375)])
        ve = estimate_voltage(table, 1300000)
        assert ve.extrapolation_mhz == 200
        assert ve.quantized_uv > 90000

    def test_slope_uv_per_mhz(self):
        table = _make_table([(1100000, 90000), (1086000, 89375)])
        ve = estimate_voltage(table, 1150000)
        expected_slope = (90000 - 89375) / (1100000 - 1086000) * 1000
        assert abs(ve.slope_uv_per_mhz - expected_slope) < 0.1

    def test_source_opps(self):
        table = _make_table([(1100000, 90000), (1086000, 89375)])
        ve = estimate_voltage(table, 1150000)
        assert len(ve.source_opps) == 2
        assert ve.source_opps[0].freq_khz == 1100000


class TestEstimateVoltageFallback:
    def test_duplicate_voltage_falls_back(self):
        """Top-two have same V, but table has different min/max — fall back to endpoint."""
        table = _make_table([(1100000, 90000), (1086000, 90000), (390000, 67500)])
        ve = estimate_voltage(table, 1150000)
        assert ve.model == 'endpoint'
        assert len(ve.warnings) > 0

    def test_single_entry(self):
        table = _make_table([(1100000, 90000)])
        ve = estimate_voltage(table, 1150000)
        assert ve.model == 'constant'
        assert ve.quantized_uv == 90000

    def test_two_entries(self):
        table = _make_table([(1100000, 90000), (390000, 67500)])
        ve = estimate_voltage(table, 1200000)
        assert ve.model == 'top-two'


class TestEstimateVoltageDeterminism:
    def test_deterministic(self):
        table = _make_table([(1100000, 90000), (1086000, 89375)])
        v1 = estimate_voltage(table, 1150000)
        v2 = estimate_voltage(table, 1150000)
        assert v1.estimated_raw_uv == v2.estimated_raw_uv
        assert v1.quantized_uv == v2.quantized_uv
        assert v1.model == v2.model

    def test_no_table_mutation(self):
        entries = [(1100000, 90000), (1086000, 89375)]
        table = _make_table(entries)
        before = table.to_bytes()
        estimate_voltage(table, 1150000)
        assert table.to_bytes() == before


class TestEstimateVoltageEdgeCases:
    def test_voltage_floor_plateau(self):
        """Low-frequency voltage-plateau OPPs should not affect estimation."""
        table = _make_table([
            (1100000, 90000), (1086000, 89375), (1072000, 88750), (1058000, 88125),
            (700000, 70000), (674000, 70000), (648000, 70000),  # plateau
            (390000, 67500),
        ])
        ve = estimate_voltage(table, 1150000)
        # Should use top-two OPPs, not be affected by plateau
        assert ve.model == 'top-two'
        assert ve.slope_uv_per_mhz > 40  # not diluted by flats

    def test_quantized_always_aligned(self):
        import random
        table = _make_table([(1100000, 90000), (390000, 67500)])
        for _ in range(20):
            target = random.randint(400000, 2000000)
            ve = estimate_voltage(table, target)
            assert ve.quantized_uv % PMIC_STEP == 0

    def test_increasing_target_does_not_decrease_voltage(self):
        table = _make_table([(1100000, 90000), (390000, 67500)])
        prev_v = 0
        for target in range(400000, 2000000, 50000):
            ve = estimate_voltage(table, target)
            assert ve.quantized_uv >= prev_v, f"voltage dropped at {target} kHz"
            prev_v = ve.quantized_uv


class TestQuantizeConsistency:
    def test_through_roundtrip(self):
        """quantize_volt should be idempotent."""
        v = quantize_volt(90000)
        assert quantize_volt(v) == v

    def test_quantize_then_roundtrip_entry(self):
        e = OppEntry(freq_khz=1000000, volt=87500, vsram=87500, u3=1, u4=1875)
        data = e.to_bytes()
        e2 = OppEntry.from_bytes(data)
        assert e2.volt == e.volt
        assert e2.freq_khz == e.freq_khz
