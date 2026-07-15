# Legacy Script Analysis: `patch_gpufreq.py`

## Overview

The monolithic script `patch_gpufreq.py` (746 lines) is a GPU OPP table patcher
for `mtk_gpufreq_mt6789.ko` targeting the MediaTek MT6789 platform.

It was written as a working research tool. This document analyzes its actual
behavior, verifies its claims against two real binaries, and inventories every
operation for reconstruction.

## Source Files

| File | SHA-256 | Role |
|---|---|---|
| `mtk_gpufreq_mt6789.ko` (workspace) | `ba5469f525224aa7bfda6e58b58e7aaaf9d0e6e25b76faddd4cb9e64e28a0b43` | Stock module (unmodified) |
| `mtk_gpufreq_mt6789.ko` (device vendor_dlkm) | `1bf51cdd7dc714d4c4bdf5d25d12cdf293bf3a27b537d8726d57014f6c08527b` | Modified OC module (running on device) |

Both are same size (196672 bytes) and ELF64 relocatable AArch64, not stripped.

## Binary Facts (Verified)

### ELF Header

- Type: REL (relocatable)
- Machine: AArch64 (little-endian)
- Section headers: 34, starting at file offset 0x2f7c0
- No program headers (kernel module)
- Not stripped

### Key Sections

| Section | File Offset | Size | Flags |
|---|---|---|---|
| `.text` | 0x1000 | 0x9018 | AX |
| `.data` | 0xb778 | 0x1538 | WA |
| `.rodata` | 0xccb0 | 0x1be4 | AMS |
| `.rela.text.*` | 0xfe88 | 0xd350 | I |
| `.symtab` | 0x242e0 | 0x7da0 | - |

### Key Symbols (in `.data`)

| Symbol | Section Offset | File Offset | Size | Description |
|---|---|---|---|---|
| `g_default_gpu` | .data+0x598 | 0xbd10 | 1080 | OPP table (45×24 bytes) |
| `g_aging_table` | .data+0x9d0 | 0xc148 | 720 | Aging table (30×24 bytes) |
| `platform_ap_fp.46` | .data+0xca0 | 0xd418 | 480 | Platform freq/volt points |
| `platform_eb_fp.47` | .data+0xe80 | 0xdff8 | 480 | Platform freq/volt points |
| `g_avs_adj` | .data+0x1060 | 0xbfd8 | 60 | AVS adjustment table |
| `g_segment_adj` | .data+0x109c | 0xc814 | 320 | Segment adjustment table |

### Key Symbols (in `.text`)

| Symbol | Value | Size | Description |
|---|---|---|---|
| `__gpufreq_pdrv_probe` | 0x74f4 | 3984 | Driver probe function |
| `__gpufreq_apply_adjust` | 0x84dc | 340 | Efuse calibration overwrite |
| `__gpufreq_avs_adjustment` | 0x8630 | 1344 | AVS adjustment function |
| `__gpufreq_init_opp_idx` | 0x8b74 | 560 | OPP index initialization |

## Old Script's OPP Table Structure (Confirmed)

The script defines a 24-byte OPP entry format (little-endian u32×6):

```
[freq_khz][volt_10uv][vsram_10uv][u3][u4][u5]
```

- `freq_khz`: Frequency in kHz (e.g., 1100000 = 1100 MHz)
- `volt_10uv`: Voltage in 10 μV units (e.g., 90000 = 900.00 mV)
- `vsram_10uv`: SRAM voltage in 10 μV units (same as volt, floor 75000)
- `u3`: 1 when freq >= 948 MHz, else 2
- `u4`: 1875 when freq >= 835 MHz, 1250 when >= 596 MHz, 625 below
- `u5`: Always 0

The stock table at g_default_gpu (file offset 0xbd10) has exactly 45 entries
matching STOCK_TABLE in the script. **Confirmed: all 45 entries match byte-for-byte**.

## Patch Operations (All 4 Verified Against Device Module)

The script performs 4 categories of modification:

### 1. avs_freq_check_bypass

| Property | Value |
|---|---|
| Location | `__gpufreq_avs_adjustment` +0xcc (file 0x96f8) |
| Stock bytes | `9f 00 05 6b 21 22 00 54` |
| Replacement | `9f 00 05 6b 1f 20 03 d5` |
| Effect | `CMP W5, W4; B.NE abort` → `CMP W5, W4; NOP` |
| Purpose | Skip efuse frequency ≠ OPP table frequency abort |
| **Verified in modified module** | `21 22 00 54` → `1f 20 03 d5` at file offset 0x96fc |

### 2. apply_adjust_probe_bypass

| Property | Value |
|---|---|
| Location | `__gpufreq_pdrv_probe` +0x89c (file 0x8d9c) |
| Stock bytes | `e0 03 14 aa e1 03 13 2a 00 00 00 94` |
| Replacement | `e0 03 14 aa e1 03 13 2a 1f 20 03 d5` |
| Effect | `MOV X0, X20; MOV W1, W19; BL __gpufreq_apply_adjust` → NOP |
| Purpose | Prevent efuse calibration overwriting OPP table (probe path) |
| **Verified in modified module** | `00 00 00 94` → `1f 20 03 d5` at file offset 0x8da4 |

### 3. apply_adjust_avs_bypass

| Property | Value |
|---|---|
| Location | `__gpufreq_avs_adjustment` +0x2c8 (file 0x98f0) |
| Stock bytes | `61 00 80 52 e0 03 13 aa 00 00 00 94` |
| Replacement | `61 00 80 52 e0 03 13 aa 1f 20 03 d5` |
| Effect | `MOV W1, #3; MOV X0, X19; BL __gpufreq_apply_adjust` → NOP |
| Purpose | Prevent efuse calibration overwriting OPP table (AVS path) |
| **Verified in modified module** | `00 00 00 94` → `1f 20 03 d5` at file offset 0x98f8 |

