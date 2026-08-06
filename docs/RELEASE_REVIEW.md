# Release Review — impact-audited v0.2.0

Audit date: 2026-08-06. Reviewer: Task 002 Release Hardening.
Base SHA: `a8ea86a87d82b61f729dd322d355c5658a54e8d0`

---

## PASS (releasable as-is)

| # | Item | Evidence |
|---|---|---|
| P1 | Tests pass on Python 3.9–3.13 | `python3 -m pytest tests/ -q` → `23 passed in 0.77s` |
| P2 | CI workflow exists and last run is green | `.github/workflows/ci.yml`; `gh run list` → `completed success` (2026-08-06) |
| P3 | CI badge added to README pointing to correct workflow | `README.md:3` — badge URL matches `ci.yml` |
| P4 | Install from git URL works; CLI functional | `pip install git+…@main` + `impact-audited --help` + baseline-only run → exit 0 (output verified) |
| P5 | Benchmark numbers reproducible at pinned commits | `scan_contamination.py` on `23953c0c…` / `38c73ce3…` with GitNexus 1.6.3: requests 28/56 (50%) strict, 63/99 (64%) broad; yfinance 7/59 (12%) strict, 39/99 (39%) broad — exact match to RESULTS.md |
| P6 | reproduce.sh now pins to full SHAs | `benchmark/reproduce.sh:17–18` — `PINS` array with full 40-char SHAs; `git checkout` to pinned commit before index |
| P7 | RESULTS.md documents full commit SHAs and tool version install command | `benchmark/RESULTS.md:11–16` — `gitnexus@1.6.3` install command; reproducibility note added |
| P8 | Relative README links valid | `benchmark/RESULTS.md` → exists; `LICENSE` → exists |
| P9 | External README links valid | `github.com/psf/requests` → HTTP 200; `github.com/ranaroussi/yfinance` → HTTP 200 |
| P10 | curl download link fixed | `README.md:90` — was `…/impact_audited.py` (placeholder); now full raw.githubusercontent.com URL |
| P11 | pyproject.toml version consistent with README | `pyproject.toml:7` version `0.2.0`; README:103 references `v0.1` fields (backward-compat note, not a version claim) — consistent |
| P12 | Forbidden files untouched | `git diff a8ea86a..HEAD -- impact_audited.py tests/ DISCLOSURE.md LINKEDIN_DRAFT.md` → empty |
| P13 | Repo description improved | Before: "Trust-but-verify…" (138 chars). After: "Detect silent indexing gaps…" with "detect" and gap-detection framing |
| P14 | Repo topics now include llm-agents, verification | `gh repo view` → topics: code-analysis, developer-tools, python, static-analysis, testing, llm-agents, verification |
| P15 | Mermaid flowchart syntax valid | `README.md:8–22` — standard `flowchart LR` syntax; renders on GitHub |
| P16 | Hero tagline visible without scrolling | `README.md:1–6` — title + badge + tagline + philosophy above first code block |
| P17 | v0.2.0 git tag and GitHub Release created | `gh release view v0.2.0` → tag exists; install URL `pip install git+…@v0.2.0` verified functional |

---

## WARNING (can improve, does not block release)

| # | Item | Evidence / Suggested action |
|---|---|---|
| W1 | Social preview image not set | GitHub API does not allow setting Open Graph image; must be set manually in repo Settings → Social Preview. Suggested: screenshot of a FAIL output or the verification-flow diagram. |
| W2 | pyproject.toml `keywords` minimal | `pyproject.toml:13` — only 3 keywords (`dependency-graph`, `impact-analysis`, `ci`). Could add `code-graph`, `llm`, `verification`. Low impact since not on PyPI yet. |
| W3 | codebase-memory-mcp comparison not automated in reproduce.sh | `benchmark/RESULTS.md:29` — noted in-doc. Adding automation would require MCP runtime; out of scope for this release. |
| W4 | reproduce.sh has no gitnexus version guard | Script requires `gitnexus@1.6.3` but does not check `gitnexus --version` before running. Numbers may drift on other versions. Low friction to add a version check. |

---

## FAIL (blocks public promotion)

None. All blocking items resolved.

---

## Post-release documentation fixes (v0.2.1 branch)

Applied after v0.2.0 release, on branch `docs/v0.2.1-accuracy`:

- **Release-note correction**: Removed false `--lang auto-detect` claim from v0.2.0 GitHub Release notes. Replaced with accurate description of automatic extension-based language detection covering Python, Rust, Go, JavaScript, TypeScript, JSX and TSX.
- **README install pin**: Added pinned `@v0.2.0` install URL as recommended install; `@main` retained as development install.
- **Failure-mode prose**: README Problem section now explicitly describes the indexer warning-and-continue behaviour and explains that query-time answers can be authoritative-looking but incomplete.
- **Benchmark dedup**: Inline benchmark paragraph removed; Benchmark section now links only to `benchmark/RESULTS.md`. Numbers unchanged.
- **Explanatory figures**: `docs/figures/verification-flow.svg` and `docs/figures/failure-mode.svg` added. Mermaid sources retained as `.mmd` files. README hero block replaced with the checked-in SVG.
