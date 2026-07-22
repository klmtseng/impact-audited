#!/usr/bin/env python3
"""impact-audited — trust-but-verify for code-graph impact analysis.

Code-intelligence tools (knowledge-graph indexers, LSP-backed "blast radius"
tools) can *silently* drop source files from their index — a parser hiccup on
one large file and every dependency edge through it vanishes, with no error the
caller notices. Their impact/"what-breaks-if-I-change-X" answers then look
confident and complete while quietly missing callers.

This tool cross-checks any such graph tool against a cheap, dependency-free
ground truth: `grep` for direct call sites. The *disagreement* is the signal.
If grep finds a caller file the graph tool didn't report, that dependency edge
is missing from the index — the answer is incomplete, and you're told so loudly
instead of trusting a silent omission.

Design: a deterministic floor (grep, always correct for direct callers) +
an opaque richer layer (the graph tool) + an independent confirmation net
(the diff). Works with ANY graph backend that prints file paths.

Usage:
  # Reliable direct-caller floor, no graph tool needed (zero deps):
  impact_audited.py SYMBOL --path /repo

  # Audit a graph tool's impact output (backend is a shell template, {sym} = symbol):
  impact_audited.py SYMBOL --path /repo --graph 'gitnexus impact {sym} -r myrepo'
  impact_audited.py SYMBOL --path /repo --graph 'other-tool trace {sym} --json'

Languages: python, rust, js, ts, go. Default `--lang auto` detects which of
these are present under --path and audits their union. Call-site detection is
`sym(` minus definition lines and FULL-LINE comments; trailing comments,
interiors of block comments, and TS interface method signatures are NOT
excluded (known over-count sources, same as plain grep). Vendored dirs
(node_modules/target/.venv/...) are pruned from both detection and the floor.

Exit codes: 0 = audit passed (or no graph tool given); 2 = graph tool omitted a
direct caller that grep found (its impact answer is incomplete); 3 = the graph
backend produced no output (missing tool / wrong command) — reported as an
error, never counted as an omission.

Optional: `pip install tiktoken` to see approximate token cost per query.
"""
import argparse, json, os, re, shlex, subprocess, sys

# Per-language knowledge: file extensions, definition-line keywords (a line
# matching `<kw> sym` is a definition, not a call site), line-comment markers.
# Vendored/build dirs excluded from BOTH language detection and the grep floor
# (asymmetric pruning would turn vendored call sites into false AUDIT FAILED).
PRUNE_DIRS = (".git", "node_modules", "target", ".venv", "venv", "__pycache__")

LANGS = {
    "python": {"exts": ("py",),                       "def_kw": r"def|class",
               "comment": ("#",)},
    "rust":   {"exts": ("rs",),                       "def_kw": r"fn|struct|enum|trait|mod|macro_rules!",
               "comment": ("//",)},
    "js":     {"exts": ("js", "jsx", "mjs", "cjs"),   "def_kw": r"function|class",
               "comment": ("//",)},
    "ts":     {"exts": ("ts", "tsx"),                 "def_kw": r"function|class|interface|type",
               "comment": ("//",)},
    "go":     {"exts": ("go",),                       "def_kw": r"func|type",
               "comment": ("//",)},
}


def detect_langs(root):
    """Languages actually present under root (cheap: one os.walk, names only)."""
    ext2lang = {e: l for l, c in LANGS.items() for e in c["exts"]}
    found = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        for fn in filenames:
            lang = ext2lang.get(fn.rsplit(".", 1)[-1] if "." in fn else "")
            if lang:
                found.add(lang)
        if len(found) == len(LANGS):
            break
    return sorted(found)


def lang_confs(langs):
    exts = tuple(e for l in langs for e in LANGS[l]["exts"])
    def_kw = "|".join(LANGS[l]["def_kw"] for l in langs)
    comments = tuple(m for l in langs for m in LANGS[l]["comment"])
    return exts, def_kw, comments


def count_tokens(s):
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(s))
    except Exception:
        return None


def files_in_text(text, root, exts):
    """Every source path mentioned in `text` that actually exists under root.
    Absolute paths are normalized to root-relative; paths outside root are
    ignored (they can't be grep-floor callers, so they must not diff)."""
    file_re = re.compile(r'[\w./-]+\.(?:' + "|".join(exts) + r')\b')
    out = set()
    for m in file_re.findall(text):
        if os.path.isabs(m):
            real = os.path.realpath(m)
            if not real.startswith(root + os.sep):
                continue
            cand = os.path.relpath(real, root)
        else:
            cand = os.path.normpath(m.lstrip("./"))
            if cand.startswith(".."):
                continue
        if os.path.exists(os.path.join(root, cand)):
            out.add(cand)
    return out


