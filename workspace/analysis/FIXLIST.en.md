# Fix List

Status of the code-level defects and gaps. Completed items first (motivation /
what was done / result), then what remains open — in priority order, with a
worklist at the end. Guardrail tests live under `workspace/tests/`
(`python3 tests/run_tests.py`; currently 117 pass + 1 expected-fail, which is
open item O1).

---

## Completed

### C1. Fabric config as the single source of truth (workstream A-1)

**Motivation.** Physical structure lived in five disconnected places: level
counts hand-copied into `mlx_system.py` constants, geometry hardcoded twice
(`nested_floorplan` and `place_grid/place_linear`, mutually unaware), per-hop
latencies in a Python dict, and level counts re-derived at runtime by parsing a
finished run's stats — the authority pointed backwards.

**What was done.** `models/fabric/mlx300.yaml` (concrete chip data: N-level
list, per-level `per_parent`/`mesh`/link params, every placeholder tagged with
its DR) + `scripts/fabric.py` (schema, loader, count/monotonicity validation,
`verify_against_stats`). All legacy constants now derive from the config;
`crossbar_stats.hierarchy()` was demoted from source-of-truth to a consistency
sentinel that raises on divergence. `CIMSIM_FABRIC` selects config variants per
process.

**Result.** The company's "3×3 macro layout is odd, try 2×4" request was
answered **without touching a single line of code** — a variant YAML plus an
env var re-ran the full experiment set:

| | 3×3 (default) | 2×4 variant (`mlx300_2x4.yaml`) |
|---|---|---|
| heatmap spread (ffn1) | 3.62× | **1.50×** (no macro adjacent to the hub) |
| empty slots | 1 macro slot + 1 slot/core | none |
| worst-case hops / propagation | 12/3/2 → 136 ns/op | **10/3/2 → 116 ns/op** |
| macro mean hops (energy) | 1.3125 | 1.5 (distance surcharge ×1.6 = +0.12% block) |
| headline ratios (1.01×/10.12×/93%) | — | unchanged |

Figures: `crossbar_comm_heatmap.png` vs `crossbar_comm_heatmap_2x4.png` (all
`*_2x4.*` artifacts sit beside the canonical ones).

> **One line:** hardware geometry is now configuration, and a config swap
> reproduces a whole company what-if in one command.

### C2. Explicit Placement object (workstream A-2)

**Motivation.** "Which logical block sits in which physical slot" existed only
as enumeration order inside `nested_floorplan`; layouts could not be input,
compared, serialized, or exchanged with the search side, and the two coordinate
generators could disagree.

**What was done.** `scripts/placement.py`: a frozen, JSON-serializable
`Placement` (per-level slot tables) with `verify()` (capacity, no overlap,
in-range, fabric match), coordinate derivation (`leaf_coords`/`level_coords`),
and the `sequential_fill` generator.

**Result.** Proven identities: `sequential_fill` reproduces the legacy
floorplan **bit for bit** (256/256 coordinates), `fabric.slots("macro")` ==
`place_grid(8)`, and the old `place_linear` is formally a **fabric variant**
(8 macros in a line do not fit a 3×3 mesh — hardware arrangement, not
placement; the type system now enforces the distinction we once got wrong).

> **One line:** a layout is now data — constructible, checkable, exchangeable —
> instead of a side effect of loop order.

### C3. Placement reaches every consumer (workstream A-3)

**Motivation.** Even with a Placement object, the three cost paths (per-pair
flows, distance-energy, propagation latency) each had their own coordinate
source; propagation latency was a constant 136 ns/op for every layout — the
tracked xfail.

**What was done.** `build_flows`, `position_aware_cost`, and `level_max_hops`
all consume `(fabric, placement)`; `run_op(op, placement=p)` swaps a whole
layout through one argument. Unit discipline is explicit: the energy overlay
uses per-level slot units (so `reference_hops` semantics hold), latency uses
global leaf-grid units (so the legacy 12/3/2 reproduce).

**Result.** The full experiment set re-ran after the rewiring: **all 12 system
totals byte-identical** (`compare_baseline` ALL MATCH, rel diff 0.00e+00 on
every number), every analysis figure and ratio unchanged — and the propagation
xfail flipped to a passing test (a different macro slot set now moves the
worst-case hops).

> **One line:** re-plumbing with zero semantic drift, machine-verified; latency
> finally sees the layout.

