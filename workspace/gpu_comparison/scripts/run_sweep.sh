#!/bin/bash
export MPLBACKEND=Agg; cd /home/yuxinr/yuxin/cimloop/workspace
PY=/home/yuxinr/miniforge3/envs/far/bin/python
run() { m=$2; if [ "$m" = "8" ]; then unset CIMSIM_FABRIC; else export CIMSIM_FABRIC=models/fabric/variants/mlx300_multidie_m$m.yaml; fi; $PY gpu_comparison/scripts/sweep.py --model $1 --macros $m ${3:+--split $3} > gpu_comparison/sweep/log_$1_m$m${3:+_$3}.txt 2>&1; }
mkdir -p gpu_comparison/sweep
run opt13b 8 & run opt13b 16 & run opt13b 32 & run opt13b 4 & run opt13b 8 col &
run gemma7b 8 & run gemma7b 16 & run gemma7b 32 & run gemma7b 4 &
wait; echo SWEEP_DONE >> gpu_comparison/sweep/log_done.txt
