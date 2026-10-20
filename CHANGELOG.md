# Changelog

## [0.3.0] — 2026-10-20

### Upgrade note

This release makes the PASS rule stricter. A run that passed on 0.2.x in the
default text graph format can now exit `5` (UNVERIFIED) when a caller sits in
the file that defines the symbol, or exit `3` when the backend answers
"ambiguous" / "not found" with exit status 0. If you gate CI on exit `0`, expect
new failures; both are cases the old version wrongly passed. With GitNexus, use
`--graph-format gitnexus` so same-file callers can be proven instead of being
reported as unverified.

### Fixed

- **False PASS on same-file callers.** In the default text graph format every
  source path in backend stdout counted as a caller, so a backend that echoes the
  audited symbol's own definition file (GitNexus prints `target.filePath`) made a
  call inside that file look covered. Such callers are now reported as
  `unverified_callers` with exit `5` / `Final: FAIL (UNVERIFIED)`
  (`declaration_files`, `main`; tests `test_a_*` in `tests/test_false_pass.py`).
  Found auditing BEAM-P2P (TypeScript/React): 12 symbols that previously passed
  now report exit 5 (text) or exit 2 (`--graph-format gitnexus`).
- **False PASS on exit-0 error replies.** A backend that exits 0 but answers
  "ambiguous" / "not found" (GitNexus does both) was parsed as a normal result,
  and the candidate files it listed counted as callers. Such replies are now a
  backend failure, exit `3` (`backend_failure_reason`, `run_graph_backend`;
  tests `test_b_*`).

### Added

- Exit code `5` (UNVERIFIED): no caller is missing, but at least one could not be
  confirmed. Exit `2` still takes precedence. Existing codes `0/2/3/4` unchanged.
- JSON fields `audit_verdict`, `unverified_callers`, `unverified_caller_count`,
  `graph_format`. `final_status` stays `PASS`/`FAIL` (`FAIL` for unverified) and
  `audit_pass` is `false` for unverified.
- `--graph-format {text,lines,gitnexus}`: `lines` = one authoritative caller path
  per line; `gitnexus` = parse `gitnexus impact` JSON, count only `byDepth`
  entries, reject `impactedCount` mismatches (`graph_caller_files`,
  `gitnexus_caller_paths`; tests `test_c_*`, `test_lines_format_rejects_non_path_lines`,
  `test_b_gitnexus_count_mismatch_is_backend_failure`).
- `--graph-fail-pattern REGEX` (repeatable, stdout and stderr) and
  `--no-default-fail-markers` (tests `test_b_custom_fail_pattern_on_stderr`,
  `test_b_default_markers_can_be_disabled`).
- `[tool.pytest.ini_options] testpaths = ["tests"]` so `python -m pytest` does not
  collect the gitignored third-party clones under `benchmark/repos/`.

### Changed

- A symbol GitNexus cannot resolve now exits `3` instead of `2`/`0` (backend
  failure takes precedence over the caller comparison).

### Unchanged

- Published benchmark numbers in `benchmark/RESULTS.md` (produced by
  `benchmark/scan_contamination.py`, which does not use the audit CLI). The
  `reproduce.sh` example audit (`to_key_val_list`) still exits `2`; it now also
  lists `src/requests/utils.py` as unverified.

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
