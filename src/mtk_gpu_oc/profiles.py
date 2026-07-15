# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from dataclasses import dataclass, field
from typing import Optional

from . import elf
from .opp import OppTable


@dataclass
class PlatformProfile:
    name: str
    target_modules: list[str]
    opp_symbol: str
    segment_adj_symbol: str
    expected_opp_count: int
    known_stock_hash: str
    known_oc_hash: str

    avs_freq_check_pattern: bytes = b''
    avs_freq_check_nop: bytes = b''
    apply_adjust_probe_pattern: bytes = b''
    apply_adjust_probe_nop: bytes = b''
    apply_adjust_avs_pattern: bytes = b''
    apply_adjust_avs_nop: bytes = b''
    segment_adj_stock_bytes: bytes = b''
    segment_adj_patched_bytes: bytes = b''

    u3_threshold: int = 948000
    u4_t1: int = 835000
    u4_t2: int = 596000
    u4_v1: int = 1875
    u4_v2: int = 1250
    u4_v3: int = 625
    vsram_floor: int = 75000
    pmic_step: int = 625
    floor_freq_khz: int = 390000
    entry_size: int = 24


MT6789: PlatformProfile = PlatformProfile(
    name='mt6789',
    target_modules=['mtk_gpufreq_mt6789.ko'],
    opp_symbol='g_default_gpu',
    segment_adj_symbol='g_segment_adj',
    expected_opp_count=45,
    known_stock_hash='ba5469f525224aa7bfda6e58b58e7aaaf9d0e6e25b76faddd4cb9e64e28a0b43',
    known_oc_hash='1bf51cdd7dc714d4c4bdf5d25d12cdf293bf3a27b537d8726d57014f6c08527b',

    avs_freq_check_pattern=bytes.fromhex('9f 00 05 6b 21 22 00 54'),
    avs_freq_check_nop=bytes.fromhex('9f 00 05 6b 1f 20 03 d5'),
    apply_adjust_probe_pattern=bytes.fromhex('e0 03 14 aa e1 03 13 2a 00 00 00 94'),
    apply_adjust_probe_nop=bytes.fromhex('e0 03 14 aa e1 03 13 2a 1f 20 03 d5'),
    apply_adjust_avs_pattern=bytes.fromhex('61 00 80 52 e0 03 13 aa 00 00 00 94'),
    apply_adjust_avs_nop=bytes.fromhex('61 00 80 52 e0 03 13 aa 1f 20 03 d5'),
    segment_adj_stock_bytes=bytes.fromhex('19 00 00 00 00 00 00 00 e8 fd 00 00'),
    segment_adj_patched_bytes=bytes.fromhex('00 00 00 00 00 00 00 00 e8 fd 00 00'),
)


def detect_profile(elf_file: elf.Elf64) -> Optional[PlatformProfile]:
    candidates = [MT6789]
    for profile in candidates:
        modinfo = elf_file.find_section('.modinfo')
        if modinfo is not None:
            data = elf_file.raw()
            text = data[modinfo.offset:modinfo.offset + modinfo.size]
            for target in profile.target_modules:
                if target.encode() in text:
                    return profile

    sym = elf_file.find_symbol('g_default_gpu')
    if sym is not None and sym.size == 1080:
        return MT6789

    return None