### C4. Real traffic structure replaces the uniform placeholder (workstream B)

**Motivation.** `build_flows` divided totals by 256 (`in_per_xb = total/nX`)
and subtree-summed trunk links, while the multicast/reduction structure parsed
from the mapping went unused: multicast trunks were overcounted (ffn1 input
trunk ×32), partially-utilized ops were smeared across the full array, and the
per-crossbar map varied in geometry only.

**What was done.** `scripts/traffic.py` (Stage 1, placement-free): spatial
factors from the mapping (M-split ⇒ input multicast, C-split ⇒ output
reduction at the parent hub, P/N ⇒ partition; resident weights carry no flow),
volumes de-multiplied from Timeloop's own leaf counters with a divisibility
guard that raises on disagreement. `build_flows(model="structured")` is the
default; `"uniform"` survives only as the v0 comparison baseline. Goldens
re-baselined to `_v1` (`tests/CHANGELOG.md`).

**Result.** Verified by 8 hand-derived tests on the frozen ffn1 mapping
(factors C=4·P=2 / M=4 / M=8), and the 12 system totals stayed pinned
(compare_baseline ALL MATCH — B touches the analysis layer only):

| quantity | v0 (uniform) | v1 (structured) |
|---|---|---|
| ffn1 glb↔macro input trunk | in_leaf × 32 | **in_leaf × 1** (−32×) |
| ffn1 output edges (all levels) | subtree sum | **identical** (no reduction below the die hub — no overcorrection) |
| per-level volume×distance share | 65% / 25% / 10% | **60% / 24% / 16%** (top level still dominates, now on real volumes) |
| ffn1 per-crossbar spread | 3.58× (geometry only) | **3.62×** (structure + geometry) |
| tiny 2×2 matmul | smeared over 256 crossbars | **32/256 active, idle zeroed** (spread 1.25× within the active set) |

> **One line:** the communication analysis now reports what the mapping
> actually does — multicast counted once, idle silicon visible — with Timeloop's
> own counters as the conservation check.

### C5. Guardrail test suite + golden protocol (task D8)

**Motivation.** Two costing bugs (a 7300× unit mismatch, a 512× decode
overcount) lived in the overlays because nothing checked code against the
declared model; headline numbers had no re-runnable anchors.

**What was done.** `workspace/tests/`: 59 tests + 2 expected-fails (fast suite
seconds, `--slow` adds one real mapper run), fixtures frozen with an
independent extraction path, versioned goldens (`_v0`/`_v1` + CHANGELOG), and
`compare_baseline.py` as the manual tier-1 gate for the 12 system totals.

**Result.** Caught a real latent bug on day one (`perceive`'s `volume` field
silently zeroed by same-name stats sections; fixed by section-merge), enforced
the A-3 no-drift acceptance, and forced an honest re-spec of a sloppy xfail via
the XPASS protocol. The suite gated every workstream above.

> **One line:** code-vs-model faithfulness is now machine-checked, and every
> published number has a frozen, versioned anchor.

### C6. Tooling and hygiene (alongside the above)

- **Unified figure driver** `scripts/make_figures.py`: 7 stages cover every
  figure; `--tag` runs config variants without clobbering canonical outputs;
  the heatmap finally has a committed generator, plus `replot_heatmap()`
  re-renders from saved comm dumps in seconds (style iterations no longer cost
  mapper minutes). Heatmap readability: YlOrRd colormap (no pure white/black),
  three-tier hierarchy borders, aspect-true canvas.
- **Environment split fixed**: io_study mounted into the container
  (`docker-compose.yaml`), `scripts/__init__.py` imports the notebook stack
  lazily — pure modules import on the host, and the two-stage host/container
  workarounds are gone.
- **Dead code removed**: `analyze_gpt2_offload.py` (predated the write model;
  superseded by the three-scenario study), `analyze_crossbar_value.py`
  (superseded by the device×workload compare), and three orphan figures with no
  generating script.

### C7. Contention modeling, two tiers (workstream W1)

