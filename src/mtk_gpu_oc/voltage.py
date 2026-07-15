# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from dataclasses import dataclass, field
from typing import Optional

from .opp import OppTable, OppEntry, PMIC_STEP


@dataclass
class VoltageEstimate:
    target_freq_khz: int
    estimated_raw_uv: int
    quantized_uv: int
    model: str
    source_opps: list[OppEntry] = field(default_factory=list)
    slope_uv_per_mhz: float = 0.0
    stock_max_freq_khz: int = 0
    stock_max_volt_uv: int = 0
    extrapolation_mhz: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def estimated_mv(self) -> float:
        return self.estimated_raw_uv / 100.0

    @property
    def quantized_mv(self) -> float:
        return self.quantized_uv / 100.0

    @property
    def is_explicit(self) -> bool:
        return self.model == 'explicit'

    @property
    def is_extrapolated(self) -> bool:
        return self.extrapolation_mhz > 0

    def summary(self) -> str:
        parts = [f'model={self.model}']
        if self.slope_uv_per_mhz:
            parts.append(f'slope={self.slope_uv_per_mhz:.1f} uV/MHz')
        if self.extrapolation_mhz:
            parts.append(f'+{self.extrapolation_mhz:.0f} MHz beyond stock')
        if self.warnings:
            parts.append(f'warnings={len(self.warnings)}')
        return f'VoltageEstimate(target={self.target_freq_khz//1000} MHz, raw={self.estimated_mv:.2f} mV, q={self.quantized_mv:.2f} mV, ' + ', '.join(parts) + ')'


def quantize_volt(volt_uv: int) -> int:
    return round(volt_uv / PMIC_STEP) * PMIC_STEP


def estimate_voltage(
    table: OppTable,
    target_freq_khz: int,
    explicit_volt_uv: Optional[int] = None,
) -> VoltageEstimate:
    if not table.entries:
        raise ValueError('OPP table is empty')

    stock_max_freq = table.entries[0].freq_khz
    stock_min_freq = table.entries[-1].freq_khz
    stock_max_volt = table.entries[0].volt
    stock_min_volt = table.entries[-1].volt

    # Explicit override
    if explicit_volt_uv is not None:
        return VoltageEstimate(
            target_freq_khz=target_freq_khz,
            estimated_raw_uv=explicit_volt_uv,
            quantized_uv=quantize_volt(explicit_volt_uv),
            model='explicit',
            stock_max_freq_khz=stock_max_freq,
            stock_max_volt_uv=stock_max_volt,
            extrapolation_mhz=max(0, target_freq_khz - stock_max_freq) / 1000.0,
        )

    slope_uv_per_mhz = 0.0
    warnings: list[str] = []

    # Determine best model based on table characteristics
    # Strategy: top-two-OPP slope preferred, fall back to whole-range endpoint
    if len(table.entries) >= 2:
        t0f = table.entries[0].freq_khz
        t0v = table.entries[0].volt
        t1f = table.entries[1].freq_khz
        t1v = table.entries[1].volt

        if t0f != t1f and t0v != t1v:
            slope_uv_per_mhz = (t0v - t1v) / (t0f - t1f) * 1000
            raw = t0v + (target_freq_khz - t0f) * slope_uv_per_mhz / 1000
            model = 'top-two'
            source = [table.entries[0], table.entries[1]]
        elif stock_max_freq != stock_min_freq and stock_max_volt != stock_min_volt:
            slope_uv_per_mhz = (stock_max_volt - stock_min_volt) / (stock_max_freq - stock_min_freq) * 1000
            raw = stock_min_volt + (target_freq_khz - stock_min_freq) * slope_uv_per_mhz / 1000
            model = 'endpoint'
            source = [table.entries[0], table.entries[-1]]
            warnings.append('top-two OPPs have identical voltage; fell back to whole-range endpoint')
        else:
            raw = stock_max_volt
            model = 'constant'
            source = [table.entries[0]]
            warnings.append('cannot determine voltage slope; using stock max voltage')
    else:
        raw = table.entries[0].volt
        model = 'constant'
        source = [table.entries[0]]
        warnings.append('only one OPP entry available; using its voltage')

    quantized = quantize_volt(round(raw))
    extrap_mhz = max(0, target_freq_khz - stock_max_freq) / 1000.0

    return VoltageEstimate(
        target_freq_khz=target_freq_khz,
        estimated_raw_uv=round(raw),
        quantized_uv=quantized,
        model=model,
        source_opps=source,
        slope_uv_per_mhz=slope_uv_per_mhz,
        stock_max_freq_khz=stock_max_freq,
        stock_max_volt_uv=stock_max_volt,
        extrapolation_mhz=extrap_mhz,
        warnings=warnings,
    )