def grep_caller_files(sym, root, exts, def_kw, comments):
    """Ground-truth direct callers: files with a real `sym(` call site.
    Definition lines (`def sym(` / `fn sym(` / ...) and line comments are not
    call sites. grep runs without a shell (arg list), so the symbol never
    touches shell syntax."""
    esc = re.escape(sym)
    proc = subprocess.run(
        ["grep", "-rnE", rf"\b{esc}\s*\("]
        + [f"--include=*.{e}" for e in exts]
        + [f"--exclude-dir={d}" for d in PRUNE_DIRS] + ["."],
        cwd=root, capture_output=True, text=True)
    files, kept = set(), []
    for ln in proc.stdout.splitlines():
        parts = ln.split(":", 2)
        if len(parts) < 3:
            continue
        fp, text = parts[0].lstrip("./"), parts[2]
        if re.search(rf"\b(?:{def_kw})\s+{esc}\b", text):
            continue
        if text.lstrip().startswith(comments):
            continue
        if os.path.exists(os.path.join(root, fp)):
            files.add(fp)
            kept.append(ln)
    return files, "\n".join(kept)


def main():
    ap = argparse.ArgumentParser(prog="impact-audited",
        description="Cross-check a code-graph impact tool against grep ground truth.")
    ap.add_argument("symbol")
    ap.add_argument("--path", default=".", help="repository root (default: cwd)")
    ap.add_argument("--graph", default=None,
        help="graph-tool command template; '{sym}' is replaced with the symbol. "
             "Its stdout is scanned for source paths. Omit to just show the grep floor.")
    ap.add_argument("--lang", default="auto",
        help="comma-separated languages to audit (%s), or 'auto' to detect "
             "from files present (default)" % "/".join(LANGS))
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args()
    root = os.path.abspath(a.path)
    sym = a.symbol

    if a.lang == "auto":
        langs = detect_langs(root)
        if not langs:
            print(f"impact-audited  «{sym}»\n"
                  f"  ⚠ no supported source files ({'/'.join(LANGS)}) found under {root}",
                  file=sys.stderr)
            sys.exit(3)
    else:
        langs = [l.strip() for l in a.lang.split(",")]
        unknown = [l for l in langs if l not in LANGS]
        if unknown:
            print(f"impact-audited: unknown --lang {unknown}; "
                  f"supported: {'/'.join(LANGS)}", file=sys.stderr)
            sys.exit(3)
    exts, def_kw, comments = lang_confs(langs)

    grep_files, grep_raw = grep_caller_files(sym, root, exts, def_kw, comments)

    graph_files, graph_raw, missed = None, "", []
    if a.graph:
        proc = subprocess.run(a.graph.replace("{sym}", shlex.quote(sym)),
                              shell=True, cwd=root, capture_output=True, text=True)
        graph_raw = proc.stdout
        if not graph_raw.strip():
            print(f"impact-audited  «{sym}»\n"
                  f"  ⚠ graph backend produced no output (exit {proc.returncode})."
                  " Is the tool installed and the --graph command correct?"
                  " Not counting this as an omission.", file=sys.stderr)
            sys.exit(3)
        graph_files = files_in_text(graph_raw, root, exts)
        missed = sorted(grep_files - graph_files)

    tok = None
    tg = count_tokens(graph_raw) if a.graph else 0
    tr = count_tokens(grep_raw)
    if tr is not None and tg is not None:
        tok = tr + tg

    audit_pass = not missed
    result = {
        "symbol": sym,
        "langs": langs,
        "grep_caller_files": sorted(grep_files),
        "graph_caller_files": sorted(graph_files) if graph_files is not None else None,
        "omitted_by_graph": missed,
        "complete_caller_files": sorted(grep_files | (graph_files or set())),
        "audit_pass": audit_pass if a.graph else None,
        "approx_tokens": tok,
    }

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"impact-audited  «{sym}»")
        if a.graph:
            print(f"  graph tool reports {len(graph_files)} caller file(s): {sorted(graph_files)}")
        print(f"  grep ground truth  {len(grep_files)} caller file(s): {sorted(grep_files)}")
        if a.graph:
            if missed:
                print(f"  🚨 AUDIT FAILED: graph tool omitted {len(missed)} direct caller(s): {missed}")
                print( "     → the index is missing these dependency edges; do not trust its "
                       "'no other callers'. Complete set = union above.")
            else:
                print("  ✅ AUDIT PASSED: grep found no caller the graph tool missed.")
        if tok:
            print(f"  ~{tok} tokens")

    sys.exit(2 if (a.graph and missed) else 0)


if __name__ == "__main__":
    main()