**Motivation.** No link carried a bandwidth anywhere, so `Bandwidth throttling =
1.00` in every stats file: Timeloop's stall mechanism existed but had never been
activated, compute latency was a zero-contention figure, and latency was
therefore insensitive to layout. A retracted claim ("finite router bandwidth →
75–1200×") had left an IOU in the writeup for a sourced replacement.

**What was done.** Two tiers with an explicit ownership split, composed by
**max, never sum** (they lower-bound the same serialization):

- **T1 — Timeloop native**, owns *storage hubs*: `Level.hub_bandwidth_words_per_cycle`
  from the fabric config is pushed into the glb spec; Timeloop stretches its own
  cycle count. Verified live: 64 w/c stretches ffn1 compute 2.6 ms → 0.84 s, and
  16→4 w/c scales exactly 4×.
- **T2 — analytic per-link**, owns *network links*: `crossbar_comm.link_occupancy()`
  computes `volume/bandwidth` per link from the v1 structured flows and takes the
  worst. It is **level-agnostic by construction** — when D2D lands (O2), die-to-die
  links feed the same function unchanged.

Both default to `null` (unlimited) in the shipped config, so the term is
identically zero and no system number can move. `analyze_bandwidth_sweep.py`
sweeps both tiers (T2 in-process; T1 one cached mapper run per point).

**Result.** The sweep produced a number that is *not* a placeholder:

| | value | provenance |
|---|---|---|
| ffn1 heaviest router-link volume | 51.2 M words | v1 structured traffic, reconciled to Timeloop counters |
| device cycle time | 1.449 µs | CiMLoop's calibrated macro model |
| **T2 knee (compute-bound ⇄ link-bound)** | **≈2.9×10⁴ words/cycle ≈ 20 GB/s** | derived from the two above |

20 GB/s per macro link sits **squarely inside the range real on-die NoCs
occupy**, so the real chip could land on either side. Per-phase robustness was
measured with the same script:

| phase | dominant term | bandwidth at which communication overtakes it | verdict |
|---|---|---|---|
| prefill | compute, 249 ms | first op (`av`) flips at ~3.6e4 w/c ≈ **25 GB/s** | inside the plausible band — **at risk** |
| decode | **write, 13.3 ms** | ~166 w/c ≈ **0.11 GB/s** | implausibly slow — **10.12% / 90% / 93% hold** |

Regime discipline is enforced in the docs: stalls-on and stalls-off are
different accounting regimes, and sweep multipliers are sensitivities, not
findings, until DR-2 calibrates the axis. Figure: `bandwidth_sweep.png`.

**Honest scope (measured, not assumed).** This tier is volume-aware and
level-aware but **NOT placement-aware**: swapping macro slots 0↔7 leaves the
serialization bit-identical (7.249810e-02 s both). `link_occupancy` reads
volumes and bandwidths, never distance, and the tree model gives each hub→node
a private link with no shared segments. So bandwidth alone does not connect
placement to latency — see O5.

> **One line:** contention is now modeled where each tier has the information
> for it, the D2D hook is in place, and DR-2 became decisive (the knee sits at a
> bandwidth real chips actually have) — but the placement→congestion link still
> needs routed contention.

### C8. Interconnect schemes as a first-class input (workstream W2)

**Motivation.** Two open items had the same root. **O5**: contention did not
follow placement -- permuting macro slots left the serialization bit-identical,
because every hub->node edge was modelled as a private wire with no shared
segment, so the chain *placement -> congestion -> latency* was broken. **O4**:
three distance metrics were in the tree (NN-min, volume-weighted Manhattan, the
collaborator's lambda-1) with no principled way to choose. Underneath both: the
communication scheme was a hardcoded assumption, on a platform whose whole point
is retargeting across designs.

**What was done.** `scripts/interconnect.py` -- a registry where every scheme
answers three questions (`hops` for distance, `path` for the shared resources a
flow occupies, `resources`), selected **per level** in the fabric config:

```yaml
link: {topology: mesh, params: {routing: xy, hub: center, multicast: native}, ...}
```

Parameters are per-scheme (a mesh takes routing/hub/multicast, a tree takes
branching/level_length), validated at config load. Three schemes ship:

| scheme | models | contention | closes |
|---|---|---|---|
| `star` | private link per node (the pre-W2 model) | none -- the lower bound | the zero-drift default |
| `mesh` | 2-D grid, XY routing | shared segments | **O5** |
| `h_tree` | k-ary tree, root shared by all | root bottleneck; `merges_by_depth()` is the lambda-1 metric | **O4** |

`link_occupancy` now accumulates traffic onto whatever resources a scheme's
`path()` returns, so `star` reduces exactly to the old per-flow form and `mesh`
makes routes overlap. `traffic.reduction_hyperedges()` supplies the missing
structure the tree metric needs (which instances must merge) -- previously
traffic.py produced per-level aggregates only.

**Results.**

*Zero drift, machine-verified.* The entire distance and contention plumbing was
replaced and all 12 system totals stayed byte-identical (`compare_baseline`
ALL MATCH). The identity rests on `leaf_distance == slot_distance x pitch`, so
`star` reproduces 1.3125 (energy) and 12/3/2 (propagation) exactly.

*The mechanism, stated precisely.* Under a routed scheme with equal flow
volumes, congestion depends only on which slots are occupied -- permuting is
provably a no-op. Placement bites when flows differ in volume: on the 3x3 mesh a
4x-volume node costs **3V on the hub and 6V in a far corner**.

*A ranking reversal.* Hand-derived, then reproduced in code:

| layout | heatmap spread (distance) | mesh peak segment (congestion) | total |
|---|---|---|---|
| 3x3 | 3.62x (worse) | **3V (better)** | 10V |
| 2x4 | **1.50x (better)** | 4V (worse) | 12V |

The same two layouts rank in **opposite orders** under the two metrics -- 2x4
spreads distance evenly but, being elongated, funnels more flows onto one
segment. Uniform is not uncongested, and a single metric would have given the
opposite recommendation.

> **One line:** how data travels is now an input rather than an assumption, and
> with it the chain placement -> congestion -> latency is finally connected --
> for the schemes where that chain physically exists.

### C9. O4 resolved: the three metrics were never rivals

NN-min is retired (it overstates: 31% vs 17.8%). The other two are the cost
models of two different topologies and both now live in the registry:
volume-weighted Manhattan is `mesh`, the collaborator's lambda-1 is `h_tree`
(`merges_by_depth`, telescoping so each merge is charged once at its outermost
boundary -- the same nested decomposition his solver uses). The critique that
pairwise distance overcounts co-resident tiles is **correct for a tree and wrong
for a mesh**; ours was the reverse.

The consequence for the search side is structural, not cosmetic: **the placement
objective itself changes with the scheme** -- a mesh wants proximity, a tree
wants shared parentage. Remaining piece: reconciling `h_tree.merges_by_depth`
against `die_solver`'s own merge counts needs his tiling model rather than ours,
so the two implementations are not yet cross-checked numerically.

### C10. Measured impact of contention: schemes, layouts, and the system denominator

**Motivation.** W2 built the mechanism (C8) but no number said how much it
matters, at which denominator, or why it is a latency story rather than an
energy story. The user asked for concrete results and figures.

**What was done.** Three scripts, all sharing one method — one real mapper run
per phase supplies the flows and compute/write terms, every scheme × layout ×
bandwidth combination re-scored analytically on top:

- `analyze_contention_impact.py` — single op (ffn1 prefill): scheme table,
  layout table, segment load map.
- `analyze_placement_tradeoff.py` — 7 variants, energy AND latency together:
  scatter with Pareto front, per-link load vectors.
- `analyze_contention_system.py` — the whole GPT-2 stack, both phases, with
  per-scheme thresholds (bandwidth below which the stack moves 1% / 2×);
  `--replot` redraws from the saved JSON without re-running the mapper.

**Results** (operating point 16,384 words/cycle; anchors pinned in
`tests/test_contention_anchors.py`):

| result | value |
|---|---|
| op latency across schemes (ffn1) | 1.75× (star) → 13.96× (bus); scheme alone **8.00×** |
| op latency across layouts (mesh, 3×3) | centre → corner glb = **1.67×**; on the fill-exact 2×4 the peak is hub-position-invariant (4× both) — the lever is grid-shape-dependent |
| system energy across ALL variants | **1.007×** total; two pairs identical to 4 decimals with 8.00×/1.60× latency between them |
| whole-stack prefill (314.65 ms stall-free) | 1.25× (star) → 6.70× (bus); glb position alone 1.64× |
| whole-stack decode (14.77 ms stall-free) | caps at **1.18×** — the serial K/V write (90%) shields it |
| decode counter-example | mesh-corner beats mesh-centre (15.62 vs 15.70 ms): partial occupancy couples active slots to hub position |

**Framing shift (user decision):** link bandwidth is a **platform input** like
the fabric geometry and the scheme, not a pending calibration — the shipped
`mlx300.yaml` values are example defaults. Results are therefore stated as
multipliers, orderings, and thresholds against that input, never absolute
milliseconds.

> **One line:** contention is a latency lever (8× across schemes, 1.6× from the
> floorplan) that the energy account is structurally blind to — and it is
> phase-dependent, capped at 1.18× in decode by the serial write.

### C11. D2D exists (workstream W3): the registry one level up

**Motivation.** O2 -- the die was a flat single-instance off-die port: no
inter-die topology, no position, no contention; the die level in the fabric
was degenerate (`per_parent: 1`, `mesh: [1,1]`, no price).

**What was done.**
- `mlx300_multidie.yaml`: 24 dies on 6×4, one layer per die; die link carries
  scheme + params + bandwidth + `pj_per_word: 5.0` (example inside the
  UCIe-class 2–8 pJ/word public band) + `reference_hops: 1.0`. The shipped
  default stays single-die = D2D-free.
- `interconnect.Star` learned node→node (through the hub switch, both spokes);
  `Mesh`/`Bus`/`HTree` already routed arbitrary pairs.
- `link_occupancy` accepts `nodes: (a, b)` flows -- die flows feed the SAME
  function as the on-die tree (level-agnostic became literal).
- `die_to_die_activation` rewritten on (fabric, placement, assignment):
  layer→die assignment is data; energy bills only the SURPLUS
  `max(hops − reference_hops, 0)` per word -- replace, never add. Single die
  and adjacent dies are zero by construction.
- `verify_against_stats` counts per die (a run always models one die).
- The former `xfail_single_die_d2d_degenerate_invariant` promoted per the
  XPASS protocol into `tests/test_d2d.py` (group 15, 7 tests): degeneracy,
  replace-not-add, conservation + the ffn2-output reconciliation anchor,
  per-scheme node→node paths, D2D contention through link_occupancy,
  snake-beats-sequential.

**Results** (`analyze_d2d.py`, closed-form on contention_system.json
denominators). The operating mode decides what the layout can touch:

- *Single pass* (one request in series): transfers (2.97 ms/boundary) hide
  behind the whole stack's compute (249 ms) — invisible at any sane link
  speed, and the chart says so instead of pretending otherwise.
- *Pipelined* (the serving mode; `die_pipeline_interval`): the busiest die
  wire races one stage (13.1 ms). At the example 256 w/c the adversarial
  assignment costs 1.36× and bus 5.21×; at 64 w/c the assignment ALONE spans
  1.81–5.43× while snake holds 1.00×. Knees per assignment: snake 32 /
  sequential 64 / adversarial 256 / bus 1,024 w/c.
- Bandwidth-free quantities: busiest wire 1/2/6 boundaries, surplus energy
  0/39.3/217.6 µJ (snake/sequential/adversarial). Decode is untouchable in
  both modes.

Pipeline identities, the exact 2.0 sequential/snake ratio, the 23× bus beat,
and the assignment ordering are pinned (group 15, 11 tests).

> **One line:** the package joined the same scheme registry, priced by surplus
> so the old totals survive bit-for-bit -- and the honest headline is a
> threshold table, not a bottleneck claim.

### C12. O10 closed: over-capacity ops now have two explicit mechanisms

**What was done.** `run_op(op, overcapacity=...)`: `reject` (default -- the
tripwire), `temporal_rewrite`, `spatial_multi_die`. Probe op (C=2048,
M=16384 = 67.1M cells = 4 dies), measured end to end:

| mechanism | energy | latency | notes |
|---|---|---|---|
| silent (before) | 2.93 mJ | 2.60 ms | reload billed at zero -- the bug |
| temporal_rewrite | 9.64 mJ | 11.32 ms | every cell reprogrammed per pass (K/V-write primitives); endurance ~1e8 inferences |
| spatial_multi_die | 2.24 mJ | 0.65 ms compute | zero reload; +4 intra-op die flows x 14.4M words -> at 256 w/c the busiest die wire serializes 163 ms |

So the mechanism CHOICE is a bandwidth question the platform now answers:
spatial wins on energy always (4.3x) and on latency only above ~3,700
words/cycle of die bandwidth; below that the rewrite is faster but burns
endurance. Implementation: capacity guard + `static_rewrite_cost` (charged
via the K/V write channel, mapping cross-checked against parsed temporal
weight tiles); spatial = `chip_in_system.meshX` + a closed-form per-die
tiler that PINS all four levels' C/M spatial factors (macro/core/crossbar +
chip) and bans glb's temporal C/M remainder sinks; die split extracted by
traffic.py (`inter_chip_in_system_spatial` -> LevelSplit("die")), intra-op
die flows feed the same link_occupancy. Tests: group 16 (capacity, 6).

**Two extra findings caught on the way:**
1. **The greedy M-first `maximize_dims` can force phantom reloads even for
   shapes that FIT** (it starves C and glb's `C=-1` remainder sink absorbs
   the difference at zero cost). GPT-2 medium dodges it only because its
   C=1024 fills the row budget exactly. The spatial policy's explicit tiler
   bypasses the greedy entirely.
2. **A weight occupies TWO cells** (W4A8 differential encoding,
   N_WEIGHT_SLICES=2 -- the `Y in [0:2)` split in every mapping): one die
   holds 8.39M weights, not 16.78M. The capacity model now uses
   CELLS_PER_WEIGHT=2; doc claims scaled by the old constant are wrong by 2x
   (see O11).

> **One line:** no silent path remains -- an over-capacity op must pick a
> mechanism, both are priced with existing primitives, and the choice
> between them is itself a platform result (a die-bandwidth threshold).

---

## Open

Priority order (what closing each one buys):

| # | gap | what closing it buys | blocks |
|---|---|---|---|
| O11 | layer→die examples ignore the 2-cells-per-weight capacity | feasible assignments + corrected §1/§6 claims; re-run analyze_d2d | follow-up of C12 |
| O6 | `distance_router` doesn't exist; solver constant underivable | reconnects the search side; lifts the 47% citation ban | search-side integration |
| O7 | contention = max over busiest wire, no queueing | tightens every latency/throughput multiplier (both levels benefit at once) | credibility of W2/W3 numbers |
| O1 | core/crossbar links carry no energy (the 1 xfail) | turns the 1.50×/3.62× and 17.8% rankings into joules | DR-1 input |
| O8 | bus energy charged by distance-to-driver | removes the artifactual star↔bus energy tie | per-scheme wire model |
| O9 | offload receiving side unmodeled | completes the offload account (die↔unit link + KV streams on die links) | offload go/no-go fidelity |

### O1. Only the macro-level router carries an interconnect energy model *(xfail)*

`inter_core_in_macro_spatial` / `inter_crossbar_in_core_spatial` are zero-energy
fanout markers, so the 3.62× and 17.8% results are rankings, not costs.
Fix: per-level link energy placeholders in the fabric config feed a CostModel
energy path (the per-hop/per-word values are platform inputs — example defaults
until a chip's own values are filled in; the request for the company's values
is DR-1).


### O7. The contention model reads only max(compute, busiest wire)

`link_occupancy` keeps one number per resource and the critical path takes
`max(compute, serial)` — i.e. perfect compute/communication overlap and no
queueing. Two consequences, both measured: the true latency lies between the
max and the sum of the two terms, and load vectors with equal peaks are
indistinguishable (`3,2,1,1,1,1,1` ≡ `3,3,3,3,3,3,3`) though their power and
hotspots differ. Fix: report the max/sum bracket per op, or add an overlap
coefficient as a per-link param; expose the full per-link vector (already
computed) to consumers instead of only the peak.

### O8. Bus energy is underestimated by construction

`Bus.hops()` charges Manhattan distance to the driver, so bus and star tie at
mean_hops 1.3125 and get identical re-priced energy — but a real bus drives the
whole line's capacitance every transfer. The latency side (whole level
serialized) is right; the energy side needs a per-scheme wire model (e.g.
`hops()` returning the full bus length regardless of node). Until then the
"identical energy, 8× latency" pair in C10 is partly a model artifact — the
qualitative conclusion (energy is contention-blind) survives, the exact tie
does not. Same gap, smaller: `h_tree.level_length` defaults to 1 per level
where a physical H-tree lengthens toward the root.

