# 03 Hardware

This page shows where each hardware parameter is set, in which unit, and whether changing it requires new per-operator measurements (accounts, see [04 Models](04_models.md)). Some parameters are command-line options of a deployment, some live in a fabric file, and two are constants in the code.

## Common changes

| you want to change | where | example | new accounts? |
|---|---|---|---|
| mesh link bandwidth | command line | `run_experiments.py --custom --bw 1.6` (GB/s per direction) | no |
| die port bandwidth | command line | `--kappa 4` (port = κ × link bandwidth) | no |
| mesh size | command line | `--grid 40,40` (default: the smallest near-square mesh that holds all dies and units) | no |
| routing | command line | `--routing yx` (default `xy`) | no |
| number, position and grouping of digital units | command line | `--units 4 --position edge --split head --resources total` | no |
| digital-unit speed, K/V memory, unit interface | command line | `--unit-param kv_words_per_second=51.2e9` (table below) | no |
| hop delay and link energy of the mesh | code: `scripts/search_eval.py` | `NS_PER_HOP_D2D = 20.0` (ns per hop), `PJ_D2D = 10.0` (pJ per byte per hop) | no |
| digital vector unit on each die (norms, activations) | fabric: `digital:` block of `models/fabric/mlx300_multidie576.yaml` | `lanes: 64`, `clock_hz: 1.0e9`, `pj_add`, `pj_mul`, `pj_lut` (pJ per operation) | no |
| macros per die | fabric variant | `make_fabric_variants.py`, then `--macros N` | **yes**, `--die-macros N` |
| how operators are split over dies | command line | `--tiling col` | **yes**, `--tiling col` |
| macro, arrays, on-die network, CIM device speed | fabric file and CiMLoop macro | see below | **yes** |

"No" means that the deployment is evaluated directly with the new value. The per-operator costs do not depend on it, because they describe what happens inside one die.

## Digital units

Each deployment places one or more digital units in reserved mesh slots. A unit runs attention (QKᵀ, softmax, AV) and holds the K/V cache in its own memory. The reference unit is defined in `scripts/offload.py` (`REF_UNIT`):

| parameter | reference | unit | meaning |
|---|---|---|---|
| `mac_per_second` | 2e12 | operations / s | compute rate (multiply-accumulates and softmax operations) |
| `pj_per_mac` | 1.0 | pJ / operation | compute energy |
| `kv_words_per_second` | 25.6e9 | bytes / s | K/V memory bandwidth |
| `kv_capacity_words` | 2e9 | bytes | K/V memory capacity |
| `kv_pj_per_word_read`, `kv_pj_per_word_write` | 50 | pJ / byte | K/V access energy |
| `link_bandwidth_gbps` | 12.5 | GB/s per direction | the unit's interface to the mesh |
| `link_pj_per_word` | 10 | pJ / byte | interface energy |
| `buffer_bytes` | 8e6 | bytes | working buffer for attention scores |
| `call_overhead_s` | 0 | s | fixed time per call |

`--unit-param NAME=VALUE` overrides any of these for one run and can be repeated. A value is one byte per "word": activations and K/V values are 8-bit.

With `--units K` (K = 1, 2 or 4):

| option | effect |
|---|---|
| `--split layer` | each unit serves a contiguous group of layers |
| `--split head` | each unit serves a group of attention heads in every layer |
| `--resources per_unit` | every unit has the full reference resources |
| `--resources total` | the reference total is shared: `mac_per_second`, `kv_words_per_second`, `kv_capacity_words`, `link_bandwidth_gbps` and `buffer_bytes` are divided by K; energies per operation and per byte are unchanged |
| `--position` | slot of a single unit: `center` (default), `edge` or `corner`; two or four units are spread evenly over the mesh |

## Fabric files

A fabric file (`workspace/models/fabric/*.yaml`) describes the physical chip:

- the levels package → die → macro → core → crossbar, how many of each and in which grid;
- the network at each level;
- the analog device;
- the digital vector unit.

`scripts/fabric.py` reads the files and documents every field. The CiMLoop description of the same die (`models/arch/`) is checked against the fabric on every CiMLoop run.

| file | used for |
|---|---|
| `mlx300_multidie.yaml` | measuring the per-operator costs (8 macros per die) |
| `variants/mlx300_multidie_m{4,16,32}.yaml` | the same die with 4, 16 or 32 macros |
| `mlx300_multidie576.yaml` | the starting point of every deployment; the deployment replaces its mesh size and keeps the rest |
| `mlx300.yaml` | a single die (intra-die analysis) |
| `simba.yaml` | Simba, for the silicon reference |

The fields you are most likely to read or edit, in `mlx300_multidie.yaml`:

```yaml
fabric:
  device:
    cycle_seconds: 1.4485714285714284e-06   # seconds per input bit slice; 7 slices = 10.14 us per row
    input_slices_per_mvm: 7
  levels:
    - name: die
      per_parent: 24          # die slots used while measuring (not the deployment's mesh)
      mesh: [6, 4]
    - name: macro
      per_parent: 8           # macros per die
      mesh: [2, 4]            # their arrangement on the die
      link: {topology: star, ns_per_hop: 5.0, ...}   # on-die network between global buffer and macros
    - name: core
      per_parent: 4           # cores per macro
    - name: crossbar
      per_parent: 8           # 256 x 256 arrays per core
  digital:                    # vector unit for element-wise operators
    lanes: 64
    clock_hz: 1.0e9
    pj_add: 0.05              # pJ per 16-bit operation
    pj_mul: 0.6
```

A process reads one fabric when it starts, selected by `CIMSIM_FABRIC=models/fabric/<file>.yaml`. The measurement scripts and `run_experiments.py` set it themselves from `--die-macros` and `--macros`, so you only set it for your own scripts.

## A die with more or fewer macros

```bash
# host or container: create the variants (4, 16 and 32 macros are listed in MACROS of the script)
python3 scripts/make_fabric_variants.py
# container: measure the model's operator costs on the 16-macro die -> results/accounts/gemma7b_S512_m16.json
python3 scripts/measure_accounts.py --die-macros 16 gemma7b 512
# host or container: evaluate a deployment with 16-macro dies
python3 scripts/run_experiments.py --custom --model gemma7b --macros 16
```

For another macro count, add it to `MACROS` in `make_fabric_variants.py` as `N: (mesh_x, mesh_y)`, and allow it in the `--macros` choices of `run_experiments.py`.

## CIM device speed

The per-operator costs come from CiMLoop's model of a NeuRRAM-class macro, at one input row per 10.14 µs. There are two ways to study another speed:

- **Recompute without new measurements.** Only the CIM compute time scales with the device speed, so a stored placement can be re-evaluated at other speeds by scaling that term:
  - every record contains `cost_grid.csv`: the best baseline and the searched placement at 1/16× to 32× the reference row rate, and at link bandwidths from 0.05 to 50 GB/s;
  - the phase analysis (`export_fig1_phase.py`, [06 Analyses](06_analyses.md)) scans the rate continuously;
  - the GPU comparison has `device_rate_factor`.
- **Model a different macro.** Change the macro in `models/arch/1_macro/` (CiMLoop) and the `device:` block of the fabric files together, then re-measure the accounts. CiMLoop stops with an error if the two disagree.
