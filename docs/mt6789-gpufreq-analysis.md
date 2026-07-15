# MT6789 GPUfreq Binary Analysis

## Module Identity

- **File**: `mtk_gpufreq_mt6789.ko`
- **SHA-256 (stock)**: `ba5469f525224aa7bfda6e58b58e7aaaf9d0e6e25b76faddd4cb9e64e28a0b43`
- **SHA-256 (modified)**: `1bf51cdd7dc714d4c4bdf5d25d12cdf293bf3a27b537d8726d57014f6c08527b`
- **ELF**: 64-bit LSB relocatable, AArch64, not stripped
- **BuildID**: `7c14c222025c4ffdecf69f3d624dd8fac76a590d`
- **Size**: 196672 bytes (both stock and modified)

## GPUFreq Data Structures

### OPP Entry (24 bytes)

```
Offset  Size  Field         Description
0x00    4     freq_khz      Frequency in kHz (LE u32)
0x04    4     volt_10uv     Core voltage in 10μV units (LE u32)
0x08    4     vsram_10uv    SRAM voltage in 10μV units (LE u32)
0x0c    4     u3            Post-divider or mode flag: 1 if freq >= 948 MHz, else 2
0x10    4     u4            Power or current limit: 1875/1250/625 depending on freq range
0x14    4     u5            Unused/reserved: always 0
```

#### Field Semantics

**`volt` / `vsram`**: Units are 10 microvolts (10μV). To convert:
- 90000 = 900.00 mV
- PMIC step size: 625 (6.25 mV)
- VSRAM floor: 75000 (750.00 mV)

**`u3`**: Binary flag:
- 1 when freq >= 948 MHz
- 2 when freq < 948 MHz

**`u4`**: Three-tier discrete value:
- 1875 when freq >= 835 MHz
- 1250 when 596 MHz <= freq < 835 MHz
- 625 when freq < 596 MHz

**`u5`**: Always observed as 0. Reserved padding or unused field.

### g_default_gpu (OPP Table)

| Property | Value |
|---|---|
| Symbol | `g_default_gpu` |
| Section | `.data` +0x598 |
| File offset | 0xbd10 |
| Entry count | 45 |
| Entry size | 24 bytes |
| Total size | 1080 bytes |

45 entries in descending frequency order (1100 MHz → 390 MHz stock).

### g_segment_adj

| Property | Value |
|---|---|
| Symbol | `g_segment_adj` |
| Section | `.data` +0x109c |
| File offset | 0xc814 |
| Size | 320 bytes |
| Stock value | 25 (first u32: segment OPP index ceiling) |

Structure appears to be an array of (segment_index, reserved, voltage_limit, ...)
tuples. The first u32 is the cumulative OPP index limit read by `gpuppm_init`.

### g_aging_table

| Property | Value |
|---|---|
| Symbol | `g_aging_table` |
| Section | `.data` +0x9d0 |
| File offset | 0xc148 |
| Size | 720 bytes (30 × 24) |

Contains `u4`-like values (1875, 1250, 625). Aging compensation data.

### g_avs_adj

| Property | Value |
|---|---|
| Symbol | `g_avs_adj` |
| Section | `.data` +0x1060 |
| File offset | 0xbfd8 |
| Size | 60 bytes |

Contains voltage adjustment values indexed by OPP.

## Stock Frequencies and Voltages

