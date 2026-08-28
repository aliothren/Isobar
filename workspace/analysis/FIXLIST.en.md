# Fix List

Status of the code-level defects and gaps. Completed items first (motivation /
what was done / result), then what remains open — in priority order, with a
worklist at the end. Guardrail tests live under `workspace/tests/`
(`python3 tests/run_tests.py`; currently 185 pass + 1 expected-fail, which is
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
| prefill | compute, 747.6 ms (v2) | first flip (`ffn2`) at 8.0e3 w/c ≈ **5.6 GB/s** on star / 1.7e4 ≈ 16.7 GB/s centre / 2.8e4 ≈ 27.8 GB/s corner | star/centre now clear of the 20 GB/s example; hub-heavy layouts still **at risk** |
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

(The two whole-stack rows and the counter-example are the exclusive-die
(v1) basis; the co-residency re-score (C14) supersedes them — 813.06 ms
stall-free, 1.00-2.42x across schemes, glb lever 1.40x, decode caps 1.15x
-- and on the v3 physical wire accounting (C17): 1.00-4.13x, 1.50x, 1.34x --
and the counter-example no longer appears at the system denominator, though
its mechanism stays pinned. The single-op rows ran on their own config and
are unaffected.)

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
- `mlx300_multidie.yaml`: 24 dies on 6×4 (superseded for 355M by the feasible 48-die config, C13); die link carries
  scheme + params + bandwidth + `pj_per_word: 10.0` (midpoint of Simba GRS's
  measured 6.6–14 pJ/word band, see ANCHORS.md) + `reference_hops: 1.0`. The shipped
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
  behind the whole stack's compute (249 ms on this entry's v1 basis;
  747.6 ms after C14 — even more headroom) — invisible at any sane link
  speed, and the chart says so instead of pretending otherwise.
- *Pipelined* (the serving mode; `die_pipeline_interval`): the busiest die
  wire races one stage (13.1 ms). At the example 256 w/c the adversarial
  assignment costs 1.36× and bus 5.21×; at 64 w/c the assignment ALONE spans
  1.81–5.43× while snake holds 1.00×. Knees per assignment (48-die feasible config): snake 64 /
  sequential 128 / adversarial 512 / bus 4,096 w/c.
- Bandwidth-free quantities: busiest wire 1/2/6 boundaries, surplus energy
  0/183.5/1368.4 µJ (snake/sequential/adversarial, 48-die config, at the measured 10 pJ/word). Decode is untouchable in
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
### C13. O11 closed: the feasible layer→die configuration is now the one in use

A gpt2-medium layer is 25.2M cells = 1.5 dies, so the earlier "one layer per
die, 24 dies" example was capacity-infeasible. The configuration now used by
every 355M die-level analysis is `mlx300_multidie48.yaml`: 48 dies on 6×8,
TWO dies per layer (attention half: qkv + K/V arrays + out_proj; FFN half:
ffn1 + ffn2, filling its die exactly), 47 hidden-state hand-offs per pass.
Re-scored results: worst-ordering energy +0.48% (was +0.15% under the
infeasible config); pipelined knees 0.04–0.35 GB/s for routed orderings
(35–280× under the GRS anchor) and 2.8 GB/s for a shared-interposer bus —
only 4.4× under the anchor, the one pressured case at 355M. Docs, figures,
and the report were updated to this configuration.

---

### C25. Wire volumes in values: the 14x / 48x unit error

**What was wrong.** Since the structured traffic model (C4, v1) the leaf
volumes were Timeloop's "Total scalar accesses" of the row drivers and the
ADCs taken as 8-bit words. CiMLoop counts the Inputs dataspace in input
bit slices (the X loops, 7 per signed 8-bit word) and the Outputs
dataspace in output bits (the Z loops, 8 per word); every physical cell
column of a weight (Y at the column level, 2 under differential encoding)
converts on its own ADC; and the total adds fills (and updates) to the
reads. Net: inputs 14x, outputs 48x the values (frozen ffn1 fixture:
917,504 = 65,536 x 7 x 2 and 1,572,864 = 32,768 x 8 x 2 x 3). C4's
"reconciled against Timeloop's counters" was the divisibility guard, not
a unit check. Timeloop's own per-level counts show each value entering the
die once and each level once per multicast group (fills = reads at the
core input buffer and the row drivers) -- the input register is already
in CiMLoop's arch; there was no physical re-read.

**What was done.** `traffic.extract` takes row-driver and ADC READS,
divides by the unit factors parsed from the mapping (X product, Z
product, the column-level Y factor), and guards that the leaves' distinct
slices reassemble P x C x N and P x M x N exactly once (raises otherwise;
43 real mappings pass); `crossbar_comm`'s uniform path follows. Value
units checked on 43 stored mappings of all shapes (355M, 2.7B, LM head,
probe). Fixture `stack_per_op_v5.json` (compute / write / digital rows
bit-identical to v4, all 60 serialization rows moved); `slow_golden_v2`
(tiny2x2 spread 1.25, unchanged). Groups 11 (values + the unit
decomposition + the reassembly guard), 14 (single-op table) and 17 (v5
block: readout, direction v5 <= v3, thresholds, ordering) re-pinned;
group 22 re-pinned. Full regeneration of every contention, anchored,
D2D, offload, tier, sensitivity, ledger and map output.

**What moved.** Every on-die contention number. Single op (ffn1 prefill,
16,384 w/c): 3.43-27.68x -> 1.00x (zero-overlap 1.07-1.59x), the scheme
ratios kept (bus/star occupancy 8.27x, corner/centre 1.67x). Whole stack
at the reference input: 1.00 / 1.52 / 1.88 / 2.27 / 4.08x -> 1.00x for
all (zero-overlap 1.01-1.11x); at the Simba anchor 1.03-5.24x -> 1.00x
(zero-overlap 1.01-1.15x); the buffer-position lever 1.49-1.55x -> 1.00x;
offloaded decode 1.03-5.61x -> 1.00x; 1% thresholds 5.7-45 GB/s ->
0.35-1.4 GB/s, doubling thresholds 1.4-22.6 GB/s -> only the bus, at
0.35 GB/s. Per-crossbar maps 3.62x / 1.50x -> 3.69x / 1.70x, region
17.8% unchanged, every energy unchanged. Ledger latency columns: the
perfect-overlap end is now compute + write (prefill on chip 1,253.7 ->
826.4 ms; offloaded end to end 749.6 -> 518.1 ms; decode 14.81 / 2.02 ms).
2.7B tiers: on-die multipliers 1.33x at the Simba NoC -> 1.00x. The
company report's within-die conclusion is rewritten: on this analog
device the on-die network hides behind compute at every published
bandwidth; the rankings survive as second-order (zero-overlap) and
energy orderings; D2D and offload conclusions unchanged.

### C23. O13 closed: the 2.7B block as a chain of die-sets, routed producer -> consumer

