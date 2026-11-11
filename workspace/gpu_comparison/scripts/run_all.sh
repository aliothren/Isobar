#!/bin/bash
# Table III: every configuration in its own process with the fabric of its die
# (the tiler's die menu is fixed at import), then the summary.
# Run from workspace/ (inside the container or with the host Python environment).
set -e
cd "$(dirname "$0")/../.."
PY=${PYTHON:-python3}
for c in gpu_comparison/configs/*.json; do
  m=$($PY -c "import json,sys; print(json.load(open(sys.argv[1]))['die_macros'])" "$c")
  if [ "$m" = "8" ]; then unset CIMSIM_FABRIC; else export CIMSIM_FABRIC=models/fabric/variants/mlx300_multidie_m$m.yaml; fi
  $PY gpu_comparison/scripts/cim_request.py --config "$c"
done
unset CIMSIM_FABRIC
$PY gpu_comparison/scripts/summarize.py
