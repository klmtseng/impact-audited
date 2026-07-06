#!/usr/bin/env bash
# Reproduce the impact-audited benchmark end to end.
# Requires: git, gitnexus (npm i -g gitnexus). Optional: pip install tiktoken.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p repos && cd repos

declare -A REPOS=(
  [requests]="https://github.com/psf/requests"
  [yfinance]="https://github.com/ranaroussi/yfinance"
)
declare -A SRC=( [requests]="src" [yfinance]="yfinance" )

for name in "${!REPOS[@]}"; do
  [ -d "$name" ] || git clone --depth 1 -q "${REPOS[$name]}" "$name"
  echo "=== indexing $name with GitNexus ==="
  gitnexus analyze "$PWD/$name" --force --skip-agents-md --name "bench-$name" \
    > "../analyze_$name.log" 2>&1 || true
  grep -c 'scope extraction failed' "../analyze_$name.log" \
    | xargs echo "  files GitNexus dropped:"
  echo "=== scanning contamination for $name ==="
  python3 ../scan_contamination.py "$PWD/$name" "../analyze_$name.log" "${SRC[$name]}"
  echo "=== example audit (should FAIL loudly) ==="
  case "$name" in
    requests) SYM=to_key_val_list ;;
    yfinance) SYM=camel2title ;;
  esac
  python3 ../../impact_audited.py "$SYM" --path "$PWD/$name" \
    --graph "gitnexus impact {sym} -r bench-$name" || true
done
echo
echo "Done. Per-repo JSON in benchmark/results_*.json; see benchmark/RESULTS.md."
