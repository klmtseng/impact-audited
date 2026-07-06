#!/usr/bin/env python3
"""Quantify how many symbols' impact answers a graph indexer must under-report,
attributed only to files the indexer's OWN log says it failed to parse.

Airtight by construction: a symbol counts as "provably incomplete" only if grep
finds it called inside a file the indexer reported dropping — so that dependency
edge cannot be in the graph, regardless of grep's precision elsewhere.

Usage:
  python scan_contamination.py <repo_path> <analyze_log> <src_subdir> \
         [--drop-pattern 'scope extraction failed for ([^:]+):']
"""
import argparse, json, os, re, subprocess


def sh(cmd, cwd):
    return subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("log", help="the indexer's analyze/index log (stdout+stderr)")
    ap.add_argument("src", help="subdir whose top-level symbols to scan")
    ap.add_argument("--drop-pattern", default=r"scope extraction failed for ([^:]+):",
                    help="regex with one group capturing a dropped file path")
    a = ap.parse_args()
    repo = os.path.abspath(a.repo)
    drop_re = re.compile(a.drop_pattern)

    dropped = {m.group(1).strip() for line in open(a.log) if (m := drop_re.search(line))}
    dropped_core = {f for f in dropped
                    if "test" not in f.lower() and not f.endswith("__init__.py")}

    names = set()
    for line in sh(f"grep -rhoE '^(def|class) ([A-Za-z_][A-Za-z0-9_]+)' --include=*.py {a.src}", repo).splitlines():
        n = line.split()[-1]
        if not n.startswith("__") and len(n) >= 4:
            names.add(n)

    hits, total = [], 0
    for n in sorted(names):
        gr = sh(f"grep -rlE '\\b{re.escape(n)}\\s*\\(' --include=*.py .", repo)
        callers = {ln.lstrip("./") for ln in gr.splitlines() if ln}
        callers = {f for f in callers if os.path.exists(os.path.join(repo, f))}
        if not callers:
            continue
        total += 1
        inside_dropped = sorted(callers & dropped_core)
        if inside_dropped:
            hits.append((n, inside_dropped))

    pct = 100 * len(hits) / max(total, 1)
    print(f"\n== {os.path.basename(repo)} ==")
    print(f"dropped core files ({len(dropped_core)}): {sorted(dropped_core)}")
    print(f"symbols with callers: {total}")
    print(f"provably-incomplete impact answers: {len(hits)} ({pct:.0f}%)")
    print(f"examples: {hits[:8]}")
    out = os.path.join(os.path.dirname(__file__), f"results_{os.path.basename(repo)}.json")
    json.dump({"repo": os.path.basename(repo), "dropped_core": sorted(dropped_core),
               "total": total, "incomplete": len(hits), "pct": round(pct),
               "examples": hits[:20]}, open(out, "w"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
