# Benchmark: how often is a code-graph impact answer silently incomplete?

**Question.** When a code-graph tool answers *"what breaks if I change symbol X?"*,
how often does it silently omit a real caller because its indexer failed to parse
the file that caller lives in?

**Setup.** Two widely-used public Python libraries, each indexed fresh:

| Repo | Commit | Non-test `.py` | Lines |
|---|---|---|---|
| psf/requests | `23953c0` | 22 | 6,874 |
| ranaroussi/yfinance | `38c73ce` | 50 | 13,715 |

Tools:
- **GitNexus 1.6.3** — `gitnexus analyze` then `gitnexus impact <sym>` (blast radius, upstream).
- **codebase-memory-mcp 0.8.1** — `index_repository` then `trace_path`/`search_graph` (fairness reference).
- **grep** — `grep -rnE '\bSYM\s*\(' --include=*.py` minus the definition line = direct-caller ground truth.

Token accounting: `tiktoken` `cl100k_base`, same encoder for every tool.

## Finding 1 — the indexer silently drops core files

`gitnexus analyze` emits `scope extraction failed for <file>` warnings and then
continues, excluding those files from the graph. On both repos the dropped files
include the **core** of the library:

| Repo | Files GitNexus 1.6.3 dropped (non-test) |
|---|---|
| requests | `src/requests/models.py`, `src/requests/sessions.py`, `src/requests/utils.py` |
| yfinance | `yfinance/const.py`, `yfinance/scrapers/history.py`, `yfinance/scrapers/quote.py`, `yfinance/utils.py` |

All dropped files are **under** the 512 KB size cap (largest: `history.py`, 167 KB
/ 3,405 lines). They are simply the larger / more complex modules — consistent
with a tree-sitter scope-extraction bug, not a documented size limit. **codebase-
memory-mcp indexed every file on both repos** with no such failures.

## Finding 2 — that makes impact answers provably incomplete

For every top-level symbol, we ask: does grep find a direct call site **inside a
file GitNexus's own logs admit it dropped**? If yes, that dependency edge cannot
be in the graph, so `impact` is guaranteed to under-report.

| Repo | Symbols with callers | Provably-incomplete impact answers |
|---|---|---|
| requests | 113 | **79 (70%)** |
| yfinance | 116 | **52 (45%)** |

This attribution needs no assumption about grep precision — it counts only
symbols referenced in files the tool itself reported failing to parse.

Hand-verified false negatives (the failure you'd actually hit):

- `requests.utils.to_key_val_list` → GitNexus: **risk=LOW, 1 caller (`utils.py`)**.
  Reality: also called in `models.py` and `sessions.py` (library core).
- `requests.adapters.HTTPAdapter` → GitNexus omits its use in `sessions.py`.
- `yfinance.utils.camel2title` → GitNexus omits its use in `base.py`.

## Finding 3 — the grep audit is well-calibrated

`impact-audited` flags a symbol only when grep finds a caller the graph tool
missed. It correctly stays **silent** on the 30–55% of symbols with no gap
(e.g. requests `ConnectTimeout`, `HTTPProxyAuth`; yfinance `Analysis`,
`ConfigMgr`) and fires precisely on the affected ones. Cost: a few hundred
tokens per query (grep output + graph output).

## Honest limitations

- Two repos, one language, one question type (direct-caller impact). A probe with
  airtight attribution, not an exhaustive benchmark.
- Tool versions GitNexus 1.6.3 / codebase-memory-mcp 0.8.1 (2026-06). May be fixed
  upstream — the transferable result is the *pattern*, not a verdict on a product.
- grep covers direct callers only, not transitive impact and not semantic queries.
- The aggregate "70% / 45%" is the share of symbols whose impact answer must be
  incomplete; it is not a claim about any single query's severity.

## Reproduce

```bash
bash reproduce.sh          # clones both repos, indexes with GitNexus, runs the scan
```

Requires `gitnexus` (`npm i -g gitnexus`) and `git` on PATH.
