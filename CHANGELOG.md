# Changelog

## [0.2.2] — 2026-08-20

### Fixed

- Package version now matches the release identity. Installing the `v0.2.1`
  tag previously reported `0.2.0` because `pyproject.toml` was not bumped with
  that documentation patch.

### Added

- `__version__` and `impact-audited --version` / `-V`.
- A standing version-identity test so the module version cannot drift from
  `pyproject.toml` again.
- `examples/silent-gap`: a checked-in fake graph backend that omits
  `caller_c.py`. `python3 examples/silent-gap/run_demo.py` reproduces the
  30-second FAIL with no GitNexus, no network, and no extra dependencies.
- `benchmark/reproduce.sh` refuses to run unless `gitnexus` on PATH is the
  version used for the published numbers (`1.6.3`). Override with
  `REQUIRED_GITNEXUS` only when measuring a different version on purpose.

### Unchanged

- Runtime comparison logic, exit-code contract, and published benchmark
  numbers (GitNexus 1.6.3 vs pinned `requests` / `yfinance` commits).
