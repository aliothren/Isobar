# 03 Hardware: the fabric file

A fabric file describes the machine the simulator prices. Copy the closest
shipped file, edit it, validate it, then point the run at it.

## Start from a shipped file

| file | use it for |
|---|---|
| `models/fabric/mlx300_multidie576.yaml` | a package of many dies; the main configuration (24 by 24 mesh) |
| `models/fabric/mlx300_multidie48.yaml` | the 48-die package of the GPT-2-medium class studies |
| `models/fabric/mlx300.yaml` | one die: macro, core and crossbar levels only |
| `models/fabric/simba.yaml` | a digital chiplet package (the Simba reproduction); shows the `digital_throughput` device class |

```bash
cp models/fabric/mlx300_multidie576.yaml models/fabric/mine.yaml
```

## The schema

```yaml
fabric:
  name: my-package
  schedule_slack: 1.0          # >= 1; multiplies every occupancy; 1.0 = the busiest-wire bound
  device:
    name: "..."
    cycle_seconds: 1.4485714285714284e-06   # per input bit slice
    input_slices_per_mvm: 7                 # row time = cycle x slices (10.14 us here)
    calibration: "..."
    # device_class: reram_macro | digital_throughput   (default reram_macro)
  levels:                      # top to bottom
    - name: package
      per_parent: 1
    - name: die
      per_parent: 576          # instances inside one parent
      mesh: [24, 24]           # [X, Y] slots; slots >= per_parent, spares stay empty
      ports: {ratio: 2.0}      # port ratio kappa: injection and ejection ports at 2 x the link rate
      slot_pitch_um: 25000.0   # optional; lets ns_per_mm be used instead of ns_per_hop
      link: {name: "die<->die", topology: mesh, params: {routing: xy, hub: center},
             ns_per_hop: 20.0, pj_per_word: 10.0, reference_hops: 1.0, calibration: "..."}
    - name: macro
      per_parent: 8
      mesh: [2, 4]
      link: {name: "glb<->macro", topology: star, params: {}, cimloop_component: router,
             reference_hops: 1.0, ns_per_hop: 5.0, calibration: "..."}
    - name: core
      per_parent: 4
      mesh: [2, 2]
      link: {name: "macro<->core", topology: star, params: {}, ns_per_hop: 2.0, pj_per_word: 0.0}
    - name: crossbar
      per_parent: 8
      mesh: [4, 2]
      link: {name: "core<->crossbar", topology: star, params: {}, ns_per_hop: 1.0, pj_per_word: 0.0}
  digital:                     # the die's vector unit; every field optional
    lanes: 64
    clock_hz: 1.0e9
    pj_add: 0.05
    pj_mul: 0.6
    pj_lut: 1.0
    intermediate_bits: 16
  attention_unit:              # the external attention engine under offload; optional
    mac_per_second: 2.0e12
    pj_per_mac: 1.0
    kv_words_per_second: 25.6e9
    kv_pj_per_word_read: 50.0
    kv_pj_per_word_write: 50.0
    kv_capacity_words: 2.0e9
    link_bandwidth_gbps: 12.5
    link_pj_per_word: 10.0
    n_units: 1
  cimloop:                     # the CiMLoop configs this fabric must agree with
    system: ws_chip2chip_link
    chip: mlx_die
    tile: mlx_core
    macro: wan_nature_2022
```

### Field notes

- **`link` of a level** is the network joining that level's instances to
  their parent's hub. `macro.link` is the on-die NoC; `die.link` is die to
  die.
- **`topology` and `params`** select an interconnect scheme from
  `scripts/interconnect.py`: `star` (a private link per instance, no
  parameters), `mesh` and `torus` (`routing: xy`, `hub: center`), `ring`,
  `h_tree`, `bus`, `cmesh`, `hier_wide`, `express`, `switch`. Each scheme
  documents its own parameters in its `PARAMS` table in that file. The
  placement search and the phase diagram were run on `mesh` with `xy`.
- **`ns_per_hop` or `ns_per_mm`**, not both. With `ns_per_mm` the loader
  multiplies by the level's `slot_pitch_um`.
- **`pj_per_word`** is the link's energy per 8-bit word beyond
  `reference_hops` hops. `0.0` records an unpriced level;
  `cimloop_component` names a calibrated CiMLoop component that is
  re-priced by distance instead.
- **`bandwidth_gbps` or `bandwidth_words_per_cycle`** on a link declares a
  static-contention limit for the CiMLoop-side occupancy readouts. It is
  not the bandwidth the deployment evaluator uses; see below.
- **`device`** is checked against the CiMLoop macro's cycle on every
  mapper run, so a fabric cannot declare a row time its macro does not
  have. `device_class: digital_throughput` switches that check off for an
  abstract digital engine and makes the declared cycle the truth.
- **`idle_power_w`** on a level would add static power. It is unset in
  every shipped file and the frozen results are dynamic-only.
