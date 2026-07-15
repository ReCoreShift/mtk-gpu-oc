# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import hashlib
import os
import sys

from . import elf
from . import profiles
from . import analysis as analysis_mod
from . import gpufreq
from . import config as config_mod
from . import compare as compare_mod
from .patch import PatchPlan, build_opp_patch_plan, build_code_patch_plan
from .verify import verify
from .voltage import estimate_voltage
from .opp import OppEntry, OPP_ENTRY_SIZE
from .gpufreq import DetectionStatus


def _format_mv(volt: int) -> str:
    return f'{volt / 100:.2f} mV'


def _format_mhz(freq: int) -> str:
    return f'{freq // 1000} MHz'


def cmd_inspect(args):
    result = analysis_mod.analyze_module(args.module)

    print(f'Module: {result["path"]}')
    print(f'  Size:   {result["file_size"]} bytes')
    print(f'  ELF:    {result["elf_class"]} {result["architecture"]} {result["endianness"]} endian')
    print(f'  Type:   {result["type"]}')
    print(f'  Name:   {result["module_name"]}')
    print(f'  BuildID: {result["build_id"][:40]}')
    print(f'  Profile: {result["profile"]}')
    print(f'  Status: {result["status"]}')
    print()

    if result['opp_table'] is not None:
        table = result['opp_table']
        fmin, fmax = table.frequency_range_mhz()
        vmin, vmax = table.voltage_range_mv()
        print(f'OPP Table:')
        print(f'  Symbol:  {result["opp_table_symbol"]}')
        print(f'  Section: {result["opp_table_section"]} +0x{result["opp_table_file_offset"] - result["opp_table_file_offset"]:x}')
        print(f'  Offset:  0x{result["opp_table_file_offset"]:x}')
        print(f'  Entries: {len(table)}')
        print(f'  Freq:    {fmin} - {fmax} MHz')
        print(f'  Volt:    {vmin:.2f} - {vmax:.2f} mV')
        print()

        if not args.quiet:
            print(f'  {"Idx":>3s}  {"Freq":>8s}  {"Volt":>9s}  {"VSram":>9s}  {"u3":>2s}  {"u4":>4s}')
            print(f'  {"---":>3s}  {"---":>8s}  {"---":>9s}  {"---":>9s}  {"---":>2s}  {"---":>4s}')
            for i, entry in enumerate(table.entries):
                print(f'  {i:3d}  {_format_mhz(entry.freq_khz):>8s}  {_format_mv(entry.volt):>9s}  {_format_mv(entry.vsram):>9s}  {entry.u3:2d}  {entry.u4:4d}')

    else:
        print('OPP Table: not found')

    print()

    if result['segment_adj_offset'] is not None:
        print(f'g_segment_adj:')
        print(f'  Offset: 0x{result["segment_adj_offset"]:x}')
        print(f'  Value:  {result["segment_adj_value"]}')
    else:
        print('g_segment_adj: not found')

    print()

    if result['patch_sites']:
        print('Patch Sites:')
        for site in result['patch_sites']:
            desc = site.get('description', '')
            status = site.get('status', 'present')
            offset = site.get('file_offset', 0)
            print(f'  [0x{offset:05x}] {site["name"]}: {desc} ({status})')
    else:
        print('Patch Sites: not detected (status may be UNSUPPORTED)')

    for w in result['warnings']:
        print(f'  WARN: {w}')