Two things were wrong with the spanning-operator (tier M / L) die flows:
they were routed hub <-> die (the attach point as a parent storage), and
they were SIZED by the structured traffic model's leaf counters -- the
row-driver reads (14x the input tensor: the bit-slice passes) and ADC reads
(48x the output piece) that are on-die re-reads out of the die's own
buffer, the outputs additionally at partial-sum width although a
column-split output is complete. The layer hand-offs had always used the
tensor once. Now (`llm_workload.block_chain / seat_block /
block_die_flows / die_flow_surplus_energy`): the block's five die-sets
(4 / 1 attention / 2 / 5 / 5) are seated disjointly on the 24-die package
in three styles (clustered = nearest free seats to the attach point in
chain order, row-fill, spread = farthest-point), every operator's input is
routed from the dies owning the previous operator's output as node-to-node
flows over the die mesh (column split: each consumer die receives every
owner's piece at activation width; input-row split: every consumer receives
all partial sums at partial-sum width -- generic, exercised by a test, no
2.7B op uses it), the offloaded attention routes Q/K/V to the attach point
and the output back, elementwise operators and the residual stream are not
routed (O24 convention), the last die-set feeds the next layer's first.
Latency: busiest die wire per die-set (link_occupancy, `width`-aware);
energy: surplus beyond one hop at 10 pJ/word. Readouts at the anchors:
tier M 3.10--6.20x -> 1.00x (zero-overlap 1.03--1.06x), 0--1.30 mJ ->
0--35 uJ; tier L prefill 1.22 / 2.14 / 1.97x -> 1.02x at every seating
(zero-overlap 1.26--1.28x), 0 / 792 / 829 mJ -> 30 / 27 / 30 mJ (+1.2--1.3%);
offloaded decode 1.27--2.50x -> 1.00--1.01x. Decomposition published
(`scale_tiers.json`: `tierL_v1`, `tierL_hub_once`, headline): the volume
basis 1.22--2.14x -> 1.02x and 792 -> 37 mJ, the routing 37 -> 27 mJ.
The combined figure's reading changed accordingly: die-set seating of a
spanning model is a ~1% energy lever and hides in latency at the measured
anchor; the latency lever at 2.7B stays on the die. Group 22
(`test_die_chain.py`, 8 tests): chain order / dies / splits, disjoint
seatings, tensor-once conservation, row-split partial sums, attach-point
routing when offloaded, decode = prefill / S, surplus rule, the readouts.

### C22. The unit link carries the die placement in every script

The offload streams' link energy (words x hops x pJ) had two hop
conventions: the offload script priced it at the seating's mean hop count
(3.5) while the scenario totals, the ledger and the two sweeps used the
interface's reference hop (1). Decision: die-side quantities carry the die
placement by default, the unit's internals stay average costs.
`llm_workload.unit_link_hops` (canonical 48-die snake seating, routed grid,
hub at the centre; a fabric with fewer dies falls back to the canonical
package) is the one source; every script passes it. Moves only the link
energy: unit 16.3 -> 17.6 mJ per prefill model (scenario B 211.0 -> 212.3
mJ, still 28% under A), ledger 212.22 -> 213.48 mJ (unit row 8.2%), decode
+2.5 uJ per token; no latency, ranking or dividend moves. Group 21 pins
the 3.5 and that hops touch the link energy alone (7 tests).

### C21. O9 closed: the offload receiving unit is a black-box interface

`fabric.AttentionUnit` (platform input DR-9): compute rate, average cost
per MAC, per-call overhead, K/V memory bandwidth / energy / capacity,
die<->unit link bandwidth / energy / reference hops, unit count. Shipped
generic public figures (ANCHORS.md): 2 T MAC/s and 1 pJ/MAC (edge-NPU
class), LPDDR4-class K/V memory (25.6 GB/s, 50 pJ/word, 2 GB), GRS-class
link (12.5 GB/s, 10 pJ/word), one unit for all layers. The unit sits at
the die scheme's hub (package attach point); `offload_streams` /
`offload_flows` put Q, K/V and the attention output on the die wires as
node-to-node flows (they share the wires with the hand-offs);
`attention_unit_cost` gives the per-layer chain (link out, compute at the
rate incl. softmax ops, K/V append + full read of the context, link
back), serial inside the unit (stated). Entered in
analyze_offload_contention (end-to-end stacks and multipliers, unit stage,
beat with the streams at the example bandwidths and at the anchor),
analyze_anchored_sweep (end-to-end decode rows), analyze_system_gpt2 (B
totals), the ledger (an "attention on the external unit" entry with link /
compute / K/V rows; the three offloaded ops point to it), and a new
sensitivity sweep (`analyze_offload_unit_sensitivity.py`: dividend vs
rate x unit count, decode ms and mJ per token vs context x K/V
bandwidth). Findings at the generic values: prefill +12.6 ms / +17.6 mJ
per model, dividend +124% kept (unit stage 8.61 < 10.63 ms; -57% at
0.25 T MAC/s); decode 0.99 -> 1.99 ms per token, energy 0.47 -> 1.76 mJ
(K/V reads), overtaking on-chip decode near 7k tokens of context; the
streams converge on the attach point: busiest wire 1/1/4/47 -> 36/25/38/143
hand-off equivalents, wire-bound at 256 w/c (10x), hidden at the 12.5 GB/s
anchor. Group 21 (6 tests): stream volumes equal the die's foregone writes
and projections, infinite unit reduces to the die side, decode scales with
context, generic magnitudes, dividend never exceeds the die side, streams
route to the hub. Die-side numbers stay published as a column.

### C20. Settings document for the company (2026-08-21)

`analysis/settings_and_assumptions.tex` (local, like the report): every
setting the simulator uses today, in plain language -- the models and
operators, the chip as configured (the four CiMLoop architecture files,
the crossbar variables, the fabric hierarchy), mapping and placement, where
each number comes from (framework output vs our formula, with the script),
the 19 assumptions with the number each one pushes, the replaceable inputs
(fabric file, constants, CiMLoop side, script arguments), and the
per-operator results. Opens with a v3 -> v4 version note.

### C19. O24 closed: the non-matmul operators run on a modeled digital unit

softmax, GELU, LayerNorm and the residual adds cannot run on the crossbars
(nothing to multiply by a resident weight); on every CIM design in the
literature they run in a digital vector unit on the same die, next to the
buffer. The die model now carries one: `fabric.digital` (DigitalUnit:
lanes, clock, per-op energies for add / multiply / table lookup,
intermediate width) -- every field a platform input (DR-8), shipped as a
generic configuration sized to the die's array output rate (64 lanes @
1 GHz; Horowitz ISSCC 2014 energies; sources in ANCHORS.md). Each operator
is closed-form (`llm_workload.block_elementwise_ops` /
`elementwise_cost`): energy = glb passes x elements x the CiMLoop-
calibrated glb access energy (15.47 pJ/word) + arithmetic x per-op pJ;
latency = arithmetic / (lanes x clock), in series with the matmuls (stated
assumption). softmax leaves the chip with the attention under offload
(`stays_on_chip_under_offload`); GELU / LayerNorm / residual stay. The
model's two ends are in too: the embedding read is priced at the DRAM
per-word energy (timed only if `offchip_bandwidth_words_per_cycle` is
set) and the LM head is a real matmul through the mapper (d x vocab
padded to 50,432, 7 dies, last token only). The half-layer stage rule now
has one source (`half_layer_stages`, used by analyze_d2d /
analyze_offload_contention / tests) and includes the digital terms.
Magnitudes at the generic configuration, 355M prefill: +8.9 mJ (+3.1%)
and +13.4 ms (+1.1%) per model -- glb passes dominate the energy
(softmax alone: 12.6 M glb accesses per layer), the digital arithmetic is
an order of magnitude below; decode: negligible. The digital unit's
width decides the latency share, so `analyze_digital_sensitivity.py`
sweeps lanes x clock (8-256 lanes, 0.5-2 GHz) for the real chip to be
read off the curve. The ledger's "未建模故未统计" rows for these operators
are now numbers; group 20 pins element counts, scaling, the offload
predicate, the stage single-source and the generic magnitudes. v4 fixture
(matmul rows bit-identical to v3, plus the four elementwise rows).

### C18. Per-operator cost ledger: one entry point (company request, 2026-08-21)

