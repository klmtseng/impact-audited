# impact-audited

**Trust-but-verify for code-graph "impact analysis".**

Code-intelligence tools — knowledge-graph indexers, LSP-backed "blast radius"
analyzers, the MCP servers that give AI agents a map of your codebase — answer
questions like *"what breaks if I change this function?"*. They're fast and
they read confident. But they share a quiet failure mode: **if the indexer
silently drops a source file** (a parser hiccup on one large file is enough),
every dependency edge through that file disappears — and the tool still answers
as if the file never existed. You get *"low risk, only one caller"* when the
symbol is actually used across the core of your codebase.

`impact-audited` catches that. It cross-checks any graph tool's impact output
against a cheap, dependency-free ground truth — `grep` for direct call sites —
and **the disagreement is the signal**: if grep finds a caller the graph tool
didn't report, that edge is missing from the index, and you're told so loudly
instead of trusting a silent omission.

It's the *validity-audit* pattern applied to tooling: a **deterministic floor**
(grep — always correct for direct callers) + an **opaque richer layer** (the
graph tool — transitive impact, risk ranking) + an **independent confirmation
net** (the diff between them).

## Why this matters (measured)

I ran a graph-based impact tool (GitNexus 1.6.3) and a knowledge-graph MCP
(codebase-memory-mcp 0.8.1) over two widely-used public Python libraries, then
checked every top-level symbol's reported callers against grep ground truth:

| Repo | Core files the graph indexer silently dropped | Impact answers provably incomplete (strict) / affected (broad upper bound) |
|---|---|---|
| [`psf/requests`](https://github.com/psf/requests) | `models.py`, `sessions.py`, `utils.py` | **50%** (28/56 strict; 64% broad) |
| [`ranaroussi/yfinance`](https://github.com/ranaroussi/yfinance) | `const.py`, `scrapers/history.py`, `scrapers/quote.py`, `utils.py` | **12%** (7/59 strict; 39% broad) |

Attribution is airtight: a symbol counts (strict tier) only when its definition
lives in a file the indexer *kept* but grep finds a real call site — definition
lines excluded — *inside a file the indexer's own logs report it failed to
parse*. The node is in the graph; that edge cannot be. Example:
`requests.utils.to_key_val_list` is reported as **LOW risk, one caller
(`utils.py`)** — but `models.py` and `sessions.py`, the heart of the library,
both call it. (That symbol is itself *defined* in a dropped file, i.e. broad
tier — and the tool still answered rather than failing loudly, which is exactly
why the broad tier is worth reporting.)

Note the fairness bar: in my runs, **codebase-memory-mcp indexed every file on
both repos with no such gap** (this comparison isn't automated in the reproduce
script, which covers the GitNexus side). So this isn't "all graph tools lie" —
it's that *some can skip files silently, and you usually can't tell which*.
That's exactly why a cheap audit is worth wiring in. Full method + caveats:
[`benchmark/RESULTS.md`](benchmark/RESULTS.md).

## Install

Single file, standard library only. `tiktoken` is optional (token accounting).

```bash
curl -O https://raw.githubusercontent.com/klmtseng/impact-audited/main/impact_audited.py
chmod +x impact_audited.py
pip install tiktoken   # optional
```

## Usage

```bash
# 1) Reliable direct-caller floor — no graph tool, zero dependencies:
./impact_audited.py to_key_val_list --path /path/to/requests

# 2) Audit a graph tool. --graph is a shell template; {sym} = the symbol.
#    Its stdout is scanned for .py paths and diffed against grep.
./impact_audited.py to_key_val_list --path /path/to/requests \
    --graph 'gitnexus impact {sym} -r requests'

# Works with ANY tool that prints file paths — swap the backend:
./impact_audited.py my_func --path . --graph 'other-graph-tool trace {sym} --json'

# 3) Machine-readable, for CI / agent tool-use:
./impact_audited.py my_func --path . --graph '...' --json
```

Exit code `0` = audit passed (or no graph tool given); `2` = the graph tool
omitted a direct caller grep found — its impact answer is incomplete; `3` = the
graph backend produced no output (missing tool / wrong command), reported as an
error rather than an omission. Wire it into CI or an agent loop to fail loudly
on silent index gaps.

## What it does and doesn't cover

- **Covers:** direct callers of a symbol — the highest-risk, highest-value layer
  of an impact query. This is where silent index gaps do the most damage.
- **Doesn't cover:** transitive/multi-hop impact (only the graph produces that —
  but once the audit flags a gap, you know the transitive answer is suspect too),
  and semantic/concept queries (no grep ground truth exists for those).
- `grep 'sym('` can over-count (same-named methods, strings, comments), so the
  audit errs toward *flagging*. The benchmark's headline number sidesteps this by
  attributing only to files the indexer's own logs admit it dropped.
- Findings are for the tool versions tested and may already be fixed upstream;
  the point is the *pattern*, not any one tool.

## License

MIT — see [LICENSE](LICENSE).
