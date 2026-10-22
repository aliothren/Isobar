#!/bin/bash
# every configuration in its own process with the fabric variant of its die (the tiler's die menu is fixed at import)
export MPLBACKEND=Agg; cd /home/yuxinr/yuxin/cimloop/workspace
PY=/home/yuxinr/miniforge3/envs/far/bin/python
for c in gpu_comparison/configs/*.json; do
  id=$(basename $c .json); m=$($PY -c "import json;print(json.load(open('$c'))['die_macros'])")
  if [ "$m" = "8" ]; then unset CIMSIM_FABRIC; else export CIMSIM_FABRIC=models/fabric/variants/mlx300_multidie_m$m.yaml; fi
  $PY gpu_comparison/scripts/cim_request.py --config $c --out gpu_comparison/cim_requests_$id.csv || echo "FAILED $id"
done