`scripts/op_breakdown.py` runs one transformer block per phase (sequential,
one mapper run per operator) and writes, under `analysis/op_breakdown/`,
a whole-model view per operator TYPE (the six matmuls x n_layers, shares
of the counted total, under both conditions -- attention on chip /
offloaded, where qk^t and av carry the marker "已卸载至片外单元,片上不统计"
-- plus rows for softmax, GELU, LayerNorm, residual adds and embedding/LM
head carrying "未建模故未统计"), then per-operator totals, then every cost
item on its own row: all 24 CiMLoop components (zero-energy links flagged
"unpriced, O1"), the placement re-pricing per component, K/V write, weight
rewrite, D2D hand-off surplus, and an explicit residual row (CiMLoop's
per-compute summary-table rounding, 0.1-0.5%); latency: compute, K/V write,
busiest-wire occupancy, network exposed at both O7 ends, propagation, D2D
hand-off, plus unmodeled rows (softmax/LN/residual, queueing, offload
receiving side, pipeline bubbles). Conservation is pinned (group 19):
energy rows sum to CiMLoop total + overlay + write + rewrite + D2D; latency
composes to both bracket ends; whole-model totals equal the system
script's (1,240.26 ms at mesh-centre / 16,384 w/c). Outputs: JSON, md,
per-phase item CSV and operator-type CSV, energy/latency/type-share
figures. Categories are deliberately NOT merged (decision: list everything
separately; mark the unmodeled rather than define boundaries). The
non-matmul rows were filled by O24 (C19); the offload receiving side (O9)
is the one cost still carrying the marker.

### C17. O22 + O23 closed: wires are accounted physically

Two conventions replaced by the physical ones, in one change, with the
before/after kept side by side (`accounting_variants` in
contention_system.json; `link_occupancy(duplex=False, psum_bytes=1.0)`
reproduces the old accounting exactly). (a) Direction: every flow keeps its
DOWN (inputs) and UP (outputs = partial sums) components; `path_directed()`
tags each resource with a direction and full-duplex schemes (every
point-to-point scheme; the bus is a shared medium) keep the two apart --
`Interconnect.DUPLEX`, per-link `duplex` override. The up route retraces
the down route (the reduction tree mirrors the distribution tree; XY-vs-YX
reply asymmetries are a routing-algorithm question, O19). (b) Width: the up
component is weighted by `fabric.psum_word_bytes` (default 2.0 = 16-bit
partial sums; platform input DR-7 -- W4 x A8 accumulated over K rows is
12 + log2(K) bits and cross-unit accumulation is commonly 16-bit).

What moved (355M, co-residency basis, perfect-overlap end): reference
input 1.00/1.13/1.58/1.34/2.42x -> 1.00/1.53/2.29/1.90/4.13x (star / centre
/ corner / tree / bus); Simba anchor 1.00-3.11x -> 1.03-5.31x, hub lever
1.50 -> 1.56x; decode cap 1.15 -> 1.34x; every threshold ~2x higher; the
single-op ffn1 table 1.75-13.96x -> 3.43-27.68x with all ratios intact
(scheme 8.07x, layout 1.67x). Direction split alone relaxes 0-20%, the
width alone raises 1.6-2.2x: the NET direction of the register is settled
-- the earlier numbers understated contention -- and pinned
(`test_v3_direction_understated_before`). At the die level the split
changes the chain integers: the sequential-rows wrap now walks back on the
opposite-direction wires (busiest 2 -> 1, equal to snake) and the
adversarial order halves (8 -> 4); bus 47 unchanged; knees 32/32/128/1024
w/c. Mechanism identities re-pinned with the old accounting kept as an
explicit `duplex=False` check (groups 15/18); v3 fixture frozen with
compute/write bit-identical to v2 and only `serial_s` re-accounted;
group-14/17 v3 pins added. Energy is untouched (the width enters the
contention tier; the energy overlay's partial-sum width is a hygiene
follow-up, transport being <2% of energy).

### C16. O7 closed: the compute/communication overlap is a published bracket

Every critical-path composition -- per op on die, single-pass and
pipelined at the die level, and the 2.7B tier -- now reports both ends:
max(compute, network) (perfect overlap via double buffering; the headline
end, identical to everything published before) and compute + network (zero
overlap). Emitted by `run_op` (`total_latency_sum_s`),
`die_pipeline_interval` (`interval_sum_s`), and every analysis script
(JSON `*_sum` fields; figures show the band, anchored bars carry
whiskers). Verified findings, all pinned (groups 17/18, 5 new tests, 147
green): (i) upper - lower == sum(min(compute, serial)) exactly -- the
bracket width IS the value of double buffering; (ii) both ends rank the
schemes identically at every anchor, so every placement ORDERING survives
O7 untouched; (iii) the doubling thresholds move at most 2x between ends
-- "when the network hurts badly" is bandwidth's decision, overlap-robust
-- while the 1% thresholds move ~64x -- "when the network is perfectly
invisible" is the microarchitecture's decision, not bandwidth's (at zero
overlap even FlooNoC leaves 33% on the bus, and the D2D bus's guard
bandwidth crosses the GRS anchor: a non-double-buffered interposer bus
pays ~8% of the beat there); (iv) Simba prefill spread 1.00-3.11x (overlap
end) vs 1.38-4.02x (zero-overlap end). The load-vector half of the
original item was already satisfied (link_occupancy returns `per_link`;
the segment maps consume it); the remaining refinement is a queueing
model, which can only move results within the bracket's interior.

### C15. O18 closed: the 48-die chain is pinned -- and the pinning caught a
24-vs-48 leftover

Group 18 (`test_feasible48.py`, 10 tests) pins the feasible configuration's
D2D chain on the v2 fixture, recomputed through the same committed
functions the analysis scripts call: half-layer stages (A 23.49312 ms with
the K/V write, B 10.38336 ms), the 6x8 chain's busiest-wire integers
(snake 1 / sequential 2 / far-pairs 8 / bus 47), surplus energies (0 /
183.5 / 1368.4 uJ), the pipelined knees (degrades below 32/64/256/1024
w/c, halves below 16/32/128/512; scenario B exactly one octave higher),
single-pass invisibility at the example point, and the 64 w/c beat tables.

Writing the pins exposed that `analyze_offload_contention.py`'s D2D table
and placement figures were still on the RETIRED 24-die configuration
(busiest integers 6/23, whole-layer stages) -- another unflagged leftover
of the 24-to-48 change, the exact class the process rule was written for.
Unified to the 48-die half-layer convention, the published offload numbers
changed: the pipelined dividend is +126% (stage 23.49 -> 10.38 ms), NOT
the +53% of v1 and NOT the +13% briefly quoted during the O12 cascade
(that figure mixed a half-layer A stage with a whole-layer B stage);
scenario B's D2D at 64 w/c reads snake 1.14x / sequential 2.29x /
far-pairs 9.15x / bus 53.7x on the v2 accounting (v3: far-pairs 4.57x, sequential = snake), every B knee doubles A's, and decode's D2D
under B is grazed at ~2.3x (sequential). Docs and figures re-cascaded;
CHANGELOG entry.

### C14. O12 closed: the co-residency basis (v2) is the published 355M basis