### O11. Layer→die assignments must respect the honest capacity

Fallout of the CELLS_PER_WEIGHT correction (C12): a gpt2-medium LAYER is
25.2M cells = 1.5 dies, so the W3 example assignment "one layer per die, 24
dies" is capacity-infeasible as stated -- the D2D results' multipliers and
mechanisms stand (boundary volumes and the busiest-wire integers do not
depend on it), but the example configuration needs either 2 dies/layer
(48 dies) or op-granular assignment, and the SUMMARY §1/§6 capacity claims
("one layer = 75% of a die", "packing would need ~6-8 dies") need the 2x
correction. Fix: recompute the assignment examples with `dies_for_op`, update
docs, re-run analyze_d2d with a feasible assignment.


### O9. The offload receiving side is unmodeled

Scenario B counts only what stays on chip: the attention unit itself, the
die↔unit link, and the KV traffic that link carries are absent. Two
consequences now that offload results are headline (C10/C11): the offload
contention numbers are an on-chip-side lower bound, and KV-offload streams
sharing the die links would add contention the model does not see (§6 items
8/11 in the SUMMARY). Fix: give the attention unit a node on the package grid
and route its flows through the same registry — the machinery exists; the
work is the traffic model for Q/K/V/attention-out volumes.

### O6. `distance_router` is referenced but does not exist

