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
against a cheap, dependency-free floor — a deterministic text scan for direct
call sites — and **the disagreement is the signal**: if the scan finds a caller the graph tool
didn't report, that edge is missing from the index, and you're told so loudly
instead of trusting a silent omission.

It's the *validity-audit* pattern applied to tooling: a **deterministic floor**
(grep — always correct for direct callers) + an **opaque richer layer** (the
graph tool — transitive impact, risk ranking) + an **independent confirmation
net** (the diff between them).

Version 0.2 is designed for CI: it has stable exit codes, machine-readable
output, explicit backend-failure handling, and support for Python,
TypeScript, JavaScript, and React JSX/TSX call sites.

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

## Supported languages

The audit scans these extensions exactly:

| Language / source form | Extensions |
|---|---|
| Python | `.py` |
| TypeScript | `.ts`, `.tsx` |
| JavaScript | `.js`, `.jsx`, `.mjs`, `.cjs` |

For every language it detects textual `symbol(...)` call sites. In `.tsx` and
`.jsx`, it also detects JSX component references such as `<Symbol />`.

## Install

Python 3.9 or newer is required. The core tool uses only the standard library.

Install the command from GitHub:

```bash
python -m pip install \
  "git+https://github.com/klmtseng/impact-audited.git@main"
impact-audited --help
```

Or use the single-file form:

```bash
curl -O https://raw.githubusercontent.com/klmtseng/impact-audited/main/impact_audited.py
chmod +x impact_audited.py
./impact_audited.py --help
```

Token accounting is optional:

```bash
python -m pip install "impact-audited[tokens] @ git+https://github.com/klmtseng/impact-audited.git@main"
```

## CLI examples

```bash
# Reliable direct-caller floor, with no graph backend:
impact-audited to_key_val_list --path /path/to/requests

# Audit a graph backend. {sym} is replaced with the shell-quoted symbol.
# The backend must print caller file paths to stdout.
impact-audited to_key_val_list --path /path/to/requests \
  --graph 'gitnexus impact {sym} -r requests'

# TypeScript / React example:
impact-audited UserCard --path ./web \
  --graph 'my-graph callers {sym} --format json'

# Machine-readable output:
impact-audited my_func --path . --graph 'my-graph callers {sym}' --json
```

Every `--graph` template must contain **exactly one literal `{sym}`
placeholder**. The CLI replaces it with the shell-quoted audited symbol before
execution. A template containing zero or multiple `{sym}` placeholders is
invalid configuration and exits with code `4` without running the backend.

Human-readable output always includes the audited symbol, baseline caller
count, graph caller count, missing callers, and a final `PASS` or `FAIL`.
JSON output includes the same information and retains the v0.1 field names for
backward compatibility.

### Exit codes

| Code | Meaning |
|---:|---|
| `0` | Audit passed, or baseline-only scan completed |
| `2` | Graph backend omitted one or more detectable callers |
| `3` | Graph backend failed, returned non-zero, or produced no stdout |
| `4` | Invalid configuration or CLI input |

### Shell security

For backward compatibility, `--graph` remains a shell command template and can
use quoting, redirection, or pipelines. The audited symbol is shell-quoted
before substitution, but the template itself is executable code. **Never build
`--graph` from untrusted pull-request content, environment variables, or user
input.** Keep the command in trusted repository or organization CI
configuration.

## CI usage

The exit codes can fail a job on omissions, backend failures, and invalid
configuration without wrapper logic:

```yaml
name: dependency-edge-audit
on: [pull_request]

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install "git+https://github.com/klmtseng/impact-audited.git@main"
      - run: npm install --global gitnexus
      - run: gitnexus analyze "$GITHUB_WORKSPACE" --name ci-repo
      - run: impact-audited my_symbol --path . --graph 'gitnexus impact {sym} -r ci-repo' --json
```

Run one audit command per symbol that your CI policy requires. Version 0.2 does
not choose changed symbols or perform transitive analysis.

## Known limitations

- This is a conservative text scan, not a parser. Same-named methods, comments,
  strings, and method declarations that resemble calls can cause false
  positives. Multiline or indirect calls can be missed.
- JSX detection covers direct `<Symbol />` / `<Symbol>` references in `.jsx`
  and `.tsx`; aliases, re-exports, dynamically selected components, and
  lowercase intrinsic elements are not resolved semantically.
- The audit checks direct caller files only. It does not implement transitive
  impact analysis, LSP integration, tree-sitter semantic analysis, or
  confidence scoring.
- The graph backend must print source paths to stdout. Relative and absolute
  paths are supported; a bare basename is accepted only when unique in the
  repository. Non-zero backend exit status is always a backend failure, even
  if partial stdout was produced.
- `.git`, dependency, virtual-environment, cache, build, and distribution
  directories are skipped.
- Benchmark findings are for the tool versions tested and may already be fixed
  upstream; the point is the verification pattern, not any one product.

## License

MIT — see [LICENSE](LICENSE).