`run_op(share_plan=...)` pins each op's per-level spatial factors to its
48-die seating share (`SHARE_355M_48DIE`), with P/Q spatial fanout banned
as well -- the decisive detail found on the first attempt: an exclusive
die lets the mapper REPLICATE a small op's weights into idle arrays (up to
8 copies for out_proj) to parallelise over input rows, and that
replication was the source of the fast v1 bases. Without it every prefill
op computes in exactly 3584 cycles = 5.192 ms; decode is untouched (its
P=1 ops were never replicated -- a built-in cross-check that passed).
Re-scored end to end: stall-free prefill stack 314.65 -> 813.06 ms (92%
compute / 8% write); reference-input scheme spread 1.25--6.70x ->
1.00--2.42x; Simba-anchor spread 1.42--8.60x -> 1.00--3.11x with the hub
lever 1.65x -> 1.50x; every knee down ~4x; D2D pipeline stage 7.92 ->
23.49 ms so the D2D verdict tilts safer (bus margin 18x under GRS); energy
within 2% per op. The v1 exclusive-die basis stays frozen (v1 fixture +
`contention_system_fulldie.json`) as the reference the blind-test
coherence ran on; the register-predicted direction (co-residency shrinks
every multiplier) is itself pinned as a test, and the earlier "mid-anchor
condition divergence" finding did not survive the honest basis -- retired
everywhere.

## Open

### The results-affecting register (read this first)

Everything currently known to BIAS published numbers, in one place -- no
item here may be discovered by being asked. Rule added to the process: any
configuration or accounting change triggers a re-audit of this register,
recorded in the CHANGELOG (the 24-to-48-die change was made without one,
which is how O12 and O20 went unflagged).

| item | which quantity errs, and which way | consequence for the conclusion |
|---|---|---|
| ~~wire volumes in counter units~~ RESOLVED (C25) | was: on-die wire volumes 14x (inputs) / 48x (outputs) the values since v1 -- Timeloop's bit-slice / bit / access counters taken as 8-bit words | every on-die contention multiplier collapsed to 1.00x at the reference input and at every anchor (zero-overlap end 1.01-1.15x); thresholds 14-48x lower (0.35-1.4 GB/s); energies, D2D, offload and O13 unchanged; the within-die "latency lever" conclusion of the company report withdrawn |
| ~~O12 co-residency~~ RESOLVED (C14) | was: compute published with 256 arrays/op vs the true 96--128 share | prediction confirmed by the re-run: stack 314.65 -> 813.06 ms, every multiplier shrank (Simba spread 1.42--8.60x -> 1.00--3.11x), knees down ~4x; the v2 co-residency basis is now the published one and the direction is pinned as a test |
| O20 joint seating (block level RESOLVED by C23; whole model open) | was: the tier-L clustered row was each op's private best seat | the block's die-sets are now seated disjointly, so every tier-L row is an achievable block configuration; the joint seating of all 32 layers (O16) can only lengthen the hand-offs -- the published rows are its lower bound |
| ~~O13 attach-point routing~~ RESOLVED (C23) | was: intra-op die flows hub-routed AND sized by Timeloop's row-driver/ADC counters (14x the input tensor, 48x the output piece at partial-sum width) | producer -> consumer routing with the tensor once: 2.7B op 3.10--6.20x -> 1.00x (zero-overlap 1.03--1.06x), +58% -> +1.6% of the op; model 1.22--2.14x -> 1.02x (zero-overlap 1.26--1.28x), +34--36% -> +1.2--1.3%; the volume basis did almost all of it, the routing a third of the remaining energy. The 2.7B placement lever is a ~1% energy lever at the anchor |
| ~~O7 max-only contention~~ RESOLVED (C16) | was: only the perfect-overlap end published | both ends now published everywhere as a bracket; the identity upper-lower = sum(min(compute, serial)) and both-end scheme ordering are pinned as tests; queueing (equal-peak load vectors indistinguishable) remains the open refinement |
| ~~O22 shared-direction wires~~ RESOLVED (C17) | was: up+down on one wire | full-duplex direction-split wires are the default for every point-to-point scheme (bus stays a shared medium); alone it relaxed multipliers 0-20% (e.g. corner 1.97 -> 1.61x at Simba) |
| ~~O23 partial-sum width~~ RESOLVED (C17) | was: partial sums at 8-bit width | 16-bit partial sums up the tree (fabric.psum_word_bytes, platform input DR-7) roughly double every wire's load; it outweighs O22, so the NET direction is settled: the earlier numbers UNDERSTATED contention (Simba spread 1.00-3.11x -> 1.03-5.31x) |
| ~~O24 softmax/LayerNorm/residual missing~~ RESOLVED (C19) | was: the block's non-matmul operators absent from every total | modeled on the die's digital vector unit (platform input DR-8, generic 64 lanes @ 1 GHz): 355M prefill +8.9 mJ (+3.1%) and +13.4 ms (+1.1%), decode negligible; denominators grew, so every contention multiplier eased slightly; qualitative conclusions unchanged |
| ~~O9 off-chip attention unit off the clock~~ RESOLVED (C21) | was: offloaded columns counted the die side only | the unit is a black-box interface (rate, cost, K/V memory, link, count; generic public defaults, DR-9); end-to-end numbers published beside the die-side ones: prefill dividend +124% survives the generic unit (needs >~1.2 T MAC/s per unit), decode 0.99 -> 1.99 ms and 0.47 -> 1.76 mJ per token, streams converge on the attach point (busiest wire 1 -> 36 hand-off equivalents) |
| O21 context ceiling | not a bias: S=512 numbers unaffected; the seating is INVALID past ~2.5k tokens | validity-domain statement only |
| half-partition choice | the 23.49 ms stage and the +126% depend on the chosen attention/FFN split; another split moves both, direction unknown | second-order |
| batch = 1 | compute and traffic scale together with batch; ratios approximately invariant, unverified | scope statement |
| **O25 anchor identity** | not a number: the on-die anchors (Simba / ESP / FlooNoC) and the D2D anchor (GRS) are DIGITAL-ecosystem links, read as if they were the operating points of analog CIM chips. No fabricated analog CIM system publishes an on-die link bandwidth; the ones that describe their fabric are DMA + shared SRAM (MX100), board-level FPGA hubs (NeuRRAM, the Tsinghua multi-chip system) or compile-time scheduled (Mythic, HERMES) -- an estimated 2-20x below the digital anchors on die and 1-2 orders below GRS die to die | every "hidden behind compute at every published bandwidth" sentence is the reading of ONE cell (NeuRRAM-class device x digital-class link), where hiding was to be expected. Against an analog-reality tier (on die 0.4-8 GB/s, D2D 0.1-2 GB/s, both estimated) the same v5 thresholds put the 2.7B die chain's busiest link at its compute time near 0.5 GB/s and 5-8x past it at 0.1 GB/s [est, linear from the GRS reading] |
| **O17 device speed** | not a number: every threshold is a words-per-cycle reading at the NeuRRAM cycle (1.449 us x 7 slices = 10.1 us per MVM row); in GB/s the thresholds scale as 1 / t_MVM | NeuRRAM is the slow end of the analog spectrum (ISAAC-class 1.6 us per MVM row, 6x; HERMES-class ~130 ns, ~76x [derived]). At the fast end the on-die 1% band moves from 0.35-1.4 to 26-107 GB/s (Simba below the bus doubling point, FlooNoC inside the band) and the 2.7B chain's 1-1.8 ms per layer of die-link occupancy at GRS exceeds a ~0.4 ms compute -- both stories flip INSIDE the analog family |