def cmd_compare(args):
    result = compare_mod.compare(args.stock, args.modified)

    print(f'Stock:    {result.stock_path}')
    print(f'  SHA-256: {result.stock_sha256}')
    print(f'Modified: {result.modified_path}')
    print(f'  SHA-256: {result.modified_sha256}')
    print(f'Total differing bytes: {result.total_differing_bytes}')
    print()

    if result.opp_changes:
        print(f'OPP Table Changes ({len(result.opp_changes)} entries affected):')
        print(f'  {"Idx":>3s}  {"Field":>12s}  {"Stock":>12s}  {"Modified":>12s}  {"Delta":>12s}')
        print(f'  {"---":>3s}  {"--------":>12s}  {"--------":>12s}  {"--------":>12s}  {"--------":>12s}')
        for idx, stock_e, mod_e in result.opp_changes[:10]:
            fd = f'{stock_e.freq_khz - mod_e.freq_khz:+d}' if stock_e.freq_khz != mod_e.freq_khz else ''
            vd = f'{stock_e.volt - mod_e.volt:+d}' if stock_e.volt != mod_e.volt else ''
            print(f'  {idx:3d}  {"frequency":>12s}  {_format_mhz(stock_e.freq_khz):>12s}  {_format_mhz(mod_e.freq_khz):>12s}  {fd:>12s}')
            if stock_e.volt != mod_e.volt:
                print(f'  {" ":3s}  {"voltage":>12s}  {_format_mv(stock_e.volt):>12s}  {_format_mv(mod_e.volt):>12s}  {vd:>12s}')
            if stock_e.vsram != mod_e.vsram:
                vsd = f'{stock_e.vsram - mod_e.vsram:+d}'
                print(f'  {" ":3s}  {"vsram":>12s}  {_format_mv(stock_e.vsram):>12s}  {_format_mv(mod_e.vsram):>12s}  {vsd:>12s}')
            if stock_e.u3 != mod_e.u3:
                print(f'  {" ":3s}  {"u3":>12s}  {stock_e.u3:>12d}  {mod_e.u3:>12d}')
            if stock_e.u4 != mod_e.u4:
                print(f'  {" ":3s}  {"u4":>12s}  {stock_e.u4:>12d}  {mod_e.u4:>12d}')
        if len(result.opp_changes) > 10:
            print(f'  ... ({len(result.opp_changes) - 10} more)')

    print()

    if result.code_patches:
        print(f'Code Patches ({len(result.code_patches)}):')
        for d in result.code_patches:
            print(f'  [0x{d.file_offset:05x}] {d.semantic_purpose}')

    if result.data_patches:
        print(f'Data Patches ({len(result.data_patches)}):')
        for d in result.data_patches:
            print(f'  [0x{d.file_offset:05x}] {d.semantic_purpose}')

    if result.rela_nullifications:
        print(f'Relocation Nullifications ({len(result.rela_nullifications)}):')
        for d in result.rela_nullifications:
            print(f'  [0x{d.file_offset:05x}] {d.semantic_purpose}')