- **`ports: {ratio: kappa}`** on a level declares its port ratio: each
  instance's one injection and one ejection port run at kappa times the
  level's link rate. The command line reads the die level's value as the
  default `--kappa`; the experiment scripts set kappa themselves.
- **`psum_word_bytes`** under `fabric:` (beside `schedule_slack`) is the
  width of a partial sum crossing a link in 8-bit words; default 2. The
  evaluator reads it for the hand-offs whose producer is split along the
  reduction dimension.

## Validate

Every `cimsim_cli.py` subcommand loads and validates `--fabric` first,
so the cheapest check is the band computation:

```bash
python3 scripts/cimsim_cli.py phase --fabric models/fabric/mine.yaml --bandwidths 0.4
```

In Python:

```python
import sys
sys.path.insert(0, "/home/workspace")
from scripts import fabric as fm
fab = fm.from_yaml("/home/workspace/models/fabric/mine.yaml")
print(fab.name, [(l.name, l.per_parent, l.mesh) for l in fab.levels])
print("row time us", fab.device.t_mvm_s * 1e6, "dies", len(fab.slots("die")), "grid", fab.level("die").mesh)
```

The loader raises a `ValueError` naming the field on a bad
file, for example `die: mesh (20, 20) has fewer slots than per_parent 576`;
likewise for both propagation forms at once, a slack below 1, or an
unknown device class.

## Point a run at it

There are two ways, and they cover different code paths.

**The process default.** Every script that calls `fabric.default()`
(the mapper runs such as `run_2p7b_block.py` and `op_breakdown.py`, and
the anchor registry's device conversions) reads the file named by
`CIMSIM_FABRIC`:

```bash
CIMSIM_FABRIC=/home/workspace/models/fabric/mine.yaml python3 -c \
  "import sys; sys.path.insert(0, '/home/workspace'); from scripts import fabric; print(fabric.default().name)"
```

**The evaluator, the search, the band, the BookSim check.** Pass the
file to the command line:

```bash
python3 scripts/cimsim_cli.py evaluate --fabric models/fabric/mine.yaml --deployment pi.json --bandwidth 0.4
```

In Python, `Workload2p7B` loads `mlx300_multidie576.yaml` unless a fabric
is passed in: `se.Workload2p7B(fabric=fm.from_yaml(path))`.

The two paths are independent. When you change the device block, set
both, or the phase diagram's device axis and the workload will disagree.

## What the evaluator takes from elsewhere

These are options of the command line (arguments of `score` in Python),
not fabric fields, in this version:

| quantity | command line | Python | main configuration |
|---|---|---|---|
| link bandwidth per direction | `--bandwidth` | `score(..., d2d_gbps=...)` | 0.4 GB/s, contrast 12.5 |
| port ratio kappa | `--kappa`, default the fabric's `ports.ratio` | `W.port_ratio = ...` | 2.0 |
| device speed scale | `--device-scale` | `score(..., device_scale=...)` | 1.0 |
| D2D energy per word, propagation per hop | `--d2d-pj-per-word`, `--d2d-ns-per-hop` | `PJ_D2D`, `NS_PER_HOP_D2D` in `scripts/search_eval.py` | 10 pJ, 20 ns |

## Changing the package geometry

Edit `mesh` on the die level; keep `per_parent` at or below the slot count
and at or above the dies the workload needs (544 for the 2.7B class). A
12 by 48 copy of the main fabric, evaluated on the random fill:

```bash
sed 's/mesh: \[24, 24\]/mesh: [12, 48]/' models/fabric/mlx300_multidie576.yaml > models/fabric/mesh12x48.yaml
python3 scripts/cimsim_cli.py baseline --fabric models/fabric/mesh12x48.yaml --rule random --out analysis/r12.json
python3 scripts/cimsim_cli.py evaluate --fabric models/fabric/mesh12x48.yaml --deployment analysis/r12.json --bandwidth 0.4 --phases prefill --loads 0
```

The same in Python:

```python
import dataclasses as dc, sys
sys.path.insert(0, "/home/workspace")
from scripts import fabric as fm, search_eval as se, search_baselines as sb
fab = fm.from_yaml("/home/workspace/models/fabric/mlx300_multidie576.yaml")
levels = [dc.replace(l, mesh=(12, 48)) if l.name == "die" else l for l in fab.levels]
fab12 = dc.replace(fab, name="mesh12x48", levels=levels).validate()
W = se.Workload2p7B(fabric=fab12)
W.port_ratio = 2.0
pi = sb.generate("random", W, seed=0)
print(f"{se.score(pi, W, d2d_gbps=0.4).t_opt_s * 1e3:.2f} ms")
```

Both print 2149.70 ms (the same random fill on the 24 by 24 mesh is
2153.11 ms). The frozen sweep did exactly this for its 12 by 48 cells.

## Fabrics the results do not cover

The evaluator's hand-off term routes on the die level's scheme. Every
published placement result is on `mesh` with XY routing. The other
schemes load and route, and a `torus` or `ring` die level runs, but its
numbers are a new experiment, not a variant of the frozen ones.