Four cross-cutting readings, more important than any row: (1) ABSOLUTE
numbers are no longer systematically small: O12, O7 and O24 have each
paid their share (the zero-overlap end bounds the overlap side from
above; the non-matmul operators are in). What remains outside the totals
is the offload receiving side (O9) and the embedding read's TIME (priced,
not timed until an off-chip bandwidth is set) -- both stated per row in
the ledger. (2) With O7
closed the overlap assumption is a published BRACKET, not a bias: the
lower end is certified optimistic, the upper end certified pessimistic,
and both ends rank schemes identically. The wire-level direction
question is settled (C17): with per-direction wires AND 16-bit partial
sums the earlier numbers UNDERSTATED contention -- every multiplier grew
(pinned as a test). What remains at the wire level is the absent queueing
model, which can only push within the bracket's interior, not past its
ends, and the partial-sum width itself, which is a platform input (16-bit
default; the real ADC/accumulator width decides).
(3) The 2.7B placement lever, once read as 1.22--2.14x and +34--36%, is
~1% of energy and hidden in latency at the measured anchor (C23): the old
reading sized die-to-die flows by on-die counters. What remains open at
2.7B is the whole-model joint seating (O16), which can only lengthen the
block-level hand-offs.
(4) The v5 numbers are one CELL of a phase diagram -- model scale x device
speed x transfer paradigm x link tier -- and every published anchor sits in
the digital-ecosystem column of it. "Placement does not matter" is the
reading of the (NeuRRAM-class device x digital-class link) cell, where it was
never expected to; the deliverable is the diagram, not the cell (O25, O17).
The thresholds themselves are ours (traffic and device cycle; no anchor
enters them) and survive the re-reading unchanged.

### The factor map

Every orthogonal factor that determines a simulated result, with its
current owner and its open items. Bold items move current conclusions.

| category | factor | current solution | improvements (item) |
|---|---|---|---|
| device | array energy/latency model | CiMLoop's silicon-calibrated wan macro (NeuRRAM class: 1.449 us cycle, 7 input slices = 10.1 us per MVM row) | device speed as a fabric input + three silicon scales + the scaling law (**O17**); the cycle is hard-coded in six scripts (O17 prerequisite) |
| device | value-dependent energy | real per-model histograms (OPT-2.7b extracted); per-crossbar mode gated by device class | seed the CNN samples (hygiene) |
| device | weight / K-V write model | append-only geometry + per-cell/row-serial params (our overlay) | write params are platform inputs (DR-5); long-context K/V (O14) |
| per-op mapping | intra-op loop tiling | **provided by the CiMLoop mapper** (EDP search) under the op's co-residency share (C14) | default greedy path guarded by the residency tripwire |
| per-op mapping | over-capacity residency policy | three explicit mechanisms + closed-form tiler (C12) | input-row split untested (O15); dynamic ops (O14) |
| per-op placement | weight blocks -> macro/core/crossbar | Placement object + sequential fill; rankings measured | unpriced links keep it a ranking (O1); search (S3) |
| per-op placement | shared-buffer attach point | scheme parameter; 1.56x lever measured (v3 accounting, Simba anchor) | search (S3) |
| on-die wiring | interconnect organisation | scheme registry: star/mesh/tree/bus per level; full-duplex per-direction wires, bus shared (C17) | more schemes (O19); bus wire energy (O8); routing-algorithm asymmetries (XY vs YX replies, O19) |
| on-die wiring | transfer paradigm | schemes are wiring; the paradigm (DMA + shared SRAM, compile-time scheduled, NoC) is implicit | paradigm -> tier mapping: DMA/shared-SRAM -> shared medium at the T1 hub bandwidth, scheduled -> star, NoC -> mesh (**O25**); `schedule_slack` input (O26) |
| cross-die mapping | dies per op and split dimension | tiling planner (power-of-two aware, residency enforced) | cross-die addition path unexercised (O15); utilisation loss quantified, not optimised |
| cross-die mapping | layer/op -> die granularity | feasible 48-die config, two dies/layer (C13); co-resident per-op mapping (C14) | context ceiling (O21); half-partition is an assumption (register) |
| cross-die placement | die-group seating on the package | the block's die-sets seated disjointly, three styles (C23) | whole-model seating (**O16**); search (S4) |
| cross-die wiring | package interconnect organisation | same registry one level up, GRS-anchored, full-duplex (C17); producer-to-consumer routing, the tensor once (C23) | O19 applies |
| traffic accounting | multicast/reduction structure and units | v1 structured traffic in VALUE units (C25: reads / bit-slice, bit and cell-column factors; reassembly guard); down/up components kept, partial sums at 16 bits on wires (C17) | hyperedge membership convention (hygiene); partial-sum width in the ENERGY overlay (hygiene, transport <2% of energy) |
| traffic accounting | cross-die traffic classes | hidden-state hand-offs + intra-op slices + the offload streams to the attach point (C21); elementwise operators move through the glb only (C19, stated) | host I/O streams |
| contention | bandwidth & queueing model | two tiers; overlap published as a max/sum bracket (C16), off by default | the max end stated as the bound it is (any schedule, given the routing) and queueing / BookSim-class checks narrowed to the NoC paradigm (**O26**); joint tier sweep (hygiene) |
| contention | operating mode | single-pass + pipelined, stage = slower half | bubbles/imbalance beyond the max rule; batch>1 (register) |
| contention | critical-path composition | write + [max, sum](compute, network) + propagation -- both ends published (C16) | missing terms O24 |
| calibration | bandwidth operating points | platform inputs + published anchors (blind-test pinned) -- all of them digital-ecosystem links | anchor grid paradigm x tier with `status`, analog-reality rows (estimated), real-system -> registry mapping table (**O25**); primary ESP citation, HERMES supplement check (O25 hygiene); UCIe-class D2D anchor |
| calibration | per-level link energy | macro silicon-calibrated + re-pricing; D2D at GRS band midpoint | core/crossbar at zero (O1; ceiling ~2% of an op after C25); bus (O8) |
| energy | static / idle power | not modeled -- every total is dynamic-only | `idle_power_w` per level (default 0) + closed-form static term, static-share sweep, peak concurrency as an output field (O27) |
| calibration | physical geometry | slot_pitch_um in the configs | first consumer: derive ns/hop and energy scale (hygiene) |
| workload | model scales/shapes | 355M / 4-die probe / full 2.7B with real distributions | scaling-law probes d in {1024, 2560, 4096, 8192} and S in {128..2048} (O17); ~320-die joint deployment (O16) |
| workload | phases & conditions | prefill/decode x attention on-chip/offloaded, end to end with the external unit as an interface (C21); non-matmul operators on the digital unit (C19) | host I/O streams |
| verification | validation machinery | counter reconciliation, closed forms, blind-test coherence, 185 tests + goldens incl. the 48-die chain pins (C15), the v3 accounting pins (C17), the ledger conservation (C18), the digital-unit pins (C19) and the v5 unit pins (C25) | change-audit process rule; the P0 gate (below) |

The per-op placement, on-die wiring and cross-die placement / wiring rows
are the search space of S3/S4; the mapping and traffic-accounting rows are
its evaluator's foundations.

Priority order (what closing each one buys), re-cut 2026-08-27 after C25 and
the anchor-identity finding: the v5 tables are complete for ONE cell of the
phase diagram; the next deliverables open the other cells (P0 anchor grid,
P1 device axis), state the model's semantics (P1), then run the search (P3).

