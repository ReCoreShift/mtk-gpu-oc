# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from dataclasses import dataclass, field
from typing import Optional
import os


@dataclass
class OppOverride:
    freq_mhz: int
    volt_mv: float


class ConfigMode:
    TOP = 'top'
    TOP_BOTTOM = 'top_bottom'
    FULL = 'full'


@dataclass
class OcConfig:
    max_freq_mhz: Optional[int] = None
    max_volt_mv: Optional[float] = None
    min_freq_mhz: Optional[int] = None
    min_volt_mv: Optional[float] = None
    opp_overrides: list[OppOverride] = field(default_factory=list)

    def mode(self) -> str:
        if self.opp_overrides:
            return ConfigMode.FULL
        if self.max_freq_mhz is not None and self.min_freq_mhz is not None:
            return ConfigMode.TOP_BOTTOM
        if self.max_freq_mhz is not None:
            return ConfigMode.TOP
        return ConfigMode.TOP


@dataclass
class BypassConfig:
    enabled: bool = True
    avs_freq_check: bool = True
    apply_adjust_probe: bool = True
    apply_adjust_avs: bool = True
    segment_adj: bool = True


@dataclass
class AppConfig:
    module_path: str = ''
    output_path: Optional[str] = None
    oc: OcConfig = field(default_factory=OcConfig)
    bypass: BypassConfig = field(default_factory=BypassConfig)


def _find_config(path: Optional[str]) -> Optional[str]:
    if path:
        if os.path.isfile(path):
            return path
        return None
    candidates = [
        'gpufreq-oc.toml',
        'mtk-gpu-oc.toml',
        os.path.expanduser('~/.config/mtk-gpu-oc/config.toml'),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def load_config(path: Optional[str] = None) -> Optional[AppConfig]:
    config_path = _find_config(path)
    if config_path is None:
        return None

    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            raise ImportError(
                'TOML parsing requires Python 3.11+ or the `tomli` package. '
                'Install with: pip install tomli'
            )

    with open(config_path, 'rb') as f:
        raw = tomllib.load(f)

    cfg = AppConfig()
    cfg.module_path = raw.get('module', {}).get('path', '')

    oc_raw = raw.get('oc', {})
    cfg.oc.max_freq_mhz = oc_raw.get('max_freq_mhz')
    cfg.oc.max_volt_mv = oc_raw.get('max_volt_mv')
    cfg.oc.min_freq_mhz = oc_raw.get('min_freq_mhz')
    cfg.oc.min_volt_mv = oc_raw.get('min_volt_mv')

    for entry in oc_raw.get('opp', []):
        cfg.oc.opp_overrides.append(OppOverride(
            freq_mhz=entry['freq_mhz'],
            volt_mv=entry.get('volt_mv', 0.0),
        ))

    bp_raw = raw.get('bypass', {})
    cfg.bypass.enabled = bp_raw.get('enabled', True)
    cfg.bypass.avs_freq_check = bp_raw.get('avs_freq_check', True)
    cfg.bypass.apply_adjust_probe = bp_raw.get('apply_adjust_probe', True)
    cfg.bypass.apply_adjust_avs = bp_raw.get('apply_adjust_avs', True)
    cfg.bypass.segment_adj = bp_raw.get('segment_adj', True)

    cfg.output_path = raw.get('output')

    return cfg


def config_to_patch_args(cfg: AppConfig) -> dict:
    result = {}
    if cfg.oc.max_freq_mhz:
        result['max_freq'] = cfg.oc.max_freq_mhz
    if cfg.oc.max_volt_mv:
        result['volt'] = cfg.oc.max_volt_mv
    if cfg.oc.min_freq_mhz:
        result['floor_freq'] = cfg.oc.min_freq_mhz
    if cfg.oc.min_volt_mv:
        result['floor_volt'] = cfg.oc.min_volt_mv
    if cfg.bypass.enabled is False:
        result['no_bypass'] = True
    if cfg.oc.opp_overrides:
        result['opp_overrides'] = cfg.oc.opp_overrides
    return result
