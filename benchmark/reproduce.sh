#!/usr/bin/env bash
# Reproduce the impact-audited benchmark end to end.
# Requires: git, gitnexus 1.6.3 (npm i -g gitnexus@1.6.3). Optional: pip install tiktoken.
#
# Tool versions used for the published numbers in RESULTS.md:
#   GitNexus 1.6.3  (npm i -g gitnexus@1.6.3)
#
# Repos are cloned at the exact commits used for the original measurement.
# Full SHAs verified 2026-08-06:
#   psf/requests     23953c0c875219a715f081cf3de7c149a7629ccf
#   ranaroussi/yfinance  38c73ce33fb1ee77d37a0998c95c06e60356298e
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p repos && cd repos

declare -A REPOS=(
  [requests]="https://github.com/psf/requests"
  [yfinance]="https://github.com/ranaroussi/yfinance"
)
declare -A PINS=(
  [requests]="23953c0c875219a715f081cf3de7c149a7629ccf"
  [yfinance]="38c73ce33fb1ee77d37a0998c95c06e60356298e"
)
declare -A SRC=( [requests]="src" [yfinance]="yfinance" )

for name in "${!REPOS[@]}"; do
  if [ ! -d "$name" ]; then
    git clone -q "${REPOS[$name]}" "$name"
    git -C "$name" checkout -q "${PINS[$name]}"
  else
    echo "  (using existing clone; commit should be ${PINS[$name]})"
  fi
  echo "=== indexing $name with GitNexus ==="
  gitnexus analyze "$PWD/$name" --force --skip-agents-md --name "bench-$name" \
    > "../analyze_$name.log" 2>&1 || true
  (grep -c 'scope extraction failed' "../analyze_$name.log" || true) \
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