| # | gap | what closing it buys | class |
|---|---|---|---|
| **O25** | the anchors are digital-ecosystem links read as analog operating points; no analog-reality tier exists | the paradigm x tier anchor grid, the analog-reality rows, the real-system -> registry mapping table; every v5 threshold table read in both columns; the first "current" conclusion that is not 1.00x (the 2.7B chain at analog-reality D2D) | reading position (P0) |
| **O17** | device speed is one hard-coded number (1.449 us in six scripts) and the flip is asserted | device speed as a fabric input; three silicon scales; the on-die scaling law (knee ~ d_model for the projections); the phase-diagram table | core experiment (P1) |
| **O26** | the max end is described as "no queueing", not as the bound it is | the T2 semantic statement; validation scope narrowed to the NoC paradigm; a `schedule_slack` input | model semantics (P1) |
| S1--S6 | no search code exists; the evaluator-proxy question is unmeasured | first search results and the proxy-optimization study | search (P3) |
| O27 | no static energy, no peak-concurrency output | idle-power input + closed-form static term; static-share sweep; concurrency field | energy completion (P4) |
| O21 | 48-die config has an unstated ~2.5k-token K/V ceiling | validity domain on every 48-die result | honesty debt (cheap) |
| O15 | the input-row split (cross-die addition of partial results) never exercised end to end | the row-split branch of the scaling law (O17) and the expensive half of the spanning mechanism | coverage |
| O1 | core/crossbar links carry no energy (the 1 xfail) | turns the 3.69x/1.70x and 17.8% rankings into joules -- now bounded to ~2% of an op (C25) | DR-1 input |
| O8 | bus energy charged by distance-to-driver | removes the artifactual star-bus energy tie | model quality |
| O19 | four interconnect schemes only | torus / ring / express links / hierarchical NoC join every sweep for free | extensibility |
| O16 | whole-model multi-die deployment never simulated jointly | ~320-die joint seating; the search's eventual target | scale extension (outside the v5 paper) |
| O20 | tier-L seated one block at a time | subsumed by O16 | honesty debt (captioned) |
| O14 | over-capacity K/V (long-context) has no policy | attention at S>~8k simulatable honestly | scale extension (outside the v5 paper) |
| O6 | `distance_router` doesn't exist; solver constant underivable | reconnects the collaborator's solver (S5); lifts the 47% citation ban | search prereq (on hold) |

### O25. The anchors are digital-ecosystem links; the analog-reality tier is missing

Nothing numerical is wrong: the thresholds are computed from our traffic and
our device cycle, and no anchor enters them. What is wrong is the READING
POSITION. The three on-die anchors and the GRS D2D anchor were chosen
because they are the only fabricated links with a published per-link
bandwidth -- and every one of them is a digital accelerator's NoC. The
analog CIM systems that exist do not run at those points:

| system | fabric | published on-die link bandwidth | registry tier |
|---|---|---|---|
| NeuRRAM (Nature 2022) | inter-core buffers and partial-sum accumulation on the board FPGA; no on-chip core network | none (chip IO, 130 nm: ~100 MB/s class [est]) | hub-IO upper bound |
| TetraMem MX100 (arXiv 2410.14882) | 10 NPUs + RISC-V + DMA engine + shared SRAM (512 KB + 1 MB), 65 nm | none (shared medium: SRAM port width x clock [est]) | bus, at the T1 hub bandwidth |
| HERMES 64-core (Nat. Electron. 2023) | a real on-chip network, per-core link controllers | not in the main text (supplement to check, arXiv 2212.02872) | star (compile-time scheduled) |
| Mythic AMP M1076 / M1108 | per-tile 64 KB SRAM + NoC router | none (product material only) | star (compile-time scheduled) |
| Tsinghua multi-chip (Nat. Commun. 2025; Yao et al. 2020) | 8 chips + FPGA hub, no chip-to-chip direct links | none (everything through the FPGA) | hub-IO / bus |
| Simba, ESP, FlooNoC (the current anchors) | digital NoCs, 12-16 nm | 8.75 / 32 / 80.6 GB/s | mesh (digital ecosystem) |

Structural estimates for what those fabrics deliver: on die 0.4-8 GB/s
(32-128 bit x 100-500 MHz), die to die 0.1-2 GB/s (board-level or older-node
direct links) -- 2-20x below the digital anchors on die, 1-2 orders below
GRS. All `status = estimated`, derivation stated beside each.

**Fix.**
1. `ANCHORS.md` and the anchor lists in `analyze_anchored_sweep.py` /
   `analyze_scale_tiers.py` (and the GRS constants in
   `analyze_multidie_placement.py` and `fabric.AttentionUnit`) become one
   anchor grid: paradigm (digital-ecosystem | analog-reality) x level (on-die |
   die-to-die). Digital entries keep their provenance and are re-labelled
   "upper bound of what fabricated NoCs deliver"; analog-reality entries carry
   the structural estimate and its derivation. Every anchor row gets a
   `status` (measured / post-layout / secondary / estimated) and a paradigm
   tag; every sweep prints both columns.
2. The real-system -> registry-tier table above goes into the settings
   document, with the model-side rule made explicit: a DMA + shared-SRAM
   fabric is a T1 number in our model (`hub_bandwidth_words_per_cycle`), not
   a T2 link; compile-time scheduled fabrics are the star scheme; NoCs are the
   mesh scheme.
3. Re-read every v5 threshold table in both columns. The sentence "hidden
   behind compute at every published bandwidth" becomes "at every
   digital-ecosystem bandwidth"; in the analog-reality D2D tier the 2.7B
   chain's busiest die link (1-1.8 ms per layer at GRS -- the v5 tier-L sum
   end minus compute over 32 layers, the FlooNoC column -- against 28.8 ms of
   compute) reaches the compute time near 0.5 GB/s and 5-8x past it at
   0.1 GB/s [est, linear from the GRS reading -- the run replaces the
   estimate]. That is a CURRENT conclusion at NeuRRAM speed, before any
   device-axis extrapolation.
4. Goldens: numbers do not move (labels + new rows); one new test group pins
   the grid and the analog-reality rows; v4-and-earlier goldens stay archived,
   not deleted.
5. Hygiene folded in: the ESP secondary citation -> the primary ESP
   publication (candidate: Jia et al., "12nm Agile-Designed SoC ...
   Multi-Plane NoC", ESSCIRC 2022 -- verify before use); HERMES supplementary
   material for link width / clock (if absent, record "not disclosed").

**Gate.** Until O25 lands, no [est] number enters an external document, and
the v4-and-earlier anchored figures and tables are retired from citation.

### O26. Say what the max end IS: a bound, not "no queueing"

`link_occupancy`'s max end is, per wire, volume / bandwidth on the busiest
wire. For a FIXED routing, any schedule -- a compile-time one included --
needs at least that long on that wire. So the max end is the exact ideal of
the scheduled paradigms (Mythic / HERMES class) and the optimistic bound of
the NoC paradigm; the sum end is the fully serialised bound. Today the
documents describe it as "no queueing", which reads as a simplification
rather than as the bound it is.
**Fix.** (1) State it in the model section of the settings document and the
report (one paragraph; "for a given routing" is load-bearing -- a scheduler
that re-routes changes the per-wire volumes, and that is a search move (S3),
not a T2 refinement). (2) Consequence for validation: queueing /
BookSim-class checks apply to the NoC paradigm only (the digital column of
O25); for the scheduled paradigms the open question is feasibility, answered
by a `schedule_slack` platform input (default 1.0, multiplies the max end)
rather than by a queueing model. (3) One test: the identity max <= any
schedule <= sum on the frozen flows.

### O27. Energy is dynamic-only; static power and peak concurrency are absent

Every energy total is CiMLoop dynamic energy plus our overlays; no idle /
leakage term exists anywhere in `scripts/`. So a layout that lengthens time
cannot cost energy through static power -- "energy is layout-blind" holds by
construction for the static part, and the report should say so.
**Fix (cheap, closed-form, after P0-P3).** `idle_power_w` per level in the
fabric (default 0) and E_static = P_idle x T_total as a ledger
post-processing row; one figure: static share 0-30% on x, the energy ranking
of layouts on y (static energy inherits the latency ranking); peak
concurrency (max simultaneously active crossbars / macros, from the mapping's
spatial factors) as a standard output field; settings assumption #20:
dynamic-only is the default tier.

### O1. Only the macro-level router carries an interconnect energy model *(xfail)*

`inter_core_in_macro_spatial` / `inter_crossbar_in_core_spatial` are zero-energy
fanout markers, so the 3.69× / 1.70× and 17.8% results are rankings, not costs.
Fix: per-level link energy placeholders in the fabric config feed a CostModel
energy path (the per-hop/per-word values are platform inputs — example defaults
until a chip's own values are filled in; the request for the company's values
is DR-1). Positioning decision (anchored-calibration round): O1 is NOT being
closed for the current paper deadline — the anchored evidence explicitly
covers scheme × hub position only, the core-level region allocation stays a
ranking, and O1 is listed as a PREREQUISITE of the search-space work (the
region dimension cannot join the objective until its links carry a price).
Ceiling after C25: the volumes a price would multiply are 14-48x smaller
than before -- per ffn1 operator each crossbar receives 65,536 values and
returns 32,768 16-bit partial sums, ~24 M word-equivalents per die; at
1 pJ/word over 2 hops that is ~0.05 mJ against the operator's ~2.7 mJ
(~2%). DR-1 turns the rankings into joules; it cannot make the within-die
placement an energy lever.


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




### O14. Long-context K/V arrays have no over-capacity policy

`temporal_rewrite` raises NotImplementedError for dynamic ops, and K/V
arrays grow with context: at S~8k a single head-group's K array exceeds one
die. Long-context decode is currently unsimulatable past that point.
**Fix:** extend the residency planner to dynamic ops (the K/V split is by
Klen -- a spatial split is an append-sharding across dies, write lands on
one die per token); charge the D2D read fan-in of attention over the shard
set. Files: `llm_workload.py` (plan_spatial for dynamic kinds + write
routing), `test_capacity.py`. Scope: outside the v5 paper (residency
detail).

### O15. Of the two ways to split an op across dies, the expensive one has never run

A spanning op can be split two ways. By OUTPUT columns: each die produces a
disjoint piece of the output, the input is broadcast to every die, and the
pieces just concatenate -- cheap, and the way every 2.7B op happened to be
split so far. Or by INPUT rows: each die consumes part of the input and
produces an INCOMPLETE partial result, and the partial results must be
ADDED ACROSS DIES -- the physically expensive direction. That second path
exists in the code and has never been exercised by any real op: an untested
road.
**Fix:** a probe op with a huge input dimension and a small output
dimension forces the input-row split; verify end to end that the mapping,
the extracted traffic (outputs marked as merging, not concatenating), and
the wire occupancy of the cross-die addition are all correct; pin as a
test. Files: probe in `test_d2d.py` (slow tier) or a script probe.
Also the row-split branch of O17's scaling law (per-die input / k, partial
sums x k): the law is stated for the column split until this runs.