```
Entry 00: 1100 MHz  900.00 mV
Entry 01: 1086 MHz  893.75 mV
Entry 02: 1072 MHz  887.50 mV
Entry 03: 1058 MHz  881.25 mV
Entry 04: 1045 MHz  875.00 mV
Entry 05: 1031 MHz  868.75 mV
Entry 06: 1017 MHz  862.50 mV
Entry 07: 1003 MHz  856.25 mV
Entry 08:  990 MHz  850.00 mV
Entry 09:  976 MHz  843.75 mV
Entry 10:  962 MHz  831.25 mV
Entry 11:  948 MHz  825.00 mV
Entry 12:  935 MHz  818.75 mV
Entry 13:  921 MHz  812.50 mV
Entry 14:  907 MHz  806.25 mV
Entry 15:  893 MHz  800.00 mV
Entry 16:  880 MHz  793.75 mV
Entry 17:  868 MHz  787.50 mV
Entry 18:  857 MHz  781.25 mV
Entry 19:  846 MHz  775.00 mV
Entry 20:  835 MHz  768.75 mV
Entry 21:  823 MHz  762.50 mV
Entry 22:  812 MHz  756.25 mV
Entry 23:  801 MHz  756.25 mV
Entry 24:  790 MHz  750.00 mV
Entry 25:  778 MHz  743.75 mV
Entry 26:  767 MHz  737.50 mV
Entry 27:  756 MHz  731.25 mV
Entry 28:  745 MHz  725.00 mV
Entry 29:  733 MHz  718.75 mV
Entry 30:  722 MHz  712.50 mV
Entry 31:  711 MHz  706.25 mV
Entry 32:  700 MHz  700.00 mV
Entry 33:  674 MHz  700.00 mV
Entry 34:  648 MHz  700.00 mV
Entry 35:  622 MHz  693.75 mV
Entry 36:  596 MHz  693.75 mV
Entry 37:  570 MHz  693.75 mV
Entry 38:  545 MHz  687.50 mV
Entry 39:  519 MHz  687.50 mV
Entry 40:  493 MHz  687.50 mV
Entry 41:  467 MHz  681.25 mV
Entry 42:  441 MHz  681.25 mV
Entry 43:  415 MHz  681.25 mV
Entry 44:  390 MHz  675.00 mV
```

## Modified Module OC Values (1200 MHz ceiling)

```
Entry 00: 1200 MHz  800.00 mV
Entry 01: 1184 MHz  793.75 mV
Entry 02: 1168 MHz  793.75 mV
Entry 03: 1152 MHz  787.50 mV
Entry 04: 1137 MHz  781.25 mV
Entry 05: 1121 MHz  781.25 mV
Entry 06: 1105 MHz  775.00 mV
Entry 07: 1089 MHz  768.75 mV
Entry 08: 1075 MHz  768.75 mV
Entry 09: 1059 MHz  762.50 mV
Entry 10: 1043 MHz  762.50 mV
Entry 11: 1027 MHz  756.25 mV
Entry 12: 1012 MHz  750.00 mV
Entry 13:  996 MHz  750.00 mV
Entry 14:  980 MHz  743.75 mV
Entry 15:  964 MHz  737.50 mV
Entry 16:  949 MHz  737.50 mV
Entry 17:  935 MHz  731.25 mV
Entry 18:  923 MHz  731.25 mV
Entry 19:  910 MHz  725.00 mV
Entry 20:  898 MHz  725.00 mV
Entry 21:  884 MHz  718.75 mV
Entry 22:  871 MHz  718.75 mV
Entry 23:  859 MHz  712.50 mV
Entry 24:  846 MHz  712.50 mV
Entry 25:  833 MHz  706.25 mV
Entry 26:  820 MHz  706.25 mV
Entry 27:  808 MHz  700.00 mV
Entry 28:  795 MHz  700.00 mV
Entry 29:  781 MHz  693.75 mV
Entry 30:  769 MHz  687.50 mV
Entry 31:  756 MHz  687.50 mV
Entry 32:  744 MHz  681.25 mV
Entry 33:  714 MHz  675.00 mV
Entry 34:  684 MHz  668.75 mV
Entry 35:  655 MHz  662.50 mV
Entry 36:  625 MHz  656.25 mV
Entry 37:  595 MHz  643.75 mV
Entry 38:  567 MHz  637.50 mV
Entry 39:  537 MHz  631.25 mV
Entry 40:  508 MHz  625.00 mV
Entry 41:  478 MHz  618.75 mV
Entry 42:  448 MHz  606.25 mV
Entry 43:  419 MHz  600.00 mV
Entry 44:  390 MHz  593.75 mV
```

The modified module uses a linear scaling strategy:
- Frequencies: stock frequencies scaled proportionally so that entry 0 hits
  the target ceiling (1200 MHz) while entry 44 stays at stock floor (390 MHz).
- Voltages: linear interpolation between ceiling voltage (800 mV) and
  floor voltage (593.75 mV), quantized to PMIC step (6.25 mV).

## Patch Sites

### Instruction Patches