def _apply_and_finish(args, data, plan, analysis_info, module_path=None):
    errors = plan.validate(bytes(data))
    if errors:
        print(f'ERROR: {len(errors)} validation error(s):', file=sys.stderr)
        for e in errors:
            print(f'  {e}', file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        for r in plan.records:
            tag = 'noop' if r.original == r.replacement else 'patch'
            print(f'  [{tag:5s}] 0x{r.file_offset:06x}  {r.name}')
        print('Dry run — no file written.')
        sys.exit(0)

    output = args.output or _default_output(module_path or args.module)
    patched = plan.apply(data)

    vr = verify(module_path or args.module, output, bytes(data), bytes(patched), plan)
    with open(output, 'wb') as f:
        f.write(patched)

    print(f'Output: {output}')
    print(f'  SHA-256: {vr.output_sha256}')
    print(f'  Bytes changed: {vr.changed_byte_count}')
    if vr.failures:
        for f in vr.failures:
            print(f'  WARNING: {f}', file=sys.stderr)


def _patch_full_table(args, cfg):
    """Apply full custom OPP table from config, plus bypass patches."""
    from .patch import PatchRecord, PatchType
    from .opp import OppEntry, u3_for, u4_for, VSRAM_FLOOR, OPP_ENTRY_SIZE
    from .voltage import quantize_volt

    module_path = args.module or cfg.module_path
    with open(module_path, 'rb') as f:
        data = bytearray(f.read())

    elff = elf.Elf64(bytes(data))
    profile = profiles.detect_profile(elff)
    if profile is None:
        print('ERROR: Unsupported module (no matching profile)', file=sys.stderr)
        sys.exit(1)

    analysis_info = analysis_mod.analyze_module(module_path)
    gpufreq_analysis = gpufreq.analyze(elff)

    if analysis_info['status'] == DetectionStatus.UNSUPPORTED:
        print('ERROR: Module analysis incomplete, cannot patch safely', file=sys.stderr)
        sys.exit(1)

    table = analysis_info['opp_table']
    if table is None or len(table) != len(cfg.oc.opp_overrides):
        print(f'ERROR: OPP table has {len(table)} entries, config has {len(cfg.oc.opp_overrides)}',
              file=sys.stderr)
        sys.exit(1)

    apply_bp = cfg.bypass.enabled
    print(f'Module: {module_path} ({analysis_info["file_size"]} bytes)')
    print(f'Profile: {profile.name}')
    print(f'Bypass: {"on" if apply_bp else "off"}')
    print(f'Custom OPP table ({len(cfg.oc.opp_overrides)} entries)')

    plan = build_code_patch_plan(profile, gpufreq_analysis) if apply_bp else PatchPlan()

    for i, override in enumerate(cfg.oc.opp_overrides):
        freq_khz = override.freq_mhz * 1000
        volt = quantize_volt(round(override.volt_mv * 100))
        new_entry = OppEntry(
            freq_khz=freq_khz, volt=volt,
            vsram=max(volt, VSRAM_FLOOR),
            u3=u3_for(freq_khz, profile.u3_threshold),
            u4=u4_for(freq_khz, profile.u4_t1, profile.u4_t2,
                      profile.u4_v1, profile.u4_v2, profile.u4_v3),
        )
        plan.add(PatchRecord(
            name=f'opp_{i:02d}',
            file_offset=table.file_offset + i * OPP_ENTRY_SIZE,
            original=table.entries[i].to_bytes(),
            replacement=new_entry.to_bytes(),
            section_name=table.section_name,
            patch_type=PatchType.DATA,
            semantic_original=str(table.entries[i]),
            semantic_replacement=str(new_entry),
        ))

    _apply_and_finish(args, data, plan, analysis_info, module_path)


def cmd_patch(args):
    cfg = config_mod.load_config(getattr(args, 'config', None))

    if cfg is not None and cfg.oc.opp_overrides:
        _patch_full_table(args, cfg)
        return

    with open(args.module, 'rb') as f:
        data = bytearray(f.read())

    elff = elf.Elf64(bytes(data))
    profile = profiles.detect_profile(elff)
    if profile is None:
        print('ERROR: Unsupported module (no matching profile)', file=sys.stderr)
        sys.exit(1)

    analysis_info = analysis_mod.analyze_module(args.module)
    elff = elf.Elf64(bytes(data))
    gpufreq_analysis = gpufreq.analyze(elff)

    if analysis_info['status'] == DetectionStatus.UNSUPPORTED:
        print('ERROR: Module analysis incomplete, cannot patch safely', file=sys.stderr)
        sys.exit(1)

    ceil_khz = args.max_freq * 1000 if args.max_freq else None
    ceil_volt = None
    floor_volt = None
    apply_bp = not args.no_bypass

    ve = None
    if ceil_khz is not None:
        table = analysis_info['opp_table']
        if table is None:
            print('ERROR: Cannot patch OPP table without detecting one', file=sys.stderr)
            sys.exit(1)

        explicit_uv = round(args.volt * 100) if args.volt is not None else None
        ve = estimate_voltage(table, ceil_khz, explicit_volt_uv=explicit_uv)
        ceil_volt = ve.quantized_uv

        if args.floor_volt is not None:
            floor_volt = round(args.floor_volt * 100)
        else:
            stock_floor_volt = table.entries[-1].volt
            floor_volt = stock_floor_volt

    print(f'Module: {args.module} ({analysis_info["file_size"]} bytes)')
    print(f'Profile: {profile.name}')
    print(f'Bypass: {"on" if apply_bp else "off"}')
    if ve is not None:
        print(f'OC: {ve.target_freq_khz // 1000} MHz ceiling')
        print(f'  Voltage model: {ve.model} ({ve.quantized_mv:.2f} mV, slope={ve.slope_uv_per_mhz:.1f} uV/MHz)')
        if ve.extrapolation_mhz > 0:
            print(f'  Extrapolation: +{ve.extrapolation_mhz:.0f} MHz beyond stock max')

    plan = build_code_patch_plan(profile, gpufreq_analysis) if apply_bp else PatchPlan()

    if ceil_khz is not None and analysis_info['opp_table'] is not None:
        opp_plan = build_opp_patch_plan(profile, analysis_info['opp_table'], ceil_khz, ceil_volt,
                                        floor_volt=floor_volt)
        for r in opp_plan.records:
            plan.add(r)

    _apply_and_finish(args, data, plan, analysis_info, args.module)


def cmd_verify(args):
    with open(args.original, 'rb') as f:
        orig = f.read()
    with open(args.patched, 'rb') as f:
        patched = f.read()

    vr = verify(args.original, args.patched, orig, patched)

    print(f'Original: {args.original}')
    print(f'  SHA-256: {vr.input_sha256}')
    print(f'Patched:  {args.patched}')
    print(f'  SHA-256: {vr.output_sha256}')
    print(f'Size:     {vr.input_size} bytes')
    print(f'Changed:  {vr.changed_byte_count} bytes')
    print()

    for f in vr.failures:
        print(f'WARNING: {f}')

    if vr.unexpected_changes:
        print(f'Unexpected changes ({len(vr.unexpected_changes)}):')
        for off, orig_b, new_b in vr.unexpected_changes[:20]:
            print(f'  0x{off:06x}: {orig_b.hex()} -> {new_b.hex()}')

    print(f'All checks: {"PASS" if not vr.failures else f"FAIL ({len(vr.failures)})"}')


def _default_output(input_path: str) -> str:
    base = os.path.basename(input_path)
    stem, ext = (base.rsplit('.', 1) + [''])[:2]
    out = f"{stem}_OC.{ext}" if ext else f"{stem}_OC"
    return os.path.join(os.path.dirname(input_path) or '.', out)


def main():
    ap = argparse.ArgumentParser(
        description='MediaTek GPUfreq analysis and patching tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('--version', action='version', version='mtk-gpu-oc 0.1.0')
    ap.add_argument('--config', metavar='FILE',
                    help='Path to TOML config file (default: gpufreq-oc.toml)')

    sub = ap.add_subparsers(dest='command', required=True)

    p_inspect = sub.add_parser('inspect', help='Analyze a GPUfreq kernel module')
    p_inspect.add_argument('module', nargs='?', help='Path to .ko file (can come from config)')
    p_inspect.add_argument('--quiet', '-q', action='store_true', help='Suppress OPP table dump')
    p_inspect.set_defaults(func=cmd_inspect)

    p_compare = sub.add_parser('compare', help='Compare stock and modified modules')
    p_compare.add_argument('stock', help='Stock (original) .ko file')
    p_compare.add_argument('modified', help='Modified (OC) .ko file')
    p_compare.set_defaults(func=cmd_compare)

    p_patch = sub.add_parser('patch', help='Apply overclock patches')
    p_patch.add_argument('module', nargs='?', help='Stock .ko file (can come from config)')
    p_patch.add_argument('--max-freq', type=int, metavar='MHZ',
                         help='GPU ceiling frequency in MHz')
    p_patch.add_argument('--volt', type=float, metavar='MV',
                         help='Ceiling voltage in mV')
    p_patch.add_argument('--floor-volt', type=float, metavar='MV',
                         help='Floor voltage in mV')
    p_patch.add_argument('--no-bypass', action='store_true',
                         help='Skip code bypass patches (OPP only)')
    p_patch.add_argument('--output', '-o', help='Output path')
    p_patch.add_argument('--dry-run', '-n', action='store_true',
                         help='Show plan without writing')
    p_patch.set_defaults(func=cmd_patch)

    p_verify = sub.add_parser('verify', help='Verify patched module')
    p_verify.add_argument('original', help='Original .ko file')
    p_verify.add_argument('patched', help='Patched .ko file')
    p_verify.set_defaults(func=cmd_verify)

    args = ap.parse_args()

    cfg = config_mod.load_config(getattr(args, 'config', None))
    if cfg is not None:
        if not getattr(args, 'module', None) and cfg.module_path:
            args.module = cfg.module_path
        if hasattr(args, 'output') and not args.output:
            args.output = cfg.output_path
        if hasattr(args, 'no_bypass') and not args.no_bypass:
            args.no_bypass = not cfg.bypass.enabled
        if hasattr(args, 'max_freq') and args.max_freq is None and cfg.oc.max_freq_mhz:
            args.max_freq = cfg.oc.max_freq_mhz
        if hasattr(args, 'volt') and args.volt is None and cfg.oc.max_volt_mv:
            args.volt = cfg.oc.max_volt_mv

    args.func(args)


if __name__ == '__main__':
    main()