### 4. segment_adj_data

| Property | Value |
|---|---|
| Location | `g_segment_adj` (file offset 0xc814, .data+0x109c) |
| Stock bytes | `19 00 00 00 00 00 00 00 e8 fd 00 00` |
| Replacement | `00 00 00 00 00 00 00 00 e8 fd 00 00` |
| Effect | g_segment_adj[0] = 25 → 0 (first u32 of structure) |
| Purpose | Remove gpuppm GPU ceiling (gpuppm_init reads this as OPP index cap) |
| **Verified in modified module** | value 25 → 0 at file offset 0xc814 |

### Relocation Nullification

After NOP'ing the two `BL __gpufreq_apply_adjust` calls, the script nullifies
the corresponding `.rela.text.*` entries by setting r_info to 0. This prevents
the kernel module loader from rejecting the NOP during relocation validation.

**Verified in modified module**: Two .rela entries nullified:
- Rela[1891] @ file 0x1afd0 (targeting .text+0x7da4): r_info zeroed
- Rela[2116] @ file 0x1c4e8 (targeting .text+0x88f8): r_info zeroed

## OPP Table Modification Strategy

### Stock Frequencies and Voltages

```
Entry  0: 1100 MHz  900.00 mV
Entry 44:  390 MHz  675.00 mV
```

Monotonically decreasing frequencies with corresponding voltages.
45 entries, uniform 24-byte stride.

### Modified Module (1200 MHz OC)

```
Entry  0: 1200 MHz  800.00 mV
Entry 44:  390 MHz  593.75 mV
```

The modified module uses a linear interpolation strategy from the stock
frequency ladder, scaling frequencies proportionally from 1200 MHz down
to 390 MHz. Voltages use a linear interpolation between the new ceiling
voltage (800 mV) and floor voltage (593.75 mV).

### Comparison with Old Script's OC_TABLE

The script contains a hardcoded `OC_TABLE` credited to @raffprjkt.
This table differs from the actual modified module's values:

- Entry 0 is identical (1200 MHz / 800.00 mV)
- All intermediate entries differ in both frequency and voltage
- The floor voltage matches (593.75 mV), but the floor frequency differs
  (545 MHz in OC_TABLE vs 390 MHz in actual module)

**Conclusion**: The device's modified module uses a different OC curve than
the script's OC_TABLE. The script's table was a reference from a different
source/test.

### Required Changes per OPP Entry

For every OPP entry changed:
- `freq_khz` (4 bytes)
- `volt` (4 bytes)
- `vsram` (4 bytes, set to max(volt, 75000))
- Potentially `u3` (depends on whether new freq crosses 948 MHz boundary)
- `u4` (depends on whether new freq crosses 835 MHz or 596 MHz boundaries)
- `u5` (always 0)

Total OPP modification: ~606 bytes in the modified module.

## Assumptions Specific to MT6789 Binary

1. `g_default_gpu` at .data+0x598 (file 0xbd10) — **must be detected structurally**
2. `g_segment_adj` at .data+0x109c (file 0xc814) — **must be detected via symbol**
3. 45 OPP entries × 24 bytes each — could vary per platform
4. OPP entry field semantics (u3, u4 threshold values) — likely platform-specific
5. AVS adjustment function boundaries — different layout in different builds
6. Relocation section naming (`.rela.text.gpufreq_set_history_state`) — build-specific
7. `__gpufreq_apply_adjust` at sym +0x84dc — function address varies
8. 196672 bytes file size — different builds produce different sizes

## Experimental/Unsupported Claims

1. Script comment mentions `segment_cap_bypass` (b.hs→b.al in `init_opp_idx`)
   as intentionally NOT applied because it causes bootloop. **Confirmed excluded**.

2. Script comment claims 0xbc10 is "OC firmware" OPP offset. **Debunked** for this
   binary — 0xbc10 does NOT contain a valid OPP table. May refer to a different
   module build.

3. Script's `--offset` flag bypasses pattern matching for re-patching.
   **Unnecessary** with proper structural detection.

4. The `write_opp_table_at()` function duplicates `build_patches()` logic
   with direct offset writes. **Duplicated code**.

## Semantic Change Inventory (Stock vs Device Modified)

| Region | File Range | Bytes Changed | Semantic Purpose |
|---|---|---|---|
| `.text` (probe) | 0x8da4-0x8da7 | 4 | NOP `BL __gpufreq_apply_adjust` |
| `.text` (AVS check) | 0x96fc-0x96ff | 4 | NOP `B.NE` efuse freq check |
| `.text` (AVS apply) | 0x98f8-0x98fb | 4 | NOP `BL __gpufreq_apply_adjust` |
| `.data` (OPP table) | 0xbd10-0xc136 | ~606 | Frequencies and voltages |
| `.data` (segment) | 0xc814 | 1 | g_segment_adj: 25 → 0 |
| `.rela.text.*` | 0x1afd8-0x1afe0 | 6 | Nullify r_info for probe BL |
| `.rela.text.*` | 0x1c4f0-0x1c4f8 | 6 | Nullify r_info for AVS BL |

Total: 133 individual byte ranges, 304 bytes changed.

## Validation Notes

- No module signature detection implemented in the script
- No modversion or vermagic checks
- No decompression handling
- Output file is written with `open().write()` — no atomic write
- No SHA-256 verification of output
- The script does not explicitly check for already-patched modules
- Pattern-based matching works because the binary is not stripped and
  patterns are 4-12 bytes with low collision probability
