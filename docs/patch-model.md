# MTK GPUfreq Patch Model

## Overclocking Strategy

The overclock is achieved through five coordinated modifications:

### 1. OPP Table Modification

The `g_default_gpu` table (45 × 24-byte entries) is the primary frequency table.
Frequencies are scaled linearly: stock frequencies are interpolated between the
new ceiling (e.g., 1200 MHz) and the stock floor (390 MHz) based on their position
in the stock frequency ladder.

Voltages are set by linear interpolation between the new ceiling voltage and
floor voltage, quantized to the PMIC step size (6.25 mV).

### 2. AVS Frequency Check Bypass

`__gpufreq_avs_adjustment` compares each OPP entry's frequency against the device's
efuse-stored frequency value. When they differ (as they will with patched OPPs),
the function aborts for that OPP index. NOP'ing the `B.NE` at +0xcc prevents this
abort.

### 3. Apply_Adjust Bypass (Probe Path)

`__gpufreq_pdrv_probe` calls `__gpufreq_apply_adjust` which overwrites OPP table
entries with efuse calibration data. NOP'ing the `BL` prevents this overwrite.

### 4. Apply_Adjust Bypass (AVS Path)

`__gpufreq_avs_adjustment` also calls `__gpufreq_apply_adjust`. Same fix.

### 5. Segment Ceiling Removal

`g_segment_adj[0]` stores the maximum OPP index allowed by the gpuppm (GPU
Power Performance Management) subsystem. Changing from 25 to 0 removes this cap.

## Voltage Estimation Model

### Stock V–F Curve Characteristics (MT6789)

The stock OPP table contains 45 entries from 390 MHz / 675 mV to 1100 MHz / 900 mV.

| Region | OPP range | Freq range | Slope | Notes |
|---|---|---|---|---|
| Upper | 0–19 | 1100–846 MHz | ~45 µV/MHz | Near-perfectly linear, 14 MHz steps, V=VSRAM |
| Mid | 20–32 | 835–700 MHz | ~52–57 µV/MHz | 11–12 MHz steps, VSRAM flattens at 750 mV |
| Lower | 33–44 | 674–390 MHz | ~25 µV/MHz | 26 MHz steps, large voltage plateaus, VSRAM clamped |

The upper region (OPPs 0–19) is the relevant range for overclocking. Each step drops
exactly one PMIC step (625 µV) over ~14 MHz with a slope of ~44.6 µV/MHz.

### Model Selection

The default model is **top-two-OPP slope extrapolation**:

```
slope = (OPP[0].volt - OPP[1].volt) / (OPP[0].freq - OPP[1].freq)
estimated_voltage = OPP[0].volt + (target_freq - OPP[0].freq) * slope
```

**Rationale:**
- The upper region is highly linear — top-two slope is identical to N=3/N=4 regression
- Resistant to low-frequency voltage plateaus that dilute whole-range endpoint models
- Deterministic, trivially explainable, no numerical dependency
- Reproduces stock max voltage exactly at the anchor point

**Fallback rules:**
1. Top-two OPPs have identical voltage → whole-range endpoint model
2. Only one OPP entry → constant voltage (stock max)
3. Single-entry table or degenerate → requires explicit `--volt`

**Comparison of models (estimates for MT6789):**

| Target | Endpoint | Top-two | Reg-3 | Reg-4 | Reg-5 | Old (removed) |
|---|---|---|---|---|---|---|
| 1100 MHz | 900.00 | 900.00 | 900.00 | 900.00 | 900.09 | 900.00 |
| 1125 MHz | 907.92 | 911.16 | 911.16 | 911.16 | 911.41 | 931.69 |
| 1150 MHz | 915.85 | 922.32 | 922.32 | 922.32 | 922.73 | 963.38 |
| 1200 MHz | 931.69 | 944.64 | 944.64 | 944.64 | 945.37 | 1026.76 |
| 1250 MHz | 947.54 | 966.96 | 966.96 | 966.96 | 968.01 | 1090.14 |
| 1300 MHz | 963.38 | 989.29 | 989.29 | 989.29 | 990.65 | 1153.52 |

The legacy origin-based formula (removed) scaled `stock_ceil_volt * freq_ratio` from
an implicit (0 MHz, 0 V) origin, producing pathologically high estimates.

### Quantization

All voltage estimates are quantized to the PMIC step (625 µV = 6.25 mV) using
`round(value / PMIC_STEP) * PMIC_STEP`.

### Physical Stability Warning

A mathematically derived voltage is **not** a proven safe voltage. The tool
performs static validation only:
- Binary structure integrity
- OPP ordering invariants
- Voltage encoding alignment

Physical stability requires device testing. The tool never represents static
validation as proof of electrical stability.

## Patch Plan Representation

A `PatchPlan` is a validated set of `PatchRecord` entries:

```python
@dataclass
class PatchRecord:
    name: str              # Human-readable label
    file_offset: int       # File offset in bytes
    original: bytes        # Expected original bytes
    replacement: bytes     # Replacement bytes
    virtual_address: int | None  # ELF virtual address (if applicable)
    section_name: str | None     # Section name
    semantic_original: str       # Human-readable original description
    semantic_replacement: str    # Human-readable replacement description
    patch_type: PatchType        # INSTRUCTION / DATA / RELOCATION
```

## Validation Rules

1. Every `original` must match the actual bytes at `file_offset` in the input
2. No two `PatchRecord` entries may have overlapping byte ranges
3. `replacement` must have the same length as `original`
4. All `PatchRecord` entries must reference valid file offsets within the module
5. For relocation nullification, `original` must be a valid `R_AARCH64_CALL26`
   entry before mutation

## Application Pipeline

1. Parse input `.ko` file
2. Run analysis to identify structures and patch sites
3. Validate structural detection (SUPPORTED / UNSUPPORTED / AMBIGUOUS)
4. Generate `PatchPlan` from requested overclock parameters
5. Verify every `PatchRecord.original` against actual input bytes
6. Apply all patches to a `bytearray` copy
7. Verify output: check that only intended bytes changed
8. Re-parse output OPP table and verify invariants
9. Write output file

## Verification

After patching, verify:
- Output file size equals input file size
- Only bytes in the `PatchPlan` records differ from input
- ELF magic and basic structure are preserved
- SHA-256 of input and output differ
- Output OPP table passes structural invariant checks
- No unexpected byte modifications outside the patch plan

## OPP Invariants

The `check_opp_invariants()` function validates every OPP table:
- Strictly descending frequency
- Non-increasing voltage
- Frequency within [200, 2000] MHz, aligned to 1 MHz
- Voltage within [0.5, 1.2] V, aligned to 6.25 mV PMIC step
- VSRAM >= voltage
- u3 in {1, 2}
- u4 in {625, 1250, 1875}
