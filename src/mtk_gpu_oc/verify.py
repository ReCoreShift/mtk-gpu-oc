# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import hashlib
from dataclasses import dataclass, field
from typing import Optional

from .patch import PatchPlan
from .opp import OppTable, OPP_ENTRY_SIZE, check_opp_invariants


@dataclass
class VerificationResult:
    input_path: str = ''
    output_path: str = ''
    input_sha256: str = ''
    output_sha256: str = ''
    input_size: int = 0
    output_size: int = 0
    size_match: bool = True
    changed_byte_count: int = 0
    only_intended_changes: bool = True
    unexpected_changes: list[tuple[int, bytes, bytes]] = field(default_factory=list)
    missing_patches: list[str] = field(default_factory=list)
    elf_magic_preserved: bool = True
    opp_invariant_errors: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def verify(input_path: str, output_path: str,
           input_data: bytes, output_data: bytes,
           plan: Optional[PatchPlan] = None) -> VerificationResult:
    result = VerificationResult()
    result.input_path = input_path
    result.output_path = output_path
    result.input_sha256 = hashlib.sha256(input_data).hexdigest()
    result.output_sha256 = hashlib.sha256(output_data).hexdigest()
    result.input_size = len(input_data)
    result.output_size = len(output_data)

    if len(input_data) != len(output_data):
        result.size_match = False
        result.failures.append(f'size mismatch: {len(input_data)} vs {len(output_data)}')

    if input_data[:4] != b'\x7fELF' or output_data[:4] != b'\x7fELF':
        result.elf_magic_preserved = False
        result.failures.append('ELF magic corrupted')

    diff_count = 0
    for i in range(min(len(input_data), len(output_data))):
        if input_data[i] != output_data[i]:
            diff_count += 1

    result.changed_byte_count = diff_count

    if plan is not None:
        intended_offsets = set()
        for r in plan.records:
            for off in range(r.file_offset, r.file_offset + len(r.replacement)):
                intended_offsets.add(off)

        for i in range(min(len(input_data), len(output_data))):
            if input_data[i] != output_data[i]:
                if i not in intended_offsets:
                    result.unexpected_changes.append((i, bytes([input_data[i]]), bytes([output_data[i]])))

        result.only_intended_changes = len(result.unexpected_changes) == 0
        if result.unexpected_changes:
            result.failures.append(f'{len(result.unexpected_changes)} unexpected byte changes')

    if diff_count == 0:
        result.failures.append('no bytes changed (patch may have no effect)')

    if result.input_sha256 == result.output_sha256:
        result.failures.append('SHA-256 unchanged')

    # Verify output OPP table integrity if detectable
    try:
        from . import elf as elf_mod
        elff = elf_mod.Elf64(output_data)
        result.elf_magic_preserved = elff is not None  # noqa

        # Try to detect OPP table in output and check invariants
        from .gpufreq import analyze as gf_analyze
        gf = gf_analyze(elff)
        if gf.opp_table is not None:
            inv_errs = check_opp_invariants(gf.opp_table)
            result.opp_invariant_errors = inv_errs
            for e in inv_errs:
                result.failures.append(f'OPP invariant in output: {e}')
    except Exception:
        pass

    return result
