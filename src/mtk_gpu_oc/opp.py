# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import struct
from dataclasses import dataclass, field
from typing import Optional


OPP_ENTRY_SIZE = 24
OPP_FIELD_NAMES = ['freq_khz', 'volt', 'vsram', 'u3', 'u4', 'u5']

VSRAM_FLOOR = 75000
PMIC_STEP = 625
OPP_VOLT_MIN = 50000
OPP_VOLT_MAX = 120000
OPP_FREQ_MIN = 200000
OPP_FREQ_MAX = 2_000_000


@dataclass
class OppEntry:
    freq_khz: int
    volt: int
    vsram: int
    u3: int
    u4: int
    u5: int = 0

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> 'OppEntry':
        fields = struct.unpack_from('<6I', data, offset)
        return cls(*fields)

    def to_bytes(self) -> bytes:
        return struct.pack('<6I', self.freq_khz, self.volt, self.vsram, self.u3, self.u4, self.u5)

    @property
    def freq_mhz(self) -> int:
        return self.freq_khz // 1000

    @property
    def volt_mv(self) -> float:
        return self.volt / 100.0

    @property
    def vsram_mv(self) -> float:
        return self.vsram / 100.0

    def __repr__(self) -> str:
        return f"OppEntry(freq={self.freq_mhz}MHz, volt={self.volt_mv:.2f}mV, vsram={self.vsram_mv:.2f}mV, u3={self.u3}, u4={self.u4})"


@dataclass
class OppTable:
    entries: list[OppEntry]
    file_offset: int
    section_name: str = ''
    symbol_name: str = ''

    @classmethod
    def from_bytes(cls, data: bytes, offset: int, count: int) -> 'OppTable':
        entries = []
        for i in range(count):
            entries.append(OppEntry.from_bytes(data, offset + i * OPP_ENTRY_SIZE))
        return cls(entries=entries, file_offset=offset)

    def to_bytes(self) -> bytes:
        return b''.join(e.to_bytes() for e in self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __getitem__(self, idx: int) -> OppEntry:
        return self.entries[idx]

    def is_descending_frequency(self) -> bool:
        for i in range(1, len(self.entries)):
            if self.entries[i].freq_khz >= self.entries[i - 1].freq_khz:
                return False
        return True

    def is_ascending_frequency(self) -> bool:
        for i in range(1, len(self.entries)):
            if self.entries[i].freq_khz <= self.entries[i - 1].freq_khz:
                return False
        return True

    def frequency_range_mhz(self) -> tuple[int, int]:
        freqs = [e.freq_mhz for e in self.entries]
        return (min(freqs), max(freqs))

    def voltage_range_mv(self) -> tuple[float, float]:
        volts = [e.volt_mv for e in self.entries]
        return (min(volts), max(volts))


def detect_opp_table(data: bytes, offset: int, max_entries: int = 64) -> Optional[OppTable]:
    if offset + OPP_ENTRY_SIZE > len(data):
        return None

    first = OppEntry.from_bytes(data, offset)
    if not (200_000 <= first.freq_khz <= 2_000_000):
        return None
    if first.freq_khz % 1000 != 0:
        return None
    if not (50000 <= first.volt <= 120000):
        return None
    if first.u3 not in (1, 2):
        return None
    if first.u4 not in (625, 1250, 1875):
        return None

    entries = [first]
    for i in range(1, max_entries):
        e_off = offset + i * OPP_ENTRY_SIZE
        if offset + (i + 1) * OPP_ENTRY_SIZE > len(data):
            break
        entry = OppEntry.from_bytes(data, e_off)
        if entry.freq_khz == 0 and entry.volt == 0:
            break
        if entry.freq_khz > first.freq_khz:
            break
        if not (50000 <= entry.volt <= 120000):
            break
        entries.append(entry)

    if len(entries) < 2:
        return None

    table = OppTable(entries=entries, file_offset=offset)
    if not table.is_descending_frequency() and not table.is_ascending_frequency():
        return None

    return table


def round_volt_mv(mv: float) -> int:
    return round(mv * 100 / PMIC_STEP) * PMIC_STEP


def u3_for(freq_khz: int, threshold: int = 948000) -> int:
    return 1 if freq_khz >= threshold else 2


def u4_for(freq_khz: int, t1: int = 835000, t2: int = 596000,
           v1: int = 1875, v2: int = 1250, v3: int = 625) -> int:
    if freq_khz >= t1:
        return v1
    if freq_khz >= t2:
        return v2
    return v3


OPP_VOLT_MIN = 50000
OPP_VOLT_MAX = 120000
OPP_FREQ_MIN = 200000
OPP_FREQ_MAX = 2_000_000


def check_opp_invariants(table: OppTable) -> list[str]:
    errors = []
    if len(table.entries) < 1:
        errors.append('OPP table is empty')
        return errors

    for i, e in enumerate(table.entries):
        if e.freq_khz < OPP_FREQ_MIN or e.freq_khz > OPP_FREQ_MAX:
            errors.append(f'OPP {i}: freq {e.freq_khz} kHz outside range [{OPP_FREQ_MIN}, {OPP_FREQ_MAX}]')
        if e.freq_khz % 1000 != 0:
            errors.append(f'OPP {i}: freq {e.freq_khz} kHz not aligned to 1 MHz')
        if e.volt < OPP_VOLT_MIN or e.volt > OPP_VOLT_MAX:
            errors.append(f'OPP {i}: volt {e.volt} outside range [{OPP_VOLT_MIN}, {OPP_VOLT_MAX}]')
        if e.volt % PMIC_STEP != 0:
            errors.append(f'OPP {i}: volt {e.volt} not aligned to PMIC step {PMIC_STEP}')
        if e.vsram < e.volt:
            errors.append(f'OPP {i}: vsram {e.vsram} < volt {e.volt}')
        if e.u3 not in (1, 2):
            errors.append(f'OPP {i}: u3={e.u3} not in (1, 2)')
        if e.u4 not in (625, 1250, 1875):
            errors.append(f'OPP {i}: u4={e.u4} not in (625, 1250, 1875)')

    if not table.is_descending_frequency():
        errors.append('frequencies are not strictly descending')
    if not all(table.entries[i].volt >= table.entries[i + 1].volt for i in range(len(table.entries) - 1)):
        errors.append('voltages are not non-increasing')

    return errors
