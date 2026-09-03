# Fix List

Status of the code-level defects and gaps. Completed items first (motivation /
what was done / result), then what remains open — in priority order, with a
worklist at the end. Guardrail tests live under `workspace/tests/`
(`python3 tests/run_tests.py`; currently 288 pass + 1 expected-fail, which is
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

| | 3×3 (the default until C27; now `mlx300_3x3.yaml`) | 2×4 (variant then; the default since C27) |
|---|---|---|
| heatmap spread (ffn1) | 3.62× | **1.50×** (no macro adjacent to the hub) |
| empty slots | 1 macro slot + 1 slot/core | none |
| worst-case hops / propagation | 12/3/2 → 136 ns/op | **10/3/2 → 116 ns/op** |
| macro mean hops (energy) | 1.3125 | 1.5 (distance surcharge ×1.6 = +0.12% block) |
| headline ratios (1.01×/10.12×/93%) | — | unchanged |

Figures: at the time `crossbar_comm_heatmap.png` (3×3) vs `crossbar_comm_heatmap_2x4.png`;
since C27 the canonical names are the 2×4 default and the comparison carries `_3x3`.

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

### C40. The hygiene slate cleared: exact energies, seeded sampling, the UCIe anchor, regen semantics (2026-09-01)

Hygiene 22 / 23 / 24 / 26 / 28 all closed -- details in
tests/CHANGELOG.md C40. Highlights: `exact_total_energy_J` replaces the
rounded per-compute-table total in `run_mlx_layer` (ffn1 fixture +0.058%,
pinned; JSON energies move <= 0.5% at the next regeneration and the
ledger's residual row closes); the value-sampling draw is seeded; every
make_figures output verified on disk and guarded; the UCIe-S 64 GB/s D2D
anchor enters the readout columns with the new, honestly-separate status
`spec` (a standard's ceiling, not a measured chip); `run_scaling_probes.py
--fresh` states the regeneration semantics. Suite: 252 passed / 1 xfail.

**Found while closing (pre-existing, NOT from these changes -- verified
identical at the pushed HEAD via stash):** two SLOW-suite goldens fail:
`test_per_level_volume_conservation_v1` (totals 12,288 vs stats 311,296
-- smells like the C25 value-unit reform applied to one side of an old
v1 identity) and `test_position_spread_golden_v2` (1.091 measured vs the
pinned 1.25 -- likely the C27 grid change never re-pinned the tiny2x2
spread). Recorded in the worklist (now folded into plan step 3 after
the renumber); re-derive with attribution, do not band-aid the pins.

### C39. The offloaded twin of the fixed-terms figure; the write-bound mechanism stated (2026-09-01)

**The mechanism half-sentence, now in writing.** ON CHIP the dynamic
attention operators (qk^t, av) are WRITE-RATE-BOUND: each decode token
must be SET into its K/V row before they can read it, so a device made
faster only on the read path keeps its on-chip attention walled by the
writes -- a fast device with attention on chip is a SELF-CONTRADICTORY
configuration, and the two exits are faster writes (DR-5) or offload
(DR-9). Stated in the settings' offload bullet, assumption 22, SUMMARY
(zh + en), ANCHORS' DR-9 section and the figure caption.

**The offloaded twin (all closed-form, zero mapper).**
`device_fixed_terms.png` becomes FOUR panels (prefill / decode x on-chip
/ offloaded, shared axes); `phase_sweep.json` gains
`fixed_terms_offloaded` + `offload_relay`. Offloaded, the die keeps the
projections + FFN (scaling with t_MVM) and the new floor is the unit +
link + die digital (DR-9 generic values: decode 1.02 ms = unit 1.00 +
link 0.01 + digital 0.01; prefill 19.71 = 8.61 + 4.03 + 7.08). The
NeuRRAM totals tie the C21 ledger exactly (518.12 ms / 1.99 ms).

**Findings -- two expectations corrected by the numbers.** (1) NO
crossing threshold: the offloaded floor beats the write wall in BOTH
phases, so offload wins single-pass latency at EVERY device tier (decode
14.78 vs 1.99 ms already at NeuRRAM) -- the expected 1-3 us "should you
offload" threshold does not exist under the generic DR-9 unit; the
crossing condition (unit + link fixed time vs the write wall) is stated
parametrically instead. (2) The offloaded decode panel is NOT a pure
scaling wedge: the unit floor (~1.0 ms) is comparable to the remaining
die matmuls, so a 76.3x device buys offloaded decode only 1.93x (vs
1.11x on chip; prefill 19.7x vs 9.33x). The true punchline is the
fixed-terms RELAY: every configuration has its own floor -- DR-5 sets
the on-chip ceiling, DR-9 the offloaded one, two ends of one decision.
Group 27 + 1 test. Suite: 250 passed / 1 xfail.

### C37. V0: silicon-point normalization rules; the HERMES self-consistency audit; a C36 mis-reading corrected (2026-09-01)

**The correction (review caught it -- the validation track's V0).** C36
plotted HERMES's 0.4 GB/s at face value on the on-die panel and read
"deep inside the everything-contends layer, 0.4 against its own 15.4 GB/s
star knee". That was a GRANULARITY MISMATCH: 0.4 GB/s is one PHYSICAL
link of a fabric with 418 links serving 64 cores (~6.5 per core), while
our axis is per OUR link -- one link feeding a macro of 32 arrays. A
fabric 38x under its own knee could not have sustained the measured 63.1
TOPS; the mis-reading failed its own sanity check.

**The rules (now explicit in the registry, `ChipPoint` docstring).**
(1) t_mvm_s is PER TOKEN (one input row through the resident array
stack); a TOPS-derived row time is tile-shape invariant (t = n_arrays x
2RC / TOPS -- the ops per row already scale with the array dimensions),
so NO array-height folding: Mythic 6.38 us and ISAAC 1.6 us stand as
derived (the adjudicated alternative -- folding to a 256-row axis --
would double-count the height). (2) A bandwidth coordinate is what the
chip's fabric supplies to the array group one of OUR links serves (32
arrays): published per-physical-link rates are aggregated (links per
array x 32); the estimated bands are authored at our granularity and
need no aggregation. HERMES's coordinate: (418/64) x 0.4 x 32 ~= 83.6
GB/s (per-link 0.4 kept as `ondie_gbps_per_link`, still the analog
band's low end).

**The self-consistency audit (`anchors.hermes_self_consistency()`).**
From published numbers only: need per core per token = 256 INT8 inputs /
133 ns ~= 1.93 GB/s; supply per core = (418/64) x 0.4 ~= 2.61 GB/s;
**headroom ~1.36x**. A fabricated analog chip provisioned its fabric
just ABOVE its own knee -- the first external silicon point validating
the knee formula (boundary = traffic / compute time), and the seed of
the paper's external-behaviour validation section. On the phase diagram
HERMES moves to (0.133 us, ~84 GB/s): above the production routed
boundary, below the bus and d >= 4096 lines -- "the organisation
decides", which is what a compile-time scheduled fabric is.

Group 23 re-pinned + 1 audit test; the diagram regenerated. Suite: 244
passed / 1 xfail.

### C36. The anchor leftovers settled: Mythic derived, HERMES published, ESP primary; MX100 blocked (2026-09-01)

**What was done (the O25 P2 leftovers, literature pass).**
1. **Mythic M1076 t_MVM derived**: 25 TOPS peak / 76 tiles / (2 x 1024 x
   1024 ops per row) = **6.38 us**; the 1024x1024 tile array from the
   published 80M weights / 76 tiles = 1.05M. The registry chip point gains
   the coordinate (status derived) -- and `device_marks()` now serves FOUR
   silicon marks, so the plane, the phase diagram, the collapse and the
   fixed-terms figures all carry the fourth mark (regenerated; groups 27 /
   30 re-pinned; the diagram's table gains a Mythic column).
2. **The HERMES link rate was published all along**: the arXiv (2212.02872)
   methods' chip spec table gives "Maximum link data-rate 3.2 Gbit/s" =
   **0.4 GB/s per link** (418 physical links, a 5 Parallel Prism fabric) --
   the earlier note blamed a paywalled supplement; corrected. This is the
   FIRST published analog-CIM link rate in the registry, and it lands
   exactly on the analog-reality band's LOW end: the identity statement
   ("no fabricated analog CIM system publishes an on-die link bandwidth")
   is amended everywhere; the band stays the CLASS estimate.
   ~~(deep inside the everything-contends layer: 0.4 GB/s against its own
   star knee of 15.4 GB/s at 133 ns)~~ -- WRONG, a granularity mismatch:
   corrected by C37 (the normalized coordinate is ~84 GB/s per 32-array
   group; HERMES provisions ~1.36x above its own knee).
3. **The ESP anchor is primary-sourced**: the ESSCIRC 2022 text (Jia et
   al., author-hosted) read -- 5 data NoC planes x 64 bit + 1 control
   plane x 32 bit at a measured 800 MHz; the paper's own headline is 281
   Gb/s tile-to-tile (all 6 planes); the anchor's 32 GB/s = the 5 data
   planes (256 Gb/s), exactly what FlooNoC's comparison quotes. Status
   secondary -> measured, with the multi-plane aggregation stated in the
   derivation (one physical plane is 6.4 GB/s); the citation-discipline
   caveat in ANCHORS.md is resolved.
4. **MX100 is BLOCKED on its source**: the SoC paper (arXiv:2410.14882,
   "Multi-diseases detection with memristive system on chip") confirms 10
   NPUs of 256x256 8-bit crossbars but publishes NO TOPS or MVM rate, and
   product material has none citable (checked 2026-09-01). Recorded as a
   new worklist item; revisit on TetraMem's 22nm SoC publication
   (announced 2026-05).

Suite: 243 passed / 1 xfail (groups 23 / 27 / 30 re-pinned).

### C35. O29 closed: the phase diagram drawn (2026-09-01)

**What was done.** `analyze_phase_diagram.py` (new; zero mapper -- reads
phase_sweep.json, scaling_law_summary.json and the registry) ->
`phase_diagram.png` + a grayscale check copy + the grid -> ratio table
(`phase_diagram_table.md`). Two panels on the same (t_MVM x bandwidth)
plane, every element of the agreed design with one visual carrier: the
slope -1 mechanism; the boundary family per width tier with model names
(d = 1024 the production base); the three shaded layers; digital anchors
as horizontal lines with statuses (never points), the estimated bands and
chip bandwidths marked as estimates; HERMES / ISAAC as error-bar points,
NeuRRAM with its t coordinate only (hub-IO); the two trend arrows; the
collapse inset; validation points coloured AND shaped by measured /
closed-form (grayscale-safe): the 17c probes on the left, the measured B2
block-chain marks on the right (they sit on the d = 2560 line at all three
silicon speeds).

**A semantics correction caught in review (not a layout nit).** The first
draft called the d >= 2560 die-level lines "chain boundaries" while the
layer label said "spanning forbidden" -- but those lines are O13 BLOCK
CHAINS INCLUDING their spanning operators (column split: each receiving
die takes the full input), which is exactly why they sit ABOVE the single
4-die operator probe. Relabelled: black d = 1024 = the PURE hand-off
stream (ops fit their die; = the die<->unit link under offload); blues =
"block chain incl. spanning operators (column split, tensor once)"; purple
= "single 4-die operator"; the three layers restated as pure hand-off /
probe / block-chain family, and the title says why the chains carry the
flood. The same phrasing propagated into the plane JSON's `d2d_form`.
ffn2's tiler step gets its own marker class ("known tiler step --
expected"), separate from genuine disagreement. Group 30
(`tests/test_phase_diagram.py`, 4 tests): layer edges + the corrected
ordering (hand-off < probe < every chain line), the validation classes
(trunk exact, ffn2 exactly x2 at d <= 4096 and back on the line from
5120), the B2 marks on the 2560 line, the outputs with pinned table rows.
Suite: 243 passed / 1 xfail.

### C34. O28 closed: the T1 (die-buffer) axis audited -- counter units again (2026-08-31)

**Motivation.** `analyze_bandwidth_sweep.py`'s Timeloop-native T1 points
stretched ffn1 to 0.84 s at "64 words/cycle" -- 160x its compute -- and the
axis could not be read in GB/s. The suspicion ("counter units again?") was
right, and it is C25's sibling on the T1 axis.

**The audit (closed form, exact).** Timeloop throttles the glb per
dataspace in ITS counter units: input fills x7 (bit slices), output fills
AND updates x8 (bit groups); the write port binds. For ffn1 that is
7*S*C + 2*8*S*M = 37,224,448 units, and every cached Timeloop point equals
write-units / bandwidth EXACTLY (rel err 0.0 at all four points) -- against
~8.9M value-unit hub words, a ~4.2x unit inflation. A declared value-unit
hub bandwidth reaching Timeloop raw is therefore over-throttled ~4-8x;
no shipped config declares one (group 29 pins that the push stays inert),
so no published number moved.

**The fix.** (1) The T1 axis is now ANALYTIC in value units
(`sweep_axes.py` axis `t1_hub`, figure `sweep_axis_t1_hub.png`): the hub is
ONE shared port -- exactly the MX100-class medium (DMA + shared SRAM) --
and per matmul op its occupancy is an identity on stored components:
hub words = the T2 bus words + the op's input tensor arriving into the
buffer once (P x C x N). The T1 = T2-bus equivalence the registry's mapping
rule promised HOLDS, shifted by the in-fill share (ffn1 +6.25%, ffn2 +20%,
av +80%). (2) Readout: knee ffn2 in every condition; 1% at 2.27 (prefill
on chip; the bus's 1.89 shifted by the in-fill) / 2.33 (offloaded) GB/s;
busiest-op net = compute at 2.42 GB/s; MX100-class chips read 3.9-5.0x at
the estimated band's low end (0.4 GB/s) and 1.00x at its high end
(8 GB/s); decode-offloaded equals prefill-offloaded exactly (S cancels in
every hub ratio -- the group 28 identity again). (3) The Timeloop path
stays as the mechanics validation with its unit stated on the figure and
an executable audit (`analyze_bandwidth_sweep.py` asserts the closed form;
unit warnings at the `mlx_system` push site and the fabric field).
Group 29 (`tests/test_t1_hub.py`, 4 tests); the sweep schema gains
`t1_hub`. Suite: 239 passed / 1 xfail. The T1 axis is the second source of
O29 validation points, as planned.

### C33. The d family on the plane; the scheme multipliers verified (2026-08-31)

**What was done.** Four refinements on C31/C32, zero mapper runs.
(1) `device_plane.png` carries the O29 boundary FAMILY: on die (routed)
one line per width tier -- d = 1024 (355M GPT-2 medium, the PRODUCTION
base, co-residency C14), 2560 (2.7B-class OPT-2.7B), 4096 (7B-class
Llama-7B width), 8192 (70B-class Llama-2-70B width); ffn2's tiler step is
an ANNOTATION on the figure, not a kinked line. (2) The die-level family
is the tiler closed form (zero mapper): the hand-off tensor once -- ffn2's
entry (S x 4d) once the block splits into die-sets (`block_chain`, column
split; `block_chain` gains `max_dies` / `dims` for d = 8192's 32-die ffn),
d = 1024 = the C13 half-layer hand-off (S x d, payer ffn1); the d = 2560
line passes exactly through the measured B2 mark (asserted at build time).
(3) The scheme multipliers are VERIFIED, not extrapolated: the probes'
stored macro edges re-scored under mesh / bus (`analyze_scaling_law.py`,
closed form) -- the routed multiplier is x4.00 EXACTLY at every d and op
(d-independent, so the family's routed lines are measured), while the bus
multiplier is NOT constant: x13.3 at the underfull d = 1024 down to the
deep-trunk asymptote x8.25 -- the O17b "x10" at the production base is
basis-specific. (4) Figure hygiene: out_proj = ffn1 coincide at every
probed d; `scaling_law_vds.png` now merges them under the C28 rule
(identical series never stacked silently). Numbers: the family at t_ref is
0.808 / 1.010 / 1.616 / 3.232 GB/s on die and 0.101 / 1.010 / 1.616 /
3.232 GB/s at the die level -- the two levels coincide for d >= 2560
(mesh's x4 multicast = ffn2's 4d-wide tensor, one number, two mechanisms).
The plane JSON gains `d_family`; groups 27 / 28 gain one test each.
Suite: 235 passed / 1 xfail.

### C32. O17c closed: the mapper-measured V(d, S) (2026-08-31)

**Motivation.** The d family of boundaries had been guessed twice: first
"knee ~ d" (the input trunk), then its correction "the busiest wire is the
partial-sum UP traffic, falling as capacity / d until d ~ 5,800" (read off
the v5 co-residency wire accounting). Both were extrapolations; the second
was in the bias table as the expected shape. An experiment, not a
verification -- and the crossing d* is a paper number.

**What was done.** `run_scaling_probes.py` (new): 48 mapper runs, single
core, ~35 minutes, resumable (finished (d, S, op) entries skipped on
restart) -- d in {1024, 2560, 4096, 5120, 6144, 8192} at S = 512 (5120 and
6144 added to pin the predicted crossing), S in {128, 256, 512, 1024,
2048} at d = 1024 (3 ops: qkv_proj strict cancel, ffn2 the knee op, qk^t
the stated exception). Regime: residency tiler, COLUMN SPLIT ONLY
(`plan_spatial` extended with `max_dies` -- d = 8192's ffn needs 32 dies
on the 48-die fabric -- and `dims=("M",)`; the O15 row split stays
unexercised), full die per piece, dh = 64, d_ff = 4d, prefill. Per
(d, S, op): the busiest macro edge's volume and DIRECTION (down = input,
up = partial sums), serialization at 16,384 w/c, compute, die split.
`analyze_scaling_law.py` (new) -> `scaling_law_vds.png` +
`scaling_law_summary.json`; group 28 (`tests/test_scaling_law.py`, 5
tests). Suite: 233 passed / 1 xfail.

**Findings -- three, each replacing a guess.**
1. **The input-trunk regime.** For every static op at d >= 2560 the
   busiest wire is the input DOWN trunk: down = S x d words per macro edge
   exactly, so serial / compute = d / 114,688 (= 16,384 w/c x 7 slices) --
   "knee ~ d" with slope exactly 1. This is the closed form the O29
   boundary family draws. ffn2 (C = 4d) rides the tiler's macro C split
   (0.0714 at d = 4096 drops to 0.0446 at 5120): the law is
   mapper-dependent exactly where the tiler steps, as predicted -- but the
   step is a quantisation wiggle on the trunk line, not a shape change.
2. **The flip d* = 1,220-1,350 measured (qkv 1,224 / out_proj 1,288 /
   ffn1 1,349; ffn2 down-dominated everywhere). The prediction 5,793 is
   FALSIFIED, off 4.3x**: it ignored the macro fanout (the up traffic
   divides across 8 macro edges) and that multi-die pieces fill their die
   exactly. The two extra runs prove the trunk line runs straight through
   the predicted crossing -- no valley there. Below d* the dies are
   underfull and the mapper replicates weights to split P (compute halves
   at d = 1024): the left branch is mapper-shaped, not a clean 1/d.
3. **S-independence is stronger than declared**: every probed ratio is
   exactly flat over S = 128-2048, the attention ops included -- qk^t's
   busiest-wire volume follows S^2 but so does its compute (ratio pinned
   at 1/14). "qk^T follows S" is a statement about absolute volume, not
   the knee ratio -- which strengthens the O29 condition choice. Bonus
   identity: the d = 2560 probes reproduce the 2.7B block's ratios on a
   different package (48 vs 24 dies): the on-die law does not see the
   package.

### C31. O17b closed: the (t_MVM x bandwidth) plane (2026-08-31)

**Motivation.** Every threshold in the repository was a single-device
reading (NeuRRAM, t_MVM = 10.14 us), and C30 had only made the device an
INPUT, with no data behind any other value of it -- while the phase
diagram's (O29) second coordinate is exactly this axis. The group 26
identity (at a fixed GB/s the seconds on a link do not depend on the
device) is what makes the plane closed-form: in the (t_MVM, GB/s) plane the
network term depends only on the bandwidth coordinate and the compute term
only on the device coordinate -- no mapper rerun, a re-scoring of stored
components like O25.

**What was done.** `sweep_axes.py`: the scoring rewritten in GB/s form
(`ser_at` = ser_ref x 11.310 GB/s / g; an identity at the NeuRRAM tier,
device-free under the cross); `axis_device_plane` -- device grid 0.05-100
us, 8 points per decade, plus the three silicon marks from the registry's
new `anchors.device_marks()` (NeuRRAM 10.14 us measured / ISAAC 1.6 us
design point / HERMES 0.133 us derived -- the ONLY measurement points; the
surface between them is closed-form), crossed with axes A, B1, B3, C (B2,
already crossed with axis A, is read at the marks only). The plane's metric
is the BUSIEST OPERATOR's network / compute ratio r(g, t), not the
whole-stack multiplier: t_MVM scales the MVM read path only -- the K/V
write (DR-5), the digital unit (DR-8), the attention unit (DR-9) and every
link's GB/s are fixed and printed on every figure. r = 1 is the closed form
g = 11.310 x (ser_ref / mm_ref) x (10.14 us / t) (slope -1 in log-log); the
bisection-swept thresholds land on it to 1e-9. Three figures:
`device_plane.png` (r contours + closed-form lines + marks + anchors),
`device_plane_collapse.png` (the collapse variable g x t_MVM: the matrix
part lands on one curve, the whole stack does not), `device_fixed_terms.png`
(prefill / decode stacked components vs t_MVM). `phase_sweep.json` gains a
`plane` block; group 27 (`tests/test_device_plane.py`, 5 tests); group 23's
schema check requires `plane`. No golden moved.

**Result.** Boundaries (prefill, attention offloaded; knee ffn2 on every
scheme): star 0.202 / routed 0.808 x3 / bus 2.02 GB/s at NeuRRAM -> 15.4 /
61.6 / 154 GB/s at HERMES (76.3x): Simba 8.75 and ESP 32 fall below the
routed line, FlooNoC 80.6 alone stays above it. The 2.7B chain's boundary
moves 1.01 -> 77 GB/s -- 6.2x past GRS: "the network is covered by compute
at every published bandwidth" flips inside the analog family, now as
measured plane readings, not an extrapolation. The die<->unit link's
boundary is 0.101 GB/s x (10.14 us / t) in both phases (S cancels). Fixed
terms: the same 76.3x device speeds prefill 9.33x (826.4 -> 88.6 ms) and
decode only 1.11x (14.78 -> 13.34 ms; the "decode 1.3x" once written here
is corrected -- the decode stack is almost entirely the K/V write).

### C30. O17a closed: the device is a fabric input (2026-08-28)

**Motivation.** The device cycle was the literal `1.449e-6` in four scripts
and, through the fabric's 18,112 words/cycle, in every config; the registry
(C26) had its own 10.14 us / 7. Three sources of one number, two roundings,
and no way to run the model on another device without editing scripts --
while the phase diagram's second axis (O17b) IS the device.

**What was done.** `fabric.Device` (`name`, `cycle_seconds` per input bit
slice, `input_slices_per_mvm`, `calibration`; `t_mvm_s`, `words_per_cycle`,
`gbps`), declared as the `device` block of every config (the calibrated
wan_nature_2022 macro: 1.4485714 us x 7 = 10.14 us per MVM row), validated,
in `provenance()`. Bandwidths are declared in GB/s (`bandwidth_gbps`,
`hub_bandwidth_gbps`, `offchip_bandwidth_gbps`, `link_bandwidth_gbps`) and
converted at load with the fabric's device; a words-per-cycle declaration
is still accepted, both at once is an error; the unit link is 12.5 GB/s =
18,107.1 words/cycle (the 18,112 rounding is gone). The registry's
`CYCLE_S` / `T_MVM_S` / `SLICES_PER_MVM` are the default fabric's device
(so CIMSIM_FABRIC re-labels every anchor consistently); `words_per_cycle` /
`gbps_of` take an optional cycle for the device axis. `Fabric.verify_cycle`
is called in `run_op`: the run's CiMLoop cycle (`GLOBAL_CYCLE_SECONDS` of
the macro) must equal the declaration -- the fabric declares, CiMLoop is
the calibrated source it is checked against. The literal sites read the
fabric: `attention_unit_cost` / `embedding_cost` / `die_pipeline_interval`
(cycle = the fabric's device unless given), `op_breakdown.CYC_DEFAULT`,
`analyze_multidie_placement`, `analyze_digital_sensitivity`; the `/1449`
print in `analyze_offload_contention` uses `an.gbps_of`. Group 26
(`tests/test_device_input.py`, 7 tests): the declaration and provenance in
every config; the run cycle recorded by a real run equals the declaration
and a 0.1% divergence is rejected; the registry reads the device; the GB/s
declarations (link, hub, off-chip, unit; both units rejected); the
invariance the device axis rests on -- a 10x faster device makes the same
GB/s link 10x fewer words per cycle and leaves every flow's seconds
unchanged (star, mesh, bus); the former literal sites; no cycle / 18112
literal in any script. Two D2D identity tests read the device instead of
their own literal.

**Result.** Compute latencies unchanged (the Timeloop path always used the
calibrated cycle); the unit-link times and the `op_breakdown` occupancies
move by -0.03% (the 1.449 -> 1.4486 us and 18,112 -> 18,107 unification),
inside every tolerance and invisible at the printed precision.

### C29. O26 closed: the busiest-wire occupancy is a bound, and `schedule_slack` (2026-08-28)

**Motivation.** Every document listed the max end as "busiest wire, no
queueing" -- a simplification to apologise for. It is a bound: for a given
routing (the scheme and the placement fix which wires each flow occupies)
any schedule, a compile-time one included, spends at least volume /
bandwidth on each wire, so the busiest wire's occupancy is the least
serialisation any schedule can reach. Exact for private links (nothing
shared) and for a shared bus (one resource; any work-conserving arbitration
reaches it); a lower bound for a routed grid or tree, where the missing
piece is the arbitration of the flows that share a segment. Hence the O7
bracket [max, sum] is two well-defined bounds, the max end is the exact
ideal of the compile-time scheduled paradigm (Mythic / HERMES class, the
star scheme in the C26 mapping) and the optimistic bound of a NoC; the
phase diagram's boundary lines (O29) inherit that authority. Re-routing
changes the per-wire volumes and is a search move (S3), not a contention
refinement. The scheduled paradigm's open question is not queueing but
feasibility -- whether a compiler reaches the bound -- which is an input,
not a model.

**What was done.** `Fabric.schedule_slack` (>= 1, default 1.0 = the bound;
in every YAML with the statement as its comment; validated at load;
recorded by `provenance()`); `link_occupancy` multiplies every occupancy by
it (`schedule_slack=` overrides) and returns the factor; the hand-rolled
beat formulas in `analyze_offload_contention.py` and `die_serial` in
`analyze_scale_tiers.py` carry it; `die_pipeline_interval`, the tier-L /
probe paths and `analyze_d2d.py` inherit it through `link_occupancy`; the
sweep header and the ledger (busiest-wire row note, md header, JSON) state
it. Group 25 (`tests/test_schedule_slack.py`): the default in every shipped
config and the validation; the bound identity on the frozen ffn1 flows for
all five schemes (fully serial schedule >= bound, per-wire greedy = bound,
bus serial = bound, star = one flow's time); slack 1.5 scales every
occupancy and keeps the bottleneck and the scheme order; the explicit
override; the D2D pipeline inherits the factor. Documents: settings model
section, assumption 7 and the inputs table; report caveat (iv); SUMMARY
zh/en 2.5 and the platform-inputs table; PROGRESS 8.2; ANCHORS mapping
rule; DIRECTION. Validation scope: queueing / BookSim-class checks apply to
the NoC column only (O19 hygiene).

**Result.** No number moved (slack = 1 everywhere); the sentence did.

### C28. What gates the hub-position lever, and the identical-series figure rule (2026-08-28)

**Motivation (from the 2026-08-28 notes).** C27 took the buffer-position
lever from 1.67x to 1.00x and explained it as "a property of the squarer
grid with its empty slot" -- two variables (aspect ratio, occupancy
structure) in one sentence, neither isolated. Separately, three coincident
curves on the sweep figures showed one colour and read as missing data.

**What was done.** `scripts/analyze_grid_gating.py`: the same ffn1 traffic
and mapping on 3x3 (one empty slot), 2x4 (filled), 4x4 and 2x8 (8 of 16
slots; half-fill and checkerboard reported separately) x hub centre /
corner; plus the heaviest-talker sweep of group 13 on every cell. Under
xy routing the corner hub's exit wire carries every macro NOT in the hub's
own column -- busiest = N - H, verified in every cell -- and a centred hub
splits four ways (busiest 4 for 8 macros). Levers: 3x3 1.67x (3 -> 5), 2x4
1.00x, 4x4 1.50x in BOTH fillings (4 -> 6), 2x8 1.00x in both. So the gate
is the grid's WIDTH ALONG THE ROUTING'S FIRST AXIS: a 2-wide grid keeps
half the macros in the hub's column and has no lever whatever the filling;
wider grids do. Neither squareness (the 4x2 half-fill block is not square,
1.50x) nor the empty slot (the 4x4 fillings have none, 1.50x) is the
condition. With yx routing the roles of width and height swap (O19). The
soft-placement lever survives on every grid: 4 -> 7 = 1.75x on the 2x4
(either hub), 2.00x / 1.60x on the 3x3, 1.75x / 1.50x on the 4x4.
`analysis/grid_gating.png` + `.json`; group 24 (`tests/test_grid_gating.py`).
Figure rule: `scripts/figstyle.py` -- identical series are merged into one
curve with a merged label and an on-figure note, tied bars are bracketed,
coincident points get one label; wired into `sweep_axes.py`,
`analyze_anchored_sweep.py`, `analyze_contention_system.py`,
`analyze_contention_impact.py`, `analyze_placement_tradeoff.py`,
`analyze_offload_contention.py`. Documents: SUMMARY zh/en 2.3.1(a),
PROGRESS 4.3, the company report's buffer-position item.

### C27. The default die grids are the fill-exact 2x4 / 4x2 (v6), 2026-08-28

**Motivation.** The company asked for the 2x4 macro layout instead of the
3x3 with an empty slot; it was answered as a VARIANT (`mlx300_2x4.yaml`,
C1) and the documents called it the primary layout -- for the per-crossbar
heatmap, the single-operator segment map and the base GPT-2 totals, which
had `_2x4` twins. Every system-level result (the v5 pins, the thresholds,
the anchored readouts, D2D, offload, the scale tiers, the ledger and the
O25 sweeps) was computed on the 3x3 grids: the default `mlx300.yaml` and
both multi-die fabrics carried `macro mesh [3,3]`, `crossbar mesh [3,3]`,
nothing in the container set `CIMSIM_FABRIC`, no result JSON recorded its
fabric, and the report said "8 macros (2x4)" above 3x3 numbers.

**What was done.** `mlx300.yaml`, `mlx300_multidie.yaml`,
`mlx300_multidie48.yaml` and `mlx300_mesh.yaml` now carry the fill-exact
grids (macro [2,4] at 800 um, crossbar [4,2], core pitch 400 um); the
earlier grids live on as `mlx300_3x3.yaml` (comparison only);
`mlx300_2x4.yaml` and the `_2x4` twins are gone, the canonical names are
the default and the comparison carries `_3x3`. `fabric.provenance()`
writes {name, die / macro / core / crossbar mesh, macro scheme} into every
result JSON. The whole chain was regenerated (`analysis/regen_v6.sh`):
contention_impact, contention_system, run_2p7b_block, the 4-die probe, the
system totals, the ledger, then every closed-form script and figure.
Fixture `stack_per_op_v6.json` frozen; groups 14 / 17 gained v6 blocks on
the 2x4 default, the 3x3 mechanism anchors load the comparison variant
explicitly (`test_contention_anchors`, `test_contention_scope`,
`test_geometry_flows`), group 23 re-pinned, `test_fabric` checks both grids.

**Result.** The single-operator table on the 2x4: star 2x / mesh centre 8x
/ mesh corner 8x / tree 8x / bus 16x on the busiest wire (was 2 / 6 / 9 /
8 / 16 on the 3x3) -- the routed schemes TIE, so the 3x3's buffer-position
lever (corner / centre 1.67x) does not exist on this die; bus / star stays
8.27x. Whole stack: 1.00x at the reference input and at every digital
anchor (unchanged); zero-overlap end at Simba star 1.01x / routed 1.05x /
bus 1.15x (was 1.01 / 1.04 / 1.07 / 1.05 / 1.15); exact 1% crossings
0.195 / 0.782 / 0.782 / 0.782 / 1.89 GB/s, doubling 0.061 / 0.243 / 0.243
/ 0.243 / 0.68 GB/s (centre rose 4/3, corner fell 4/5, tree unchanged);
analog-reality low end: routed 1.31x, bus 3.33x. Energies moved only
through the router distance term (mean hops 1.5 vs 1.3125): whole-model
prefill 298.77 mJ (was 298.38), offloaded 213.75 (213.48), decode 666.8 /
1,755.9 uJ; line-vs-grid router lever 1.33x = 0.25% of a block (was 1.52x
/ 0.34%). Compute, write, D2D (die grids untouched), the 2.7B chain, the
unit link, the probe, the O25 D2D readouts: unchanged. Suite: see the
header count.

### C26. O25 closed: the anchor registry, the analog-reality tier and the per-axis sweeps (2026-08-28)

**Motivation.** The four bandwidth anchors were hard-coded in four scripts
and one test with two different cycle roundings and no identity field; every
"hidden at every published bandwidth" sentence was a reading in the
digital-ecosystem column only, and the analog-reality tier existed as an
[est] paragraph.

**What was done.** `scripts/anchors.py` (new) is the single source: the
digital anchors with `status` (measured / secondary / post-layout), the
analog-reality tier as an estimated BAND (on die 0.4-8 GB/s, D2D 0.1-2
GB/s, derivation stated), the CHIP POINTS of the phase diagram (t_MVM +
bandwidth coordinates, a status per coordinate: NeuRRAM measured, HERMES
derived, ISAAC design point, MX100 / Mythic / Tsinghua pending), one
`CYCLE_S` (10.14 us / 7) and the GB/s <-> words/cycle conversion.
`analyze_anchored_sweep.py`, `analyze_scale_tiers.py`,
`analyze_corner_flip.py` (moved to the v5 fixture; finding: the buffer-
position flip of v1/v3 does not exist in value units -- corner never wins),
`analyze_d2d.py`, `analyze_offload_contention.py` and the two anchor tests
import from it; `anchored_sweep.json` keys are registry keys; every anchor
readout prints both paradigms' columns. `scripts/sweep_axes.py` (new): the
per-axis harness -- A on-die link (5 schemes x 4 conditions, the knee
operator per condition), B1 D2D 355M 48-die (single-pass / pipelined x 4
orderings x on chip / offloaded), B2 D2D 2.7B chain (3 seatings x 2
conditions, crossed with A -> the on-die x D2D map), B3 the 4-die probe, C
the die<->unit link, H the partial-sum width; log grid 8 points per decade
plus the anchor values and the 2^k points, both overlap ends, exact
thresholds by bisection; `phase_sweep.json` + `sweep_axis_*.png`;
`make_figures.py` gained the anchored / d2d / offload / scale_tiers / sweep
stages. Group 23 (`tests/test_anchor_registry.py`, 15 tests) pins the
registry, the one-constant rule, the conversion, the digital columns'
agreement with the v5 pins, the band-end readouts, the exact thresholds,
the knee operators and the D2D / unit-link readouts.

**Result.** Numbers pinned before C26 did not move (the `analyze_d2d` /
`analyze_offload_contention` cycle rounding 1.449 -> 1.4486 us shifts their
readouts by 0.03%, inside every tolerance; the words/cycle knees are
unchanged). New readouts at the NeuRRAM tier: on die at 0.4 GB/s bus 3.33x,
mesh corner 1.58x, h-tree 1.31x, mesh centre 1.16x, star 1.00x (all 1.00x
at 8 GB/s); exact 1% crossings 0.195 / 0.586 / 0.782 / 0.977 / 1.89 GB/s,
doubling 0.061 / 0.182 / 0.243 / 0.304 / 0.68 GB/s; knee operator qk^T on
the point-to-point schemes in prefill on chip (ffn2 on the bus), ffn2
everywhere once offloaded. The 2.7B chain: 1.00x at GRS; 1% at 1.02-1.72
GB/s, doubling at 0.26-0.40 GB/s, 4.9-7.0x at 0.1 GB/s (replaces the [est]
"compute met near 0.5 GB/s"). The 48-die pipeline offloaded: 12-19x (mesh)
/ 70.5x (bus) at 0.1 GB/s, the dividend needs 1.2-1.9 GB/s. The unit link:
1.01x at GRS (518.1 ms = the ledger), 1% at 9.8 GB/s. Current conclusion at
NeuRRAM speed: shared media cross the line in the analog-reality tier,
point-to-point links at the 0.1 GB/s die-to-die tier; every digital anchor
reads 1.00x. The P0 gate is lifted for these numbers. Left over (P2): MX100
/ Mythic t_MVM derivations, the HERMES supplement, the ESP per-link figure
(primary publication identified, not yet read).

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
| ~~O21 context ceiling~~ RESOLVED (C38) | was: the seating's validity domain unstated (~2.5k estimated) | computed: 2,048 tokens (cell ceiling, closed form), guarded at run time, stated wherever the 48-die config appears |
| half-partition choice | the 23.49 ms stage and the +126% depend on the chosen attention/FFN split; another split moves both, direction unknown | second-order |
| batch = 1 | compute and traffic scale together with batch; ratios approximately invariant, unverified | scope statement |
| ~~O25 anchor identity~~ RESOLVED (C26) | was, not a number: the on-die anchors (Simba / ESP / FlooNoC) and the D2D anchor (GRS) are DIGITAL-ecosystem links, read as if they were the operating points of analog CIM chips. No fabricated analog CIM system publishes an on-die link bandwidth; the ones that describe their fabric are DMA + shared SRAM (MX100), board-level FPGA hubs (NeuRRAM, the Tsinghua multi-chip system) or compile-time scheduled (Mythic, HERMES) -- an estimated 2-20x below the digital anchors on die and 1-2 orders below GRS die to die | every "hidden behind compute at every published bandwidth" sentence is the reading of ONE cell (NeuRRAM-class device x digital-class link), where hiding was to be expected. Against an analog-reality tier (on die 0.4-8 GB/s, D2D 0.1-2 GB/s, both estimated) the same v5 thresholds put the 2.7B die chain's busiest link at its compute time near 0.5 GB/s and 5-8x past it at 0.1 GB/s [est] -- measured by C26: doubling below 0.26-0.40 GB/s, 1% below 1.0-1.7 GB/s, 4.9-7.0x at 0.1 GB/s |
| ~~O17c d-scaling extrapolation~~ RESOLVED (C32) | was, twice: "knee ~ d" (input trunk), then "the busiest wire is the partial-sum UP traffic, falling as capacity / d until d ~ 5,800" (read off the v5 co-residency accounting; ffn1 65,536 down / 2.1 M up per macro edge there) | measured (48 runs, C32): ABOVE the flip the busiest wire IS the input trunk and ratio = d / 114,688 exactly (the first guess's shape); the flip d* = 1,220-1,350, 4.3x below the second guess's 5,793 (which ignored the macro fanout and exact die fill); below d* the mapper replicates weights in underfull dies; ffn2 steps with the tiler's C split; every probed ratio is S-independent, attention included |
| ~~default die grids 3x3-with-a-hole~~ RESOLVED (C27) | was: the default fabric and both multi-die fabrics carried the 3x3 macro / 3x3 crossbar grids with one empty slot, so every system-level result (v5 pins, thresholds, anchored readouts, D2D, offload, scale tiers, ledger, the O25 sweeps) was computed on the grid the company had asked to replace, while the heatmap and the single-op segment map alone had 2x4 twins and the report already said "8 macros (2x4)" | the default is the fill-exact 2x4 / 4x2 since C27 (3x3 = `mlx300_3x3.yaml`, comparison only), every result JSON records its fabric, everything regenerated (v6): the three routed schemes now tie at 4x star on the busiest wire -- the 3x3's buffer-position lever (1.67x) does not exist on this die; mesh-centre thresholds rose 4/3, corner fell 4/5; star / bus / compute / write / D2D / energies unchanged except the +0.13% distance term |
| ~~O30 what gates the hub lever~~ RESOLVED (C28) | was: "3x3 vs 2x4" mixed the aspect ratio with the empty slot, and C27 called the lever "a property of the squarer grid with its empty slot" | measured on 3x3 / 2x4 / 4x4 (two fillings) / 2x8 (two fillings), same traffic and mapping: corner busiest = N - macros in the hub's column (xy routing); a 2-wide grid keeps half the macros there -> no lever (2x4, 2x8, any filling); 3x3 1.67x, 4x4 1.50x in both fillings -> the gate is the width along the routing's first axis, neither squareness nor the empty slot; the soft-placement lever (heaviest talker x4 moved) is 1.75x on the 2x4 and survives everywhere |
| **O17 device speed** (17a done C30; 17b done C31) | not a number: every threshold was a single-device reading (NeuRRAM, 10.14 us per MVM row); the plane now measures the device axis -- the busiest-operator boundary scales exactly as 1 / t_MVM (closed form, pinned to 1e-9 against the sweep) | NeuRRAM is the slow end of the analog spectrum (ISAAC design point 1.6 us, 6.3x; HERMES ~133 ns, 76.3x [derived]). Measured plane readings (prefill, attention offloaded): the on-die r = 1 boundary moves from 0.20 / 0.81 / 2.0 GB/s (star / routed / bus) to 15.4 / 61.6 / 154 GB/s at HERMES -- Simba and ESP fall below the routed line, FlooNoC alone stays above; the 2.7B chain's boundary moves 1.01 -> 77 GB/s, 6.2x past GRS -- both stories flip INSIDE the analog family. The whole stack does NOT scale: the same 76.3x device speeds prefill 9.33x and decode 1.11x (K/V write and digital unit fixed; the fixed-term decomposition figure) |

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
| device | array energy/latency model | CiMLoop's silicon-calibrated wan macro (NeuRRAM class: 1.4486 us cycle, 7 input slices = 10.14 us per MVM row), declared as the fabric's `device` block and checked against the macro on every run (C30); the (t_MVM x bandwidth) plane measured (C31: closed-form boundaries, collapse, fixed terms), the width law mapper-measured (C32: trunk ratio d/114,688, flip d* in 1.2-1.35k), four silicon marks (C36) | -- (device axis closed; default die grids fill-exact 2x4 / 4x2 since C27, `mlx300_3x3.yaml` kept for comparison) |
| device | value-dependent energy | real per-model histograms (OPT-2.7b extracted); per-crossbar mode gated by device class; the CNN sampling seeded (C40) | -- |
| device | weight / K-V write model | append-only geometry + per-cell/row-serial params (our overlay) | write params are platform inputs (DR-5); long-context K/V (O14) |
| per-op mapping | intra-op loop tiling | **provided by the CiMLoop mapper** (EDP search) under the op's co-residency share (C14) | default greedy path guarded by the residency tripwire |
| per-op mapping | over-capacity residency policy | three explicit mechanisms + closed-form tiler (C12) | input-row split untested (O15); dynamic ops (O14) |
| per-op placement | weight blocks -> macro/core/crossbar | Placement object + sequential fill; rankings measured | unpriced links keep it a ranking (O1); search (S3) |
| per-op placement | shared-buffer attach point | scheme parameter; the hub lever is GATED by grid width (C28: nil on the fill-exact 2x4, 1.67x on the 3x3 variant); the soft heaviest-block lever survives every grid (1.5-2x) | search (S3); the anchored soft-lever table = plan step 2 |
| on-die wiring | interconnect organisation | scheme registry: star/mesh/tree/bus per level; full-duplex per-direction wires, bus shared (C17) | more schemes (O19); bus wire energy (O8); routing-algorithm asymmetries (XY vs YX replies, O19) |
| on-die wiring | transfer paradigm | paradigm -> tier mapping in the registry (C26: DMA/shared-SRAM -> the T1 hub axis, compile-time scheduled -> star, NoC -> mesh); `schedule_slack` input (C29); the T1 hub axis itself in analytic closed form (C34) | -- |
| cross-die mapping | dies per op and split dimension | tiling planner (power-of-two aware, residency enforced) | cross-die addition path unexercised (O15); utilisation loss quantified, not optimised |
| cross-die mapping | layer/op -> die granularity | feasible 48-die config, two dies/layer (C13); co-resident per-op mapping (C14); the 2,048-token attention context ceiling computed and runtime-guarded (C38) | half-partition is an assumption (register) |
| cross-die placement | die-group seating on the package | the block's die-sets seated disjointly, three styles (C23) | whole-model seating (**O16**); search (S4) |
| cross-die wiring | package interconnect organisation | same registry one level up, GRS-anchored, full-duplex (C17); producer-to-consumer routing, the tensor once (C23) | O19 applies |
| traffic accounting | multicast/reduction structure and units | v1 structured traffic in VALUE units (C25: reads / bit-slice, bit and cell-column factors; reassembly guard); down/up components kept, partial sums at 16 bits on wires (C17); the hyperedge membership convention confirmed at the loop-nest level (C38) | partial-sum width in the ENERGY overlay (transport <2% of energy) |
| traffic accounting | cross-die traffic classes | hidden-state hand-offs + intra-op slices + the offload streams to the attach point (C21); elementwise operators move through the glb only (C19, stated) | host I/O streams |
| contention | bandwidth & queueing model | two tiers; overlap published as a max/sum bracket (C16), off by default; the max end stated as the bound it is (C29: exact for star / bus, a lower bound for routed grids; `schedule_slack` >= 1 for schedules that cannot reach it); the T1 hub axis analytic in value units, Timeloop's counter-unit throttling kept as validation-only (C34); the PACKET bracket on NoC-paradigm links (C46: [pipelined bound, round-serialized end], explicit link fields, off on every production config) | BookSim residual measurement = plan step 4 (NoC paradigm only) |
| contention | operating mode | single-pass + pipelined, stage = slower half | bubbles/imbalance beyond the max rule; batch>1 (register) |
| contention | critical-path composition | write + [max, sum](compute, network) + propagation -- both ends published (C16) | missing terms O24 |
| calibration | bandwidth operating points | registry `scripts/anchors.py` (C26): grid with `status`, the analog-reality band, chip points, per-axis sweeps at both columns; ESP primary-sourced from the ESSCIRC 2022 paper, status measured (C36); the HERMES per-link rate is published spec, normalized to our per-macro granularity with a self-consistency audit (C36/C37); UCIe-S spec-tier D2D anchor (C40); Mythic t_MVM derived from datasheet TOPS (C36) | MX100 row time blocked on its source (plan step 10); real platform bandwidths on DR-2 |
| calibration | per-level link energy | macro silicon-calibrated + re-pricing; D2D at GRS band midpoint | core/crossbar at zero (O1; ceiling ~2% of an op after C25); bus (O8) |
| energy | static / idle power | not modeled -- every total is dynamic-only | `idle_power_w` per level (default 0) + closed-form static term, static-share sweep, peak concurrency as an output field (O27) |
| calibration | physical geometry | slot_pitch_um in the configs; first consumer landed -- `ns_per_mm` x pitch resolved to ns/hop at load (C38) | energy scale from pitch may follow |
| workload | model scales/shapes | 355M / 4-die probe / full 2.7B with real distributions | scaling-law probes d in {1024, 2560, 4096, 8192} and S in {128..2048} (O17); ~320-die joint deployment (O16) |
| workload | phases & conditions | prefill/decode x attention on-chip/offloaded, end to end with the external unit as an interface (C21); non-matmul operators on the digital unit (C19) | host I/O streams |
| verification | validation machinery | counter reconciliation, closed forms, blind-test coherence, 288 tests + goldens (48-die chain pins C15, accounting pins C17, ledger conservation C18, digital-unit pins C19, unit pins C25, device-axis groups 27-30); the change re-audit rule covers the registers AND this factor map (see the process rule below) | external-behaviour validation = plan steps 1 and 4; the two stale slow-suite goldens = plan step 3 |

The per-op placement, on-die wiring and cross-die placement / wiring rows
are the search space of S3/S4; the mapping and traffic-accounting rows are
its evaluator's foundations.

Priority order (what closing each one buys), re-cut 2026-08-27 after C25 and
the anchor-identity finding: the v5 tables are complete for ONE cell of the
phase diagram; the next deliverables open the other cells (P0 anchor grid,
P1 device axis), state the model's semantics (P1), then run the search (P3).

| # | gap | what closing it buys | class |
|---|---|---|---|
| ~~O25~~ done (C26) | was: the anchors are digital-ecosystem links read as analog operating points; no analog-reality tier; no chip points | the anchor grid (paradigm x tier, `status` per row) plus a CHIP-POINT registry (t_MVM, on-die and D2D bandwidth, each with its own status); the closed-form per-axis sweeps (on-die, three D2D workloads, unit link, partial-sum width) at the NeuRRAM tier, each reporting which operator sets the knee; the first "current" conclusion that is not 1.00x (the 2.7B chain at analog-reality D2D) | reading position + data base (P0) |
| **O17** (done: 17a C30, 17b C31, 17c C32) | was: device speed one hard-coded number, then one input with no data behind other values -- now a measured axis AND a measured d family: the plane's closed-form boundaries land on the swept thresholds to 1e-9, the whole stack does not scale (decode 1.11x at 76.3x), and the d law is the input trunk ratio = d / 114,688 above the measured flip d* = 1.2-1.3k | -- | closed (O29 consumes it) |
| ~~O26~~ done (C29) | was: the max end described as "no queueing", not as the bound it is | the statement (exact for star / bus, a lower bound for routed grids), `schedule_slack`, group 25 | model semantics |
| ~~O28~~ RESOLVED (C34) | was: the T1 axis unaudited -- Timeloop's points stretched ffn1 to 160x at "64 w/c"; counter units suspected | confirmed: Timeloop throttles the glb write port in counter units (fills x7 slices; output fills+updates x8 bit groups = 37,224,448 for ffn1), every cached point = units/bw exactly; the readable T1 axis is now analytic in value units, hub = bus + in-fill (the equivalence holds, ffn1 +6.25%), 1% at 2.27-2.33 GB/s, MX100-class 3.9-5.0x at the band's low end; no shipped config declares a hub bandwidth, so nothing published moved |
| ~~O29~~ RESOLVED (C35) | was: the phase diagram -- the paper's figure -- had no owner | drawn (`phase_diagram.png` + grayscale copy + `phase_diagram_table.md`, `analyze_phase_diagram.py`, zero mapper): boundary families with model names, three-layer shading, anchors as lines, chips as error-bar points, two arrows, collapse inset, validation points shaped by measured/closed-form; the right panel's semantics corrected in review (blues = block chains INCL. spanning ops, hence above the single-operator probe); group 30 |
| S1--S6 | no search code exists; the evaluator-proxy question is unmeasured | first search results and the proxy-optimization study | search (P3) |
| O27 | no static energy, no peak-concurrency output | idle-power input + closed-form static term; static-share sweep; concurrency field | energy completion (P4) |
| ~~O21~~ (C38) | was: an unstated ~2.5k-token K/V ceiling | computed 2,048-token ceiling + run-time guard + validity statements | closed |
| O15 | the input-row split (cross-die addition of partial results) never exercised end to end | the row-split branch of the scaling law (O17) and the expensive half of the spanning mechanism | coverage |
| O1 | core/crossbar links carry no energy (the 1 xfail) | turns the 3.69x/1.70x and 17.8% rankings into joules -- now bounded to ~2% of an op (C25) | DR-1 input |
| O8 | bus energy charged by distance-to-driver | removes the artifactual star-bus energy tie | model quality |
| O19 | four interconnect schemes only | torus / ring / express links / hierarchical NoC join every sweep for free | extensibility |
| O16 | whole-model multi-die deployment never simulated jointly | ~320-die joint seating; the search's eventual target | scale extension (outside the v5 paper) |
| O20 | tier-L seated one block at a time | subsumed by O16 | honesty debt (captioned) |
| O14 | over-capacity K/V (long-context) has no policy | attention at S>~8k simulatable honestly | scale extension (outside the v5 paper) |
| O6 | `distance_router` doesn't exist; solver constant underivable | reconnects the collaborator's solver (S5); lifts the 47% citation ban | search prereq (on hold) |

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

### O28. ~~The T1 (die-buffer) bandwidth axis is unaudited~~ -- closed (C34)

The suspicion was right: Timeloop charges the glb in COUNTER units (input
fills x7 bit slices; output fills and updates x8 bit groups; the write
port binds at 37,224,448 units for ffn1) and every cached point equals
units / bandwidth exactly -- C25's sibling on the T1 axis, caught before
any config declared a hub bandwidth. The four planned items all landed in
C34: the unit audit (closed form, exact, executable in
`analyze_bandwidth_sweep.py`); the analytic value-unit T1 occupancy with
the Timeloop points as mechanics validation; the equivalence statement --
T1 hub = T2 bus + the op's input arriving once (an identity on stored
components, pinned in group 29); and the axis in the harness
(`sweep_axes.py` `t1_hub`, 1e-3..1e4 GB/s) with the MX100-class reading
(3.9-5.0x at the estimated band's low end, 1.00x at the high end). The
second source of O29 validation points.

### O29. ~~The phase diagram has no owner~~ -- drawn (C35); the agreed design, kept for reference

Design agreed 2026-08-27. Axes: device speed (t_MVM, per MVM row) x link
bandwidth, both log. The boundary is closed-form -- knee bandwidth =
busiest-wire volume / (S x t_MVM) -- a line of slope -1 on the plane. Two
panels on the SAME plane: on-die (left) and die-to-die (right; the chain
boundary solid, the spanning boundary dashed; the capacity ratio is the
selector between them, not an axis). Every narrative element has one
visual carrier: the mechanism = the line's slope; the boundary FAMILY = one
line per measured V (d as a label -- 17c measured the family: the trunk
lines ratio = d / 114,688 above the flip d* = 1.2-1.3k, with tiler steps); the device axis = the horizontal
coordinate; the ecosystem mismatch = where the points sit (analog chips as
points with a t_MVM and a bandwidth coordinate, estimated ones with error
bars; digital NoC anchors as horizontal lines, never points); the current
conclusion = three layers (below the point-to-point knee everything
contends; between it and the bus knee the organisation decides; above,
placement-free); the trend = two arrows (model scale moves the boundary,
device speed moves the chips); validation = independent points (17c runs,
O28 T1 points) coloured by measured ratio (<1.05 / 1.05-1.5 / >1.5) against
the closed-form lines; the collapse inset (bandwidth x t_MVM = words per
MVM-row time). Condition: the on-die panel uses "prefill, attention
offloaded" (S-independent) unless O25's knee report argues for two operator
families; the offload-decode shift is a dashed variant on the D2D panel
only. Grayscale-safe; the grid -> ratio table in the repo; the caption
states the three pitfalls (d beyond one die -- and the up traffic being the
other half; the estimated tier; digital anchors as lines). Depends on O25
(points, sweeps), O17a-c (all done: device input C30, plane C31, measured
V(d, S) C32), O28 (done, C34: the T1 axis + the MX100-class reading).
Every dependency closed, and C35 delivered the standalone figure
(`phase_diagram.png`): ratio-coloured validation points, the two arrows,
the three-layer shading, the grayscale pass, the table -- with the
die-level semantics corrected in review (the d >= 2560 lines are block
chains INCLUDING their spanning operators, hence above the
single-operator probe; the pure hand-off is the d = 1024 line only).

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

### O17. The device-speed axis: one hard-coded number, and the on-die scaling in d an open question

**Current state.** The device is a fabric input since C30 (17a done):
`device: {cycle_seconds, input_slices_per_mvm}` in every config, read by
every latency and every GB/s <-> words/cycle conversion (the registry's
constants are its values), bandwidths declared in GB/s and converted at
load, the CiMLoop macro's cycle checked against the declaration on every
run. Thresholds in words/cycle are device-invariant only at
a fixed slice count; the honest axis is seconds per MVM row (cycle x input
slices): NeuRRAM 7 x 1.449 us = 10.1 us; ISAAC-class 16 one-bit slices x
100 ns = 1.6 us (6x -- not the 14.5x a per-slice comparison suggests);
HERMES-class ~130 ns (63.1 TOPS / 64 cores / (2 x 256 x 256) [derived];
~76x). The on-die scaling in d_model was stated as "knee ~ d" (input trunk
S x d over compute S x t_MVM); our own data contradict it: the busiest wire
is the partial-sum UP traffic (ffn1: one macro edge carries 65,536 values
down and 2.1 M words up), which scales as S x M_share x 2 with M_share =
die capacity / d under the column split -- falling with d until the input
side (S x d) takes over near d ~ 5,800 on this die. Measured: projections'
serial / compute 0.027 (355M) -> 0.022 (2.7B), ffn2 0.054 -> 0.045, while
qk^T rises 0.054 -> 0.071 (32 heads). Those comparisons mixed bases
(v5 share accounting vs the multi-die runs); the C32 probes measured the
family in one regime and settled it -- see 17c below.

**Fix, in three parts.**
- ~~17a, the device as a fabric input~~ **done (C30)**: `device: {cycle_seconds,
  input_slices_per_mvm}` -> t_MVM; every script reads it; bandwidths declared
  in GB/s (YAML and registry) and converted at load; the CiMLoop macro's
  `GLOBAL_CYCLE_SECONDS` is checked against the fabric value on every run.
- ~~17b, the plane~~ **done (C31)**: the t_MVM axis (0.05-100 us, 8 points
  per decade; the three silicon marks from `anchors.device_marks()` are the
  only MEASUREMENT points -- the surface between them is closed-form)
  crossed with axes A, B1, B3 and C (B2 at the marks only). The metric is
  the BUSIEST OPERATOR's network / compute ratio, not the whole-stack
  multiplier: the K/V write (65.43 ms of the 826.4 ms prefill stack) and
  the digital unit (13.37 ms) do not scale with the device, so the
  whole-stack collapse in g x t_MVM fails while the matrix part collapses
  exactly (the collapse figure; words/cycle is that unit only at the
  NeuRRAM slice count). FIXED and printed on every figure: the write model
  (SET pulse, DR-5), the digital unit (1 GHz, DR-8), the attention unit
  (DR-9), the link bandwidths. Measured: boundaries star 0.202 / routed
  0.808 / bus 2.02 GB/s at NeuRRAM -> 15.4 / 61.6 / 154 GB/s at HERMES;
  the fixed-term decomposition (device 76.3x faster, prefill 9.33x, decode
  1.11x faster -- the finding, not a bug; the "1.3x" earlier in this file
  was mis-scaled and is corrected by the measured 14.78 -> 13.34 ms).
- ~~17c, the measured V(d, S)~~ **done (C32)**: 48 mapper runs (d in
  {1024, 2560, 4096, 5120, 6144, 8192} at S = 512 -- 5120 / 6144 added to
  pin the predicted crossing -- and S in {128..2048} at d = 1024, 3 ops),
  residency tiler, column split only, full die per piece. Measured: above
  the flip the busiest wire is the INPUT TRUNK and ratio = d / 114,688
  exactly; the flip d* = 1,220-1,350, not the predicted 5,793 (falsified,
  4.3x -- macro fanout + exact die fill); ffn2 steps with the tiler's C
  split; every probed ratio is S-independent, attention included (its
  volume follows S^2, so does its compute). These are the INDEPENDENT
  validation points of the phase diagram (O29). The row split (O15)
  remains the one stated exception still unexercised.

Order: 17a (C30) -> 17b (C31) -> 17c (C32) -- all done; O28 remains open.

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

### O21. ~~The 48-die configuration has an unstated context ceiling~~ -- closed (C38)

Computed: `attention_die_context_ceiling` = (DIE_WEIGHT_CELLS - 8 d^2
resident cells) / (4 d cells per token) = **2,048 tokens** at d = 1024
(the "~2.5k" estimate corrected; a cell-capacity upper bound -- array
packing can only round it down). `check_context_ceiling` raises past it
and `die_to_die_activation` calls it on the two-dies-per-layer path (die
slots >= 2 x layers); S = 512 unaffected. The validity domain is stated
in SUMMARY (zh + en), PROGRESS and settings (assumption 5 now carries the
computed value). The long-context mechanism itself remains O14.


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
the results-affecting register above AND of the factor map (the
current-solution / improvements table), recorded in tests/CHANGELOG.md,
in the same change. Discovering a stale assumption by being asked is a
process failure. (The factor map was outside this rule's wording until
2026-09-01 and accumulated five stale cells over C32-C40; swept then,
and in scope ever since.)

P0 gate (2026-08-27): until O25 lands, no [est] number enters an external
document; v4-and-earlier anchored figures and tables are retired from
citation; every new row is built on the v5 fixtures. Correction history
stays in the CHANGELOG -- the paper presents v5 numbers and the four
validation mechanisms (closed forms, counter reconciliation, anchor
landing, regression pins), not the corrections.

## Worklist

Everything closed so far lives under Completed (C13--C40) and in the
struck rows above. Compact roll-up: co-residency shares; the overlap
bracket; physical duplex wires with 16-bit partial sums; the digital
vector unit and end-to-end offload in the totals; producer-to-consumer
die routing; value-unit wire volumes; the anchor registry with chip
points and provenance; the fill-exact grids and the hub-lever gate; the
busiest-wire statement with `schedule_slack`; the device as a fabric
input; the (t_MVM x bandwidth) plane with the collapse and fixed terms;
the measured V(d, S) with the d family and verified scheme multipliers;
the T1 audit; the phase diagram; the anchor closures (Mythic derived,
HERMES published + normalized + self-consistency-audited, ESP
primary-sourced, UCIe spec tier); the context ceiling with its run-time
guard; the write-bound mechanism and the offloaded fixed-terms twin; and
the whole hygiene slate. C-numbers remain as changelog IDs only; the
archive sections below keep their historical O-tags for traceability.

**The plan forward, in execution order.** Its spine is the paper's
validation chapter (inherited calibration / counting / semantics /
external behaviour / robustness) and then the freeze.

1. ~~**Simba reproduction**~~ **DONE 2026-09-03 (C41-C48;
   SIMBA_PREREG §12 is the closing record)** -- was: (8 working days)
   the external validation of the
   SOFTWARE-placement channel: Simba measured fixed hardware with only
   the assignment varied, which is precisely what our search targets, so
   after this step the validation chapter carries one external contrast
   per layer (HERMES audits the accounting caliber; Simba the
   soft-placement effect). Build a Simba preset fabric at the papers'
   EXPERIMENT operating point (36 chiplets 6x6, evaluation on 32; per
   chiplet 16 PEs + Global PE + RISC-V on a 4x5 NoC mesh; NoC 70
   Gb/s/link at 0.72 V; GRS in the experiments' 11 Gb/s mode = 5.5 GB/s
   per link direction, NOT the 12.5 GB/s max the worklist assumed; X-Y
   routing; weights preloaded, layer-sequential) -- extraction DONE
   2026-09-02, every parameter verbatim-sourced in
   `analysis/papers/simba_extracts.md`, pre-registration in
   `analysis/SIMBA_PREREG.md` awaiting user review; ResNet-50 conv layers
   (Timeloop-native); reproduce the measured placement levers. THREE
   targets, pinned to their exact experiments (SIMBA_PREREG.md): (1)
   far/near seating spread (MICRO'19 Fig 9: res4a_branch1, four
   chiplets, tiling fixed; the five seatings DECODED from the figure --
   expanding squares from a corner, longest-pair distance 2..10; the
   text's "12 hops" is a source inconsistency, unused; measured bars
   1.000..2.530) -- ordering tier is the hard line, factor tier [1.265, 5.06]
   (band on the measured 2.53); (2) the data-placement gain (Fig 15: 32 chiplets, greedy IA/OA
   placement vs the sequential default; best bar pixel-reads 1.160 =
   the abstract's 16%, seven of 19 layers at 1.00) -- direction must be
   right, magnitude 8-32%, direction-first; (3) the scaling shape (Fig 7's three layer
   classes 17/12/24 of 53; ordering classes with elbow positions within
   2x, NO absolute line; JSSC Fig 18's sync breakdown = reference
   reading only — its sync component is on our unmodeled list) -- target 3 is DROPPABLE: it must be
   reachable with config + assignment changes only, and if any scale
   point needs a new mechanism it is dropped, never coded for. Day
   plan: 1 DONE 2026-09-02 (extraction + pre-registration; gate =
   user review of SIMBA_PREREG.md); 2 DONE 2026-09-03 = C41 (simba.yaml at the experiment point; the
   device_class bypass, explicit-field only; group 31 pins; config
   FROZEN); 3
   DONE 2026-09-02 = C42 (closed-form conv workload, touched-extent
   volumes, guard substitution stated; execution model confirmed, no
   amendment needed); 4 DONE 2026-09-02 = C43 (the
   hand-check HARD GATE passed: pilot 3x3, multicast/reduction
   membership, conservation, anti-im2col, conv==matmul bridge -- all
   against hand integers); 5 DONE 2026-09-02 = C44 (T1 run under amendment A1: serialization
   seating-flat, T1a degenerate/not claimed, T1b tier-2 class gap in
   the declared UNDER direction -- the whole 2.5x is per-packet latency
   + sync, BookSim to stamp; SIMBA_PREREG §8); 6 DONE 2026-09-03 = C45 (T2 under amendment A2:
   the placement lever reproduces -- greedy never loses, best-gaining
   layer coincides (res3a_branch1); T2b double-sided tier-2, same
   mechanism as T1 read from the gain side; res2c tie = self-aligned
   baseline artifact, recorded; SIMBA_PREREG §9); 6.5 DONE 2026-09-03 = C46 (the packet-level
   bracket, inserted before T3 on review: pessimistic end = declared
   round-serialized discipline, NOT a bound; 17/16 header share = a real
   tightening on both ends; T1 pessimistic ladder tracks the measured
   bars from below, residual 0.7-5.2% distance-linear; sub-case bracket
   contains 1.05; BookSim's task upgraded to "measure the residual";
   SIMBA_PREREG A3 + §10); 7 DONE
   2026-09-03 = C47 (T3: graded rail 1/3 -- the first falsified
   pre-registration choice, logged; class bracket contains measured
   3/3, post-hoc labeled; tiling-freedom divergence again on res3a;
   Simba = the first DIGITAL chip point on both plane panels, excluded
   from device_marks by the new paradigm field -- the diagram predicts
   exactly the D2D exposure Fig 9 measured; SIMBA_PREREG A4 + §11); 8 DONE 2026-09-03 = C48 (the
   measured-vs-bracket figure `simba_validation.png` + make_figures
   stage; SUMMARY §2.6 EN+ZH, PROGRESS, README synced; SIMBA_PREREG §12
   closing verdict with the handover pointers). **STEP 1 COMPLETE**
   (C41-C48): the validation chapter carries one external contrast per
   layer -- HERMES audits the accounting caliber, Simba the
   soft-placement effect; BookSim inherits the scoped residual list,
   the robustness table inherits the bracket row. The C30 device self-check bypass is keyed on an
   EXPLICIT `device_class` field in the device block (default
   `reram_macro` keeps today's hard check; only a declared
   `digital_throughput` class skips the macro reconciliation, with the
   validate() sanity checks kept) -- never inferred from missing ReRAM
   parameters, so a typo'd ReRAM config still fails loudly. Provenance
   goes into anchors.py derivation strings + ANCHORS.md, the same
   discipline as ESP / HERMES / Mythic, no separate file. GATE --
   before the first simulation runs, a half-page
   pre-registration is due (half a day, content prep not a new step):
   (a) a per-target criteria table, one hard line per published effect
   -- the ~16% communication-aware placement gain and the ~2.5x
   far-chiplet tail spread each get their own pass criterion (trend
   direction, ordering, or factor range; magnitude within 2x overall);
   (b) two pre-declarations in the configuration mapping: the device
   layer stands in Simba's digital MACs with an abstract
   equivalent-throughput unit (device physics is NOT under validation
   here), and the bias direction -- our busiest-wire occupancy is a
   declared optimistic lower bound for a wormhole NoC, so any
   systematic deviation should be an UNDERESTIMATE (the unmodeled items
   -- queueing, flit serialization, router pipelining, sync barriers,
   control overhead, DRAM streams -- all push the same direction, and
   the list is written out so the yardstick exists before the numbers
   do), and mismatches are triaged in that direction first; PLUS the
   execution-model alignment declared from the extracted
   weight-residency conditions (layer-sequential is our platform's
   standing assumption; preload-vs-pipeline follows the paper's
   placement experiments as extracted; if the day-3 config wiring
   contradicts the declaration, the pre-registration is AMENDED before
   any target runs -- otherwise days 5-6 deviations cannot be triaged);
   (c) the triage rule, three tiers: direction and magnitude within
   criteria = pass, into the validation chapter; direction matches the
   declared underestimate but magnitude beyond the 2x band = class gap,
   magnitude recorded in the limitations paragraph with the most likely
   unmodeled item named, and left for the BookSim step to stamp (if its
   schedule-slack interval covers the magnitude, the attribution
   upgrades from inference to measurement); direction wrong (we
   OVERestimate) or an ordering broken = the pre-declared gap cannot
   explain it, formal changelog reopen, debugging in dependency order
   (conv traffic extraction first, then routing/seating, then occupancy
   semantics). The half-page cleared = Simba is released to run.
2. **Soft-placement lever table at the anchors** (half a day, closed
   form, no new simulation; run before or alongside the document round).
   Attribution framework: hardware placement (scheme / links / geometry /
   device) sets WHERE the boundary lines sit; software placement (the
   heaviest block's macro, unit-to-die assignment / seating / ordering on
   fixed hardware) moves the busiest-wire load -- each line is really a
   1.4-2x wide BAND, and the analog-reality operating points ride the
   lines, where exactly that width is hidden-vs-exposed. Fold best/worst
   heaviest-block attribution x the analog-reality anchors x conditions
   into WHOLE-STACK readouts (expected: ~1.31x at 0.4 GB/s stretching to
   ~1.5-1.7x; larger at the band's low end; zero above the knee), and
   collect the die-level rows (2.7B seating 1% threshold 1.02-1.72 GB/s;
   48-die offloaded orderings 12-19x at 0.1 GB/s; the +124% dividend
   threshold 1.2-1.9 GB/s moving with the ordering). This is the search
   chapter's motivation table; the ultimate proof stays the
   proxy-optimization experiment of step 7.
3. **Document round.** DR-table refresh (real-bandwidth input returns to
   first order in the analog-reality column; the write model stays the
   one device-side input that moves decode); the settings document's
   version header; the company report absorbing the recent findings; the
   SUMMARY validation section (the five-part frame above); the README
   fork-index section (docs + key scripts) already landed in the
   2026-09-01 md refresh -- this step only re-checks it is current, and
   extends the script list if new entry points appeared. Includes
   re-deriving and re-pinning the two stale slow-suite goldens found
   during the hygiene pass (pre-existing at the pushed HEAD: the
   volume-conservation identity apparently left in counter units on one
   side -- both numbers clean multiples of 4096 -- and the tiny-example
   position spread never re-pinned after the grid change); re-derive
   with attribution, never band-aid the pins.
4. **BookSim cross-check** (3-day timebox). Since C46 its task is
   UPGRADED: not "explain the 2.5x" but "measure the packet bracket's
   residual" (T1's distance-linear 0.7-5.2% = acks / multicast rounds /
   sync) and calibrate where in [pipelined, round-serialized] real
   schedules sit. Convert the extracted mesh
   flows of one operator into cycle-accurate NoC traces (both injection
   models, assumptions stated); three bandwidth points around the knee;
   the reading -- BookSim makespan over our max end -- turns the
   NoC-paradigm `schedule_slack` from a default 1.0 into a measured
   interval (ANCHORS' NoC row gains it). It validates ONLY the max-end
   claim: not volumes (counted), not device timing (calibrated), not the
   scheduled/DMA side (exact by construction).
5. **Robustness table** (half a day, closed form). Every published
   conclusion x model error 2x / 5x: does the region verdict survive a
   k-fold boundary shift on the log axis. One row for the attribution
   split itself: does the 1.4-2x software band survive or collapse to 1,
   and if it collapses, in which diagram cells the soft-placement
   narrative fails. The validation chapter's closer.
6. **FREEZE.** Preconditions: fast AND slow suites fully green (step 3's
   goldens resolved first); the slow suite runs weekly and mandatorily
   before every freeze.
7. **After the freeze: the placement search milestone.** An evaluator API
   wrapping the existing pipelines (anchor column and device tier as
   arguments; `schedule_slack` honoured) -> baselines + greedy -> the
   search studies -> the proxy-optimization experiment over the pure
   soft space (macro attribution + die assignment / seating / ordering;
   the hub knob only in width >= 3 design exploration). Run only in the
   cells where the diagram has play (fast device, shared medium,
   offload-decode, weak D2D x spanning).
8. **After the freeze: static energy + peak concurrency** (closed-form,
   cheap; archive: O27). A per-level idle-power input; the static term
   inherits the latency ranking, giving slow layouts a cost the
   dynamic-only account cannot see.
9. **Kept, lower** (open model items; archive tags for the sections
   below): the input-row split of die spanning (O15) -- now the one
   stated exception of the measured width law; the long-context K/V
   residency policy (O14); whole-model joint seating (O16 / O20);
   lower-level link energies (O1, the expected-fail; awaiting DR-1);
   bus energy under-estimated by construction (O8); interconnect
   registry growth, torus first (O19).
10. **Blocked / waiting on external input.** The MX100 row time (no
    published rate as of 2026-09-01; revisit on TetraMem's 22nm SoC
    publication). Platform inputs: DR-1 (lower-level link energies),
    DR-2 (real link bandwidths -- replaces the estimated bands and the
    chips' estimated error bars with points), DR-4 (propagation sign),
    DR-5 (the write model), DR-9 (the real offload unit's values).

Paper scope. Thesis: when the communication cost of
analog CIM is first-order is a phase diagram (model scale x device speed x
transfer paradigm x link tier); this work is the first instrument that can
draw it, with the axes calibrated against published silicon. Three
contributions: the instrument (placement-explicit, contention-computable,
paradigm-selectable; T2 statement, four validations, microsecond
re-scoring), the diagram (on-die and D2D unified by two ratios plus the
device axis; current conclusions at the slow analog tier -- point-to-point
free, shared medium at the line, spanning forbidden at weak D2D -- and trend
conclusions from the scaling law and the four silicon scales), and the
search (S1--S6, with the proxy-optimization failure as the result).
WORDING RULES for the contribution sentences (review, 2026-09-01):
placement is written LAYERED -- hardware placement (scheme / links /
geometry / device) sets where the boundary lines sit, software placement
(block and unit assignment on fixed hardware) is the 1.4-2x width of each
line; the software lever is reported honestly at 1.4-2x, never borrowing
the scheme-level 8x -- the argument is positional ("in the critical zone
the map marks, that gap is exactly hidden-vs-exposed, and the real analog
operating points live in that zone"). The two-client structure goes into
the general-platform positioning paragraph: hardware-side multipliers
serve design exploration, the software band serves deployment search --
one instrument, two client classes. Energy
in one sentence: dynamic energy is layout-blind (v5: <=0.2% on die, +1.2-1.3%
across dies at the GRS anchor), static energy inherits the latency ranking
(O27). Out of scope for the paper: the agent direction, residency detail
(O14 / O16), company-specific wording, meshX > 1, O15, the long-form
report. BookSim-class checking is IN scope -- it is plan step 4, its
slack interval feeds the validation chapter and the ANCHORS NoC row;
the old note meant a RANGE limitation (such checks apply to the NoC
paradigm column only, per the C29 bound statement), not an exclusion.

Not scheduled until asked: giant layers across dies beyond the tiler's
range, multi-package scaling.
