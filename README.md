# mtk-gpu-oc

Structural analysis and patching tool for MediaTek GPUfreq kernel modules.
Overclock your MediaTek GPU by modifying the OPP frequency–voltage table
and bypassing runtime calibration overwrites.

**Supported platforms:** MT6789 (initial). Designed for extensibility.

## Installation

```bash
pip install mtk-gpu-oc
```

Or from source:

```bash
git clone https://github.com/ReCoreShift/mtk-gpu-oc.git
cd mtk-gpu-oc
pip install -e .
```

## Quick start

```bash
# Inspect a kernel module
mtk-gpu-oc inspect mtk_gpufreq_mt6789.ko

# Generate an overclocked module (1200 MHz ceiling, auto voltage)
mtk-gpu-oc patch stock.ko --max-freq 1200 -o patched.ko

# Generate with explicit voltage
mtk-gpu-oc patch stock.ko --max-freq 1200 --volt 800 -o patched.ko

# Compare stock and modified modules
mtk-gpu-oc compare stock.ko patched.ko

# Verify a patched module
mtk-gpu-oc verify stock.ko patched.ko

# Dry-run (show plan without writing)
mtk-gpu-oc patch stock.ko --max-freq 1200 --dry-run
```

## Commands

| Command     | Description                                         |
|-------------|-----------------------------------------------------|
| `inspect`   | Display ELF identity, OPP table, patch sites        |
| `patch`     | Apply overclock patches (bypass + OPP table)        |
| `compare`   | Semantic diff between two modules                   |
| `verify`    | Validate patched module integrity                   |

## How it works

Overclocking a MediaTek GPU requires five coordinated changes:

1. **OPP table modification** — Scale frequencies in `g_default_gpu` table
2. **AVS freq check bypass** — NOP the efuse frequency mismatch abort
3. **Apply_adjust bypass (probe)** — NOP the BL that overwrites OPPs during probe
4. **Apply_adjust bypass (AVS)** — NOP the BL in the AVS adjustment path
5. **Segment ceiling removal** — Zero `g_segment_adj[0]` to remove the OPP cap

Plus relocation entry nullification to pass kernel module loader checks.

## Voltage estimation

Default model: **top-two-OPP slope extrapolation**. The voltage slope between
the two highest OPP entries is used to estimate the voltage at the target
frequency. Fallback models handle degenerate tables:

| Model       | When used                          |
|-------------|------------------------------------|
| top-two     | Two distinct top frequencies/volts |
| endpoint    | Top-two have identical voltage     |
| constant    | Single entry or degenerate table   |
| explicit    | User provides `--volt`             |

**A mathematically estimated voltage is not a proven safe voltage.** Always
test patched modules on device and have a recovery path (e.g., backup the
original module, have flashing tools ready).

## Architecture

```
src/mtk_gpu_oc/
    elf.py       Generic ELF64 parsing (platform-independent)
    opp.py       OPP entry types, encoding, detection, invariants
    gpufreq.py   MediaTek GPUFreq structural analysis
    profiles.py  Platform-specific profiles (MT6789)
    analysis.py  Module analysis orchestration
    compare.py   Semantic stock-vs-modified comparison
    patch.py     Patch plan generation, validation, application
    verify.py    Independent patch verification
    voltage.py   Voltage estimation abstraction
    config.py    TOML config file loading
    cli.py       CLI argument parsing
```

## Limitations

- Only MT6789 is currently supported
- Voltage curve is linear interpolation (not per-entry hand-tuned)
- No device-side stability validation
- Module signature verification not implemented
- Mali GPU driver interaction not analyzed

## Development

```bash
# Run tests
python3 -m pytest tests/ -v

# Run integration tests with stock module
MTK_STOCK_MODULE=research/stock/mtk_gpufreq_mt6789.ko python3 -m pytest tests/ -v
```

## Documentation

- `docs/mt6789-gpufreq-analysis.md` — Reverse engineering notes
- `docs/patch-model.md` — Voltage model and patch plan details
- `docs/legacy-script-analysis.md` — Original script reconstruction

## License

Mozilla Public License 2.0. See `LICENSE`.
