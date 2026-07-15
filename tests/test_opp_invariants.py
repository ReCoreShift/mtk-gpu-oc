import os
import pytest

from mtk_gpu_oc.opp import (
    OppEntry, OppTable, check_opp_invariants,
    OPP_ENTRY_SIZE, VSRAM_FLOOR, PMIC_STEP,
    OPP_VOLT_MIN, OPP_VOLT_MAX, OPP_FREQ_MIN, OPP_FREQ_MAX,
)


def _entry(freq_khz=1000000, volt=80000, vsram=None, u3=1, u4=1875):
    return OppEntry(
        freq_khz=freq_khz,
        volt=volt,
        vsram=vsram or max(volt, VSRAM_FLOOR),
        u3=u3,
        u4=u4,
    )


class TestCheckInvariants:
    def test_empty_table(self):
        t = OppTable(entries=[], file_offset=0)
        errs = check_opp_invariants(t)
        assert 'empty' in errs[0]

    def test_valid_table_no_errors(self):
        t = OppTable(entries=[
            _entry(freq_khz=1100000, volt=90000),
            _entry(freq_khz=1000000, volt=80000),
            _entry(freq_khz=900000, volt=75000),
        ], file_offset=0)
        errs = check_opp_invariants(t)
        assert errs == []

    def test_freq_not_descending(self):
        t = OppTable(entries=[
            _entry(freq_khz=1000000),
            _entry(freq_khz=1100000),  # ascending!
        ], file_offset=0)
        errs = check_opp_invariants(t)
        assert any('not strictly descending' in e for e in errs)

    def test_volt_not_non_increasing(self):
        t = OppTable(entries=[
            _entry(freq_khz=1100000, volt=80000),
            _entry(freq_khz=1000000, volt=85000),  # higher voltage!
        ], file_offset=0)
        errs = check_opp_invariants(t)
        assert any('not non-increasing' in e for e in errs)

    def test_freq_out_of_range(self):
        t = OppTable(entries=[
            _entry(freq_khz=100, volt=80000),  # too low
        ], file_offset=0)
        errs = check_opp_invariants(t)
        assert any('outside range' in e for e in errs)

    def test_volt_out_of_range(self):
        t = OppTable(entries=[
            _entry(freq_khz=1000000, volt=10000),  # too low
        ], file_offset=0)
        errs = check_opp_invariants(t)
        assert any('outside range' in e for e in errs)

    def test_volt_not_aligned(self):
        t = OppTable(entries=[
            _entry(freq_khz=1000000, volt=80100),  # not multiple of 625
        ], file_offset=0)
        errs = check_opp_invariants(t)
        assert any('not aligned' in e for e in errs)

    def test_vsram_below_volt(self):
        t = OppTable(entries=[
            _entry(freq_khz=1000000, volt=80000, vsram=70000),
        ], file_offset=0)
        errs = check_opp_invariants(t)
        assert any('vsram' in e for e in errs)

    def test_u3_invalid(self):
        t = OppTable(entries=[
            _entry(freq_khz=1000000, u3=3),  # must be 1 or 2
        ], file_offset=0)
        errs = check_opp_invariants(t)
        assert any('u3' in e for e in errs)

    def test_u4_invalid(self):
        t = OppTable(entries=[
            _entry(freq_khz=1000000, u4=999),  # not in valid set
        ], file_offset=0)
        errs = check_opp_invariants(t)
        assert any('u4' in e for e in errs)

    def test_freq_not_aligned_to_1mhz(self):
        t = OppTable(entries=[
            _entry(freq_khz=1000500, volt=80000),  # not aligned to 1000
        ], file_offset=0)
        errs = check_opp_invariants(t)
        assert any('not aligned' in e for e in errs)

    def test_real_stock_table(self):
        """The stock MT6789 table should pass all invariant checks (integration)."""
        MTK_STOCK_MODULE = os.environ.get(
            'MTK_STOCK_MODULE',
            os.path.join(os.path.dirname(__file__), '..', 'research', 'stock', 'mtk_gpufreq_mt6789.ko'),
        )
        try:
            with open(MTK_STOCK_MODULE, 'rb') as f:
                data = f.read()
        except FileNotFoundError:
            pytest.skip(f'stock module not found at {MTK_STOCK_MODULE}')
            return

        from mtk_gpu_oc.elf import Elf64
        from mtk_gpu_oc.gpufreq import analyze as gf_analyze
        elff = Elf64(data)
        gf = gf_analyze(elff)
        assert gf.opp_table is not None
        errs = check_opp_invariants(gf.opp_table)
        assert errs == [], f'Stock table failed invariants: {errs}'