1. **`avs_freq_check_bypass`** (`.text` +0x86f8, file 0x96f8)
   ```
   Stock:   9f 00 05 6b 21 22 00 54   CMP W5,W4; B.NE abort
   Patched: 9f 00 05 6b 1f 20 03 d5   CMP W5,W4; NOP
   ```
   - Purpose: Prevent efuse frequency mismatch from aborting AVS
   - Why needed: Patched OPP freqs differ from device efuse values

2. **`apply_adjust_probe_bypass`** (`.text` +0x7d9c, file 0x8d9c)
   ```
   Stock:   e0 03 14 aa e1 03 13 2a 00 00 00 94   MOV X0,X20; MOV W1,W19; BL apply_adjust
   Patched: e0 03 14 aa e1 03 13 2a 1f 20 03 d5   MOV X0,X20; MOV W1,W19; NOP
   ```
   - Purpose: Prevent `__gpufreq_apply_adjust` from overwriting OPP table
     with efuse calibration data during probe

3. **`apply_adjust_avs_bypass`** (`.text` +0x88f0, file 0x98f0)
   ```
   Stock:   61 00 80 52 e0 03 13 aa 00 00 00 94   MOV W1,#3; MOV X0,X19; BL apply_adjust
   Patched: 61 00 80 52 e0 03 13 aa 1f 20 03 d5   MOV W1,#3; MOV X0,X19; NOP
   ```
   - Purpose: Same as above but called from AVS adjustment path

### Data Patches

4. **`segment_adj_data`** (`.data` +0x109c, file 0xc814)
   ```
   Stock:   19 00 00 00   ...  e8 fd 00 00   (g_segment_adj[0] = 25)
   Patched: 00 00 00 00   ...  e8 fd 00 00   (g_segment_adj[0] = 0)
   ```
   - Purpose: Remove gpuppm OPP index ceiling

### Relocation Nullification

For each patched `BL` instruction, the corresponding `.rela.text.*` entry's
r_info field must be zeroed to prevent the kernel module loader from
rejecting the NOP during relocation processing.

| .rela entry | File Offset | Targets | Symbol |
|---|---|---|---|
| Rela[1891] | 0x1afd0 | `.text+0x7da4` | `__gpufreq_apply_adjust` |
| Rela[2116] | 0x1c4e8 | `.text+0x88f8` | `__gpufreq_apply_adjust` |

## Structural Detection Strategy

### OPP Table Detection

1. Locate `g_default_gpu` symbol in `.symtab`
2. If symbol not found, scan `.data` for descending frequency sequence:
   - 45 consecutive 24-byte entries
   - First field (u32 LE) in range [200000, 2000000], divisible by 1000
   - Strictly descending values
   - Voltage field values in reasonable range [50000, 100000]
3. If both fail, report UNSUPPORTED

### Patch Site Detection

1. Use `.symtab` to locate `__gpufreq_apply_adjust`, `__gpufreq_avs_adjustment`,
   `__gpufreq_pdrv_probe`
2. Compute relative offsets for known instruction patterns within each function
3. Verify pattern bytes match exactly
4. If symbols not available, fall back to pattern matching with context
   validation

### g_segment_adj Detection

1. Look up `g_segment_adj` symbol directly
2. Verify value is integer in expected range [0, 45]
3. If not found, scan for pattern `19 00 00 00 00 00 00 00 e8 fd 00 00`
   with surrounding context validation

## Unresolved Questions

1. What does `platform_ap_fp.46` / `platform_eb_fp.47` contain? (Appears to be
   string data, not OPP entries.)
2. Does `g_aging_table` need modification for overclock stability?
3. Are there thermal or power limit interactions beyond what these patches address?
4. Does the Mali GPU driver (`mali_kbase_mt6789.ko`) impose separate frequency
   limits that must be addressed?
5. What is the exact relationship between `u4` and actual power/current limits?
6. Does modifying the OPP table alone (without code patches) produce a functional
   overclock, or are all four patches strictly required?

## Confirmed Dependencies

The device-modified module applies ALL of these changes:
- 3 instruction NOP patches
- 1 data value change
- 2 relocation nullifications
- 45 OPP entry modifications

All are necessary for the overclock to take effect at runtime.
