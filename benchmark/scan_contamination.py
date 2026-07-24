#!/usr/bin/env python3
"""Quantify how many symbols' impact answers a graph indexer must under-report,
attributed only to files the indexer's OWN log says it failed to parse.

Definition lines are never counted as call sites (`def sym(` / `class sym(`
are excluded), so a symbol merely *defined* in a dropped file does not count.

Two tiers are reported:

  strict — the symbol is DEFINED in a file the indexer kept, but has a real
           call site inside a dropped file. The graph contains the node but
           cannot contain that edge → the impact answer is silently
           incomplete, guaranteed.
  broad  — any symbol with a real call site inside a dropped file, including
           symbols defined in dropped files (there, tool behavior varies:
           some answer incompletely, some fail loudly; treat as upper bound).

Usage:
  python scan_contamination.py <repo_path> <analyze_log> <src_subdir> \
         [--drop-pattern 'scope extraction failed for ([^:]+):']
"""
import argparse
import json
import os
import re
import subprocess


def grep(pattern, cwd, path):
    """Run the benchmark's grep without passing repository data through a shell."""
    return subprocess.run(
        ["grep", "-rnE", pattern, "--include=*.py", "--", path],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    ).stdout


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

    # symbol -> definition files
    defs = {}
    for line in grep(
        r"^(def|class) ([A-Za-z_][A-Za-z0-9_]+)", repo, a.src
    ).splitlines():
        m = re.match(r"([^:]+):\d+:(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]+)", line)
        if m and len(m.group(2)) >= 4 and not m.group(2).startswith("__"):
            defs.setdefault(m.group(2), set()).add(m.group(1).lstrip("./"))

    tiers = {"strict": {"total": 0, "hits": []}, "broad": {"total": 0, "hits": []}}
    for n, deffiles in sorted(defs.items()):
        esc = re.escape(n)
        callers = set()
        for line in grep(rf"\b{esc}\s*\(", repo, ".").splitlines():
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            fp, text = parts[0].lstrip("./"), parts[2]
            if re.search(rf"\b(def|class)\s+{esc}\b", text):
                continue  # a definition line is not a call site
            if os.path.exists(os.path.join(repo, fp)):
                callers.add(fp)
        if not callers:
            continue
        inside_dropped = sorted(callers & dropped_core)
        tiers["broad"]["total"] += 1
        if inside_dropped:
            tiers["broad"]["hits"].append((n, inside_dropped))
        if not (deffiles & dropped):  # node is in the graph
            tiers["strict"]["total"] += 1
            if inside_dropped:
                tiers["strict"]["hits"].append((n, inside_dropped))

    print(f"\n== {os.path.basename(repo)} ==")
    print(f"dropped core files ({len(dropped_core)}): {sorted(dropped_core)}")
    out = {"repo": os.path.basename(repo), "dropped_core": sorted(dropped_core)}
    for tier, d in tiers.items():
        n, tot = len(d["hits"]), d["total"]
        pct = 100 * n / max(tot, 1)
        print(
            f"[{tier}] symbols considered: {tot} | "
            f"provably-incomplete impact answers: {n} ({pct:.0f}%)"
        )
        print(f"        examples: {d['hits'][:6]}")
        out[tier] = {
            "total": tot,
            "incomplete": n,
            "pct": round(pct),
            "examples": d["hits"][:15],
        }
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"results_{os.path.basename(repo)}.json",
    )
    with open(path, "w") as output:
        json.dump(out, output, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