`die_solver.py` sets `W_MACRO_DIST = 4.0` ("measured: distance_router ERT @
HOP_DISTANCE=4", lines 96-108) and `placement_sim_compare.py` feeds
`spec.variables["HOP_DISTANCE"]` (line 74). That component is **not in the
branch, not in io_study, not in the installed Accelergy plugin, and not in
upstream** — `mlx_die.yaml` is byte-identical to main. Consequences:

- `placement_sim_compare.py` cannot run (it also needs `fetch_weights_hbm2_ws`,
  which is still in io_study — see the merge list);
- the **47%** distance-weighted improvement is not reproducible from committed
  code. **Citation rule until it is: the 11% flat figure may be used, the 47%
  may not appear in any external material.** (`ROUTER_PJ_PER_WORD = 48.254` is
  fine — it is our known flat-router 48.3 pJ.)

**Proposed fix, no ERT needed.** 4.0 is exactly the maximum macro-to-macro slot
Manhattan distance on the 3x3 macro mesh, so the constant is derivable from the
fabric geometry we already have. Using the **mean** instead (3x3: 1.929,
2x4: 2.000) additionally makes the solver sensitive to the macro layout — the
"next step up in fidelity" the solver's own docstring flags as missing.

---

## Merge list: io_study → workspace

The agreed direction is one tree. Concretely (env junk like `.cache`/`.jupyter`
excluded):

**Move over (unique to io_study):**
- `scripts/die_floorplan.py`, `scripts/die_locality.py`
- `models/arch/3_chip/cim_tile_array.yaml`
- `models/arch/4_system/fetch_weights_hbm2_ws.yaml`, `multi_chip_hbm2.yaml`
- `tutorials/bert100m_crossbar_logging.ipynb`, `llama3_attention_offload.ipynb`,
  `tile_array_demo.ipynb`

**Reconcile (same path, both modified — need a joint diff pass):**
- `scripts/crossbar_stats.py` — your MLX-level overrides + the W4A8 `array_cols=2`
  fix vs our `hierarchy()` addition (the one known real overlap)
- `models/arch/2_tile/mlx_core.yaml`, `models/arch/3_chip/mlx_die.yaml`,
  `models/include/variables_common.yaml` — your edits vs ours, diff before merging
- `scripts/utils.py`, `processors.py`, `tl_output_parsing.py`, `__init__.py` —
  likely small deltas, diff to confirm
- One decision: `fetch_weights_hbm2_ws` (keeps DRAM for the one-time weight load)
  vs our `ws_chip2chip_link` (no weight DRAM) — pick one as default or keep both
  as config options

**Drop (unmodified duplicates of the upstream/workspace copies):**
- everything else under `io_study/scripts/`, `io_study/models/`,
  `io_study/tutorials/` that diffs clean against workspace

---

## Next up (worklist, priority order)

1. **Search-side integration** — fix O6 (derive `W_MACRO_DIST` from fabric
   geometry; mean vs max makes the solver layout-sensitive), then use our
   evaluator as the solver's validator (Spearman harness). Lifts the 47% ban.
2. **O7: queueing / overlap upgrade** — report the max/sum bracket per op, or
   an overlap coefficient per link; expose the full per-link vector. Both
   contention tiers (on-die W2, D2D W3) tighten at once.
3. **O1: lower-level link energies** — placeholder per-hop/per-word fields
   already exist in the fabric config (with `slot_pitch_um` to derive from);
   wire them into a cost path and the xfail flips.
4. **O9: offload receiving side** — attention unit as a package node.
5. **io_study merge** — the file-by-file list above; mechanical.

Not scheduled until asked: multi-die capacity packing (assumption 2), giant
layers across dies (`meshX>1`).