### O16. The 2.7B results examine one op at a time; a real deployment seats everyone at once

Today's tier-L numbers take each operator ALONE, place its 4--5 dies on the
package, measure, and hand the dies back. A real deployment keeps ALL 32
layers' weights resident simultaneously: roughly 320 dies, every operator's
die group claiming a disjoint region of the package, and each operator's
output crossing the package into the next operator's region. That joint
question -- who gets which region, and what the traffic between regions
costs -- has never been simulated, and it is exactly the problem the
placement search will ultimately have to solve.
**Fix:** a ~320-die fabric variant; an allocator that seats all die groups
disjointly; hand-off flows between consecutive operators' regions; score
latency/energy under 2--3 seating heuristics. Files: new fabric variant,
`analyze_deployment.py` (new); the op-chain hand-off volumes already exist
in `llm_workload.py`. Scope: outside the v5 paper; it remains the search's
eventual target (S4).

### O17. The device-speed axis: one hard-coded number, and the flip asserted rather than drawn

**Current state.** The device cycle is the literal `1.449e-6` in
`analyze_d2d.py`, `analyze_offload_contention.py` (three places),
`analyze_multidie_placement.py`, `analyze_digital_sensitivity.py`,
`op_breakdown.py` (`CYC_DEFAULT`) and `llm_workload.py` (`cycle_seconds`
default); the fabric stores bandwidths in words per cycle AT that cycle (die
link and unit link 18,112 = 12.5 GB/s), so a cycle change would silently
re-label every anchor. Thresholds in words/cycle are device-invariant only at
a fixed slice count; the honest axis is seconds per MVM row (cycle x input
slices): NeuRRAM 7 x 1.449 us = 10.1 us.

**Fix.**
1. The fabric gains `device: {cycle_seconds, input_slices_per_mvm}` and every
   script reads it; bandwidths are declared in GB/s (YAML and anchors) and
   converted to words/cycle at load. This refactor comes first -- it is the
   only code the sweep needs.
2. `analyze_device_sweep.py`, closed-form: every threshold scales as
   1 / t_MVM. Three silicon scales: NeuRRAM 10.1 us per MVM row (calibrated);
   ISAAC-class 1.6 us (16 one-bit slices x 100 ns, the ISCA 2016 design point;
   6x); HERMES-class ~130 ns (63.1 TOPS / 64 cores / (2 x 256 x 256)
   [derived]; ~76x) -- derivations into ANCHORS.md. Re-read at each scale: the
   on-die 1% band and bus doubling point, the D2D masking ratio of the 2.7B
   chain, the offload dividend. What is FIXED across the sweep and must be
   said so on the figure: the write model (SET pulse, DR-5), the digital unit
   (1 GHz), the attention unit, the link bandwidths. At the fast end decode
   becomes write- and unit-bound -- that is the finding, not a bug ("device
   76x faster, decode 1.3x faster").
3. The scaling law. For the projections (qkv / out / ffn) under the column
   split, trunk volume S x d over compute S x t_MVM: the on-die knee is
   proportional to d_model and independent of S. NOT for the row split (input
   / k, partial sums x k; O15) and NOT for the attention crossbar operators
   (K^T resident, output S x S: knee ~ S). Probe d in {1024, 2560, 4096, 8192}
   at S = 512 and S in {128 .. 2048} at d = 1024; pin the proportionality as a
   test. [est] from v5: 355M 0.35-1.4 -> 2.7B 0.9-3.5 -> 7B-class 1.4-5.6 ->
   70B-class 2.8-11 GB/s (1% band), so from the 7B class the analog-reality
   on-die tier (0.4-8 GB/s) sits inside the band and the shared-medium tier
   crosses the doubling point near the 1B class -- the trend conclusion
   beside O25's current one.
4. Deliverable: one table, model tier x device tier x paradigm / link tier ->
   knee position against that tier's bandwidth (the phase diagram's numeric
   base), and one figure with the analog-reality and digital bands marked.

### O19. The interconnect registry should grow beyond its four schemes

The registry ships star / routed mesh / tree / bus, and its design is
extension-by-construction: a new scheme only answers three questions (how
far between two points, which wires a flow occupies, what wires exist).
Worth queueing, roughly in order of payoff: torus (wrap-around mesh,
removes the edge-long paths that make the corner placements expensive),
ring, express links (skip connections over the mesh), direction-split
full-duplex links (today up- and down-traffic share each wire -- a
conservative 2x), hierarchical wide-link networks of the FlooNoC class, and
routing-algorithm parameters (adaptive vs fixed order). Each lands as one
class in `interconnect.py` plus its hand-derived identity tests; every
existing analysis then sweeps it for free.

### O20. The 2.7B layers are seated one block at a time

C23 seats the BLOCK's die-sets disjointly (17 of 24 dies), so the
tier-L rows are achievable block configurations and the old "clustered =
per-operator lower bound" caveat is retired at block level. What is still
assumed is that every layer is a copy of the same block seating (the last
die-set feeds the next layer's first). The whole-model seating -- 32 blocks
on a ~576-die package -- can only lengthen those hand-offs.
**Fix:** subsumed by O16's allocator; until then the tier-L caption states
"block-level; the whole-model seating is its upper bound".

### O21. The 48-die configuration has an unstated context ceiling

The attention die holds the K/V arrays, and K/V grows with every generated
token: past roughly 2.5k tokens of context the attention die overflows and
the two-dies-per-layer seating stops being valid. No published number is
wrong at S=512, but the configuration's validity domain was never stated.
**Fix:** state the ceiling wherever the 48-die config is introduced; add a
capacity check that raises when S plus generated tokens exceeds it; the
long-context fix itself is O14.


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

## The search milestone (S1--S6): first placement-search results

No search code exists today: `placement.py` (the Placement object,
sequential fill), `placement_aware.py` (the cost overlay) and
`analyze_placement_*.py` (enumeration) are the evaluator side. S1 is still the
first line of search code. All scoring is closed-form re-scoring on frozen
per-op data, so search iterations cost microseconds, not mapper minutes.

| # | task | files / how | what it delivers |
|---|---|---|---|
| S1 | **Evaluator API**: one function `score(config) -> (E, T_single, T_pipe)` wrapping the existing pipelines; config = {scheme+params per level, hub position, macro slot permutation, unit->die assignment, die-set placement}; anchor column and device scale as arguments (O25, O17); `schedule_slack` honoured (O26) | new `scripts/search_eval.py`, thin calls into `link_occupancy` / `die_to_die_activation` / `die_pipeline_interval` + the frozen v5 fixtures | the objective the search and the collaborator's solver both consume; pinned by identity tests against the published tables |
| S2 | **Heuristic baselines**: snake / clustered / centre-hub / sequential as first-class configs, plus a **constructive greedy** (flows in descending volume, each placed where the incremental peak-wire load is smallest) | `search_eval.py` registry | the bar a search must beat; the shared baseline of S3, S4 and S6 |
| S3 | **On-die search (355M)**: simulated annealing + exhaustive-where-small over hub position x scheme params x macro permutation; objective T_single per anchor column, E as constraint | new `scripts/search_ondie.py`; SA ~10^4 evals, seconds | does search beat the best heuristic, and in which cells; Pareto front (E vs T) |
| S4 | **Package search (355M 48-die + 2.7B die-sets)**: SA over unit->die assignment and die-set seating; objective T_pipe + surplus energy | new `scripts/search_package.py` | search vs snake / clustered gap; a tie is a finding too (publish it honestly) |
| S5 | **Solver reconciliation** (needs O6): `W_MACRO_DIST` from fabric geometry, the collaborator's solver on the same objective, Spearman against `score()` | `die_solver.py` (his), `search_eval.py`, a Spearman harness | the two search efforts become comparable; lifts the 47% citation ban |
| S6 | **Proxy-optimization study**: same SA, space, budget and seeds; only the evaluator changes -- E0 full `score` / E1 volume x distance / E2 prefill-only / E3 the wrong paradigm tier; every solution re-scored by E0 under every condition | `search_ondie.py` + a harness | the 4 x N cross matrix: where a simplified evaluator returns the wrong layout, plus one "safe cell" control row (slow device x wide link: every evaluator expected to tie) |

Cell discipline: search experiments run only where the phase diagram has
play -- the fast device tier, the shared-medium tier, offload-decode, weak
D2D x spanning -- and the safe cell as the control. Running the search in the
(NeuRRAM x digital-link) cell reproduces 1.00x and proves nothing.

Dependencies: S1 on the v5 fixtures and O25's anchor columns; S3/S4 on P1's
cells; S6 on S3; S5 on O6 and the collaboration discussion (ON HOLD since
2026-08-21).

## Process rule (added after the 24-to-48-die miss)

Any configuration or accounting change MUST be followed by a re-audit of
the results-affecting register above, recorded in tests/CHANGELOG.md, in
the same change. Discovering a stale assumption by being asked is a
process failure.

P0 gate (2026-08-27): until O25 lands, no [est] number enters an external
document; v4-and-earlier anchored figures and tables are retired from
citation; every new row is built on the v5 fixtures. Correction history
stays in the CHANGELOG -- the paper presents v5 numbers and the four
validation mechanisms (closed forms, counter reconciliation, anchor
landing, regression pins), not the corrections.

## Worklist (priority order)

Done (see Completed): O12 (C14), O18 (C15), O7 (C16), O22/O23 (C17), O24
(C19), O9 (C21, C22), O13 (C23), the unit fix (C25).

1. **O25 anchor grid** (P0, before anything else): the paradigm x tier
   registry with `status`; the analog-reality rows with derivations; the
   real-system mapping table into settings; both columns on every threshold
   table; the 2.7B chain read at analog-reality D2D; test group; ESP primary
   citation and the HERMES supplement check.
2. **O17 device axis** (P1, the core experiment): the `1.449e-6` refactor
   into a fabric `device` block with GB/s-declared bandwidths first; then the
   three silicon scales, the fixed-terms statement, the scaling-law probes
   (d and S), the phase-diagram table and figure.
3. **O26 T2 statement + `schedule_slack`** (P1: documents, one parameter,
   one test).
4. **S1--S6** (P3, after P0/P1 have produced the cells): S1 evaluator API ->
   S2 baselines + greedy -> S3 / S4 -> S6 proxy study; S5 / O6 when the
   collaboration discussion resumes.
5. **O27 static energy + peak concurrency** (P4, cheap).
6. **Documents** (P5, after each of the above): settings / SUMMARY (zh + en)
   / report: anchor identity, mapping table, T2 statement, the DR table
   (DR-2 returns to first order in the analog-reality column; DR-5 stays the
   one device-side input that moves the decode conclusions); README script
   index; a CHANGELOG entry per step with the register re-audit. The deck is
   maintained on the user's side.
7. Kept, lower: O21 (cheap; with step 6), O15 (needed for the row-split
   branch of O17's law), O16 -> O20, O14, O1 (DR-1 input; ~2% ceiling after
   C25), O8, O19.
8. Small hygiene: derive `res.energy` from the exact per-component
   `Energy (total)` lines instead of the rounded per-compute summary table
   (pytimeloop `parse_stats_stream`: pJ/compute x computes) -- the
   per-operator ledger shows the gap as a 0.1-0.5% residual row; seed the
   CNN sample inputs in `crossbar_value_real.py`
   (removes the 1.199 vs 1.204 sampling drift); prune `make_figures.py`
   stages that regenerate deleted figures; derive `ns_per_hop`/`hop_scale`
   from `slot_pitch_um` (its first consumer); UCIe-class D2D anchor; T1 x T2
   joint operating-point sweep; verify `reduction_hyperedges` membership
   convention against Timeloop's spatial index order.

Paper scope (the v5 narrative). Thesis: when the communication cost of
analog CIM is first-order is a phase diagram (model scale x device speed x
transfer paradigm x link tier); this work is the first instrument that can
draw it, with the axes calibrated against published silicon. Three
contributions: the instrument (placement-explicit, contention-computable,
paradigm-selectable; T2 statement, four validations, microsecond
re-scoring), the diagram (on-die and D2D unified by two ratios plus the
device axis; current conclusions at the slow analog tier -- point-to-point
free, shared medium at the line, spanning forbidden at weak D2D -- and trend
conclusions from the scaling law and the three silicon scales), and the
search (S1--S6, with the proxy-optimization failure as the result). Energy
in one sentence: dynamic energy is layout-blind (v5: <=0.2% on die, +1.2-1.3%
across dies at the GRS anchor), static energy inherits the latency ranking
(O27). Out of scope for the paper: the agent direction, residency detail
(O14 / O16), company-specific wording, meshX > 1, O15, BookSim-class
validation (digital column only), the long-form report.

Not scheduled until asked: giant layers across dies beyond the tiler's
range, multi-package scaling.
