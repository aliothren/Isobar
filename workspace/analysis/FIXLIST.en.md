# Fix List

Status of the code-level defects and gaps. Completed items first (motivation /
what was done / result), then what remains open — in priority order, with a
worklist at the end. Guardrail tests live under `workspace/tests/`
(`python3 tests/run_tests.py`; currently 428 pass + 0 expected-fail (slow adds group 38), which is
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
| per-op placement | weight blocks -> macro/core/crossbar | Placement object + sequential fill; rankings measured, and in joules since C58-c (one per-leaf constant, orders exact) | search (S3); DR-1 swaps the derived prices |
| per-op placement | shared-buffer attach point | scheme parameter; the hub lever is GATED by grid width (C28: nil on the fill-exact 2x4, 1.67x on the 3x3 variant); the soft heaviest-block lever survives every grid (1.5-2x) | search (S3); the anchored soft-lever table = plan step 2 |
| on-die wiring | interconnect organisation | scheme registry: TEN schemes (star/mesh/h_tree/bus + torus/ring C60 + switch/cmesh/hier_wide/express C63) with reply/o1turn knobs; full-duplex per-direction wires (C17), bus shared; energy wire models (C59); count/length accessor split with the packet guard over five schemes (C60/C63) | O19 CLOSED -- nothing queued; real layouts swap the declared constants |
| on-die wiring | transfer paradigm | paradigm -> tier mapping in the registry (C26: DMA/shared-SRAM -> the T1 hub axis, compile-time scheduled -> star, NoC -> mesh); `schedule_slack` input (C29); the T1 hub axis itself in analytic closed form (C34) | -- |
| cross-die mapping | dies per op and split dimension | tiling planner (power-of-two aware, residency enforced) | cross-die addition path unexercised (O15); utilisation loss quantified, not optimised |
| cross-die mapping | layer/op -> die granularity | feasible 48-die config, two dies/layer (C13); co-resident per-op mapping (C14); the 2,048-token attention context ceiling computed and runtime-guarded (C38) | half-partition is an assumption (register) |
| cross-die placement | die-group seating on the package | the block's die-sets seated disjointly, three styles (C23) | whole-model seating (**O16**); search (S4) |
| cross-die wiring | package interconnect organisation | same registry one level up, GRS-anchored, full-duplex (C17); producer-to-consumer routing, the tensor once (C23); ring/torus ordering-spread readout at the die level (C60: weave lever 3.4x); switch = the computable placement-irrelevant D2D option (C63) | O19 CLOSED; DR-3/real package data swap constants |
| traffic accounting | multicast/reduction structure and units | v1 structured traffic in VALUE units (C25: reads / bit-slice, bit and cell-column factors; reassembly guard); down/up components kept, partial sums at 16 bits on wires (C17); the hyperedge membership convention confirmed at the loop-nest level (C38) | partial-sum width in the ENERGY overlay (transport <2% of energy) |
| traffic accounting | cross-die traffic classes | hidden-state hand-offs + intra-op slices + the offload streams to the attach point (C21); elementwise operators move through the glb only (C19, stated) | host I/O streams |
| contention | bandwidth & queueing model | two tiers; overlap published as a max/sum bracket (C16), off by default; the max end stated as the bound it is (C29: exact for star / bus, a lower bound for routed grids; `schedule_slack` >= 1 for schedules that cannot reach it); the T1 hub axis analytic in value units, Timeloop's counter-unit throttling kept as validation-only (C34); the PACKET bracket on NoC-paradigm links (C46: [pipelined bound, round-serialized end], explicit link fields, off on every production config) | BookSim residual measurement = plan step 4 (NoC paradigm only) |
| contention | operating mode | single-pass + pipelined, stage = slower half | bubbles/imbalance beyond the max rule; batch>1 (register) |
| contention | critical-path composition | write + [max, sum](compute, network) + propagation -- both ends published (C16) | missing terms O24 |
| calibration | bandwidth operating points | registry `scripts/anchors.py` (C26): grid with `status`, the analog-reality band, chip points, per-axis sweeps at both columns; ESP primary-sourced from the ESSCIRC 2022 paper, status measured (C36); the HERMES per-link rate is published spec, normalized to our per-macro granularity with a self-consistency audit (C36/C37); UCIe-S spec-tier D2D anchor (C40); Mythic t_MVM derived from datasheet TOPS (C36) | MX100 row time blocked on its source (plan step 10); real platform bandwidths on DR-2 |
| calibration | per-level link energy | macro silicon-calibrated + re-pricing; D2D at GRS band midpoint; core/crossbar at derived prices in the overlay (C58, 1.11% of ffn1, inside the C25 ceiling) | bus (O8); DR-1 replaces the derived tier |
| energy | static / idle power | not modeled -- every total is dynamic-only | `idle_power_w` per level (default 0) + closed-form static term, static-share sweep, peak concurrency as an output field (O27) |
| calibration | physical geometry | slot_pitch_um in the configs; first consumer landed -- `ns_per_mm` x pitch resolved to ns/hop at load (C38) | energy scale from pitch may follow |
| workload | model scales/shapes | 355M / 4-die probe / full 2.7B with real distributions | scaling-law probes d in {1024, 2560, 4096, 8192} and S in {128..2048} (O17); ~320-die joint deployment (O16) |
| workload | phases & conditions | prefill/decode x attention on-chip/offloaded, end to end with the external unit as an interface (C21); non-matmul operators on the digital unit (C19) | host I/O streams |
| verification | validation machinery | counter reconciliation, closed forms, blind-test coherence, 393 tests + goldens (48-die chain pins C15, accounting pins C17, ledger conservation C18, digital-unit pins C19, unit pins C25, device-axis groups 27-30); the change re-audit rule covers the registers AND this factor map (see the process rule below) | external-behaviour validation = plan steps 1 and 4; the two stale slow-suite goldens = plan step 3 |

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
| ~~O15~~ RESOLVED (A2/C61) | was: the input-row split never exercised end to end | measured: a load-relocation valve between levels (on-die relaxes up to 4x, the bill moves to the psum-dominated die edge; two-level statement is the hard rule); underfull direction refuted except C-heavy shapes; ffn1 identity sentinel pinned (group 46) | coverage |
| O1 | ~~core/crossbar links carry no energy~~ CLOSED (C58: derived prices, overlay column 1.11% of ffn1; rankings in joules with orders exact; the last xfail promoted) | DR-1 replaces the derived prices outright (a constant swap) | DR-1 input |
| O8 | ~~bus energy charged by distance-to-driver~~ CLOSED (C59: per-scheme energy wire models -- bus = whole serpentine line, h-tree = registered physical table; the artifact tie retired, span 1.007x -> 1.057x) | real layout lengths swap the example constants | model quality |
| ~~O19~~ CLOSED (C60 + C63 batch) | was: four interconnect schemes only | ten schemes: + torus/ring (C60), switch, cmesh, hier_wide, express + reply/o1turn knobs (C63); every addition with degeneration short tests; five count/length-split schemes under the packet guard; the batch's findings: switch = the computable placement-irrelevance ceiling, cmesh k* crossover, express = an absolute valve not a sensitivity antidote, hier_wide = poured readings right numerically wrong structurally, reply knob provably inert in the busiest-wire account | extensibility |
| ~~O16~~ MEASURED under the static-spread hypothesis (A4/C62-b) | was: whole-model deployment never simulated jointly | one measured flat seating (544 dies, 17/layer x 32): whole vs block x 32 = +1.27% latency at GRS (+12% at 0.1 GB/s), +1.83% energy -- geometry-dominated increment, the ~4% D2D share cited with its geometry attached; hybrid residency = decision-layer future work; the seating is the S4 test payload | scale extension (outside the v5 paper) |
| ~~O20~~ | tier-L seated one block at a time | subsumed by O16, now measured (A4/C62-b): the published block rows ARE the lower bound, and the whole-machine surcharge is quantified (+1.27% latency at GRS) | honesty debt (captioned, now quantified) |
| ~~O14~~ CLOSED at the declaration tier (A3/C62-a) | was: over-capacity K/V has no policy | O21 gate gained the opt-in window mode (truncate + the verbatim semantics note: equivalent sliding-window attention, accuracy outside scope); validity domain re-stated (S<=2048 full attention / any S windowed, declared); eviction + tiered residency archived as un-built design space awaiting product intent -- no machinery, no pricing, no scans | scale extension (outside the v5 paper) |
| ~~O6~~ RETIRED with S5 (C64-a) | was: distance_router missing, solver constant underivable | the collaborator has withdrawn; nothing consumes W_MACRO_DIST any more; the 47% ban becomes PERMANENT (11% flat stays usable) | -- |

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

### O1. Only the macro-level router carries an interconnect energy model *(mechanism closed C58-b; was the last xfail)*

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

A5 EXECUTION (2026-09-08, C58-a; six-day plan approved with mergers
2+3 / 5+6; days 1-2 DONE, days 3-6 pending).
DAY-1 ROUTE RULING (user, before any number ran): the OVERLAY route --
the CiMLoop account is untouched. Three filed reasons: (i) semantic
honesty -- the account route would CLAIM "the CiMLoop components carry
these levels' energy" via a stand-in simulation-grade edit (moving every
pinned total ~2%, a full re-pin round buying only a relocated constant),
while the overlay route DECLARES "a supplemental mutual-estimate outside
the calibrated account", the D2D-surplus convention, at the price of one
test's acceptance clause; (ii) evidence grades stay where they belong --
these prices are derived-tier; writing them into the silicon-calibrated
per-word account would dilute the "inherits calibration" status of that
layer: CiMLoop account = inherited silicon calibration, overlay = our
declared supplement; (iii) when DR-1 lands, the overlay route swaps a
constant; the account route would need another model-change round.
The xfail's acceptance clause is rewritten accordingly (recorded in the
test docstring): passes on positive derived prices in the fabric config
PLUS a positive overlay energy column for both levels (day 3).
DAY-2 PROVENANCE RULING (user): route (b) -- geometric scaling from the
calibrated anchor; NOT (a) the 1 pJ/word example default (a sentinel
built to prove the ceiling, not an estimate). Chain, each step sourced:
router energy on ffn1 (silicon-calibrated account) 26.68 uJ / 8,912,896
C25 value-words through glb<->macro = 2.993 pJ/word at 1 hop; scaled by
the C38 declared pitch ratios (800/400/100 um; energy ~ wire capacitance
~ length; the pitches are platform-declared example defaults until real
ones arrive) -> core 1.497, crossbar 0.374 pJ/word. Pre-registered
BEFORE the run: the route, the fallback rule ((a) only on a broken
geometry chain, labeled EXAMPLE DEFAULT -- its own provenance class,
never mixed), and the acceptance gate; the specific price values were
NOT pre-registered (they are readouts of the chain, not predictions).
GATE RESULT: charging ffn1's value volumes (10.49 M core-level +
25.17 M crossbar-level) at the derived prices, 2 hops = 50.3 uJ = 1.86%
of the 2.70 mJ operator -- the C25 ~2% ceiling reproduced by an
independent arithmetic; PASS. Artifacts:
scripts/derive_lower_link_prices.py -> analysis/lower_link_prices.{json,md};
pins: tests/test_lower_link_prices.py (group 42).
DAYS 3-4 DONE 2026-09-08 (C58-b; released with two riders, both
honored): mechanism = fabric carries the derived prices (calibration
label "derived-C58a route (b); overlay-only; DR-1 replaces outright")
and analyze_lower_link_energy.py charges the C25 TOUCHED-EXTENT value
volumes outside the CiMLoop account (rider 2: the conservation gate is
that caliber -- leaf 25,165,824 words EXACTLY = row reads/7 + adc
reads/16, upper levels at or below it). Rider 1, the itemized
breakdown: core 10,485,760 words x 1.0000 mean hops x 1.4967 pJ =
15.69 uJ; crossbar 25,165,824 x 1.5000 x 0.3742 pJ = 14.12 uJ; total
29.82 uJ = 1.11% of the 2.70 mJ ffn1 operator -- inside the C25 ~2%
ceiling, below the day-2 flat-2-hop arithmetic (real mean hops < 2,
the pre-filed direction). Hops caliber: level-hop = one slot pitch;
since price ~ pitch, level framing is asserted identical to
per-leaf-unit charging (the caliber choice cannot move the total).
The last xfail PASSES under its rewritten acceptance and is PROMOTED
in this same round (the runner's own rule) -- the suite carries ZERO
expected-fails for the first time. Group 42 +4 pins.
DAYS 5-6 DONE 2026-09-08 (C58-c) -- A5 CLOSED.
Day 5, rankings -> joules, and the order pin passes in its STRONGEST
form: route (b) prices every level proportionally to its pitch, so all
three on-die levels share ONE per-leaf-slot price (2.9934/8 = 1.4967/4
= 0.3742/1 = 0.374177 pJ/word/leaf, asserted to 1e-9) -- every volume x
distance ranking converts to joules by a single constant, orders and
ratios preserved EXACTLY by construction: 1.70x stays 1.70x (busiest
crossbar 0.343 uJ vs lightest 0.202 uJ on the 2x4 default), 3.69x
stays 3.69x (3x3 variant, 0.276 / 0.075 uJ). Region half: the
committed 17.8% index metric is UNTOUCHED and reproduced; the
physical-length re-score (macro step 800 um, core step 400 um --
pre-registered, since the index metric is anisotropic in disguise)
reads 21.4% with the ORDER PRESERVED (dataflow order 6.75 uJ/layer vs
size order 8.58, gap 1.83 uJ/layer, x12 layers 81 vs 103 uJ/pass;
caliber: inter-operator activation transport, an attribution readout
at the same per-leaf constant -- in neither the CiMLoop account nor
the overlay column). THE SEARCH-SIDE SENTENCE (pre-registered
strengthening, now pinned): distance rankings may be read as energy
rankings exactly as long as price ~ length holds; a DR-1 with prices
NOT proportional to wire length can genuinely reorder the maps -- that
would be a recorded finding, never a parameter adjustment.
scripts/analyze_ranking_joules.py (region stage host / main stage
container) -> analysis/ranking_joules.{json,md}; pins group 43.
Day 6, closeout: the company report's energy decomposition table
(SUMMARY zh/en 2.1) gains the supplement row -- core/crossbar wires
+29.8 uJ = +1.11% outside the baseline's 100%, itemized 15.7 + 14.1,
with the "transport < 2% is a lower bound" caveat upgraded to
"~2.8% all-in, remaining unpriced terms still network terms"; factor
map re-audited (per-op placement + calibration rows). O1 CLOSED at the
derived-price tier; DR-1's arrival is a constant swap.


### O8. Bus energy is underestimated by construction *(closed C59 -- per-scheme energy wire models)*

`Bus.hops()` charges Manhattan distance to the driver, so bus and star tie at
mean_hops 1.3125 and get identical re-priced energy — but a real bus drives the
whole line's capacitance every transfer. The latency side (whole level
serialized) is right; the energy side needs a per-scheme wire model (e.g.
`hops()` returning the full bus length regardless of node). Until then the
"identical energy, 8× latency" pair in C10 is partly a model artifact — the
qualitative conclusion (energy is contention-blind) survives, the exact tie
does not. Same gap, smaller: `h_tree.level_length` defaults to 1 per level
where a physical H-tree lengthens toward the root.

A6 EXECUTION -- DAY 1 (2026-09-08, C59 pre-registration; inventory
closed BEFORE any code is touched).

RULING 1 (user): bus wire model = SERPENTINE, line length (N-1) slot
pitches, charged in full to EVERY transfer regardless of endpoints --
driver position becomes energy-irrelevant (stays latency-relevant).
Filed with the user's added reason: physically the natural routing of
a shared line across a 2x4 grid, AND the disciplinally conservative
pick -- serpentine >= bounding-box half-perimeter, i.e. the choice
HARSHER on bus, self-coherent with a correction whose whole point is
"bus energy was undercounted"; pre-registered as a replaceable example
model, real layout swaps the constant. RULING 2 (user): h_tree rides
in the same round, CONDITION: the geometry rule ("subtree span halves
per branching step, wire length follows the span") must land as a
LITERAL per-level length TABLE in the registry -- h_tree is the
collaborator's lambda-1 host topology (S5), their solver must read the
same table; an embedded formula would force another caliber round.
Separate pins, no new item.

ENERGY consumers of scheme hops (switch to energy_hops, day 2):
position_aware_cost's fabric path (scheme mean -> mean energy hops;
feeds analyze_placement_tradeoff's energy rows), crossbar_comm.
build_flows d_of + die-flow distance (feeds the per-crossbar maps, the
C58 overlay column, ranking_joules, and the D2D energy family:
die_flow_surplus_energy / analyze_scale_tiers / analyze_d2d_energy_
column). LATENCY/CONTENTION consumers stay on hops(), untouched:
link_occupancy / serialization, level_max_hops (propagation),
unit_link_hops, simba_targets, op_breakdown, every descriptive
mean_hops column.

MOVING-PIN LIST (closed): NO committed numeric test pin moves. Every
shipped config is star/mesh, and for those energy_hops == hops by
definition (day-2 gate: default-fabric totals bit-identical). The tie
pin test_the_energy_tie_identity keeps its numbers (mean_hops 1.3125 /
1.75 are latency-side facts); its docstring's clause "so identical
re-priced energy" is rewritten and an energy-side broken-tie assertion
is added. Moving READOUTS (regenerated day 3): placement_tradeoff.json
+ placement_energy_latency.png + placement_link_loads.png (bus rows).

PRE-REGISTERED EXPECTATIONS, two tiers (the user's supplement 1: the
component-tier ratio is CONDITIONAL on star's unit price not moving --
discharged by construction, star's energy_hops == hops is asserted,
not assumed). Component tier: bus energy_hops = N-1 = 7 (macro level,
8 slots), constant over endpoints AND drivers; bus/star router-term
ratio 7/1.3125 = 5.33x. Operator tier: bus-centre 2.7128 mJ ->
~2.86 mJ (router term 35.0 -> 186.8 uJ), variant energy span 1.007x ->
~1.06x. SENTENCE TRIAGE, pre-written: (i) "star <-> bus identical
energy" DIES (the artifact this round exists to retire); (ii) a NEW,
physically-correct tie appears: bus-centre == bus-corner in energy
(the whole line swings either way; they still differ in latency);
(iii) "(b) is a latency finding, not an energy finding" SURVIVES
(~1.06x energy span vs 8.25x occupancy -- weakened in degree, not in
kind; the (b) paragraph's numbers are rewritten); (iv) "energy is
contention-blind" SURVIVES sharpened: the energy account now sees the
MEDIUM, still not the schedule. h_tree: direction only (lengths grow
toward the root; the table's values are readouts of the rule, no
numeric prediction filed).

DOC-REWRITE LIST (user's supplement 1; executed day 3, closed now):
SUMMARY en 2.3.1b(b) tie numbers + sentence and the zh twin; SUMMARY
en ~500-504 artifact caveats (2) and (3) + zh ~355; SUMMARY en ~1629
"There is also 1 xfail" -- STALE since C58 (an A5 leftover caught by
this inventory), rewrite + check for a zh twin; FIXLIST O8 close +
factor-map row (the O8 line in the open-items table); test_contention_
anchors module + tie-test docstrings. Nothing else quotes the tie
(grep: contention-blind / identical energy / 2.7128 / 8.25).

A5-LINKAGE ANSWER (user's supplement 2, answered at inventory as
ordered, not filed as N/A): core and crossbar levels are star
(point-to-point via the hub) in EVERY shipped config, and every sweep
variant() swaps the MACRO level only -- no bus variant exists at the
lower levels today. BUT a shared local bus at core->crossbar is a
plausible real CIM-macro layout, and the C58 overlay column reads
build_flows distances -- so the lower levels are covered BY
CONSTRUCTION, not by filing: energy_hops is scheme-generic, build_
flows switches to it, and a day-4 pin exercises a synthetic bus-at-
crossbar variant through the overlay column (expectation: each
transfer inside a core charges the full local line, (n_xbar_slots - 1)
slot pitches, and the overlay column responds accordingly). If DR-1 or
the company's layout later declares those levels bus-type, it is a
config edit, not a model round.

DAYS 2-4 DONE 2026-09-08 (C59) -- O8 CLOSED. Day 2 mechanism:
energy_hops on the Interconnect base (= hops; point-to-point schemes
are identity BY DEFINITION), Bus override = the serpentine line (N-1
= 7 slot pitches, endpoint- and driver-blind; hops()/path() untouched
so latency and contention still see the driver), HTree override = the
hops arithmetic over physical_level_length() with the rule's output
for the shipped lambda-1 host registered as LITERALS
(anchors.HTREE_MACRO_LEVEL_LENGTH_SLOTS = (2.0, 1.0); rule == literal
asserted; latency-side flat default untouched per the O8 ruling).
Consumers switched exactly per the day-1 list (pa re-pricing ->
mean_energy_hops; build_flows d_of + die distance; die_flow_surplus_
energy; scale_tiers; d2d_energy_column; multidie_placement). GATE:
fast suite all green untouched -- zero committed pins moved, as the
closed list predicted. Day 3 re-run, expectations vs data (two-handed):
bus rows 2.8580 mJ BOTH (the pre-written physically-correct new tie
CONFIRMED to 1e-12), span 1.057x (~1.06x pre-filed), h-tree 2.7513 mJ
(direction confirmed), latency side unmoved (all rows 2.60 ms).
RECORDED IMPRECISION in the pre-reg: the component-tier 5.33x was
anchored on the 3x3 host's 1.3125 (where the tie pin lives) -- it
holds there exactly (7/1.3125); the 2x4 default reads 4.67x (7/1.5).
Star row 2.7113 vs the C27-era doc quote 2.7128: star is C59-invariant
by construction (its energy path reads mean_energy_hops == mean_hops),
so the drift predates this round -- doc refreshed, noted in place.
Sentence triage executed as pre-written: artifact tie DEAD; new bus
tie ALIVE; "latency finding, not energy finding" SURVIVES on wire
models (1.057x vs 8.25x); "contention-blind" SHARPENED (the account
sees the medium, not the schedule). Day 4: docs (SUMMARY zh/en 2.3.1b
(b) rewritten with the new numbers; artifact caveats 2/3 marked
closed; the stale "1 xfail" paragraph found at day-1 inventory
rewritten in both languages), tie-test docstring + energy-side broken-
tie asserts (group 14), group 44 (6 pins: identities, serpentine,
both-grid ratios, registry table, tradeoff readout, and the A5-linkage
crossbar-level bus variant charging the full 7-pitch local line
through the same flow machinery the overlay column reads). Real
layout lengths swap the example constants; no model round needed.




### O14. Long-context K/V arrays have no over-capacity policy *(closed at the declaration tier, A3/C62-a)*

A3 EXECUTION (2026-09-09, half-day unit, per the narrowed ruling: the
company's roadmap is nowhere near long context and the item is weakly
tied to the paper's claims -- minimum-cost closeout, no execution
machinery). Landed: check_context_ceiling gained over_ceiling="window"
(default "reject" byte-identical, pinned); window mode truncates to the
2,048-token ceiling and ships WINDOW_MODE_DECLARATION verbatim (the
semantics change to equivalent sliding-window attention; the accuracy
impact is outside this platform's evaluation scope). Validity domain:
S <= 2048 (full attention) / any S (window mode, semantic change
declared on file) -- stated in the guard docstring, SUMMARY zh/en, and
here. EVICTION and TIERED residency: design space exists, awaiting
product intent -- NOT built, NOT priced, in NO scan.

`temporal_rewrite` raises NotImplementedError for dynamic ops, and K/V
arrays grow with context: at S~8k a single head-group's K array exceeds one
die. Long-context decode is currently unsimulatable past that point.
**Fix:** extend the residency planner to dynamic ops (the K/V split is by
Klen -- a spatial split is an append-sharding across dies, write lands on
one die per token); charge the D2D read fan-in of attention over the shard
set. Files: `llm_workload.py` (plan_spatial for dynamic kinds + write
routing), `test_capacity.py`. Scope: outside the v5 paper (residency
detail).

### O15. Of the two ways to split an op across dies, the expensive one has never run *(resolved C61 -- A2 measured it end to end)*

A2 EXECUTION -- PRE-REGISTRATION (2026-09-09, C61; filed with the
review's three amendments BEFORE any mapper fires).

WHAT A2 IS: the scaling law (trunk d/114,688, flip 1,220-1,350,
multiplier x4, S cancelling) was measured under COLUMN SPLIT ONLY --
the regime line in scaling_probes.json says so. Row split (cut the
input dim C; partial sums add across macros/dies at 24-bit words, 3x
activation width) is the law's ONE declared exception and R10's "the
other capacity regime". A2 turns that exception into measured rows.
Expected shape: a tail-piece, not a reversal.

DAY 0 -- THE IDENTITY RERUN (the single most important step; gate
clause physically executed). Re-run the mapper, settings untouched
from O17c (fabric, seeds, heuristics, column split only), at d = 1024
/ 2560 / 4096, S = 512, all six block matmuls (18 runs) into a
SEPARATE file (a2_identity_rerun.json; scaling_probes.json is frozen
and not touched), and compare per (d, op) against the frozen probes.
JUDGMENT STANDARD (amendment 3): three tiers -- EXACT (bitwise);
NOISE (float drift, relative <= 1e-9 -- the fast suite's standing
tight tolerance, NOT a new convention): recorded as mechanical noise,
no blockage; DRIFT (anything beyond, or ANY structural mismatch:
dies / split / piece shapes / bottleneck resource / direction): A2
SUSPENDS on the spot, the drift becomes its own prior item. Only
after day 0 passes does any later difference attribute to the split
switch -- single-variable discipline.
DAY 0 RESULT (2026-09-09): PASS in the strongest form -- 18/18 EXACT,
worst relative drift 0.000e+00 (not even noise-tier): every structural
field, bottleneck resource/direction and per-edge down/up volume
bitwise identical to the frozen probes. The environment did not move;
from here every difference attributes to the split switch.

DAY 1 -- HAND GATE (Simba precedent): one hand-computable operator,
FORCED C split; reduction membership, 3-byte psum volumes and the
conservation identities locked by hand integers. The mechanism had
one closed-form endorsement on the Simba path (res4b C:4, psum x3);
what A2 adds is the MAIN path, so the gate's target is "the mapper's
row-split structure is correctly EXTRACTED by traffic.py", not the
mechanism. Extraction wrong => stop at the gate, fix extraction only.
DAY 1 RESULT (2026-09-09): PASS, 13/13 hand checks first try
(scripts/a2_hand_gate.py -> a2_hand_gate.json). The hand operator
(P=128, C=16,384, M=1024 -- exactly 2 dies, C:2 pieces exactly one
full die each, all powers of two): planner picks C:2; the mapping
carries the die-level C split and run_op's residency guards hold (no
temporal reload, fanout used); traffic.extract reads the split, the
edge volumes land on the hand integers EXACTLY (down 1,048,576/die =
the disjoint slice, 2x = the full input once -- a row split
multicasts nothing; up 131,072/die = the FULL-M unmerged partial
sums), the reduction hyperedge is [[0, 1]], and build_flows carries
the same numbers into the flow structure the pricing machinery eats.
CALIBER NOTE recorded in the gate file: psum pricing here is DR-7
16-bit (x2 words); the review's "3 bytes" was the Simba round's
24-bit wire caliber -- never to be mixed. One correction to this
pre-registration's own text during the gate build: DIE_WEIGHT_CELLS
is 256 x 256 x 256 = 16,777,216 (arrays are 256x256), so the hand
operator was sized C=16,384, not 8,192 -- caught by the planner
check, fixed before the mapper fired.

DAY 2 -- PREDICTIONS (three + one closed-form condition, written
before the scan):
 P1 (busiest-wire family swap), PER LEVEL by amendment 1: the
    reduction aggregates at whichever level the split lands on, so the
    inequality "reduction volume x3 > input-trunk volume x1" (C25
    value caliber) is filed as ONE LINE PER LEVEL -- macro-level wires
    and die-level links judged separately; a "die level swaps, macro
    level does not" outcome must reconcile against its own line
    without ad-hoc explanation.
 P2 (S-cancellation survives), WELDED to its scope by amendment 2:
    the argument -- trunk and psum volumes both scale linearly with S
    -- holds for PROJECTIONS AND FFN, exactly this round's scope, so
    cancellation should survive globally HERE; the pre-registration
    records the dependency ("no S^2 term in scope") so the conclusion
    cannot later be mis-extended to attention row splits.
 P3 (the design-bearing one): the below-flip anomaly is the mapper
    REPLICATING weights on underfull dies; row split is the other exit
    -- pre-write "with row split allowed, underfull widths (production
    d = 1024 included) MAY pull back toward the trunk line".
 FROZEN-NUMBER FENCE: 0.81 GB/s, the flip interval, the trunk
    constant, x4 -- all four gain the "column-split regime" label
    (identity changes, numbers do not); every A2 readout lands in NEW
    rows (field row_split). If d=1024/row-split reads near 0.40 that
    is a new conclusion entered as a new row + one prose sentence;
    0.81 stays in place, the replication-signature narrative wording
    untouched.

DAY 2 CONCRETIZATION (2026-09-09, filed BEFORE the scan; the
closed forms below are paper arithmetic, no mapper has run).
P1 PER-LEVEL CLOSED FORMS (amendment 1 executed -- one line per
level, each judged against its own account):
  DIE-LEVEL line (C:n split, psum x2 word-equivalents, DR-7): the die
  edge's family swaps to psum when  2 x M x n > C.  Per op:
    qkv_proj  (C=d, M=3d):  6dn > d  -> psum-dominated for EVERY n.
    out_proj  (C=d, M=d):   2dn > d  -> psum for every n.
    ffn1      (C=d, M=4d):  8dn > d  -> psum for every n.
    ffn2      (C=4d, M=d):  2dn vs 4d -> n=2 is an EXACT TIE to the
      word (2 x d x 2 = 4d); n >= 3 psum. Pre-written: at ffn2's
      minimal split the two families carry literally equal volume --
      the direction tag is read from the data, not predicted.
  MACRO-LEVEL line (inside each die, piece C/n x full M): family
  swaps when  2 x (M / m_M) > (C/n) / m_C  with m_C, m_M the
  mapping's macro spatial factors -- the FORMULA is filed, the
  factors are read from each run's mapping (they are the tiler's
  choice, not ours). Direction expectation: the row split makes the
  on-die piece M-heavy (full M, thin C), so the macro line MAY swap
  too -- but each level reconciles against its own line; "die swaps,
  macro does not" is a legal outcome that must not need prose.
P2, WELDED (amendment 2 executed): the S-check pair is (d=2560,
  ffn2, S in {128, 512}) forced-C -- both volumes (down P x C/n, up
  P x M x 2) are linear in S=P, no S^2 term exists in the
  projection/FFN scope, so every row-split ratio must be S-free
  HERE; the weld line travels with the readout.
P3 EXPERIMENT SHAPE: (a) natural spans -- forced-C at d in {2560,
  4096, 5120, 6144, 8192}, four statics each; a (d, op) with NO
  feasible C-only tiling is a RESULT (the row split's feasibility
  frontier, recorded, never patched around). (b) the
  replication-alternative probe at d=1024: a VOLUNTARY 2-die C:2
  (probe-side forced n, not a tiler change; pieces quarter-to-half
  die). If the residual tiler cannot express the shape -> record,
  queue to O16, stop (the R10 boundary). If it runs, pre-written
  direction: the boundary threshold MAY fall from the 0.81 GB/s
  replication-shaped reading back toward the trunk line (~0.40-class
  numbers); either way it lands in a NEW row.
FENCE EXECUTION: SUMMARY zh/en scaling section gains the explicit
  regime tag on its four numbers + the "A2 row_split readouts land in
  new rows only" pointer (done with this filing); frozen_v6.md is
  frozen and untouched; the tex tables (report + company) quote 0.81
  and are deferred to the writing month per the standing
  md-only-tex-on-request rule -- noted here so the deferral is a
  decision, not an oversight. Scan output: analysis/a2_row_split.json
  (separate file; scaling_probes.json stays frozen).
RUN MATRIX (day 3+4): 5 widths x 4 statics forced-C (~20 mapper
  runs, minus infeasible rows) + ffn2@2560 S=128 (+1) + d=1024
  voluntary C:2 x 4 statics (+4): ~25 runs.

DAYS 3+4 (mergeable) -- the scan: row split enabled, O17c width
family + flip-interval probes; reconcile against P1-P3. SCOPE FENCES,
two cuts: attention ops OUT (K/V-array row split drags residency
policy -- O14/DR-5's territory; the company path is offload, no
consumer) -- projections + FFN only; O16/O20 joint seating OUT: if
the residual tiler does not support "each die holds a C slice's full
M weights", STOP at "record the unsupported shape, queue to O16" --
A2 walks TO R10's boundary, never past it.

DAYS 3+4 RESULT (2026-09-09): 25/25 points ran, feasibility
frontier EMPTY (the R10 boundary was never reached; the voluntary
d=1024 C:2 was expressible, no O16 queue entry needed). Reconciliation
(full table analysis/a2_row_split.md): P1 die line 100% (20/20 natural
psum; ffn2@1024 n=2 the EXACT TIE, verbatim); P1 per-level vindicated
("die swaps, macro does not" in 6 small-n rows, each squared by its
own inequality + tiler factors); P2 S weld holds (ffn2 S=128 == S=512
at 0.0179). P3 REFUTED IN THE MAIN: the voluntary underfull row split
makes M-heavy ops exactly 2x WORSE on-die (compute halves, full-M
psum stays) and only ffn2 (C-heavy) halves -- the company sentence
flips to "replication stays the better underfull exit except for
C-heavy shapes". TWO NEW FINDINGS booked: (1) at trunk-regime widths
row split RELIEVES the on-die busiest wire up to 4x (ffn2 0.0714 ->
0.0179) by thinning the per-die trunk, with the price relocated to
the psum-dominated die edge -- a two-level statement, mandatory; die
counts move both ways (qkv 10 vs 15 at d=5120: row split can tile
BETTER). (2) ffn1's row ratio == its column ratio at every d with the
direction flipped dn -> up (the C=d, M=4d arithmetic identity).

DAY 5 DONE 2026-09-09 (C61 closeout). The archive wording carries
the review's two framings verbatim: (1) the row split is NOT a
good/bad switch but a LOAD-RELOCATION VALVE between levels -- the
on-die side buys margin, the die level pays the bill -- and the HARD
RULE (the first constraint the search side must encode if the split
regime joins the variable set): any use is stated at BOTH levels,
the on-die number alone yields exactly the wrong recommendation; die
counts moving both ways shows the valve relocates load, not area.
(2) the ffn1 identity is pinned as a FREE REGRESSION SENTINEL: two
independent code paths must forever emit the same number at every
width; either breaking turns that pin red first. Deliverables landed:
SUMMARY zh/en row-split subsection (valve + hard rule + flipped
company sentence: replication stays the better underfull exit except
C-heavy shapes); R10 note -> the named other regime is MEASURED, the
column-split structure stands unmoved in its own regime; O15 RESOLVED
(open-items row + archive title); pins group 46 (9 tests: day-0
18/18, day-1 13/13, P1 die line + exact tie, per-level split rows,
P2 weld, P3 refutation with the exact 2x, the relief valve at both
levels, the ffn1 sentinel read from BOTH files, the regime fence);
C61 filed. No phase-figure psum family this round: the on-die busiest
wire under row split stays below or at the column-split line at every
measured width -- the boundary family the figure draws is unchanged;
noted as the reason, not skipped silently.

BUDGET AND STOP-LOSSES: 1-2 days of machine time, one mapper pass per
width point; both stop-losses (day-0 identity, day-1 gate) are reused
discipline, nothing new.

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

### O16. The 2.7B results examine one op at a time; a real deployment seats everyone at once *(A4 in progress -- static spread, the only hypothesis this round)*

Tier-L numbers take each operator ALONE, place its 4-5 dies on the
package, measure, and hand the dies back. A real deployment keeps ALL
32 layers' weights resident simultaneously -- by the STANDING
block_chain rule that is 17 dies per layer (qkv 4 + attention 1 +
out_proj 2 + ffn1 5 + ffn2 5; per-op residency and power-of-two tiling
charged honestly), 544 dies for the model. The joint question -- who
gets which region and what the traffic between regions costs -- is
exactly the die-level search's eventual target (S4).

A4 EXECUTION (narrowed ruling, 2026-09-09: STATIC SPREAD ONLY, the
simplest hypothesis, 2-3 days. The platform's true mechanism binary --
spatial_multi_die vs temporal_rewrite -- is already in the machinery;
hybrid residency and friends are DECISION-layer optimization, not
platform mechanism: future work, not built. The rewrite path does NOT
run at machine scale -- one closed-form line bounds it out as the
"static spread is the only realistic hypothesis" footnote. Product
side-goal: the seating becomes the S4 die-level search's test
payload.)

PRE-REGISTRATION (day 1, all numbers produced BEFORE the readout
script existed; the review's three amendments integrated in place):

* SEATING RULE: each layer = the standing block_chain die-sets
  (17/layer, from the mapper-measured scale_2p7b_per_op.json), layers
  laid contiguously in the placement's slot order (row-fill);
  handoffs = the tensor-once convention. Die-count REVISION recorded:
  the review's "~320-die scale" was a capacity-packing estimate
  (~10/layer); the declared rule gives 17 x 32 = 544 seated.
* GEOMETRY DECLARED, not sourced: 24 x 24 = 576 slots (32 spare),
  near-square, no product basis -- the same provenance class as the
  ruled 16 x 20, recorded as a revision, not a quiet swap. It shapes
  the adjacent-handoff distances and the busiest-link position; the
  readout's sensitivity to the grid aspect is OUT of this round's
  scope (an S4 search question if it ever matters). Fabric:
  models/fabric/mlx300_multidie576.yaml (config-only).
* COMPOSITION SEMANTICS: the end-to-end whole-machine latency is the
  PURE SERIAL sum of 32 layers (the layer-sequential assumption's
  direct extension), batch-1 single-request -- NEVER to be tabled
  against b1_orderings' pipeline readouts; direct comparison
  forbidden.
* TWO-AXIS EXPECTATIONS (each axis judged by its own account; no
  cross-frame verdicts):
  LATENCY -- whole-machine >= the block x 32 extrapolation; the main
  term is the 31 inter-layer boundaries (absent from the
  extrapolation). Closed-form pre-estimate: baseline 32 x 27.523 ms
  = 880.7 ms (matmul account); boundary words 31 x S x d =
  40,632,320; at GRS 12.5 GB/s +3.25 ms = +0.369%, at 0.4 GB/s
  +101.6 ms = +11.5%; propagation ~0.6 us, negligible.
  ENERGY -- whole-machine ~= extrapolation + the D2D increment, and
  THERE B2's sub-percent frame applies: flat 40.63 M words x 10 pJ =
  +0.406 mJ on 2.270 J = +0.018%; adjacent hops = the reference, the
  surplus overlay adds zero on top.

DAY 1 DONE 2026-09-09: the fabric variant loads and validates; the
closed-form numbers above are on file.

DAY 2 DONE 2026-09-09 (analyze_full_model_seating.py ->
a4_full_model.{json,md}; closed form, zero mapper; both columns carry
the full account -- matmuls from the stored mapper-measured file,
elementwise/digital terms, and D2D flat + surplus + propagation
SYMMETRICALLY). Headline (batch-1 pure-serial semantics, the wrap
boundary excluded): whole-machine 1034.8 ms at GRS vs the block x 32
extrapolation 1021.8 ms = +1.27%; +5.2% at 2 GB/s, +10.0% at
0.4 GB/s, +12.0% at 0.1 GB/s. Energy: 2.394 vs 2.351 J = +1.83%.
RECONCILIATION, three parts: (1) latency direction HELD at every
anchor; magnitudes explained, not adjusted -- the pre-estimate
assumed tensor-once x1 while the STANDING block_die_flows convention
multicasts to every consumer die (qkv column-split on 4 -> measured
inter-layer words exactly 4x the estimate: 162.5 M, +13.0 ms at GRS
= 4 x 3.25), and the estimate's baseline was matmul-only. (2) energy
direction held but MAGNITUDE EXCEEDS THE PRE-REGISTERED FRAME: +1.83%
vs B2's sub-percent -- booked as a FINDING with the cause identified
(the frame assumed tensor-once near-adjacent hops; the measured
increment carries the x4 multicast and a 5.6 mean-hop profile on the
declared geometry; surplus 82.5 mJ dominates the 14.2 mJ flat).
Corollary: whole-machine D2D energy ~4.0% of the account -- a few
percent, not sub-percent, at machine scale. (3) propagation 29.7 us,
negligible as pre-written.

DAY 3 DONE 2026-09-09 (C62-b closeout; the review's decomposition ask
executed first). THE INCREMENT SPLIT BY NATURE, one division each:
43.03 mJ = 1.63 caliber (the x4 multicast flat -- an accounting-
convention correction, geometry-free) + 9.99 inter-layer hop surplus
+ 31.41 layer-offset variation -- and the data sharpened the review's
two-way split into three terms: the LARGEST single term is the
layer-offset variation (layer 0, the extrapolation base, is the one
cluster seated wholly inside a grid row; the other 31 straddle row
wraps and carry higher intra surplus), itself a declared-geometry
product. Verdict: GEOMETRY-DOMINATED, 96.2% -- so the "~4.0%" share
sentence ships QUALIFIED: it carries the declared-geometry factor,
moves with the grid shape and the layer path, and is never to be
cited as a bare constant. The review's two confirmations recorded:
the extrapolation baseline is the measured block account x 32
INCLUDING its own D2D (flat + surplus + propagation, symmetric
columns), NOT day 1's matmul-only 880.7 ms; and the mid-run column-
asymmetry bug was fixed before any number was read (note retained,
now pinned). S4 payload shipped inside a4_full_model.json with the
review's seam rider: the 16-package x 2-layer example split field
(package_of_layer map + the 15 seam boundaries), so the search month
re-prices seam-cost upper-bound variants directly. Pins group 47
(6 tests); SUMMARY zh/en subsection; O16 MEASURED under the
static-spread hypothesis / O20's captioned debt now quantified;
C62-b.

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
ring, express links (skip connections over the mesh), ~~direction-split
full-duplex links~~ (RETIRED C63-a: this sentence predated O22 and was
never synced -- the direction-split account LANDED at O22/O23
(2026-08-21, v2->v3), every published multiplier was re-pinned on it
then, the resolved-items table has carried "~~O22 shared-direction
wires~~ RESOLVED (C17)" all along, and duplex=False survives only as
the explicit pre-O22 comparison knob in tests; the O19 batch plan's
duplex item was misled by this line and is CLOSED-AS-ALREADY-DONE with
an EMPTY moving-pins list), hierarchical wide-link networks of the
FlooNoC class, and routing-algorithm parameters (adaptive vs fixed
order). Each lands as one
class in `interconnect.py` plus its hand-derived identity tests; every
existing analysis then sweeps it for free.

A7 EXECUTION -- DAY 1 (2026-09-08, C60 pre-registration; contract and
affected-readout list closed BEFORE code).

RULING 1 (user): torus AND ring in one round. Ring is not merely the
free 1D specialization -- it has independent narrative value at the
DIE level: the 48-die pipeline's hand-off traffic is neighbor-
dominated, ring is that flow's natural topology, and "how much of the
ordering penalty does the ring erase" is a company-facing seating-
recommendation sentence. RULING 2 (user): sweep minimal set = the
contention OCCUPANCY table + the HUB-POSITION gating table (group 24
family); placement_tradeoff's seven-variant table is SKIPPED; plus ONE
die-level readout row -- the 48-die ordering spread (d2d_impact.json
assignments, b1 machinery) under ring and torus -- the one product-
meaning readout of this round, closed-form on existing machinery.
Expectation pre-written: the spread NARROWS (the ring removes the "far
end"). RULING 3 (user): SUMMARY zh/en gain the torus/ring row THIS
round under the standing bilingual-sync practice -- no known-gap note
left for the writing month; paragraph-level polish stays deferred.
RULING 4 (the undeclared physical assumption, ruled before start):
wrap links are NOT free equal-length wires in 2D packaging. Default =
FOLDED torus: on a folded axis EVERY hop's physical length is 2 slot
pitches, and both latency (the ns_per_mm chain) and energy (C58's
price ~ length) charge it; label "folded, per-axis link length"; the
idealized equal-length build stays available behind an explicit
param, labeled idealized.

CONTRACT (the registry's three questions, folded model): (1) distance:
hops(a, b) RETURNS PHYSICAL LENGTH in slot units -- per axis
min(direct, wrap) x that axis's fold factor (2 where folded) -- which
is the registry's standing semantics (mesh's Manhattan number is both
count and length under a uniform pitch), so the ns_per_mm chain and
the C58 pricing machinery consume the folding automatically, and the
C59 identity assertion survives VERBATIM: torus and ring are
point-to-point, energy_hops == hops on physical length. Hop COUNT
(mean strictly below mesh) is asserted separately in the pins. (2)
wires: a folded axis of width W >= 3 carries its W wrap-completing
links; an axis of width <= 2 gets NO wrap links and NO folding --
torus degenerates to mesh there (the pre-filed degenerate note: on
the 2x4 macro grid the payoff axis is the 4-wide one; it survives the
folded model unchanged). Ring = the 1D cycle over the placement
order, folded: every link 2 slot pitches uniform. (3) routing /
direction tags follow mesh's convention (dimension-ordered with a
per-axis wrap decision; XY-vs-YX replies stay an O19-queue item).

REVIEW CLAUSES (filed 2026-09-08 before the run; both land in the
contract). CLAUSE 1, the real hidden trap behind "hops() returns
physical length": the platform ALSO carries a per-ROUTER-crossing
semantics (the A3/C46 packet discipline -- a packet pays a per-router
constant per hop, a COUNT, not a length; on every shipped mesh the
two numbers coincide, so the mismatch is silent). Folded torus splits
them for the first time: a wrap route crosses 1 router but 2 slot
pitches of wire. Landed as BOTH remedies: the accessors are SPLIT
(router_hops(a, b) = the count, hops(a, b) = the physical length;
identical for every unfolded point-to-point scheme, asserted), the
pins assert them separately, AND fabric validation RAISES if packet
parameters are activated on a level whose scheme folds (the message
points at the split accessors) -- the silent-caliber-mismatch avenue
is closed by construction, not by memory. CLAUSE 2: expectation (b)
was arithmetically imprecise ("nearly neutralized") -- the ring's
mean shortest distance is ~3/4 of the line's and the fold doubles it,
so the fold generally slightly OVERSHOOTS the count saving. The
precise three-sentence portrait, pre-written: MEAN propagation/energy
flat to SLIGHTLY WORSE; TAIL (the corner long paths) significantly
improved (wrap truncates them); the NET benefit is busiest-wire load
redistribution. A small mean regression is a HIT, not a flip -- and
these three sentences ARE the honest portrait the company gets when
asked whether torus is worth building.

DAY-3 EXPECTATIONS, REWRITTEN per ruling 4 + clause 2 (two-handed,
flips are findings): (a) hop-COUNT mean: torus strictly below mesh on
any axis wider than 2 -- holds; (b) the three-sentence portrait: mean
physical propagation/energy flat-to-slightly-worse, tail truncated,
net benefit = busiest-wire redistribution -- i.e. the corner/centre
occupancy ratio compresses toward 1 and the hub-position lever
weakens: torus is the hardware antidote to hub-position sensitivity,
a control arm for the placement storyline; (c) energy side: the C58
constant applies to per-axis-weighted PHYSICAL length -- realized
through hops() itself, C58-c order inheritance BY PHYSICAL LENGTH;
(d) die level: the 48-die ordering spread narrows under ring (and
torus), the seating-recommendation sentence quantified. NO shipped
config changes; NO existing pin moves (new classes only -- the day-2
gate).

DAYS 2-4 DONE 2026-09-08 (C60) -- torus + ring LANDED. Day 2:
Torus (folds any axis of width >= 3, per-hop physical length 2 there;
width <= 2 degenerates to mesh -- the pre-filed note held), Ring (the
1D cycle over placement order, uniformly folded), the clause-1
accessor split (router_hops = count / hops = physical length; base
identity for every unfolded scheme) and the validation guard (packet
params + folded scheme refuse with a pointer to router_hops). Gate:
zero committed pins moved. Day 3 readouts (analyze_torus_ring.py ->
torus_ring.{json,md}; pins group 45, 9 tests): (1) the 3x3
corner/centre peak lever (pinned 5/3) reads EXACTLY 1.00 under torus
-- the hub-position lever CAN BE ZEROED BY TOPOLOGY, the strongest
form of the pre-registered compression; the antidote works for
ECCENTRIC hubs only (central hubs gain no count -- wrap never helps a
path <= half-width -- and pay the fold: mean physical wire 1.67-2.0x
worse on grids this small, exceeding clause 2's 'slight', booked);
the 2x4 production grid stays 1.00/1.00 -- zero disturbance to the
frozen claims. (2) THE FLIP, booked per discipline: the 48-die
ordering spread WIDENS under ring, 6.55x -> 12.26x (a 1D cycle's far
end is longer than a 2D mesh's; 'the ring removes the far end' is
true against a chain) while torus NARROWS it to 3.57x; the ordering
roles swap (ring's native sequential rows reads exactly 1.000, snake
degrades to 1.745). Day 4, the review's three placements + the
caliber confirmation, all landed: (i) the company seating sentence is
now the three honest sentences (ring exactly optimal for in-order
flow BUT makes ordering more critical; torus is what relaxes ordering
criticality; mesh between) -- SUMMARY zh/en NEW section 2.9; (ii) the
weave knob's lever on the ordering-penalty axis = 3.4x (12.26 vs
3.57), filed beside the scheme and bandwidth knobs as a third hand on
that boundary -- footnote hooks added at the 12-19x pipeline
paragraphs in both languages; (iii) the optimal ordering itself swaps
with the weave -- a direct instance of the paradigm-dependence
clause; S2's baseline library registers orderings per weave, S6's
mis-paradigm arm gains a ready-made construction. CALIBER
CONFIRMATION (the review's B-table ask): the count and phys spread
columns coincide STRUCTURALLY, not by copying -- BOTH 6x8 axes fold
(fold 2,2; the review's guessed single-axis cause was wrong in
detail), so physical length is a uniform scalar of the count for
every scheme at that level and cancels in worst/best ratios; asserted
elementwise in the script, flows verified to cross both folded axes;
the 2x4 macro grid's non-uniform fold (1,2) is the contrast case.
Conclusion-level ledger: every frozen claim untouched (production
on-die insensitivity, the 12-19x band -- mesh-caliber, identity
unchanged, soft lever 1.4-2x); all changes in the design-implication
layer, the expected shape of A7's stocking-for-search.

O19 BATCH (2026-09-09, C63; hard deadline 9/16 -- the writing month
does not yield). TWO QUALITATIVE RULINGS, filed before execution:
(1) THE WEAVE NEVER ENTERS THE SEARCH'S VARIABLE SET. Fabrics are the
hardware side -- they move boundary lines and serve design-
exploration users; the search's variables are soft placement only.
At most the search RE-RUNS under different weave conditions -- that
is condition enumeration (semantically S6's adjudication territory),
not a search dimension. This sentence is the principle the search
milestone's space definition cites. (2) ADDING REAL WEAVES =
INSTRUMENT-SIDE completion. Each real weave buys the same three
things: another redemption of the paradigm-configurable claim, a new
line on the phase diagram, one more control arm for the die-level
ordering/seating readouts. It does NOT testify for the paper's claims
(no evidence chain stands on a new weave); it is
what-the-platform-covers material.
ITEM 1 (duplex) -- RE-VERDICT AFTER THE MANDATED INVENTORY:
CLOSED-AS-ALREADY-DONE, moving-pins list EMPTY. The direction-split
account landed at O22/O23 and every published multiplier was
re-pinned on it then; the resolved-items table said so all along.
Residue fixed this round: the stale O19 queue sentence (retired above
in place), the stale Mesh docstring ("segments are undirected"), and
one confirmation pin (the DUPLEX contract per scheme + the split
actually keying occupancy resources). Zero account movement; the
premise correction is itself the item's result.
ITEM 2 (switch weave) PRE-REGISTRATION (filed before code,
2026-09-09): CONTRACT -- class `Switch` (the repo naming rule stands:
"crossbar" is always the ReRAM array); real-world identity =
package-level NVSwitch-class switches / fully custom die-to-die
crossbars; semantics = NON-BLOCKING UP TO PORT BANDWIDTH, i.e. the
weave that is placement-irrelevant BY CONSTRUCTION. Port bandwidth is
the ONLY first-order parameter (the level's existing link bandwidth
field); NO internal hop concept -- hops(a, b) is a declared
end-to-end constant (param, default 1.0; 0 for a = b), and
energy_hops/router_hops inherit it (C59/C60 identities hold
trivially); a flow a->b occupies a's port TX and b's port RX (the
duplex split keys them), so occupancy = per-port volumes; THE N^2
WIRING COST IS DECLARED IN THE IDENTITY DOCSTRING AND ENTERS NO
ACCOUNT. SHORT TESTS: placement-irrelevance IS the topology test
(any seating permutation -> identical occupancy readouts); the
star-degeneration identity (for hub-rooted flows, switch occupancy
== star occupancy: star is the idealized unlimited-bandwidth switch,
its own docstring says so). EXPECTATIONS, pre-written: every
die-level ordering/seating readout collapses to EXACTLY 1.00 spread
under switch (constructive, both calibers -- count and physical);
on the phase diagram it is a horizontal ceiling line; the busiest
"wire" is the busiest PORT. The company sentence this buys: the
"switch vs mesh" decision becomes computable -- the price of buying
off placement sensitivity outright is N^2 wiring, and both sides of
that trade now have numbers. Readout + figure: the die-level three
orderings x {mesh, ring, torus, switch} comparison (switch a flat
line), repo PNG with a committed generator.
ITEM 2 DONE 2026-09-09 (C63-b). Both pre-registered expectations
landed EXACTLY: the switch's ordering spread is 1.00 in both calibers
(the three control arms read their pinned 6.55x / 12.26x / 3.57x
beside it) and the busiest port carries identical crossings under
every ordering -- placement-irrelevance measured, not asserted.
Figure: analysis/switch_ordering.png (committed generator). ONE
PRE-REGISTRATION REFINEMENT, caught at test-writing time, before any
published sentence: the star-degeneration identity holds for
NODE-TO-NODE flows (die hand-offs, the weave's habitat -- load
multisets and bottleneck equal, pinned); for HUB-ROOTED flows the
switch honestly FUNNELS through its single hub port (8 x 100 -> 800
vs star's private 100 -- star is the N-port idealization, its own
docstring says so); both faces pinned (group 48). The N^2 wiring
price is declared in the class identity and enters no account.
ITEM 3 (CMesh) PRE-REGISTRATION (filed before code, 2026-09-09):
CONTRACT -- class `CMesh(Mesh)`, the concentrated mesh (commercial
NoCs' common form: k nodes share one router). Param `concentration:
[cx, cy]` = the router tile shape (k = cx x cy); routers sit at tile
centers; a flow goes node -> its router (a PRIVATE access link,
emitted only when the node is not co-located with its router center)
-> dimension-order route over the ROUTER grid (physical distance
between adjacent routers = the tile pitch, slot units) -> router ->
node. [1, 1] DEGENERATES TO MESH EXACTLY -- the short test: hops
equal for every pair including HUB, occupancy bottleneck and shared-
segment load multiset equal. EXPECTATIONS, pre-written, direction
unique: the CONCENTRATION FACTOR (busiest shared-segment load on the
uniform hub-rooted flows, the pinned busiest-wire table's machinery)
rises MONOTONICALLY with k -- more nodes funnel per router; the
boundary band sits above mesh's for every k > 1. Readout + figure:
busiest-wire load and mean hops vs k in {1, 2, 4, 8} on the 2x4
macro grid (8 slots: k=8 is the single-router funnel extreme), repo
PNG with a committed generator.
ITEM 3 DONE 2026-09-09 (C63-c). ONE PRE-REGISTRATION AMENDMENT,
filed at implementation time BEFORE any readout ran: our occupancy is
a WIRE account, but CMesh's concentration cost physically lives at
the ROUTER LOCAL PORT (k tile nodes share one router's injection/
ejection bandwidth) -- a wire-only model would let the funnel vanish
at high k (all-private access links) and the monotonicity expectation
would have flipped for the wrong reason. Amended contract: a shared
per-tile port resource carries the funnel (emitted for k > 1; the
HUB is router-resident, mesh-consistent, and attaches to no port).
RESULTS, all expectations landed: k=1 degenerates to mesh EXACTLY
(hops equal on every pair incl. HUB, busiest 4.0 = the pinned grid
funnel, zero extra resources); port load = k EXACTLY (2/4/8,
monotone by construction); the overall bottleneck reads 4.0 / 4.0 /
4.0 / 8.0 over k = 1/2/4/8 -- ON THIS GRID CONCENTRATION IS FREE UP
TO k* = 4 (the router funnel stays under the grid funnel; tie at 4)
AND BINDING BEYOND (k = 8, the single-router extreme, doubles the
bottleneck and the binding resource is the port). The design
sentence this buys: "how many nodes per router is free" is now a
computed crossover, not a rule of thumb. Figure:
analysis/cmesh_concentration.png (committed generator); pins group
48 (+3).
OPTIONAL ITEM (express links) PRE-REGISTRATION (trigger met --
items 2-3 closed fast; filed before code, 2026-09-09). THE TWO FREE
PARAMETERS, LOCKED: (1) the FAMILY is uniform and station-free --
every row and column line carries an express link from every position
c to c + s (no "station alignment" hidden degree of freedom; the
honestly higher wire price is declared); (2) SKIP s is the only
parameter; s >= the axis extent means zero links and EXACT mesh
degeneration (short test). CALIBERS: an express link is s slot
pitches of wire, so PHYSICAL hops == the Manhattan distance, equal to
mesh pair-by-pair (asserted -- express saves router crossings and
local-segment contention, never wire length); router_hops counts one
per express traversal -- the THIRD appearance of the C60 count/length
split, and the packet guard's folded-scheme list gains "express".
WIRE PRICE (the curve's x axis, closed form, declared): mesh line
wire normalised to 1; express adds (addable links x s) per covered
line; torus = x2 on folded axes; switch = the N^2 class.
EXPECTATIONS, two-handed: the corner/centre lever (the pinned 5/3 on
the 3x3) compresses toward 1 but NOT to 1 (a partial antidote);
count means strictly drop wherever an axis distance >= s; physical
means identical to mesh. PRE-WRITTEN RISK: on the 3x3 the express
wire price lands exactly at torus's 2.0x -- if torus dominates
express at equal price there (1.00 vs partial), "on small grids the
fold dominates the shortcut" IS the finding, booked as such; the
shortcut's habitat is expected at larger extents (the 6x8 die host,
s in {2, 3, 4}). POSITIONING: the price curve of hub-insensitivity
-- scatter of (wire price, corner/centre lever) over {mesh,
express(s), torus, switch} on both hosts, extending A7's verdict
from two antidotes to a spectrum.
OPTIONAL ITEM DONE 2026-09-09 (C63-d). Readouts, both hands booked
(figure: analysis/express_price_curve.png). 3x3 host: the pre-written
risk landed as an EXACT TIE, not dominance -- express s=2 and torus
both zero the lever (1.000, busiest 3/3) at the same 2.0x wire price:
on the small host the shortcut and the fold are the same medicine at
the same price. 6x8 host, THE UNREGISTERED FINDING: express s=2 makes
the hub LEVER WORSE (2.000 vs mesh's 1.667) while improving BOTH
absolutes (centre 24 -> 16, corner 40 -> 32) -- a sensitivity RATIO
can degrade under relief that helps the centre more; the lever is
non-monotone in s (2.0 / 1.5 / 1.0 over s = 2/3/4); and TORUS
DOMINATES every express variant on this host (lever 1.000 at 2.0x
wire, at or below every express price). The pre-registered
"compresses toward 1 but not to 1" was wrong in BOTH directions
(exact 1.000 on the 3x3; worse on the 6x8) -- booked. The honest
spectrum sentence, replacing the planned one: express is NOT a
reliable sensitivity antidote -- it is an ABSOLUTE-decompression
valve (the only weave whose centre-hub busiest drops below mesh:
16 < 24), while the FOLD is the dominant sensitivity antidote at 2x
wire and the switch pays the N^2 class for the same lever plus
node-to-node flatness. Group 48 +3 pins (contract/degeneration, the
packet-guard extension, the curve findings).
QUEUED-CONDITIONAL ITEM A (FlooNoC-class hierarchical wide links)
PRE-REGISTRATION (trigger met; filed before code, 2026-09-09).
ADDENDUM CAUGHT AT CONTRACT TIME: CMesh's backbone step crosses one
router over a tile pitch of wire -- count != length -- but item 3
left router_hops un-overridden (returning physical) and the packet
guard did not list cmesh; FIXED with this item (CMesh.router_hops =
router-grid crossings + the guard gains cmesh and hier_wide).
CONTRACT, locked: class `hier_wide` = CMesh topology + a WIDE
MULTI-CHANNEL BACKBONE -- FlooNoC's identity is multiple PHYSICAL
channels (not virtual): each backbone segment carries `channels: W`
parallel physical channels; a flow rides lane = (source node % W,
HUB-sourced = lane 0) -- deterministic, declared. Local tier = the
cmesh attach (private access wire + the shared gateway port, the
k-funnel carrier). DEGENERATION CHAIN, both pinned: W = 1 == cmesh
exactly; W = 1 AND tile [1,1] == mesh exactly. WIRE PRICE declared:
cmesh's + backbone x W. ANCHOR CALIBER declared: the FlooNoC
80.6 GB/s (post-layout) is PER PHYSICAL CHANNEL; W channels = W x
anchor backbone capacity. Declared-example instance: tile [2,2],
W in {1, 2, 4} -- no product basis, same provenance class as every
declared geometry.
EXPECTATIONS, two-handed: (a) backbone channel relief -- the busiest
backbone channel's load splits ~evenly by the lane rule (exact for
uniform sources); (b) THE FIDELITY QUESTION the item exists for: at
the FlooNoC anchor bandwidth on the ffn1 macro flows, the
native-structure serialization vs the mesh-poured baseline -- hand
one: the wide backbone relieves (native <= poured); hand two: the
LOCAL tier's gateway funnel (k = 4) binds instead and native READS
WORSE -- in which case the fidelity upgrade's value is precisely
revealing that a wide backbone cannot rescue a concentrated local
tier, and the "anchor number poured into a mesh" reading was
optimistic on structure. Either hand upgrades the digital control
tier from a poured number to a placeable structure.
ITEM A DONE 2026-09-09 (C63-e). THE THIRD OUTCOME, neither
pre-written hand (figure: analysis/hier_wide_fidelity.png): every
hier_wide variant TIES the poured-mesh reading numerically (4.000x
vs the star floor, ffn1 flows at the 80.6 GB/s-per-channel anchor)
-- but the BINDING RESOURCE MIGRATES: mesh binds on a grid segment,
hier_wide binds on the LOCAL GATEWAY PORT (the k = 4 funnel) at
every W, and widening the backbone W = 1 -> 4 changes NOTHING (its
width cannot be consumed on this host). The tie itself is this
host's funnel coincidence (grid 4 == gateway 4). The fidelity
sentence, which IS the item's deliverable: the poured-mesh reading
of the FlooNoC anchor was RIGHT NUMERICALLY AND WRONG STRUCTURALLY
-- the digital control tier now names where its constraint sits (the
concentrated local tier, not the wide backbone), which no poured
number could say. Degeneration chain pinned (W=1 == cmesh modulo
prefix; +[1,1] == mesh); lane rule pinned (src %% W, HUB lane 0);
the CMESH ADDENDUM landed (router_hops = router-grid crossings; the
packet guard lists cmesh and hier_wide -- five count/length-split
schemes now). Group 48 +3 pins.
QUEUED-CONDITIONAL ITEM B (routing-algorithm params)
PRE-REGISTRATION (filed before code, 2026-09-09; the occupancy-side
completeness debt -- the XY-vs-YX reply asymmetry has been on record
in the base-class docstring since O22). CONTRACT: two Mesh params,
both DEFAULT-NEUTRAL (the defaults reproduce today's paths verbatim
-- zero pins move): (1) `reply: "retrace"` (default; node->hub
retraces the hub->node route, the pre-O19 behavior) | `"yx"` (replies
ride the OPPOSITE dimension order, the common real-NoC form -- up
load lands on segments the down route never uses); (2) `routing`
gains `"o1turn"` -- the balanced dimension-order model, DECLARED as
the parity rule (flows from even-indexed sources route XY, odd YX;
deterministic; the 50/50-split oracle would need fractional paths the
interface does not carry -- the parity form is the honest static
stand-in and is labeled so). EXPECTATIONS, two-handed: under the
full-duplex account the down side is untouched by the reply choice;
YX replies move the UP load onto disjoint segments, so (a) when the
up side binds (psum-weighted up, x2), the busiest wire DROPS; (b)
when the down side binds (up at 0.5), the overall number does NOT
move -- the debt only pays where partial sums dominate. Readout on
both weights, both hosts (2x4, 3x3), o1turn rows alongside; figure.
ITEM B DONE 2026-09-09 (C63-f) -- and the debt closed more
decisively than planned, by THREE stacked findings (figure:
analysis/routing_params.png): (1) THE PATH IDENTITY, caught by the
pin's own first draft: for hub flows, retrace-of-XY IS the YX path
(a single-bend dimension-order route walked backwards runs y-then-x)
-- the reply knob is PATH-IDENTICAL on its entire hub-flow domain,
pinned as equality. (2) THE SINK-FUNNEL INVARIANT: even where paths
could differ, a sink-convergent pattern's busiest wire is fixed by
conservation at the sink's incident segments -- every reply variant
ties on every tested pattern and weight. The on-record XY/YX reply
asymmetry therefore CANNOT move any busiest-wire number in this
account; where routing algorithms could matter is the queueing tier,
explicitly outside the O26 bound. (3) The o1turn PARITY stand-in
(the declared model; the fractional 50/50 oracle does not fit the
one-path-per-flow interface) NEVER beats plain XY on any tested
pattern and often doubles the busiest wire (all-pairs 12 vs 8 and
9 vs 6; mirror 4 vs 2 and 2 vs 1) -- it ships as a condition-
enumeration arm carrying this warning, never as an optimization.
Both knobs are default-byte-neutral (the full-suite gate ran green
before any readout; a Torus._route signature mismatch surfaced by
the gate was fixed in the same edit). The pre-written hand "YX
replies relieve where the up side binds" is REFUTED and the
refutation pinned. Group 48 +2 pins.
BATCH CLOSED 2026-09-09: items 1-3, the optional, and both
queued-conditional items all executed inside the 9/16 deadline --
NOTHING remains queued on O19. The registry stands at ten schemes
(star, mesh, h_tree, bus, torus, ring, switch, cmesh, hier_wide,
express + the routing/reply knobs), every one carrying topology and
degeneration short tests, five of them under the count/length packet
guard. OPTIONAL express links only if 2-3 close fast (pre-register
hop distance + placement rows first; positioning: the price curve of
hub-insensitivity, extending A7's torus verdict from two antidotes to
a spectrum). QUEUED-CONDITIONAL (not deferred; trigger = items 2-3 +
optional done AND before 9/16): FlooNoC-class hierarchical wide links
(upgrades the digital control tier from "an external anchor number
poured into a mesh" to a placeable, sweepable real structure) and
routing-algorithm params (YX replies / adaptive -- occupancy-side
completeness debt; the XY/YX asymmetry is on record). Discipline:
post-v6 files, pure addition, per-weave topology + degeneration
short tests, expectations pre-written, flips booked; frozen_v6 and
both tex untouched; SUMMARY zh/en one line per item at closeout.

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
| ~~S5~~ RETIRED (C64-a, 2026-09-10) | was: solver reconciliation with the collaborator (needed O6) | the collaborator has withdrawn; S5 is retired, O6 retires with it, and the 47% figure is PERMANENTLY UNPUBLISHABLE (the 11% flat figure remains usable per the standing citation rule) | -- |
| S6 | **Proxy-optimization study**: same SA, space, budget and seeds; only the evaluator changes -- E0 full `score` / E1 volume x distance / E2 prefill-only / E3 the wrong paradigm tier; every solution re-scored by E0 under every condition | `search_ondie.py` + a harness | the 4 x N cross matrix: where a simplified evaluator returns the wrong layout, plus one "safe cell" control row (slow device x wide link: every evaluator expected to tie) |

SEARCH V1 PRE-REGISTRATION (C64-a, 2026-09-10; the semantic
authority is the repo-resident spec analysis/SEARCH_SPEC.en.md --
the revised SYNC_search_v1 with every accepted amendment integrated
in place and marked [AMENDED]; below are those amendments plus the
run disciplines, filed BEFORE the first line of search code):
(1) TILER FEASIBILITY EVERYWHERE (the O10 lesson, the O17c 4.3x
flip-point miss its precedent): |D_k|'s lower bound AND its
fill-exact value come from plan_spatial, never ceil(vol/cap);
legal(Pi) folds tiler feasibility in beside Placement.verify; the
ORACLE TABLE's group-size axis is the TILER-FEASIBLE SIZE SET
(possibly sparse), not the integers above a bound -- DP states
unchanged, the enumeration domain follows this definition.
(2) DP EDGE-WEIGHT DIRECTION STATEMENT: the interval DP prices
hand-off fees at ADJACENT-SEATING REFERENCE HOPS (alpha refines
under fixed gamma); this makes the DP systematically OPTIMISTIC on
hand-off fees, but hand-offs are the measured cheapest edge class
(the 0.10 GB/s-threshold family), so the bias's effect on cut-point
choice is EXPECTED NEGLIGIBLE -- its actual magnitude falls out of
day 8's joint-vs-decomposed small instance for free and is filed
back against this statement.
(3) CONSTRAINT MODE = REJECTION (no penalty terms -- J semantics
stay pure, no free coefficient), WITH THE ANTI-STRANDING GUARDRAIL:
every multi-start seed set MUST contain at least one FEASIBLE named-
baseline solution (ladder table v0 is the candidate pool); if ALL
baselines are infeasible in a cell, "the constraint is unsatisfiable
there" is a RESULT on file -- never rescued by a penalty. FT
bookkeeping: segment-borne member terms ride their segment, global
terms once (the A4 serial semantics extended).
(4) THE DELTA COLUMN RIDES EVERY RESULTS TABLE FROM S3 ON: Delta =
T_pess / T_opt (T_pess produced alongside T_opt from S1 day 2);
where candidates' Deltas differ significantly the conclusion states
whether the ranking survives the protocol-tier worst assumptions --
the section-5 bracket policy's execution face, not deferred to
writing.
(5) RANDOMNESS: seed sets pre-registered per experiment; every
reading reports the multi-start DISTRIBUTION (median + range),
never a single best.
(6) COLLABORATOR WITHDRAWAL, three synced deletions: no interface
hand-off at S1 day 3; S2's `clustered` baseline is SELF-IMPLEMENTED
from the literature definition (Gemini's rectangular clustering);
S5 retired, O6 retired, the 47% permanently unpublishable (rows
updated above).

S1 DAY 1 DONE 2026-09-10: scripts/search_space.py -- the Pi triple
(gamma cut vector + segment/stage views; alpha seat map with
hub/attach; beta structural v1), legal() = the Placement.verify
formalisation WITH the tiler fold-in (rejection message cites O10),
feasible_die_counts() = the oracle's group-size axis (amendment 1's
entity), JSON round-trip, and the A4 544-seat + 16x2-seam payload
parsing to the LEGAL standard Pi (32 blocks, 16 stages). Gates all
green (group 49, 6 pins): the O10-type counterexample REJECTED
(2.7B ffn1 at capacity's 4 -> refused, tiler demands 5), gamma/
overlap/hub/attach/beta pathologies each refused, the feasible set
measured sparse (ffn1: 4 absent, 5 present). S1 DAY 2 DONE 2026-09-10: scripts/search_eval.py -- score(Pi, W,
mu, caliber, d2d_gbps) -> Score(t_opt, t_pess, e, delta, per-phase
decomposition), fully closed-form on frozen accounts (zero mapper).
ONE INTERFACE AMENDMENT recorded: the die-set granularity is DECLARED
BY THE WORKLOAD (the condition layer's frozen tiling owns it) --
legal(pi, fabric, inventory) refactored accordingly, with two
constructors (per-op block_chain for the 2.7B class; unit-granularity
C13 two-dies-per-layer for the 355M class -- co-residency inside a
unit is part of T, not of the search). THE TRIPLE IDENTITY ANCHORS
ALL GREEN (group 49): (1) score(A4-Pi) == a4_full_model's
whole-machine column at every bandwidth anchor AND its energy, to
1e-9, decomposition fields included; (2) the 355M backend reproduces
the stored b1 ordering rows -- avg hops / busiest / surplus / wire-ms
for all three orderings, to 1e-9 (via die_to_die_activation +
link_occupancy, the UCFG unit-chain convention verbatim); (3) the
per-op rows ARE the frozen account (verbatim equality, both phases),
and layer serial/energy equal A4's stored values. Also pinned: the
pipe caliber's structure (16 stages, interval = max stage, single is
gamma-blind), decode + weighted-mu assembly (exact linearity), and
Delta == 1.0 on packet-free weaves by construction (the toll
implemented generically for packet-declared links). S1 DAY 3 DONE 2026-09-10 -- S1 CLOSED (C64-b). The reviewer's three
follow-ups landed FIRST: (1) the spec document itself is amended for
the day-2 inventory change (code and spec move together; the freeze
discipline is now written into the spec's execution note: post-freeze
interface changes go ONLY through formal spec amendment + FIXLIST,
never casual edits); (2) Delta is recorded as produced from day 2
onward, and Delta = 1.0 on packet-free weaves is written into the
spec as a DEFAULT ASSUMPTION BY CONSTRUCTION, not a verified
conclusion; (3) the weave question answered: caliber does NOT carry
it -- the weave is a condition and enters via the workload
constructor's new `die_weave=(topology, params)` parameter (both
backends), added BEFORE the freeze as S6's E3 entry point; score()
stays weave-free. Day-3 mechanism: ScoreSession -- the incremental
hook (a seat move recomputes only the moved set's in-boundary and its
successor's; the single-boundary flow builder replicates the
block_die_flows convention verbatim) with the INCREMENTAL == FULL
identity pinned over random swap sequences to 1e-12; `device_scale`
(O17 semantics: divides the COMPUTE term alone, fixed terms stay,
energy never moves -- pinned); the die_weave knob pinned on the 355M
ring case (the C60 ordering-role swap survives in the physical
caliber: sequential 2.0 / snake 3.49 = the folded x2 of the pinned
counts). THE S1 SIGNATURE IS FROZEN: score(pi, W, mu, caliber,
d2d_gbps, device_scale) + Workload{2p7B,355M}(fabric, [d2d_bw_wc],
die_weave) + ScoreSession.update(new_seats) + legal(pi, fabric,
inventory). Group 49 totals 14 tests.
POST-CLOSEOUT FOLLOW-UPS (review, landed 2026-09-11 via the freeze
discipline -- spec amendment + this record, no signature change):
(1) SCHEDULE_SLACK'S SEAT clarified in the spec: an O26 platform
input riding the workload's FABRIC (the weave's entry route),
consumed where its semantics apply -- the occupancy-bound paths
(link_occupancy reads it; the 355M backend inherits it); the 2.7B
serial hand-off term is a direct transfer time, not an occupancy
bound, so slack rightly does not multiply it; S6 arms share the
condition layer and none tunes it. Not dropped; seated -- and no new
score() argument was ever needed. (2) THE RING-CONDITION INCREMENTAL
PIN added: incremental == full re-pinned under die_weave=("ring",{})
-- day 3's only bug was a wrap edge case and the ring weave is built
entirely on wrap; SA hammers the incremental path and S6 runs
non-default weaves, so the two now meet in one pinned run (1e-12,
caliber unchanged). THE IDENTITY-PIN SET (triple anchors +
incremental==full, default AND ring) IS PERMANENT in group 49 --
it does not retire with S1. S2 DAY 4 DONE 2026-09-11: scripts/search_baselines.py -- the seven
named generators under ONE signature (generate(name, W, seed) -> Pi;
every output passes legal(); gamma ships as singleton cuts -- the
chain partition belongs to the S4 DP, declared). Sources per the
spec's literature coordinates (SIAM's least-Manhattan collected
verbatim; NMAP's constructive + pairwise-swap refinement running on
NMAP's OWN comm-x-distance cost -- arm isolation: that cost never
leaks into E0; clustered self-implemented as compact per-stage
regions, the Gemini intent; heaviest_first per Graham/LPT). Pins
(group 49 +2): all seven legal on BOTH workload classes (2.7B
per-op AND 355M per-unit), seeded determinism, random varies by
seed, the registry CLOSED (an eighth name is refused), and the
DEGENERATION pin -- `sequential` reproduces the A4 payload map
exactly (the mapper's default-seat by-product). S2 DAY 5 ITEM 0 DONE 2026-09-11 -- THE BASELINE FAITHFULNESS CHECK
(the review's pre-ladder gate; fixes under the freeze discipline,
recorded as implementation repairs BEFORE any ladder number):
A1 nmap convergence: the 2-pass cap could stop short -- replaced by
run-to-convergence (high safety cap + loud failure); the permanent
pin re-runs one full swap pass after generate() and demands zero
improvements (both workload classes). A2 least_manhattan: stepwise
greedy REPLAYED independently, every pick aligned (permanent pin).
A3 clustered: THE CHECK BIT -- 4 of 32 stages DISCONNECTED under the
original blob growth (one shattered to a single slot), and the first
repair (component-aware growth) then failed loudly at stage 31
because diamond growth fragments the tail; the implementation was
REPLACED by literal RECTANGLE TILING (the Gemini definition at its
word: 3-wide x 6-tall rectangles, 8 columns x 4 rows = 32 for the
2.7B class [CORRECTED by check D's hand recomputation -- the record
first said 6x3/4x8, orientation reversed; the code and the hand
arithmetic agree on 3x6, a waste-1 tie taken first-found]; snake
order over rectangles; within-rectangle row-major; connectivity,
perfect tiling and determinism BY CONSTRUCTION; the 355M class
degenerates to 1x1 rectangles = the snake walk, noted). Permanent connectivity pin on
both classes. A4 heaviest_first: strict descending-weight order +
per-step least-stretch picks replayed independently (permanent pin;
on the uniform-weight unit chain the order degenerates to chain
order, noted in the traces). B evaluator-parameter blindness pinned
(bandwidth exercised at two values on the 355M constructor; caliber/
mu/device_scale structurally unseen; geometry is the allowed
dependency). C REVERSE FAITHFULNESS (one-off, filed): on the 2.7B
chain the literature congestion pathology does NOT appear --
clustered reads BETTER on the busiest wire (10.49M vs sequential/
snake's 26.21M); per the rule the implementation was inspected FIRST:
the mechanism is structurally explained (sequential/snake lay the
chain as one corridor, so the busiest wire carries a whole intra-
layer ffn1->ffn2 multicast, 5.24M x 5; rectangle regions hand the
same multicast across a WIDE border, 5.24M x 2) and the pathology's
premise -- competing many-to-many cross-traffic -- is absent from a
pure pipeline chain: the non-appearance is a property of the traffic
pattern, not an implementation artifact. D PREP delivered:
analysis/baseline_traces.md (per-step candidates/choices for the
hand replay on the 48-unit host; the rectangle-tiling parameters
fully recomputable; source recomputability notes -- SIAM/NMAP/
Gemini: no directly recomputable original example, rule replay
covers; noted honestly). CHECK D, THE HAND-COMPUTABLE PORTION EXECUTED (agent, 2026-09-11;
independent derivations from the rule texts + grid geometry, THEN
compared against code): (1) the clustered rectangle parameters fully
recomputed by hand -- divisor enumeration lands on the waste-1 pair,
stage-0's 17 slots derived slot-by-slot (drop idx 122) and EQUAL to
the code's; the derivation CAUGHT the record's orientation reversal
(fixed above); stage 1 starting at slot 3 confirms the 8x4 rectangle
grid. (2) heaviest_first's first two placements hand-derived with
the tie-break arithmetic (centre anchor (2.5, 3.5) -> four distance-1
ties -> index break -> slots 20 then 14) -- equal. (3) nmap's
comm-descending head hand-reasoned (uniform chain weights: middles
2w before endpoints 1w; unit0/unit47 last) -- equal. (4) snake's
first ten slots and sequential's identity order hand-derived --
equal. The genuinely NON-recomputable residue stays as noted in
baseline_traces.md (SIAM/NMAP/Gemini publish no directly
recomputable example; rule replay covers). THE REMAINING HUMAN
PORTION of check D is reduced to reading the cited rule statements
against the code/traces; until the user accepts D, the ladder may
run but every number is PROVISIONAL, C64-c does NOT close, and the
seed pool is NOT delivered to S3. CLOSEOUT ITEM 1 DONE 2026-09-11 -- CITATION EXCERPTS + THE NMAP
REVERT THEY FORCED: the two verbatim source excerpts are pasted into
baseline_traces.md with correspondence notes (Gemini Sec. VII: "a
layer is assigned to consecutive and rectangle-like core group" =
the rectangle-tiling definition, and the SAME sentence supplies the
congestion premise closeout item 2 must measure; NMAP Sec. 5:
initialize() + mappingwithsinglepath() pseudocode). The pseudocode
settles the pre-registered branch AGAINST the standing code, twice:
(a) TERMINATION -- the original refinement is a FIXED single O(U^2)
pairwise sweep with per-row best-commit, NOT run-to-convergence; the
A1 repair above had installed run-to-convergence, which is hereby
REVERTED per the original (this supersedes the A1 wording above);
(b) SELECTION -- initialize() picks the next core DYNAMICALLY (max
communication with the already-mapped set) and seats it minimising
comm x distance to ALL mapped cores, not a static descending order.
Both restored in `_gen_nmap_greedy` (now split `_nmap_construct` +
`_nmap_refine_sweep`; the convergence AssertionError cap is gone --
the sweep IS the termination). Declared adaptations stay declared:
chain-comm x centroid-Manhattan caliber, equal-size die-set swaps.
The A1 pin is REWRITTEN per the directive: an independent replay of
the original's exact sweep structure (coded in the test from the
pseudocode, per-row best-commit) starting from `_nmap_construct`'s
output must land on generate()'s seating seat-for-seat, both
workload classes (test_faith_A1_nmap_original_single_sweep_replay).
SEARCH_SPEC section 9's nmap row amended ([AMENDED 7]); the
clustered-row section 9 sync remains closeout item 3. Suite 393
green after the revert. USER PASSED THE EXCERPTS 2026-09-11 = CHECK D ACCEPTED (per the
directive: the eyeball closes it); the faithfulness gate A-D is
fully green and ladder numbers may become OFFICIAL. CLOSEOUT ITEM 2 DONE -- C REINFORCEMENT, MEASURED (upgrade from
reasoning-closed): scripts/check_c_crosstraffic.py supplies the
Gemini premise synthetically on the 2.7B host (every stage fans out
an equal V to stages +2/+4/+8, 82 competing stage pairs; flows by
the frozen R-split boundary convention verbatim, routing by
link_occupancy unchanged; uniform-chain control rides, no hand).
PRE-REGISTERED both hands, then read: E+ LANDS -- with the premise
supplied clustered's busiest wire is the WORST OF ALL SEVEN
seatings (30.00M words vs snake 28.00M, sequential 22.24M, random
18.29M) while the uniform-chain control keeps clustered BEST
(6.18M vs snake 15.06M): the pathology's presence tracks its
premise exactly, both directions measured. MECHANISM (from the
bottleneck witness): clustered's top-5 wires are seg(11,y)-(12,y),
y=0..4 -- the mid-grid seam between rectangle columns, saturated
UNIFORMLY at 30.00M each: XY routing keeps horizontal runs inside
the 6-row rectangle band, so ALL eastward inter-rectangle demand
of a band funnels into its 6 seam wires -- literally "clustering
cores for each layer together cannot disperse this transfer
demand". Corollary reading: under the premise the ordering INVERTS
to more-dispersed-is-better (random/heaviest_first best), which is
Gemini's own remedy direction. Figure:
analysis/check_c_crosstraffic.png. CHECK C IS NOW MEASURED-CLOSED
BOTH WAYS: premise absent -> no pathology (pure chain, clustered
protected by wide borders); premise supplied -> pathology appears
on cue. CLOSEOUT ITEM 3 DONE -- SPEC SECTION 9 SYNC: clustered row
rewritten to the literal rectangle tiling ([AMENDED 8], A3
fragmentation story + 355M degeneration clause + traces pointer);
nmap row was [AMENDED 7] under item 1. CLOSEOUT ITEM 4 DONE -- the
355M degeneration PIN: generate("clustered") == generate("snake")
seat for seat on the 1-die-per-unit class
(test_clustered_355m_degenerates_to_snake; suite 394 green). CLOSEOUT ITEM 5 -- LADDER TABLE V0, EXPECTATIONS PRE-REGISTERED
BEFORE THE RUN (two-handed; flips are findings): the declared
table = 7 baselines x {2.7B class: T_single at three cells -- safe
(GRS 12.5 GB/s, scale 1), weak-D2D (0.4 GB/s, from the standing
anchor set), fast-device (12.5, device_scale 10 per the O17
test) -- plus T_pipe(safe), E, d2d_words; 355M class: the anchor-2
caliber avg_hops / busiest_x / wire_ms / surplus at the stored
example bw}; mu = prefill one-hot, singleton cuts as shipped.
E1 random is the worst T of the seven at the safe cell (every
named <= random). E2 nmap_greedy lands in the best two named on
safe-cell T (the greedy-tier claim). E3 the E column's relative
spread (max-min)/min <= 2% (A4's geometry-dominated prior, 1.83%
whole-vs-block). E4 the T spread (max/min) WIDENS from the safe
cell to the weak-D2D cell AND to the fast-device cell (the
phase-diagram play; this is why the search runs only in active
cells). E5 355M: clustered == snake row identity (pinned); random
worst on wire_ms. RESULTS (scripts/ladder_v0.py; table + figure + seed pool
analysis/ladder_v0.{json,png}; readings OFFICIAL, D accepted):
2.7B safe-cell T_single ladder: nmap_greedy 1034.792 ms =
least_manhattan < clustered 1034.793 < snake 1034.796 <
sequential 1034.808 < heaviest_first 1034.831 < random 1034.865;
E column: clustered 2.3379 J best, random 2.5251 J worst; 355M:
snake/least_manhattan/clustered/heaviest_first 1.00 avg hops /
2.97 wire-ms, nmap 1.04, sequential 1.74 (the standing b1 row),
random 4.45 hops / 11.87 wire-ms. E1 LANDS (random worst, every
named better). E2 LANDS (nmap_greedy tops the safe-cell T
ladder). E5 LANDS (clustered == snake row bit-identical; random
worst by 4.0x wire time). E3 FLIPS -- booked as FINDING F-L1: the
energy spread across the seven seatings is 8.008%, four times the
2% prior; at the safe cell ENERGY, not latency, is the
placement-sensitive column of the 2.7B caliber (T spread 0.007%).
E4 FLIPS -- booked as FINDING F-L2, with the mechanism VERIFIED
in the frozen caliber rather than patched: the per-boundary flow
SET (words) is placement-INVARIANT by construction (every
producer die ships its piece to every consumer die regardless of
where they sit), so the d2d serial term words/bw -- the term the
weak-D2D cell amplifies -- is seating-invariant, and T_pipe
(32.3499 ms, max stage) is bit-identical across all seven;
placement enters T only through the ~us propagation term
(73 us total spread) and enters ENERGY through the distance
surplus. CONSEQUENCE FOR S3 (filed now, before any search runs):
on the 2.7B class the SEATING level is effectively an
energy-column optimization under a near-flat T (lexicographic
T-then-E semantics stay as declared), while the TIME-side
placement play lives in the 355M wire-time caliber (4.0x spread)
and in the cuts/segment level -- the active-cell discipline for
S3's two instances must point the 2.7B instance at E + the 355M
instance at wire time, NOT at 2.7B T_single, or the search
optimizes a flat column. C64-c CLOSES: ladder v0 official, both
classes + figure; the section-6 anti-stranding SEED POOL (all
seven named Pi per class, serialized) DELIVERED to S3 in
analysis/ladder_v0.json. Registry, faithfulness A-D, excerpts,
C-reinforcement, spec section 9 sync, degeneration pin: all
green. Suite 394. POST-CLOSE NOTES ROUND EXECUTED 2026-09-11 (5 items, before S3
opens): (1) E-COLUMN RECONCILIATION, the one-number ruling: the
T-ladder leaders' E gap to the E-best seat (clustered 2.3379 J)
is nmap_greedy +0.001405 J = +0.0601% and least_manhattan
+0.000255 J = +0.0109% of system energy -- BOTH within the 0.1%
gate, so the within-0.1% branch applies: the two standing
sentences are filed EACH WITH ITS SCOPE (spec section 6 [AMENDED
9]): "8.0%" = the FULL seven-seat spread, dispersed end included;
"latency-optimal seating costs below one-thousandth in energy" =
the T-best-to-E-best gap; the blanket "within-percent boredom"
sentence is retired. (2) F-L2's S3 consequence is now SPEC, not
just a note: section 6 [AMENDED 9] adds the instance-to-objective
mapping (2.7B seating -> E; 355M ordering -> wire time; cuts and
condition levels keep T with E as tie-break) and scopes the old
tie-break clause to T-objective instances. (3) 355M DEGENERATE
CORNER declared in spec section 10 [AMENDED 10]: six named
baselines tie at 1.00 avg hops = the chain-adjacency lower bound,
the uniform-chain ordering problem is closed by heuristics; the
S3 ordering instance is DECLARED to run under the cross-traffic
class load (the check-C fan-out family) -- chosen over the A3
co-residency alternative to keep the two instances' conditions
disjoint; the uniform-chain version is filed as a solved
degenerate corner, never a search demo. (4) The condition-bound
flip (same clustered seating: best 6.2M pure chain <-> worst
30.0M fan-out) is REGISTERED as S6 evidence material (spec
section 7 [AMENDED 11]) and opens the writing-materials library
analysis/MATERIALS.md -- not left in the check record. (5) Ladder
figure revised per review: left panel now plots T/best-1 in ppm
("excess over cell best", +1 offset notation), middle panel title
states the invariance ("D2D words: seat-invariant, set by
construction"), all three panels share the 2.7B T-ladder order;
figure-group README analysis/ladder_v0.md added with the
two-lever caption (ladder left/middle = the package-seat
propagation lever, us-scale; check-C figure = the die-mesh
busiest-wire occupancy lever, multiple-fold -- juxtapositions
must say so). S3/C64-d DAY 6 PRE-REGISTRATION (declared BEFORE implementation
runs; scope = the SA BODY + the ergodicity page + engine gates
ONLY -- no instance runs, no official search numbers today; the
two instances are days 7-8 and their expectations get their own
pre-registration): the engine ships the spec section 8 pieces --
three operator families (permutation = single-slot exchange
between two sets; migration = slot to free slot, with the
TWO-STEP evict+place form on capacity-saturated hosts, and the
355M host IS saturated at 48 units / 48 slots so its migration
family degenerates to the two-step form by construction, declared;
swap = whole-set pairwise, equal sizes, the NMAP-style family),
Metropolis acceptance with a parameterized geometric schedule
(t0 = 0 is the greedy mode), REJECTION-mode feasibility (spec
section 6 [AMENDED 3]: an infeasible proposal is rejected and
counted, never penalized), multi-start over an explicit seed set,
full determinism given the RNG seed, and the CONSTRUCTIVE-PATH
routine the ergodicity page argues with. Engine GATES (correctness
gates, not findings -- a failed gate is a bug fixed and recorded,
not bookable): G1 every state visited by random operator walks is
legal(), both workload classes, all three families; G2 the
incremental == full identity extends to ENGINE-GENERATED deltas
(ScoreSession driven by proposal moves, migrations to free slots
included -- the S1 pin only exercised swaps); G3 greedy (t0=0)
monotone non-worsening + same-seed reruns bit-identical (toy
objective, DECLARED MEANINGLESS: weighted slot-index sum --
exists only to exercise machinery, its numbers are not readings);
G4 constructive_path(a, b) lands exactly on b with every
intermediate legal and length <= the mismatched-slot count, random
legal pairs both classes; G5 rejection mode never accepts an
infeasible state and counts rejections. The line-load incremental
structure (ordered per-wire loads, recompute-affected-then-remax)
ships WITH the ordering instance on day 7 where it earns its pin;
ScoreSession covers the 2.7B incremental leg today. Ergodicity
page: analysis/ergodicity.md -- constructive path between any two
legal seatings at fixed cuts (monotone mismatch argument),
irreducibility because every path move has positive proposal
probability, aperiodicity from rejection self-loops, the
saturated-host two-step case, and the DECLARED degenerate
configurations (A1 degeneracy theorem zeroes the within-die space
absent co-residency -- the within-die instance runs under A3;
the 355M uniform chain is the solved corner per [AMENDED 10]). DAY 6 DONE 2026-09-11: scripts/search_sa.py (propose with the
three families exactly as declared; apply_delta;
constructive_path with the monotone-mismatch construction; anneal
with Metropolis + geometric schedule + greedy mode + rejection
counting + the infeasible-start refusal implementing the
section-6 guardrail's engine side; multistart with per-start
derived RNG and name-ordered tie-break) + analysis/ergodicity.md
(the one-page argument as pre-registered, including the
saturated-host statement: exchange = swap = two-step migrate on
one-die sets, the path uses exchanges only there) +
tests/test_search_sa.py = GROUP 50, 9 gates, ALL GREEN FIRST RUN:
G1 legality walks both classes (plus the saturated-migration
shape check: on 48/48 every migrate touches exactly two sets);
G2 ScoreSession == full score to 1e-12 on 12 engine-generated
deltas (free-slot migrations included -- new coverage beyond the
S1 swap-only pin); G3 greedy monotone + same-seed bit-identical
reruns, Metropolis best_j <= start and best reproduces its own J;
G4 constructive path exact, all intermediates legal, length <=
mismatch count on four named pairs across both classes, and the
size-mismatch refusal; G5 rejection mode never accepts an
infeasible state, counts rejections, never penalizes, and refuses
an infeasible START (the guardrail's engine half). No instance
numbers produced today (toy objectives declared meaningless).
Fast suite 394 -> 403. DAY-6 REVIEW ROUND APPLIED (the reviewer's audit passed the
mathematics; fixes were bookkeeping + two rigor sentences): (1)
ergodicity.md now states the implicit step EXPLICITLY -- the
annealing chain inherits the proposal chain's irreducibility
because at fixed t > 0 the Metropolis acceptance of any finite
Delta is strictly positive (and greedy t0 = 0 claims no
ergodicity); and carries the SCOPE + USAGE TEMPLATE for
constrained instances: the constructive path argues the FULL
structurally-legal space, feasibility rejection walks a subset,
connectedness does not inherit -- every constrained instance
fills (a) walks-the-full-space or (b) its own connectedness
argument; the S4 sparse cuts axis is the first expected client
of (b), slot left in the page. (2) The nine-gate LIST in full so
the count audits without opening files (group 50):
g1_random_walks_stay_legal, g1_saturated_migration_is_two_step,
g2_scoresession_matches_full_on_engine_deltas,
g3_greedy_monotone_and_deterministic,
g3_metropolis_still_tracks_best,
g4_constructive_path_both_classes,
g4_path_refuses_mismatched_inventories,
g5_rejection_mode_never_accepts_infeasible,
multistart_deterministic_and_picks_min -- 394 + 9 = 403. (3) The
two C64-d-attached hangers CHECKED IN: the S6 which-instance
declaration is now SPEC ([AMENDED 12]: the four arms run on the
die-level ordering instance under the cross-traffic class load,
E1's flip exhibit and E2's one-hot axis both live there; the row
inherits the day-7 condition confirmation) -- and ladder_v0.json
is HASH-PINNED: sha256 = d41b4ecf0a8736fe6c30cb81f5d2c1ac
c4b8a495392b5e277a5f3a8fd6646c75 (the file is regenerable and
uncommitted by repo policy; the hash makes the official readings
and the delivered seed pool auditable -- a regeneration that
changes the hash is a moving number and must be explained).
DAY-7 DECISION STANDING AS DECLARED BY THE REVIEW: the
cross-traffic condition flips from changeable to SET when the
ordering instance first reads numbers -- the user's confirm (one
word) or veto arrives with the day-7 release; a veto must land
before numbers, else the arm's readings are provisional-marked.
DAY 7 OPENED 2026-09-14; THE RELEASE CARRIED NO VETO, so per the
declared rule the CROSS-TRAFFIC CONDITION IS NOW SET (changeable
-> fixed; [AMENDED 10] and the S6 [AMENDED 12] row both stand on
it). DAY-7 PRE-REGISTRATION (written BEFORE any number is read):
THE ORDERING INSTANCE, declared in full -- Omega = the standard
frozen 2.7B Pi space (per-op sets, legal() unchanged; the
ergodicity page's usage template is filled with option (a): this
instance walks the full structurally-legal space, no feasibility
predicate). J = the wire-time caliber on the DECLARED cross-
traffic class load: stages = the 32 layers (per-op sets unioned
per layer, exactly check-C's granularity), pairs (s, s+k) for
k in {2,4,8}, s+k < 32 (82 pairs), V = 1e6 words per pair, flows
by the frozen R-split boundary convention verbatim, routed on the
nominal 1 word/cycle die mesh; J is REPORTED as busiest-wire
volume in words (wire time = volume x cycle at the nominal
bandwidth -- the monotone identity is declared, the numbers stay
comparable to the filed 18.29M-30.00M ladder). The named ladder
for THIS instance = the check-C fan-out column (sequential 22.24M
/ snake 28.00M / clustered 30.00M / least_manhattan 29.12M /
nmap_greedy 26.76M / heaviest_first 19.29M / random 18.29M), and
the objective must REPRODUCE those numbers as an identity anchor
before any search runs (pin). BUDGET, declared: multi-start over
the seven named seeds (the delivered pool), base seed 0, all
three operator families, Schedule(t0 = 1.0e6 words, alpha =
0.996, steps = 2000) per start -- identical budget on both legs.
LEGS: active leg = the fan-out load above; CONTROL leg = the
uniform chain pattern ((s, s+1), 31 pairs, same V) -- the safe-
cell analog on this instance. The Delta column rides as 1.00 BY
CONSTRUCTION (packet-free mesh weave; construction-default
declared at S1). EXPECTATIONS, two-handed: E-O1 the multi-start
best is <= every named rung on its leg -- BY CONSTRUCTION (seeds
include the named seatings and best-tracking never loses them);
the pin verifies the bookkeeping, this is not a bet. E-O2 (the
real bet, active leg): search lands SUBSTANTIVELY below the best
named rung (random 18.29M) -- bar: >= 10% below (< 16.46M);
landing in [0, 10%) is a FINDING (the dispersed floor is near-
optimal and the named ladder already brackets the space). E-O3
(control leg): the search best stays in the compact family's
neighborhood -- J <= clustered's 6.18M with margin <= 15%; a
larger margin is a FINDING (the corridor pattern has real seating
headroom beyond rectangle tiling -- NOTE the solved-corner claim
[AMENDED 10] is about the 355M avg-hops caliber and is NOT
touched by this leg either way). E-O4 the incremental line-load
structure (per-pair wire-contribution cache; a move recomputes
only the pairs touching the moved sets' stages, then re-takes the
max -- the spec section 8(a) structure, delivered HERE where it
is consumed) matches the full link_occupancy evaluation to 1e-9
along random engine walks (its pin, plus the within-stage
op-swap J-invariance pin: J sees stage unions only). Flips booked
as findings; readings become official only with the suite green
and this block already on file. DAY 7 RESULTS (scripts/search_ordering.py; pins group 51 FIRST,
all green before the run: P1 the objective REPRODUCES the filed
check-C fan-out ladder rung for rung AND matches the independent
full link_occupancy evaluation; P2 incremental == full along
random engine walks, integer-count exactness; P3 within-stage op
swaps exactly J-invariant -- J sees stage unions only; P4 the
control-leg chain anchor. Suite 403 -> 407). OFFICIAL READINGS
(analysis/search_ordering.{json,png}; sha256 of the json =
3da4291210855991099f21ddaa87f093d8707201df7b6e25785cc2a9c12e
8618): ACTIVE LEG (fan-out): search best 16.294M words busiest
wire, from the nmap_greedy start; regret vs best named (random
18.29M) = 0.891, i.e. 10.9% below -- E-O2 LANDS, clearing the
pre-registered 10% bar by 0.9 points (honest note: close to the
bar, the margin is real but not large). ALL SEVEN STARTS converge
into a 1.8%-wide band (16.294-16.588M) and EVERY start ends below
EVERY named rung -- the reading is multi-start-consistent, not a
lucky seed; notable: the best start was the COMPACT nmap_greedy
seed, i.e. the SA walked out of the compact basin and past the
dispersed floor. CONTROL LEG (uniform chain): search best 6.118M
from the clustered start, 1.0% below clustered's 6.18M -- E-O3
LANDS well inside the 15% neighborhood bound (the compact
corridor family is confirmed near-optimal for the chain pattern;
all starts land 6.118-6.235M). E-O1 held by construction and
verified in the bookkeeping (per-start best <= its own start rung
and <= all rungs). E-O4 pinned (P2 + the run's own final
incremental-vs-full assert on the best seating). Delta column =
1.00 by construction (packet-free mesh), reported in the json. NO
FLIPS on day 7. Acceptance traffic: ~52-57% of proposals accepted
early-schedule per start (recorded per start in the json). S6
NOTE, filed for [AMENDED 12]: the four arms inherit THIS instance
exactly (same Omega / budget / seeds); E1's distance-proxy arm is
expected to walk TOWARD compactness on this load and score
30M-class under E0 -- the pre-written S6 cell expectation, to be
formalized at S6's own pre-registration. DAY 8 OPENED 2026-09-14. PRE-REGISTRATION (before any run): THE
WITHIN-DIE INSTANCE = SA on the A3 co-residency space exactly as
C49-b declared it (the REALIZABLE reopened space; offload config,
d = 1024, blocks tile integrally): attn die = qkv_proj on 3 of 8
macro slots + out_proj on 1 of the rest (280 joint seatings, FOUR
FREE slots -> the migrate family runs its plain form), ffn die =
ffn1 on 4 + ffn2 on 4 (70 seatings, SATURATED -> two-step form);
within-op order irrelevant by uniformity (sets, not tuples).
Ergodicity template filled with option (a): full structurally-
legal space, no feasibility predicate (legality = set sizes +
slot disjointness, BY CONSTRUCTION in the engine; the die-level
tiler clause does not apply to this level, declared). J = the
per-die JOINT STACK COST at the g = 0.4 GB/s anchor (the below-
knee active cell), the C49-b composition verbatim: sum over the
die's ops of write + prop + max(compute, a3_ser x scale), with
a3_ser = the stored-lever (D,U) x 8/k flows on the op's own seats
through the production 2x4 mesh (glb centre) link_occupancy at
REF_WC, and scale = REF_WC / wc(0.4); levers READ FROM the stored
soft_lever.json (no refit); phases prefill AND decode. REFERENCE
(this instance's ladder): the space is exhaustively enumerable --
ground truth = the EXHAUSTIVE optimum; rungs reported = shipped-
contiguous seating (qkv {0,1,2} + out {3}; ffn1 {0..3} + ffn2
{4..7}), exhaustive best, exhaustive worst. IDENTITY ANCHOR
(pin, before any SA): the recomputed A3 fold (both dies + the
fixed rest of the stack) reproduces the STORED soft_lever.json
a3_cells rows at every anchor, both phases (stack 1.4341/1.057
at 0.4, mech 3.0/2.6667) to 1e-9-class tolerance. BUDGET,
declared: 2 dies x 2 phases, 3 starts each (shipped / random
seed 0 / reversed-shipped), Schedule(t0 = 0.02 x J(shipped),
alpha = 0.98, steps = 400), base seed 0, all three families.
EXPECTATIONS, two-handed: E-W1 SA regret vs the exhaustive
optimum = 1.000 EXACTLY on every die x phase (the space is tiny;
a miss is an engine-quality finding, not a space finding). E-W2
the identity anchor above (an anchor, not a bet). E-W3 OPEN
two-handed reading, no direction pre-claimed: whether the
shipped-contiguous seating already sits at the optimum (finding
either way: "shipped is optimal in the reopened space" vs "free
headroom on the shipped mapping", with the margin). E-W4 SAFE-
CELL CONTROL realized here: at g = 2.0 (above the knee) the
stored ratio is 1.0 -- the objective is FLAT, every seating
ties; the exhaustive check must confirm all-ties and SA must
return best = start (no strict improvement exists). Delta column
1.00 by construction (no packet fields on the within-die
schemes). DAY 8 RESULTS (scripts/search_withindie.py; pins group 52 first:
W1 the recomputed A3 fold == the stored a3_cells rows both
phases all anchors; W2 SA hits the exhaustive optimum; W3 the
g = 2.0 safe cell is all-ties. Suite 407 -> 410). OFFICIAL
READINGS (analysis/search_withindie.json, sha256 = f10a22bfde59
2cf27a8095112dea4ad6d394450f05f35872d7c971171e080a60): E-W1
LANDS EXACTLY -- SA regret vs the exhaustive optimum = 1.000000
on all four die x phase cells (winning start: random0 in each).
E-W2 the identity anchor held (stack 1.4341/1.057 at 0.4, mech
3.0/2.6667 reproduced). E-W3 the open reading RESOLVES to "FREE
HEADROOM ON THE SHIPPED MAPPING", booked as a FINDING: the
shipped contiguous seating sits MID-BAND, +17.8%/+17.5% (attn
prefill/decode) and +20.0%/+19.7% (ffn) above the exhaustive
best per-die joint cost at 0.4 GB/s; exhaustive bands 1.515
(attn) and 2.000 (ffn). The optimum INTERLEAVES the co-resident
ops (ffn1 {0,1,3,5} / ffn2 {2,4,6,7}; qkv {0,1,6} + out {4}) --
the MASKED form of the same mechanism, one level down
[REWORDED per the day-8 review: NOT "the flip repeats" -- this
data contains no rank inversion; what the condition changes is
the MAGNITUDE (18-20% in the 0.4 active cell, ZERO in the safe
cell) -- rank inversion stays exclusive to the check-C flip, the
sharpest piece of the evidence set; MATERIALS.md entry reworded
accordingly, the 18-20% permanently bound to "0.4 GB/s active
cell x A3 co-residency" with the safe-cell zeroing as the other
half of the sentence, plus the review's third-level reading:
whether within-die placement matters at all is itself a CELL
question]. E-W4 LANDS: g = 2.0
all-ties confirmed exhaustively and SA returns best == start --
the S3 pre-registration's safe-cell all-ties expectation is
realized. NO ENGINE-QUALITY FLIPS. S3 CLOSE-OUT (C64-d DONE, days 6-8): the SA body + ergodicity
page (day 6, gates G1-G5 = group 50); the ordering instance
under the SET cross-traffic condition with the line-load
incremental structure and its pins (day 7, group 51; active-leg
regret 0.891 vs best named, control-leg 0.99 vs clustered); the
within-die instance on the A3 co-residency space with exhaustive
ground truth (day 8, group 52; regret exactly 1.000, shipped
headroom finding). Spec section 10's S3 ship list is fully
delivered: SA body per section 8, ergodicity page, two
single-level instances, regret readings against the declared
references, Delta column riding (1.00 by construction on every
leg -- packet-free weaves). Expectations: pre-registered on all
three days; two flips across S3, BOTH bookable findings (day-7
none; day-8 shipped-headroom is a reading not a flip -- the open
two-handed E-W3 resolved; the S2-era F-L1/F-L2 stand). Suite
385 -> 410 across S3. DAY-8 REVIEW ROUND APPLIED 2026-09-14: (1) the BIT-LEVEL
COINCIDENCE ruled STRUCTURAL, one line, decomposition printed:
attn/prefill-worst and ffn/prefill-shipped are the SAME TERM
MULTISET -- all four ops share write = 0, prop = 1.8e-7 s,
compute = 5.19168e-3 s in the stored ledger, and the ser word
counts land on the power-of-two lattice ({4,194,304 + 2,097,152}
words vs {2,097,152 + 4,194,304}): identical addends in a
different order, hence bit-identical sums including the float
noise (decode pair likewise, {8192 + 4096} words). Same lattice
explains the exact 1.2000 / 2.0000 ratios. Noted, no line to
chase. (2) The SEVEN test names 403 -> 410, per the standing
audit rule (group 51: test_p1_objective_reproduces_the_filed_
fanout_ladder, test_p2_incremental_matches_full_along_engine_
walks, test_p3_within_stage_op_swap_is_invariant,
test_p4_control_chain_anchor; group 52: test_w1_fold_reproduces_
stored_a3_cells, test_w2_sa_hits_the_exhaustive_optimum,
test_w3_safe_cell_is_all_ties). (3) EDGE-WEIGHT MAGNITUDE
BACKFILL RESCHEDULED, on the record not silent: [AMENDED 2]
pre-registered the DP hand-off-fee optimism magnitude to fall
out of "day 8's joint-vs-decomposed small instance" under the
ORIGINAL numbering; the S3 day 8 (within-die) came due without
it because that instance belongs to S4's linkage -- NEW HOME =
S4 DAY 10 (the joint-vs-decomposed small instance of the DP+SA
linkage); this line is the reschedule record and the item MUST
appear in S4's day-9/10 pre-registration as front matter.
(4) RULED BY THE USER 2026-09-14 -- path (a), absorbed into S4
day 10: the linkage's SA-seating leg on the A4 payload runs with
E as its main objective per [AMENDED 9] and produces the seating
instance's first readings there; spec [AMENDED 13] records it,
the S3 close-out wording is fixed in both SUMMARYs ("its own two
instances complete; the seating instance's readings are an S4
day-10 deliverable"), and S4's pre-registration MUST carry it as
front matter next to the edge-weight backfill. Original open
text kept below for the audit trail: the 2.7B SEATING instance -- [AMENDED 9] gave it main
objective E, S6 inherits the ORDERING instance per [AMENDED 12],
and no seating-instance reading exists yet while the S3
close-out says "ship list fully delivered"; one of the two
statements needs revision. Recommended path (a): absorb into S4
day 10 -- the linkage's SA-seating leg on the A4 payload runs
with E as its main objective per [AMENDED 9] and produces the
instance's first readings there, recorded as an explicit
amendment + close-out wording fix; alternatives (b) explicit
postponement after S4, (c) rule it out (user's own reasons).
The SUMMARY close-out sentence is adjusted once the ruling
lands. S4's release is NOT blocked by (3)/(4) per the review;
both ride as S4 pre-registration front matter. DAY 9 OPENED 2026-09-14 (S4 / C64-e first half). FRONT MATTER,
carried per the day-8 review: (i) the [AMENDED 2] edge-weight
optimism magnitude backfill is DUE DAY 10 (joint-vs-decomposed
small instance of the linkage); (ii) the 2.7B seating instance
produces its first readings DAY 10 as the linkage's SA-seating
leg with main objective E ([AMENDED 13], user-ruled). DAY-9
PRE-REGISTRATION (before any run): THE INTERVAL DP, declared in
full. Blocks = the 32 homogeneous layers; state F(k, j, d) =
first j blocks in k segments using d dies (spec section 8 level
1, states unchanged per [AMENDED 1]). ORACLE, closed form on the
frozen accounts (zero mapper): t(segment [i, j), g) = (j - i) x
layer_serial_s(prefill) + entry hand-off fee; the GROUP-SIZE
AXIS g runs over the LAYER-LEVEL tiler-feasible size set = all
sums of per-op feasible counts (ss.feasible_die_counts per op,
per-op cap = standing + 3), a SPARSE set: 17 is the standing
minimum (4+1+2+5+5) and 16 MUST be absent (it would need ffn1 =
4, the O10 counterexample) -- pinned. V1 DECLARED FLAT IN g:
tau(g) = layer_serial_s at the production point for every
feasible g (the replication/heterogeneity speed model is OUT of
v1 scope, stated -- the spec's "DP earns its keep under
heterogeneity or replication" enters day 10+ through constrained
two-phase mu, weave conditions and seam variants, which move the
FEES; today's job is a PROVABLY CORRECT DP). FEES per [AMENDED
2]: the entry boundary priced at ADJACENT-SEATING REFERENCE
HOPS = 1, fee_s = inter-layer boundary words (the evaluator's
own boundaries() convention, read once from the standing
payload) / (12.5 GB/s GRS) -- systematically optimistic,
direction declared, magnitude backfill day 10. CALIBERS: pipe
(primary; the DP is MINIMAX -- F = min over cuts of max(stage
times), stage = m x tau + entry fee, wrap excluded) and single
(sum form; expected degenerate to k = 1 since cuts only add
fees). BUDGET d <= 576. GATES (correctness, not findings):
D1 DP == brute force on randomized SYNTHETIC small instances
(heterogeneous per-block tau, random fees, randomly-thinned
sparse G; L <= 8, exhaustive over all cut sets x g choices) --
the real optimality gate, both calibers; D2 the sparse axis is
honored: a size absent from G never appears in any plan, and the
layer-level echo of O10 (16 absent / 17 present) is pinned;
D3 homogeneous-payload degeneracy: for every k the DP interval
equals the balanced-cut interval, minimal g = 17 everywhere
(flat tau => no die wasted), single-caliber optimum is k = 1
with zero fees; D4 determinism + budget accounting (allocated =
544 = 17 x 32 at the optimum); D5 reconstruction returns (cuts,
per-segment g) that re-price EXACTLY to the DP value. ERGODICITY
TEMPLATE SLOT (b) RESOLVED for S4 (the page gets the fill): the
sparse cuts/size axis hosts NO Markov chain -- the DP enumerates
it EXACTLY, so feasible-region connectedness is moot there; the
only chains S4 runs are the linkage's SA-seating legs, which
walk the full structurally-legal seating space (option (a)).
EXPECTATIONS, two-handed: E-D1 the homogeneous stack is
NEAR-DEGENERATE exactly as the spec pre-wrote -- uniform/
balanced cutting optimal at every k (A4's flat spread is that
point), now DP-VERIFIED rather than assumed; a deviation is a
finding. E-D2 the pipe-caliber optimal k on the standing payload
at GRS: the interval falls ~1/k with balanced cuts while fees
add per-segment -- expected optimum at the LARGEST k the fee
tax permits; the reading (k*, interval, fee share) is the day's
number, no bar pre-set (first reading, bracketed not bet).
Flips booked as findings. DAY 9 RESULTS 2026-09-14 (scripts/search_dp.py; gates group 53
first, all green: D1 DP == brute force on 6 randomized synthetic
instances x k in {1,2,3} x both calibers -- heterogeneous taus,
random fees, thinned sparse G; D2 sparse axis honored + the O10
echo pinned; D3 homogeneous degeneracy; D4 determinism + budget;
D5 reconstruction re-prices exactly, asserted inside solve().
Suite 410 -> 415; test names: test_d1_dp_equals_brute_force_on_
synthetic_instances, test_d2_sparse_axis_honored_and_o10_echo,
test_d3_homogeneous_degeneracy_and_single_k1,
test_d4_determinism_and_budget_accounting,
test_d5_reconstruction_reprices_exactly). READINGS on the
standing payload: the LAYER-level feasible size set G =
{17..28} with 16 ABSENT (the O10 counterexample surfacing at
layer granularity: 16 would need ffn1 = 4; the fixed-function
attention die is a declared singleton axis {1} -- it is not a
weight matmul and is not tiler-planned, clarification recorded);
layer_s 28.7848 ms, inter-layer boundary 5.24M words -> fee
0.4194 ms at reference hop 1 (GRS). E-D1 LANDS: balanced cuts at
EVERY k, minimal g = 17 everywhere, 544 dies allocated -- the
pre-written near-degeneracy is now DP-VERIFIED, A4's flat spread
is exactly this point. Single caliber prefers k = 1 (921.113 vs
921.533 ms at k = 2: cuts only add fees), as pre-registered.
E-D2 READING: pipe-caliber k* = 32 (one layer per stage),
interval 29.2042 ms = layer_s + one fee, fee share 1.44% at GRS
-- at the safe-cell bandwidth the fee tax never overturns
deeper pipelining on the homogeneous stack; the interesting k*
regime (fees biting) moves to the weak-D2D / condition-varied
cells, which is DAY 10's linkage territory. ERGODICITY SLOT (b)
FILLED on the page: the sparse axis hosts no chain -- exact DP;
the linkage's SA legs fill option (a). NO FLIPS. LEDGER PROVENANCE LINE, added per the day-9 review (the attention
DIGITAL-UNIT cost, auditable for the 9.33x / 1.11x citations):
the unit is fabric.DigitalUnit (O24), a PLATFORM INPUT (DR-8);
shipped generic configuration 64 lanes x 1 GHz (sized to the die
array output rate: 256 arrays x 128 outputs per 1.4486 us device
cycle = 22.6 G results/s), per-op energies from the Horowitz
ISSCC 2014 45 nm table at 16-bit intermediates, registered in
ANCHORS.md -- provenance grade: GENERIC PUBLIC EXAMPLE VALUES,
not vendor-calibrated (the DR-8 register row carries the grade).
Latency formula: arith_ops / (lanes x clock). At the 2.7B point
(d = 2560, S = 512, prefill, per layer): softmax 524.29 us, GELU
491.52 us, LayerNorm 204.82 us, residual 40.96 us; at the 355M
point (d = 1024): softmax 262.14 us prefill / 0.51 us decode,
elementwise total 557.07 / 1.09 us per layer. WHERE IT ENTERS:
2.7B account -- the elw term of Workload2p7B.layer_terms_s
(block_elementwise_ops x elementwise_cost), a FIXED term that
device_scale does NOT divide (pinned:
test_device_scale_shrinks_the_matrix_part_only); 355M account --
the same elementwise_cost values as fixed adders in the
stack_latency composition (the C49 record's convention). The
qk^t / av MATMULS are separate array ops in the frozen per-op
account (2.7B prefill compute 2.596 / 1.298 ms) and DO scale;
only the vector unit is the fixed digital term. Constant wrt
seating and ordering -- it appears in no placement objective;
the line exists so the 9.33x (prefill device sweep) and 1.11x
(decode, K/V-write-walled) figures cite a traceable number. DAY 10 OPENED 2026-09-14 (S4 second half). PRE-REGISTRATION --
the review's three declarations FIRST, then exhibits, then
numbers. (1) T_PREFILL BUDGET, per the user's frame (a
DEMONSTRATION pre-registered constraint, not a performance
promise; too loose binds nothing, too tight kills feasibility):
PROPOSED B = 120 ms, selection procedure declared -- the
constrained solver is min T_decode(single caliber: cuts only ADD
decode fees, so decode wants FEW cuts) subject to
T_prefill(pipe interval) <= B, whose optimum is the SMALLEST k
whose balanced interval fits the budget; the staircase of
critical points is interval(m) = m x 28.7848 + 0.4194 ms at
max-stage m = ceil(32/k), so B = 120 sits inside the m = 4 step
(k* = 8), differing from the unconstrained decode optimum k = 1
-- the constraint BITES, meeting the acceptance standard; the
run reports the FULL threshold staircase with readings on both
sides of every critical point, including the first-bite edge
921.11 ms (k 1 -> 2) and the local edges 115.56 / 230.70 ms.
(2) EDGE-WEIGHT BACKFILL, quantified negligibility standard
declared BEFORE the measurement: the [AMENDED 2] optimism is
NEGLIGIBLE iff (a) re-running the DP with fees priced at the
ACTUAL SA-found seating's hops (per cut boundary: words/bw +
max_hops x 20 ns, vs the reference words/bw + 1 x 20 ns) changes
NO cut decision at k in {2,4,8,16,32} nor in the constrained
exhibit at B = 120; AND (b) the bottleneck-stage reading shifts
< 1% at every tested k. Either failing -> the magnitude is a
FINDING and the DP fee model is upgraded, not excused. (3) THE
2.7B SEATING INSTANCE's first readings ([AMENDED 13]): main
objective E; REFERENCE DECLARED = the ladder E column, reference
rung clustered 2.3379 J (the E-best named; direct exhaustion of
the 544-seat space is impossible, declared); regret reported vs
all seven rungs, T alongside as the flat column; evaluator = a
diff-driven ScoreSession-backed incremental E callable (its own
pin); budget: seeds {clustered, snake, random0}, Schedule(t0 =
0.005 J, alpha = 0.996, steps = 1200), base seed 0, all three
families. EXHIBITS, expectations two-handed: EX1 constrained
two-phase table (the previously-unobtainable result class):
T_decode monotone increasing in k (each cut adds a decode fee),
constrained k* = smallest feasible k -- the staircase IS the
exhibit; flip = finding. EX2 weave condition enumeration (the
die_weave knob, O19 pool): seating SA rerun under torus and ring
vs the mesh default, same budget/seeds; expectation: the E
spread across seatings NARROWS under torus (the fold shortens
worst-case distances; O19's hub-lever zeroing precedent) and
WIDENS under ring (the weave lever precedent, 12.26x vs 3.57x
ordering spread); flips = findings. EX3 seam-bound variant: cuts
BOUND to the A4 seam example (16 layers/package -> cuts (16,32),
use_seam payload) vs the DP's free k = 2; expectation: the seam
bound costs ~nothing at GRS (16|16 IS balanced, fee 0.42 ms) --
interval equal to free k = 2 to within the fee; the exhibit
prices a real deployment bound; flip = finding. GATES (group
54): L1 the constrained solver == brute enumeration over k on
the standing instance at several B (and bites at B = 120); L2
the SessionE incremental == full score e_J along engine deltas;
L3 backfill identity -- actual fees at hops = 1 reproduce the
reference DP exactly. Numbers only after this block; S4 closes
with the day + SUMMARY sync. DAY 10 RESULTS (scripts/search_linkage.py, gates group 54 first,
all green -- test_l1_constrained_solver_structure_and_bite,
test_l2_session_e_matches_full_score,
test_l3_backfill_identity_at_reference_hops; suite 415 -> 418;
data analysis/search_linkage.json, sha256 = c984708bc4257970
f6bdd6387439fde0b19a6ccf8022b5f4d22ef97b1fce45f3): EX1 LANDS,
the constraint BITES per the acceptance standard: B = 120 ms ->
constrained k* = 8 (T_prefill 115.56 ms, T_decode 24.115 ms) vs
unconstrained decode-optimal k = 1; full staircase filed
(first-bite edge 921.11 ms verified on both sides by gate L1;
thresholds 460.98 / 317.05 / 230.70 / ... / 115.56). Honest
note: the decode price of pipelining at GRS is feather-light
(~0.7 us per cut; T_decode 24.110 -> 24.115 ms over k 1 -> 8) --
the staircase is real but the two-phase tension at GRS is
gentle; it steepens where fees grow (weak D2D), the cell
discipline's point. BACKFILL DUE CLOSED (spec [AMENDED 2] now
carries the number): cut-boundary hops up to 10 at the SA-found
seating; NO cut change at any tested k; bottleneck shift 2.2e-7
... 6.8e-6 relative -- NEGLIGIBLE under the pre-declared
standard. SEATING INSTANCE FIRST READINGS ([AMENDED 13]): best
E = 2.337921 J = the clustered rung EXACTLY (start clustered,
unimproved in 1200 steps; snake likewise unimproved at its rung;
random improved 2.525133 -> 2.489385 without reaching the
clustered basin) -- regret 1.0000 vs the E-best named (the
json's 1.00001 is a 4-decimal-constant rounding artifact,
declared); the first reading is honest: at this budget the
E-best named seating is not beaten, the E-column named ceiling
stands (deeper budgets belong to S6-era runs); T flat column
1034.793 ms rides. EX2 SPLITS, one land one flip, plus a bonus
finding: ring LANDS -- the E spread across the three rungs
explodes (2.512 / 3.499 / 6.433 vs mesh 2.338 / 2.354 / 2.525)
AND the ordering INVERTS: snake < clustered under ring (3.347
after SA polish still above snake's 2.512) while clustered <
snake on mesh/torus -- booked as FINDING F-L4: a genuine RANK
INVERSION on the E column across the weave CONDITION (the
condition-bound motif now measured on a third axis: traffic
pattern, then cell, now weave). TORUS FLIPS the expectation --
booked as FINDING F-L3: every rung's E RISES under torus
(clustered 2.3379 -> 2.3789, random 2.5251 -> 2.6418) and the
spread WIDENS slightly (1.11 vs 1.08), against the
count-caliber precedent the expectation leaned on: the E column
reads the PHYSICAL caliber, where the torus fold is a TAX
(folded wires are twice as long; compact seatings gain nothing
to offset it) -- the C59/E3 folded-x2 lesson resurfacing on the
energy column. EX3: EXPECTATION-PREMISE ERROR, recorded as
such, then the corrected reading: the pre-registration misread
the A4 seam example as 2 packages x 16 layers; it is 16
packages x 2 layers (cuts every 2 layers, 16 segments), so the
declared baseline (free k = 2) was the wrong comparison. The
corrected exhibit: the seam-bound plan IS the free DP's
balanced k = 16 plan -- intervals BIT-IDENTICAL
(0.05798899839999999 s both, verified) -- the seam bound costs
ZERO at its own segment count; the script's EX3 is fixed to the
same-k baseline for future regeneration. No model number moved;
the error lived in the expectation text alone. S4 CLOSES
(C64-e DONE, days 9-10): exact interval DP over the sparse
tiler-feasible axis (gated vs brute force), DP+SA linkage on
the A4 payload, the three exhibits delivered, both front-matter
dues paid ([AMENDED 2] backfilled with numbers, [AMENDED 13]
seating readings produced), ergodicity slot (b) filled. Spec
section 10 S4 ship list complete. Suite 410 -> 418 across S4.
FIGURE ROUND (day-10 review; the user ordered both figures drawn,
everything else passed): DECLINED per the review -- no figure
for the seating E column (engine validation, not a selling
point) nor the constraint staircase (the table is clearer).
FIGURE 1 analysis/weave_inversion.png (generator
scripts/fig_weave_inversion.py + weave_inversion.json): ring |
torus side by side, ALL SEVEN named seatings each, ONE shared
y-scale per the craft note, unit = D2D surplus traffic in G
word-hops (declared: exactly the measured E-column
seat-dependent channel / 10 pJ -- the quantity the inversion was
measured on), mesh reference dots in both panels, x fixed to the
mesh ladder order. The full seven-rung computation SHARPENS
F-L4 beyond the three-start version: under ring the ENTIRE
ladder reorders -- sequential becomes best (10.78 G) ahead of
snake (20.05) while clustered falls mid-field (118.8) and
least_manhattan/nmap blow up (92.8/96.0 vs mesh 2.7/2.8);
torus preserves the mesh order rung for rung, wholesale shift
~2.5x -- "some weaves reorder, some only shift" is now one
glance. FIGURE 2 analysis/condition_axes.png (generator
scripts/fig_condition_axes.py; drawn NOW on the user's
instruction, the reviewer's caution RECORDED: this is a
narrative close-out figure and may be RESEEDED when section 5
takes shape after S6): three slopegraph panels -- load axis
clustered/snake CROSS (6.18/15.06 -> 30.00/28.00 M words); cell
axis shipped/interleaved CONVERGE to the 10.38 ms tie (labeled
MASKS, gap -> 0, deliberately NOT an inversion per the settled
scope wording); weave axis clustered/snake CROSS (2.67/4.25 ->
118.80/20.05 G word-hops); per-panel units labeled, the verdict
carries the panel. DAY 11 OPENED 2026-09-14 (S6 / C64-f first half). PRE-
REGISTRATION (arms + gates today; argmin RUNS are day 12; every
number below that cites filed rungs is ARITHMETIC ON THE FILED
LADDER, not a new reading). THE FOUR ARMS on the ordering
instance, [AMENDED 12] inherited exactly (same Omega = frozen
2.7B Pi space, same seeds = the seven named, same algorithm =
the day-6 SA, same budget rule): E0 (truth) = the mu-weighted
busiest-wire volume over the DECLARED PATTERN MIX mu = {chain
0.5, fanout 0.5} (equal demonstration weights, declared,
swappable; J0 = 0.5 x busiest_chain + 0.5 x busiest_fanout, the
day-7 line-load machinery per pattern). E0 DEFINITION CHANGE,
stated with its reason (day-11 review): S3 day 7's instance
objective was the SINGLE fan-out load; S6's truth is the
two-pattern MIX -- a necessity of the experiment design (a
single-condition arm is only meaningful against a
multi-condition truth), NOT a revision of day 7: S3's 16.294M
is a fan-out-LEG number and is never compared to S6 mix
numbers except leg by leg. The 0.5/0.5 weights are
demonstration-arbitrary and the conclusions must not ride on
them: after the main run the same arm solutions are re-scored
(and E0 re-optimized) under mu = {0.3, 0.7}; one line files
whether every verdict holds. E2 MAPPING DECLARED [REASON
REWRITTEN at the day-11 review -- the first wording ("the
sharpest deception available") stated the RESULT as the
selection criterion, which a referee kills as arm-tuning]:
one-hot on CHAIN because chain is THE STANDARD pipeline load,
the single condition any engineer tunes for by default; that it
lands as the worst arm is a FINDING, not the reason it was
chosen. Per the same review a FAN-OUT one-hot arm (E2b) rides
at near-zero cost: with both one-hot directions run,
"single-condition tuning does not transfer" is claimed in both
directions, not a chosen one; the matrix becomes 5 x 5. E1 = the Hu-Marculescu distance proxy, the spec's
literal Sigma_e v_e dist(e): every producer-die -> consumer-die
flow of the SAME mu-weighted pair set at piece x Manhattan
[the pre-registration first wrote "stage-centroid distance"
here -- a deviation from the pre-written definition, caught by
gate R4 and corrected BEFORE any run; day-11 record] (citation
in code; per C58 its validity domain is price-proportional-to-
length WITHOUT a contention axis -- this instance HAS one,
which is the exhibit). E3 = J0's mix computed under the WRONG
WEAVE = ring (O19 pool; bus declined: its shared-medium busiest
resource is SEAT-INVARIANT, the objective degenerates to a
constant and regret is undefined -- per the day-11 review that
degeneration is PROMOTED to a standalone exhibit in
MATERIALS.md, the measured form of "without the right paradigm
the objective cannot even be written", not merely a decline
reason). BUDGET RULE, uniform across
arms with unit-sane scaling (declared): Schedule(t0 = (max seed
J_i - min seed J_i)/20 in the ARM'S OWN units, alpha = 0.996,
steps = 2000), 7 named starts, base seed 0, all families.
PROTOCOL: each arm argmin -> ALL re-scored by E0 -> regret
R_i = E0(Pi_i*) / E0(Pi_0*); the cross-scoring matrix E_j(Pi_i*)
raw; the core exhibit cell = "self-scores well, E0 scores
badly". CELLS: active cell = the declared mix; SAFE-CELL
CONTROL = mu one-hot chain as the condition for ALL arms (there
E2 == E0 by definition). PER-CELL EXPECTATIONS, pre-written
from the filed rungs (mix rungs by arithmetic: random 12.65M
best named, heaviest 14.03, sequential 15.36, nmap 17.41,
clustered 18.09, lm 18.18, snake 21.53): ACTIVE cell -- E1 walks
compact (distance always rewards compactness) and E0 judges it
30M-class on the fanout half: R_E1 >= 1.3 expected; E2 (chain
one-hot) walks the same compact direction: R_E2 >= 1.3; E3
(ring-optimal) reorders per F-L4: R_E3 > 1, bracket looser
(>= 1.05); E0's own arm must land at or below the best named
mix rung (by construction of seeding + best-tracking). SAFE
chain cell -- all four regrets ~ 1.00 (E1 and chain-E0 agree on
compactness there; E2 == E0; E3's ring chain optimum is
adjacency-shaped like mesh's), the all-tie control. Flips
booked as findings. GATES (group 55, today): R1 E2 == the chain
component of E0 (identity on probes); R2 E3 deterministic,
differs from E0 on a probe (non-degenerate), and its host is
the ring weave verbatim; R3 E1 hand-check on a tiny synthetic
seating (centroid arithmetic by hand); R4 isolation probe --
the four arms' rankings of the seven named seatings are NOT all
identical (top-1 disagreement between E1 and E0 expected from
the filed arithmetic); R5 determinism given seed. DAY 11 RESULTS: arms shipped
(scripts/search_referee.py: MixJ over the two line-load legs,
E2 = chain one-hot, E3 = the ring-hosted mix, E1 =
DistanceProxyJ) + gates group 55 all green (suite 418 -> 423;
test_r1_e2_is_the_chain_component_of_e0,
test_r2_e3_is_ring_hosted_and_not_degenerate,
test_r3_e1_hand_check_on_a_tiny_seating,
test_r4_isolation_probe_rankings_differ,
test_r5_arms_deterministic). GATE R4 EARNED ITS KEEP BEFORE ANY
ARM RAN [RECORD REWORDED at the day-11 review: the first
write-up framed the episode around the deception cell
dissolving -- an arm-tuned-toward-failure framing, inadmissible
in this file or the paper; the correct framing follows]: the
first E1 draft DEVIATED FROM THE PRE-WRITTEN PROXY DEFINITION
(the spec's literal Sigma_e v_e dist(e)) by pricing
stage-CENTROID distances; the SYMPTOM was collapse under
dispersed seatings (a spread set's centroid sits mid-grid;
random scored 194.9M-wd best); the FIX moved the implementation
TOWARD the spec definition (per-flow word-hops, the same
mu-weighted pair set as E0, no contention term) BEFORE any
argmin ran; no reading existed under the deviant form. The
episode's residue -- two faithful-looking proxies contradicting
each other, one fully fooled by dispersion -- is filed as
MATERIAL (MATERIALS.md), better registered than hidden. The
corrected seven-rung probe (arithmetic on filed machinery, not
a search reading): E1 ladder clustered 10.180G < sequential
10.226G < snake 11.112G < nmap 11.417G < lm 11.682G <
heaviest 14.486G < random 15.277G word-hops -- NEAR-INVERTED
against the E0 mix ladder (random 12.65M best ... snake 21.53M
worst): the two judges now demonstrably disagree at the rung
level -- the R4 premise on file. DAY-12 VERDICT STANDARDS,
fixed at the day-11 review before the runs: (i) the
cross-scoring matrix is COMPLETE, 5 x 5 (E0 / E1 / E2-chain /
E2b-fanout / E3): every arm's argmin scored under every
evaluator, self-score and truth-score in one table; (ii) the
acceptance threshold uses S3's measured noise floor -- a
defective arm's E0-regret must EXCEED the multi-start
convergence band's 1.8% to write "definitely wrong"; within
1.8% only "possibly wrong"; (iii) predictions pre-written from
the filed rungs: E1 and E2-chain converge to compact seats and
read clearly costly under the mix; E3's ring-optimal linear
ordering lands near the sequential rung under the mesh mix,
medium regret; all three above E0's optimum and beyond the
noise band = section 5's three pieces assembled; E2b-fanout
expected NEAR-RIGHT under the mix (its own condition is half
the truth) and clearly wrong in the chain safe cell -- the
one-hot pair is symmetric by design; (iv) safe-cell (chain
one-hot) control: E1 / E3 regrets ~ 1.00, E2-chain == E0 there
by definition, E2b the deceived arm there. Flips booked. DAY 12 RESULTS 2026-09-15 (scripts/search_s6.py; gate r6
E2b == the fan-out leg added first, suite 424; data
analysis/search_s6.json, sha256 = 596fa0999bdefbcbc560a89881
19200324d5d6600a6a9fdc8e7c1f3b5cc89301; figure search_s6.png.
Operational note: the host-side task was killed at a session
teardown mid-run; the container-side process SURVIVED and
completed untouched -- no restart, no partial artifact, the
json is written once at the end). ACTIVE CELL: E0's own optimum
11.382M (random start), 10.0% below the best named mix rung
(12.65M) -- the search beats the ladder on the mix as well.
REGRETS AND VERDICTS (threshold = the S3 noise band 1.8%,
final verdicts apply the pre-registered weight-robustness
clause): E1 = 1.5891 DEFINITELY WRONG (the core matrix cell:
self-judge 1.00, truth 1.59; its argmin's E0 score 18.088M sits
at the clustered mix rung -- the distance proxy walked to
compact exactly as pre-written, and holds 1.7054 at 0.3/0.7);
E2-chain = 1.0724 DEFINITELY WRONG (1.0926 at 0.3/0.7;
consistency note: its own-judge optimum 6.118M chain IS the S3
control-leg optimum, the arm reproduced S3 exactly); E3 =
1.0982 DEFINITELY WRONG (1.0953 at 0.3/0.7; the "lands near
the sequential rung" detail was off -- its E0 score 12.50M
polishes BELOW sequential's 15.36 rung; medium regret held);
E2b-fanout = 1.0181 = BAND-EDGE (exceeds 1.01804 by 8e-5) and
FAILS the weight-robustness clause (1.0035 at 0.3/0.7, inside
the band) -- FINAL VERDICT: NOT claimed wrong; the pre-written
symmetric prediction ("near-right, its condition is half the
truth") holds; the json's mechanical verdicts field is the
0.5/0.5 read and is superseded by this record (script comment
added). WEIGHT-SENSITIVITY LINE: at mu = {0.3, 0.7} the three
defective-arm verdicts HOLD (1.7054 / 1.0926 / 1.0953, all
beyond the band; E0' re-optimization gains only 0.31% over the
re-scored 0.5/0.5 argmin) -- no conclusion rides on the
weights, except E2b's band-edge as designed. BENIGN-LOAD CONTROL LEG
(chain one-hot) [TERMINOLOGY FIXED at the day-12 review: this
leg is NOT a "safe cell" -- that term stays reserved for MASKED
cells where every seating ties (the within-die g = 2.0 kind);
under the chain load seatings still matter (E2b wrong 13.5%,
E3 38.5%), the load is merely benign; conflating the two would
turn our own data against the "no crossing along the bandwidth
axis" sentence in section 5]: E1_chain 1.0096 inside the band
(ties, as pre-written); E2-chain == truth by definition; E2b
deceived there, 1.1346 (the symmetric one-hot roles land);
E3_chain = 1.3846 -- EXPECTATION FLIP booked as FINDING F-S6a:
THE WEAVE ARM IS WRONG EVEN UNDER THE BENIGN LOAD. The pre-registration
assumed ring's chain optimum resembles mesh's; it does not --
ring's chain optimum is ring-ADJACENCY (sequential-like, which
scores 8.47M-class on the mesh chain = 1.38x) while mesh's
chain optimum is the rectangle family: "compact is
weave-relative" bites even in the benign-load cell. The flip
STRENGTHENS paradigm-dependence (E3 wrong in both cells) while
flipping the all-ties control expectation for that one arm.
SECTION 5'S THREE PIECES ARE ASSEMBLED AND DISJOINT:
condition-bound (the load axis), paradigm-dependence (the
weave axis + both E3 cells), rank inversion proper (E1 vs E0,
now measured at ARGMIN level, not just rung level). The 5x5
matrix reads as designed: diagonal 1.00 everywhere, the E1 row
the core exhibit (self 1.00 / truth 1.59 / judge-E2b 1.85).
S6 CLOSES (C64-f DONE, days 11-12) => THE SEARCH MILESTONE
(worklist step 7) CLOSES: S1 evaluator frozen + triple anchors;
S2 registry + faithfulness gate + ladder v0 + seed pool; S3 SA
body + ergodicity page + two instances; S4 DP + linkage + three
exhibits + both dues; S6 five arms + matrix + controls; S5
retired with the collaborator. Hash-pinned artifacts:
ladder_v0.json d41b4ecf..., search_ordering.json 3da4291...,
search_withindie.json f10a22bf..., search_linkage.json
c984708b..., search_s6.json 596fa099....
Suite across the milestone: 385 -> 424, zero expected-fail. DAY-12 REVIEW ROUND (two items; the operational item passed as
noted): (1) TERMINOLOGY FIXED across the records, both SUMMARYs,
MATERIALS and the script -- the chain one-hot leg is the
BENIGN-LOAD CONTROL LEG, never a "safe cell": that term stays
reserved for MASKED cells where every seating ties (the
within-die g = 2.0 kind); on the chain leg seatings still
matter (E2b 13.5%, E3 38.5% there), the load is merely benign;
conflating the two would let our own data bite section 5's "no
crossing along the bandwidth axis" sentence. F-S6a rephrased
accordingly ("the weave arm is wrong even under the benign
load"). (2) E2b's JUDGEMENT BASIS UPGRADED, one supplementary
run (deterministic, reproduces day-12's E0 arm bit for bit --
11.3824M from the random start): the review is right that the
S3 1.8% band was measured on the PURE FAN-OUT target; the
correct scale for a mix-target verdict is E0's OWN seven-start
scatter = 11.3824-11.6176M = a 2.067% BAND. E2b's 1.0181 falls
INSIDE it -- the "not claimed wrong" verdict now stands
DIRECTLY on the primary band criterion, with the
weight-robustness clause (1.0035 at 0.3/0.7) as reinforcement
rather than the sole decider. The other three verdicts (7.2 /
9.8 / 58.9%) clear the wider band unchanged. The script now
computes and stores E0's own band on every regeneration
(per_start_best kept in the json). Commit/push per the user's
instruction NOW -- pushed at 6ebc158. TEX ROUND 2026-09-15 (user-ordered; the local
phase_diagram_report.tex only, per the standing re-scoping): the
report is restructured to Progress Report (4) -- the diagram half
kept, the narrative extended with two new sections ("Searching
the band": evaluator-on-frozen-accounts + the seven-heuristic
ladder + the caliber split (seating moves energy 8%, latency
ppm) + open-vs-closed band verdicts (11% below the best
heuristic under cross-traffic; exhaustive-optimum exactness and
the interleaving reading on the reopened on-die space; the
uniform-cutting degeneracy and the constrained staircase); "The
objective is the hard part": the three failure modes
(invert/mask/redefine) + the five-arm referee reading with the
59/7/10-and-38 percent verdicts, the near-optimal fan-out arm,
and the bus paradigm degeneration). Five figures added
(ladder_v0, search_ordering, condition_axes, weave_inversion,
search_s6); abstract, claims list, band section, Simba
next-steps line, limitations and conclusion stitched
accordingly. Report red-lines held: no internal numbering, no
test or correction history, qualitative conclusions carry the
prose. Static checks: environments paired, all refs resolve,
all 11 figures present, brace-balanced (no local latex
toolchain; compile is the user's side). 2.7B HAND-OFF ACCOUNTING REVIEW, 2026-09-15 -- VERDICT
REVERSED, THE AGENT'S PRIOR "NON-GAP" RULING WITHDRAWN. The prior
reply argued "batch-1 = one hand-off in flight = no contention =
words/bw exact". That holds for 355M (one stage one die, one flow
per hand-off) and FAILS for 2.7B: a 2.7B hand-off is many
concurrent flows (every producer die -> every consumer die at
once, the E4 mechanism's own wording) sharing the declared mesh;
batch-1 serialises LAYERS, not the flows inside a hand-off. The
old `seg_bnd_s += words/wps` collapsed a whole hand-off into one
stream over one link -- inconsistent with the weave declaration
(mlx300_multidie576.yaml: die<->die mesh, xy, centre hub) and
with the energy channel, which already routes every flow. IT WAS
A 2.7B BACKEND GAP. FIXED (no rerun yet -- reporting stops for
acceptance per the notes): search_eval.busiest_link_words --
every flow of a boundary routed on the declared weave
(die_ic.path_directed), volume x width accumulated per (link,
direction) exactly as link_occupancy's node-flow branch, busiest
link / rate = the hand-off time; wired into boundaries() and
ScoreSession.update (incremental == full pins still green) and
into _assemble for BOTH calibers. PINS (group 49 +4, suite 424
-> 428, all green first run): hand example without sharing (two
producers on one column, consumer between: busiest = V/2 =
half the total); hand example with sharing (two producers on
one row feeding along it: both pieces stack on the last links,
busiest = V = total); SINGLE-FLOW DEGENERATION exact (one die ->
one die: busiest == words, three geometries); ACCUMULATOR ==
link_occupancy bottleneck volume on real 2.7B boundary flows
(nominal-bandwidth fabric, 1e-12). ANCHOR #1 RE-ESTABLISHED AS A
RELATION: energy / words / surplus / propagation reproduce
a4_full_model.json exactly as before; stored latency - new
latency == sum over the 159 boundaries of (total - busiest) /
rate at every one of the four bandwidth anchors (1e-9), and the
difference is non-negative (the old term WAS the bound).
NEW-VS-OLD AT THE ANCHOR POINTS (A4 seating, prefill, single
caliber): busiest-link words summed 1308.6M vs total 1420.8M
(ratio 0.921; per-boundary total/busiest from 1.000 at
attention@L0 to 2.000 at the ffn2 -> qkv layer boundaries);
whole-machine latency 12.5 GB/s 1034.81 -> 1025.83 ms (-0.87%),
2.0 GB/s 1631.55 -> 1575.42 (-3.4%), 0.4 GB/s 4473.19 ->
4192.54 (-6.3%), 0.1 GB/s 15129.35 -> 14006.72 (-7.4%);
hand-off share of the whole-machine serial time 10.98% -> 10.20%
at GRS, 79.4% -> 78.0% at 0.4 GB/s. SECOND GAP SURFACED BY THE
ANCHOR ARITHMETIC (filed, NOT acted on -- awaiting ruling): the
day-9 DP ORACLE OMITS THE INTRA-LAYER HAND-OFFS. Its segment
cost is m x layer_serial_s (no D2D at all) + ONE inter-layer fee,
while the evaluator's pipe caliber sums every boundary in the
segment -- the four intra-layer hand-offs per layer carry 88% of
the D2D words (1258M of 1421M; ~3.15 ms per layer at GRS).
Evidence in the record: ladder v0's T_pipe = 32.35 ms (the
evaluator) vs the DP's k = 32 interval 29.20 ms -- the gap IS the
intra-layer term. Consequences: the "fee share 1.44%" was one
inter-layer fee against an understated stage, not the hand-off
share (10.98% of the whole); balanced-cut optimality is
unaffected (a per-layer constant); interval VALUES and the
constrained exhibit are affected -- at B = 120 ms an eight-stage
pipeline's true interval is ~128 ms, infeasible, so k* likely
moves 8 -> 11. Goes into the rerun list as item 4's first half.
RERUN PRE-REGISTRATION (written now, RUNS WAIT FOR ACCEPTANCE;
every item reports old vs new + delta): expectations -- the 2.7B
latency ladder OPENS in the weak-D2D and active cells (seat
dependence enters through the per-boundary total/busiest ratio,
1.0-2.0; bracket: T spread at GRS of order 1%, several % at
0.4 GB/s -- two-handed, flips booked), the safe cell stays flat;
the energy column does not move; 355M readings do not move
(single-flow degeneration pinned). Items: (1) A4 whole-machine
column, prefill/decode x four bandwidth anchors x three device
tiers, hand-off share old/new, and re-estimates of the 9.3x /
1.11x fast-edge readings and the C39 numbers; (2) ladder v0's
2.7B part -- seven baselines x three cells, T and E columns
re-issued; F-L1 / F-L2 re-judged under the new numbers (the
originals marked SUPERSEDED, kept); [AMENDED 9]'s seating-
instance objective re-decided on the new column split; (3) the
S4 seating instance rerun under the re-decided objective, EX1
(with the DP oracle repaired to take segment costs from the
evaluator's boundaries, intra + inter, busiest-link) / EX2 /
EX3 re-issued -- the weave exhibit's latency side becomes
meaningful; (4) the DP oracle repair + fee backfill: segment
costs and hand-off fees from the evaluator's actual busiest-link
times at the SA-found seating, the "no cut change, < 1%"
standard re-judged; (5) ergodicity page and documents: every
SUMMARY / MATERIALS / tex sentence that reads "2.7B seating
latency flat" or "seating moves only energy 8%" rewritten or
withdrawn per the new numbers; (6) NOT rerun: 355M S3 / S6
results (backend unchanged, single-flow degeneration pinned),
the within-die A3 instance. Also seated as follow-ups, not
done: schedule_slack now applies to the 2.7B term by O26
semantics (default 1.0, no number moves); pipe-caliber
cross-segment concurrency stays a separate open question.
REPORTING STOPS HERE for acceptance of the definition, the
degeneration pin and the re-established anchor. ACCEPTED 2026-09-15 (AGENT_notes_r3r4_v4, section D): D.1
delivered and accepted; D.2 RULED -- the DP cost table's per-layer
time is DEFINED as the evaluator's layer time under the current
seating (intra-layer hand-offs included, new accounting), starting
from the A4 default seating and, inside the fee-backfill loop,
re-run once more on the SA-found seating; cut-fee share and D2D
total share are reported SEPARATELY with their denominators
named; D.3 rerun list RELEASED. D.4 PRE-REGISTRATION, the two
lines the notes add (written before any rerun number): (a)
seatings that SPREAD their flows have a busiest/total ratio
clearly below the default seating's 0.921; (b) the INTRA-LAYER
hand-offs (88% of D2D words) are the seat-sensitive main channel
-- the inter-layer cut fee is not. Standing lines: the 2.7B
latency ladder opens in the weak-D2D and active cells, the safe
cell stays flat; the energy column does not move; 355M readings
do not move. D.3 ITEM 2 DONE (ladder v0's 2.7B part re-issued under the
busiest-link term; scripts/ladder_v0.py gains the busiest/total
column and its figure switches to percent with the ratio panel;
analysis/ladder_v0.json regenerated, sha256 now 7e4a662affed413b
3db5715f50078fbb3d319ce6a7cf072397cb5fb014f3bbea -- the explained
regeneration; the prior d41b4ecf... readings SUPERSEDED, kept in
this record). NEW T LADDER, safe cell (GRS, ms): random 960.62 <
least_manhattan 960.64 < nmap_greedy 962.14 < heaviest_first
968.80 < clustered 973.26 < snake 1023.07 < sequential 1025.83 --
spread 6.79% (was 0.007%); weak-D2D cell 1.947x (random 2153 vs
sequential 4193); fast-device 1.260x; T_pipe now seat-dependent
(30.33..32.35 ms; was bit-identical). BUSIEST/TOTAL per seating:
random 0.3468, lm 0.3476, nmap 0.3608, heaviest 0.4191, clustered
0.4587, snake 0.8968, sequential 0.9210 -- D.4 line (a) LANDS and
the T ladder is ORDERED by this ratio (index fills stack every
flow of a hand-off on the same few links; dispersal spreads them).
E column unchanged (8.008%); 355M rows bit-identical. PRE-
REGISTRATION READ-OUT: "opens in weak/active cells" LANDS; "safe
cell stays flat" FLIPS -- FINDING F-L5: at the measured tier with
GRS links the seating lever on whole-model latency is 6.8%, not
ppm (a 10% hand-off share moved 2.6x by the ratio). E3/E4 RE-
JUDGED: F-L1 and F-L2 SUPERSEDED (both columns move; the T spread
widens 1.95x at weak D2D -- the original E4 expectation lands
under the corrected accounting; E3's 8.0% energy flip unchanged).
The energy-best (clustered) and latency-best (random) seatings
DIFFER; "latency-optimal seating costs below one-thousandth in
energy" RETIRED (random is 8.0% above clustered). [AMENDED 9] RE-
DECIDED per the notes' delegation: [AMENDED 15] returns the
seating instance to main objective T, energy tie-break.
D.3 ITEM 1 DONE (scripts/rerun_a4_column.py ->
analysis/a4_column_v2.json, sha256 b3b35b56212522bfce56e9c24b29
94ad9918f951806971c4ee36ac0c8afd4506): prefill and decode x four
bandwidth anchors x four device tiers, the old latency recovered
through the pinned relation. PREFILL new vs old (ms): NeuRRAM
12.5 GB/s 1025.83 vs 1034.81 (-0.87%), 2.0 1575.42 vs 1631.55
(-3.44%), 0.4 4192.54 vs 4473.19 (-6.27%), 0.1 14006.72 vs
15129.35 (-7.42%); HERMES-GRS 247.04 vs 256.02 (-3.51%); the
delta grows with the hand-off share and saturates near 7.8%
(default seating busiest/total 0.921). DECODE 0.07% (GRS) ..
4.4% (0.1 GB/s). THE TWO SHARES, denominators named: D2D TOTAL
(all 159 hand-offs / whole serial latency) 10.20% at NeuRRAM-GRS,
41.5% / 78.0% / 93.4% at 2.0 / 0.4 / 0.1 GB/s, HERMES-GRS 42.4%;
INTER-LAYER hand-offs (31 layer boundaries / whole) 1.15% at
NeuRRAM-GRS, 4.68 / 8.80 / 10.54% down the axis -- the former
"fee share 1.44%" was this quantity on a stage denominator,
superseded. 2.7B device sweep NeuRRAM -> HERMES: prefill 4.15x
(old 4.04x), decode 1.086x (unchanged). The 9.33x / 1.11x FAST-
EDGE READINGS AND C39 are 355M whole-stack figures (826.43 ms;
one die per unit, one flow per hand-off) -- untouched BY
CONSTRUCTION, the single-flow degeneration pin the guarantee.
THIRD MISMATCH SURFACED BY APPLYING D.2 (fixed the same day by
D.2's own principle -- costs from the evaluator; the user may
overrule): the first D.2 table kept the DP's "hand-off fee at
cut points only" and read 1013.99 ms at k = 1 (single) vs the
evaluator's 1025.83 -- the 11.84 ms gap is the 31 inter-layer
hand-offs paid INSIDE segments, which the evaluator charges to the
receiving layer whether or not a cut sits there (cutting is free:
one mesh, no priced package seam; the evaluator's single caliber
is cut-blind). TABLE MADE EVALUATOR-IDENTICAL (spec [AMENDED 16]):
each layer's time folds in its entry hand-off, the cut fee is
zero, PINNED both ways (test_d3b: DP single + propagation ==
evaluator single; DP pipe interval on its own k = 2/8/32 plans ==
the evaluator's pipe interval on a Pi with those cuts, 1e-9).
Consequences: "cuts only add fees, k = 1 optimal under single"
RETIRED (single is cut-blind); EX1's decode price for cutting
(24.110 -> 24.115 ms) was an artifact -- the two-phase constraint
has NO decode cost in this model, it selects the smallest feasible
depth, and a genuine trade-off needs a PRICED package seam (open
modeling item, not fabricated); the D.2 "cut-fee share" reports
as the inter-layer share paid at every boundary and the cut-
DEPENDENT fee as zero; [AMENDED 2]'s optimism statement is moot.
D.3 ITEM 4 DONE (scripts/search_dp.py on the evaluator-identical
table, A4 seating, GRS): intra-layer hand-offs 2.097..3.146 ms per
layer, entry hand-offs 0.2097..0.4194 ms per layer; single k = 1
1025.798 ms == evaluator minus propagation; D2D total share
10.21%, inter-layer share 1.15%, cut fee 0; balanced cuts at
every k (k = 32 interval 32.3499 ms == ladder v0's T_pipe -- the
DP and the evaluator now agree); uniform-layer reference k = 8
128.22 vs standing 128.69 ms. THE D.2 LOOP (DP at the SA-found
GRS seating vs the A4 default, scripts/search_linkage.py): cut
DECISIONS unchanged at every k in {2,4,8,16,32} (balanced holds)
while the bottleneck VALUE moves 6.9..7.3% (hand-off total
104.68 -> 32.94 ms) -> the pre-registered "no cut change AND
< 1%" standard FAILS on its value half: the table is seat-
dependent in value, not in decision -- the DP must be run at the
deployed seating (DP -> SA -> DP is required, not optional).
EX1 RE-ISSUED: B = 120 ms -> k* = 11 (sizes [2,3,3,...]; T_prefill
97.05 ms; old k* = 8 at 115.56 under the superseded table, as
predicted 8 -> 11); T_decode 24.314 ms at EVERY depth; feasibility
staircase (B at which the smallest feasible depth steps): 1025.75
-> k2, 513.25 -> 3, 352.75 -> 4, 257.0 -> 5, 224.25 -> 6, 192.0 ->
7, 160.25 -> 8, 128.5 -> 9, 128.25 -> 10, 127.5 -> 11, 96.5 -> 12.
EX3 RE-ISSUED: seam-bound (16 x 2) 64.6999 ms == free k = 16
64.6999 (delta 0) under the seat-dependent table too.
D.3 ITEM 3 DONE (analysis/search_linkage.json regenerated, sha256
989058b564078cdba7c00cf3273670a28bbad8a45667381ed316957c395154d4;
objective T per [AMENDED 15]; seeds clustered/snake/random,
Schedule(t0 2 ms @GRS / 20 ms @0.4, alpha 0.996, 1200 steps)):
GRS -- best T 954.136 ms (random start; all three starts end
954.14..954.77, within 0.07%), vs best named random 960.62 ->
regret 0.9932 (0.7% below: the dispersed fill is already near the
latency optimum at the measured tier; busiest/total 0.2898; the
T-best seating's E 2.517 J, 7.7% above the E-best). WEAK 0.4
GB/s -- best T 1908.50 ms (random start; starts 1908.5..1921.3),
vs best named 2153.11 -> regret 0.8864, 11.4% BELOW the best
heuristic: substantive where the hand-off share is large (78%).
EX2 (T objective, GRS): torus 948.71 ms (E 2.632), mesh 954.14
(E 2.517), ring 962.32 (E 6.291) -- latency within +-1% across
weaves, energy diverging up to 2.5x: at the measured link tier
the weave decides energy, not latency (the energy-column findings
F-L3/F-L4 stand unchanged). Pre-registered "ladder opens in weak
cell, search margin there" LANDS (11.4%); GRS margin small (0.7%)
-- reading, not flip (no bar was set). D.3 ITEM 5 (documents):
SUMMARY en/zh passages rewritten in place + a revision paragraph;
the tex's search sections rewritten (seating-through-link-sharing,
the depth/feasibility framing, the unpriced seam named); MATERIALS
carried no stale statement. D.3 ITEM 6: 355M S3/S6 and the
within-die instance not rerun (single-flow degeneration pinned).
Suite 428 -> 429 (test_d3b split into the DP == evaluator identity pins). D.3 CLOSED pending the user's acceptance. USER RULINGS 2026-09-15 (post-D.3): the package handling
(evaluator-identical table, zero cut fee, priced seam as an open
item) ACCEPTED as proposed; the tex edits made in the D.3 item-5
doc sync were UNAUTHORISED (tex moves only when named) and are
REVERTED to the ordered round's state -- the stale tex passages
(seating-by-ppm claim, the decode-price staircase) are REPORTED,
not edited, until the user names the tex again. BAND-ENERGY
EXPERIMENT, PRE-REGISTERED (the reviewer's cheap question, to be
answered before any writing decision; the 7.7% claim itself is
NOT revised now): among seatings inside the LATENCY CONVERGENCE
BAND (T <= 1.018 x the T-optimum of the cell; 1.8% = the S3
multi-start band) find the energy minimum; report its energy
relative to the energy-optimum seating (clustered, 2.3379 J) and
the geometry of the two optima. METHOD: rejection-mode SA (spec
section 6 semantics, no penalty) minimising E with feasibility
T <= cap, evaluated on one ScoreSession pass per proposal; seed =
the cell's T-best seating (in band by definition; the E-best
clustered is OUTSIDE the band at GRS: 973.26 > 971.31 ms cap, so
it cannot seed); three RNG seeds (0/1/2), Schedule(t0 = 0.005 J,
alpha 0.996, 1500 steps); cells GRS and 0.4 GB/s. READ-OUT: E of
the band minimum vs E-best; geometry as busiest/total (link
stacking), distance surplus energy, mean max hops, for the
T-best, the E-best and the band minimum. TWO HANDS: (a) a
near-zero-cost seating exists in the band (E within ~1% of the
E-best) -> the prior "latency-optimal choice costs below
one-thousandth in energy" conclusion survives with a LEVEL
qualifier (on-die and 355M); (b) the band minimum stays several
percent above -> the package level is a REAL latency-energy
trade-off point. Magnitude prior: dispersion (low stacking) and
compactness (short distance) pull opposite ways at the die level
-- a partial trade, order 3-4% residual, is the guess; the reading decides. B6's 2.7B row (arm one) is filled alongside. ADDENDUM before the second number: the first
pass (dispersed-side seed only) showed the GRS band constraint NEVER
binding (0 infeasible rejections; band min +6.17% is a budget
reading) while the energy-optimum seating misses the GRS cap by
0.2% (973.26 vs 971.31 ms) -- an existence question needs a seed
from the COMPACT side too: the E-best (clustered) seating polished
INTO the band by greedy T descent (t0 = 0, up to 600 steps; the
polished seating must be feasible or the seed is reported as
unreachable), then band-constrained E minimisation from it under
the same schedule and three RNG seeds; both seeds' band minima reported, the lower one is the reading. BAND-ENERGY RESULTS (scripts/band_energy.py ->
analysis/band_energy.json): GRS cell (cap 971.31 ms = 1.018 x
954.14): the E-best seating (clustered, 2.3379 J) is OUT of the
band by 0.2%; the T-best seating (954.14 ms) costs 2.5170 J =
+7.66%; from the DISPERSED side the band E-minimisation reaches
2.4822 J (+6.17%, constraint never binding -- a budget reading);
from the COMPACT side the greedy T descent that brings clustered
INTO the band (973.26 -> 957.74 ms, -1.6%) already costs +4.32%
in energy (2.4390 J) and the band-constrained E minimisation from
there finds nothing lower (three seeds identical) -> BAND MINIMUM
FOUND = +4.32% (an upper bound on the true band minimum; both
sides searched, neither found lower). WEAK cell (0.4 GB/s, cap
1942.85 ms): the compact-side seed is UNREACHABLE (600 greedy
T-descent steps end at 2064 ms, still 6% out of band -- the
compact geometry cannot be polished into the weak-cell band);
dispersed-side band minimum 2.4951 J = +6.72% with the constraint
BINDING (816-876 infeasible rejections per seed). VERDICT under
the pre-registered hands: hand (b) at BOTH cells -- the 544-die
package level is a REAL latency-energy trade-off point: no
seating inside the latency band comes within ~1% of the energy
optimum; the residual is >= 4.3% at GRS (found) and 6.7% at weak
links. The prior "latency-optimal choice costs below
one-thousandth in energy" therefore holds ONLY with a level
qualifier (on-die and the 355M unit chain); it does NOT extend to
the package level. Magnitude prior (3-4%) landed at GRS. GEOMETRY
of the optima (GRS): T-best = dispersed -- busiest/total 0.290,
mean max hops 25.7, distance surplus 0.206 J; E-best = compact
rectangles -- 0.459 / 4.4 hops / 0.027 J; the band minimum is an
intermediate geometry -- 0.322 / 18.3 hops / 0.128 J. MECHANISM
(structural, not a search artifact): un-stacking a hand-off's
flows requires spreading its consumer set across the mesh, which
lengthens every path, and the energy column prices path length
-- dispersion (latency) and compactness (energy) pull on the same
seating in opposite directions; the two optima cannot coincide
at this level. HOW TO WRITE IT is the user's call after this
reading (no claim changed now; the tex untouched). B6 ARM ONE,
the 2.7B ROW (fixed gamma, search alpha/beta; reference = the
best NAMED T seating, random -- a heuristic reference, unlike the
within-die row's exhaustive optimum, kept apart): GRS -0.7%
(954.14 vs 960.62 ms), weak D2D -11.4% (1908.5 vs 2153.1 ms);
the energy-column row of the same instance is retired with [AMENDED 15]. BAND SWEEP, pre-registered (the reviewer's cheap
reinforcement; same machinery, one number becomes a curve): repeat
the band-energy minimisation at band widths 1.8% / 3.6% / 7.2% per
cell, both seed sides, three RNG seeds each; the read-out is the
TRADE-OFF FRONT "how much latency bought back how much energy"
(band width -> band-minimum E relative to the E-best, plus the
band minimum's T and geometry). PRE-WRITTEN: the front is
monotone non-increasing in band width by construction (a wider
band contains the narrower one -- a violation is a search-quality
finding, not a space finding); the (b) verdict STRENGTHENS if the
whole front stays above +4% (the trade is expensive at every
width examined) and WEAKENS toward (a) if the 7.2% point comes
within ~1% of the E-best (the cost is merely the narrow band).
At GRS the E-best seating enters the feasible set once the band
exceeds 2.0% (973.26 vs 954.14 ms), so the GRS front is EXPECTED
to hit exactly 0% at 3.6% and 7.2% -- declared in advance, it is
arithmetic, not a finding; the informative front is the WEAK cell, where the E-best sits 33.6% above the T-optimum and no tested width contains it. SWEEP RESULTS (band_energy.json regenerated, sha256
a62f220c264a3543f968d2d86d078b1f03209eb619d7b8b9f1af53a678936eb4;
the +4.32% / +6.72% single-band numbers above stand unchanged at
1.8%). SEARCH-QUALITY FINDING FIRST, caught by the sweep's own
pre-registered guard: the first sweep pass reported +4.32% at the
3.6% and 7.2% GRS bands -- bands that already CONTAIN the E-best
seating (973.26 ms <= 988.48 ms cap), whose energy is 0% by
definition. The SA, seeded only from the dispersed and the
polished-compact sides, never reached the clustered basin. FIX:
the known feasible point is seeded whenever it is in band, and a
second assertion now guards it (E-best feasible => band minimum
<= E-best, else a search-quality finding). No space claim rested
on the bad pass; the 1.8% readings (both cells) are unaffected
because the E-best is out of band there. THE FRONT, latency paid
(vs the cell's T-optimum) -> energy still above the E-best:
GRS 1.8% -> 0.38% paid, +4.32%; 3.6% -> 2.00% paid, 0.00%; 7.2%
-> 2.00% paid, 0.00% (the arithmetic point declared in advance:
once the band admits the E-best seating the front is exactly 0 and
pays only the 2.00% that seating costs in latency). WEAK cell
1.8% -> 1.49% paid, +6.72%; 3.6% -> 3.50% paid, +6.62%; 7.2% ->
6.49% paid, +6.29% -- monotone, and FLAT: paying 6.5% of latency
buys back 1.4 energy points of the 7.7 the T-optimum costs. VERDICT
STRENGTHENED, with the shape now visible: the whole weak-cell front
stays above +6.2% at every width examined, so the latency-energy
trade at the package level is not merely a narrow-band artifact --
it is expensive across the range (hand (b), per the pre-written
criterion "the whole front stays above +4%"). The GRS cell reads
differently and honestly: there the two optima are only 2.0% apart
in latency, so a deployment willing to give up 2% of latency gets
the energy optimum outright -- the trade is real but cheap at the
measured link tier, and expensive where hand-offs dominate. The
shape is the reviewer's point: one number said "no seating in the band is energy-cheap"; the curve says "at GRS the band just has to be 2% wide, at weak links no width in range suffices". A-GROUP OPENED 2026-09-15 (AGENT_notes_r3r4_v4 section A; D.3
closed, so the die-level halves run too). PRE-REGISTRATION, all
four items before any number. A4 NAMING REGISTRY (no run): one
file, analysis/METRICS.md, one row per published quantity with
its DENOMINATOR and instance-semantics label -- the two the notes
name (bandwidth-equivalent envelope ratio 1.4-2x, denominator =
the bandwidth needed to hold the operating point; ordering
latency spread 6.55x/12.26x/3.57x, denominator = that weave's
best ordering latency, adversarial configurations marked), the
four S-series ones (regret ratio; E0 regret %; band_ratio =
exhaustive worst / best; noise band = multi-start convergence
scatter), the two the hand-off review added (cut-fee share vs
D2D total share, different denominators, never mixed), and the
band-sweep pair (latency paid / energy bought). The old ordering
triple stays NAMED APART from the new weave energy spread. A2
ENVELOPE QUANTIFIER (no run): every published placement number
carries certified or observed -- certified = exhaustive over the
declared space (the within-die A3 instance: 280/70 seatings,
band 1.51x/2.00x, safe cell all-tie), observed = multi-start SA
with the evaluation set listed (7 named seatings + the SA seed
set + adversarial configurations). Ruling recorded: the main
proof exhibit is the S6 cross-scoring matrix (observed); the
exhaustive instance is the certified ENVELOPE exhibit; the
2.7B seating latency column's SUPERSEDED-PENDING mark LIFTS
(D.3 re-issued it). A3 LOW-BANDWIDTH ANCHORS: add 0.1 and 0.2
GB/s to the soft-lever anchor set and read the within-die lever's
three-stage staircase (flat above the knee -> opening ->
saturating). EXPECTATION, pre-written: as bandwidth falls the
whole-stack ratio approaches the MECHANISM ratio (3.00 attn /
2.67 ffn, the C49-b readings) because serialisation swallows
every fixed term; the plateau is therefore ~2.7-3.0x, and a
plateau materially above the mechanism ratio would be a finding.
A1 CERTIFIED THREE REGIONS: per phase-diagram cell classify with
the BRACKET's two rails -- certified compute-dominant when even
the pessimistic communication rail sits below compute, certified
communication-bound when even the optimistic rail sits above it,
uncertain between. DECLARED IN ADVANCE: on production
(packet-free) weaves the two rails coincide (Delta == 1.00 by
construction), so the uncertain band has width ZERO and every
production cell classifies outright; a middle band exists only on
packet-declared (Simba-class) fabrics. The deliverable is the region-semantics data layer for the phase diagram's figure, on the 2.7B payload with the corrected hand-off term, across the four device tiers x the bandwidth anchor set. A-GROUP RESULTS 2026-09-15, all four items done. A4 DONE:
analysis/METRICS.md -- the registry, one row per published ratio
with denominator, instance semantics and quantifier; the ordering
latency spread and the new weave ENERGY spread are named apart as
required; the hand-off section keeps the three shares separate
(D2D total / inter-layer / cut-dependent) with the busiest-over-
total geometry row; the band-sweep pair (latency paid / energy
bought) is registered. A2 DONE (no reruns, so every pinned hash
stands): the registry carries the certified/observed column and
every generator now stamps `quantifier` + `evaluation_set` into
its own output for future runs (search_withindie certified;
ladder_v0 / search_ordering / search_s6 / search_linkage /
band_energy observed with their evaluation sets; certified_regions
certified, closed-form). The exhibit ruling is recorded in the
registry: main proof exhibit = the S6 matrix (observed), the
exhaustive within-die instance = the certified envelope exhibit.
The 2.7B seating latency column's SUPERSEDED-PENDING mark is
LIFTED (D.3 re-issued it). A3 DONE (scripts/analyze_soft_lever.py
with 0.1 / 0.2 GB/s added; analysis/soft_lever.json regenerated,
stack-reproduction self-check 0.0e+00 as before): the three-stage
staircase is now visible on both levers. A2-lever (synthetic,
uniform mapping) prefill: 1.0000 (>= 2.0 GB/s, flat) -> 1.6093
(0.4) -> 1.7199 (0.2) -> 1.7347 (0.1) against its mechanism ratio
1.750 -- the pre-written "plateau tends to q_max/q_min" LANDS,
within 0.9% at 0.1 GB/s. A3-lever (the realizable co-residency
one) prefill: 1.0000 -> 1.4341 -> 1.6220 -> 1.6979 against its
mechanism ratios 3.00 (attn) / 2.67 (ffn) -- the expectation
FLIPS, booked as FINDING F-A3: the realizable lever does NOT
approach its mechanism ratio inside the analog band (1.70 of
2.67-3.00 at 0.1 GB/s, ~60% of the way). MECHANISM, structural:
the stack ratio is (fixed + worst)/(fixed + best) where `fixed`
is every operator the lever cannot move; as bandwidth falls the
fixed part saturates too, so the asymptote is the mechanism ratio
ONLY when the lever moves essentially the whole stack. The A2
stressor sweeps every lever op (fixed share 21.4% at 0.1 GB/s
and falling), so it approaches its ratio; the A3 lever moves four
projection ops on two dies while attention, the elementwise terms
and the other dies stay put, so its plateau is strictly below.
The honest form of the claim: q_max/q_min is the lever's
CEILING, approached only in proportion to the share of the stack
the lever commands. Decode staircases, for the record: A2 1.2669
/ 1.1624 / 1.0843, A3 1.2294 / 1.1283 / 1.0570 at 0.1 / 0.2 /
0.4 -- the write wall dilutes both, as standing. A1 DONE
(scripts/certified_regions.py -> analysis/certified_regions.json):
48 production cells (2 phases x 4 device tiers x 6 bandwidths),
ZERO uncertain, widest rail gap exactly 0.000e+00 s -- the
declared zero-width band on packet-free weaves CONFIRMED as
arithmetic, not discovered. Prefill: NeuRRAM is
communication-bound at <= 0.4 GB/s and compute-dominant from 2.0
up; the boundary walks right with device speed (Mythic flips
between 2.0 and 8.0, ISAAC likewise, HERMES only above 8.0) --
the diagram's slope-(-1) story in certified form. Decode: every
tier is compute-dominant from 0.2 GB/s up and communication-bound
only at 0.1 (ratios 1.06-1.15) -- the decode stack's fixed terms
own it. THE MIDDLE BAND EXISTS AND IS DEMONSTRATED: the same
payload on a packet-DECLARED weave (32 B payload) reads
certified communication-bound at 0.1-0.4 GB/s and UNCERTAIN at
2.0 / 8.0 / 12.5 (comm 104.7 .. 10498.7 ms straddling compute
921.1 ms at GRS) -- the three-band classification has a middle band exactly where the paradigm declares packets, and nowhere else. TWO PINS BROKE ON THE A3 EXTENSION and were repaired,
recorded rather than quietly fixed: test_anchored_stack_cells and
test_a3_natural_coresidency_reopens_the_space addressed the anchor
list BY POSITION (cells[0] meant 0.4 GB/s), so prepending 0.1 / 0.2
mis-indexed them. No pinned number was wrong: both are re-addressed
BY VALUE (a _by_g helper), every standing reading re-asserted at its
own anchor (A2 1.6093 / A3 1.4341 prefill, 1.0843 / 1.0570 decode,
fixed share 0.762 / 0.967, unity above the knee), and the extension
gets its own pin -- test_low_anchor_staircase_and_plateau fixes the
new rows (A2 1.7199 / 1.7347, A3 1.6220 / 1.6979, decode A3 1.2294)
AND the F-A3 statement itself (A2 reaches >99% of its 1.750
mechanism ratio; A3 stays below 70% of its 2.67). Lesson filed: an
anchor set that can grow must be addressed by value in its pins.
Suite 429 -> 430 (the two repaired plus the new one). ARTIFACT
HASHES after the A group: soft_lever.json
046ae8153c1cd3e55452fbb43e3e719e906598d09231820dea5bb7c7ef0f6fe7
(regenerated with the 6-anchor set; the within-die fold identity
re-verified against the extended rows, still exact), 
certified_regions.json
bf9f07fdc0287ba0a659653fb562033357e4f526b42b825f5a221153539eb6fb,
band_energy.json
a62f220c264a3543f968d2d86d078b1f03209eb619d7b8b9f1af53a678936eb4.
A GROUP CLOSED. Per the notes' execution order the remaining items
are B5's joint-exact sub-item, B6 arm three (needs B5), and B7 (the BookSim re-ranking, whose 355M half can run now and whose package-layer probe the hand-off revision makes newly meaningful). ORDER RULED 2026-09-15 (the reviewer proposed B7 before
B5/B6-arm-3; accepted, reason on file): the corrected hand-off term
now carries the 2.7B ladder, the band front and A1's die-level
regions, and has had NO external adjudication -- B7's package-layer
probe is exactly the instrument for it, so it goes first and both
halves run together. B7 PRE-REGISTRATION (before any run). SCOPE
DECLARED, with its limitation stated rather than discovered: the S6
cross-traffic instance is NOT BookSim-tractable (82 stage pairs x
17x17 unicasts x ~460 packets = 1e7 packets), so B7 runs on a SMALL
PACKAGE INSTANCE -- the bridge's own 6x6 = 36-die mesh, the same
grid, routing (XY/dor) and hop caliber the step-4 pre-registration
fixed -- and the readings are about the TERM and the RANKING it
induces, not about the 576-die numbers themselves. The bridge is
parameterised on k for this (default 6 unchanged; every step-4 pin
re-run). HALF A, the term's external adjudication: 2.7B-style
hand-offs on the 36-die package -- a producer set of P dies R-split
sending V words to a consumer set of C dies (every producer to
every consumer, the frozen convention) -- across declared
geometries (compact adjacent blocks, dispersed, and the stacked
worst case), each scored three ways: (i) our busiest-link term,
(ii) the bridge's own flit-caliber channel/injection bound, (iii)
BookSim's measured batch completion. GATE FIRST: (i) and (ii) must
agree exactly after unit conversion -- both are the same
busiest-resource accounting, so a mismatch is an implementation
bug, not a finding. EXPECTATIONS, two-handed: our term is an
OCCUPANCY BOUND, so BookSim must land AT or ABOVE it (a completion
below the bound would falsify the accounting and is the falsifier
this probe exists to offer); the gap is queueing + the bridge's
known interface constant, and the pre-written bracket is 1.0x-1.5x
with the stacked geometry tightest (its busiest link is genuinely
serialised) and the dispersed geometry loosest (many links share
the load, so routing and arbitration have more room). HALF B, the
ranking: several seatings of a scaled-down cross-traffic load on
the same 36-die package, ranked by our term and by BookSim
completion; report Spearman rank correlation, top-1 and top-3
overlap, and the selected-solution regret (what BookSim says about
the seating our term picks). MINIMUM BAR, pre-registered: our
term's best seating must not be BookSim-worse than our term's
worst (no full inversion), and the top-1 disagreement, if any, must
cost less under BookSim than the S3 noise band (1.8%). The scale-
down (V reduced so the packet count is tractable) is DECLARED: it
preserves our rate-level ranking exactly (volume is linear) but
changes BookSim's queueing regime, so a ranking disagreement at
small V is reported as a small-V reading, never extrapolated to the
576-die instance. The 355M half needs no BookSim adjudication of
the term itself: its hand-offs are single-flow and the degeneration to words/rate is already pinned -- recorded, not skipped. B7 RESULTS 2026-09-15 (scripts/b7_handoff_probe.py ->
analysis/b7_handoff_probe.json, sha256 pinned below; the bridge
parameterised on k, default 6 unchanged, every step-4 pin green).
GATE FIRST, PASSED EXACTLY: our busiest-link term equals the
bridge's own flit-caliber channel bound on all three geometries
after packet quantisation (2176 / 816 / 2176 flits, integer
equality) -- the two accountings are literally the same
busiest-resource sum, as they had to be. HALF A, the external
verdict: BookSim lands ABOVE our term in every geometry -- compact
1.204x, stacked 1.201x, dispersed 2.376x -- so THE TERM IS NOT
FALSIFIED as a lower bound, the falsifier this probe existed to
offer did not fire. The pre-written bracket 1.0-1.5x with
"stacked tightest, dispersed loosest": the DIRECTION lands exactly
(stacked 1.201 is the tightest, dispersed the loosest) and the
MAGNITUDE BUSTS at the dispersed end (2.376 > 1.5) -- booked as
FINDING F-B7: OUR HAND-OFF TERM OMITS THE NODE'S OWN INJECTION /
EJECTION PORT. Evidence in the same row: the dispersed geometry's
busiest mesh link carries 816 flits but its busiest INJECTION
channel carries 1088 -- the binding resource is the die's own port,
not any wire, and our term counts only wires. Re-referenced
against max(channel, injection) -- the caliber the step-4
pre-registration already fixed for the bridge's own rails --
dispersed reads 1.782x, still the loosest but no longer an
outlier of the same kind; the residue is queueing plus the
bridge's per-packet interface constant, concentrated at the
endpoints because dispersion spreads the mesh load and
CONCENTRATES the endpoint load (4 producers x 4 consumers = 64
packets through one port at each end). CONSEQUENCE, scoped honestly [DIRECTION CORRECTED at the
day-15 review -- the first write-up of this paragraph said the
spreads were LOWER bounds on the truth; the arithmetic says the
opposite and the corrected reading follows]: the term stays a
valid lower bound on every single number, but its LOOSENESS IS
DISTRIBUTED BY GEOMETRY -- compact geometries are understated by
only ~1.2x, dispersed ones by 1.8-2.4x. On the 2.7B ladder the
BEST seatings are the dispersed ones (busiest/total 0.29-0.35)
and the WORST are the compact ones (0.92), so correcting lifts
the ladder's best end MORE than its worst end and the spread
SHRINKS. Arithmetic on our own numbers: at GRS the seat-invariant
part is 921.1 ms, the worst seating's hand-off term 104.7 ms and
the best's 39.4 ms, giving our 6.8%; re-priced at 1.20x (compact)
and 1.78-2.38x (dispersed) the ends become 1046 ms and 991-1015
ms -- a spread of 3.1-5.6%. At 0.4 GB/s the same correction takes
1.95x down to roughly 1.5-1.8x. SO THE PUBLISHED SPREADS WERE UPPER BOUNDS ON THE TRUE
SPREAD, not lower; the DIRECTION of the ladder is unaffected (half
B's ranking survives). TWO STANDING CONCLUSIONS WERE THEREFORE
MARKED NOT FINAL until the port was priced and the numbers re-run:
(i) the SA seating gains (GRS -0.7%, weak -11.4%) are won on
seatings MORE dispersed than random, so the true gains are SMALLER
than reported; (ii) the band experiment and its front move too --
pricing the port penalises extreme dispersion, the latency optimum
shifts toward middle geometries, and middle geometries are also
energy-cheaper, so the GRS cell's (b) verdict is likely to SOFTEN.
BOTH PREDICTIONS LANDED under the port revision recorded below
(gains 11.4% -> 3.5%; the weak front bends from flat to
4.7%-paid-for-3.5-points). FOLLOW-UP SEATED, NOT DONE (a model change needs a ruling):
add the per-die port as a resource in the hand-off term --
busiest over {links, node ports} instead of links alone, which is
link_occupancy's own natural extension; until ruled, every
placement number keeps the "wire-only" caliber label. HALF B, the
ranking: Spearman rho 0.886 over six seatings, TOP-1 AGREEMENT
(corners best under both), top-3 overlap 2/3, SELECTED-SOLUTION
REGRET EXACTLY 1.0000 -- the seating our term picks is the seating
BookSim picks -- and no full inversion (our best is BookSim-better
than our worst). MINIMUM BAR MET on both clauses. The two
reorderings are precisely where our term TIES or nearly ties:
sequential and clustered are an exact 8192-word tie for us and
BookSim separates them (1287 vs 1260), snake and striped are an
exact 6144 tie and BookSim separates them (1235 vs 1112) -- the
disagreements live entirely inside our term's ties, which is the
best case a coarser caliber can hope for. SCALE-DOWN DECLARED and
kept: V = 8192 words (half A) / 2048 (half B) on a 36-die package,
so the queueing regime is not the 576-die one; nothing here is
extrapolated to the big instance. The 355M half needs no run
(single-flow hand-offs, degeneration pinned) -- recorded.
ARTIFACT: analysis/b7_handoff_probe.json sha256 7da511a788bc4dd3fda01dd63cf5e2ecd997114d151eb75ceecd9c65c39ff155. B7 HALF A CLOSED; the missing half and the port ruling follow.
B7's 355M/S6 HALF DONE (my "single-flow degeneration, no run
needed" reason was WRONG and is withdrawn: the degeneration pin is
about a chain's one-to-one hand-off, while the half B7 owed was the
S6 VERDICT ORDER under an outside judge -- 82 competing hand-offs
sharing links, a different claim entirely).
scripts/b7_s6_rerank.py shrinks the same structure to the 36-die
package (6 stages x 4 dies, fan-out +2/+4, V = 1536 words), lets the
four arms search it with S6's own objectives, then scores every
winner by our truth AND by BookSim: ORDER PRESERVED EXACTLY -- ours
[E0, E2, E2b, E1], BookSim [E0, E2, E2b, E1], Spearman rho 1.000,
E0 best and E1 worst under BookSim. Magnitudes compress under the
packet judge (E1 regret 1.846 ours vs 1.260 BookSim), consistent
with the endpoint/queueing story, but the verdict the paper rests on
survives an external adjudicator. Artifact sha256
3ae97939e58418cc634c43434b49008e95358a10f48302d3b34eb5677dd0e472.
PORT RULED IN 2026-09-15 (the reviewer's recommendation, accepted;
reason recorded: counting links but not ports is a KNOWN looseness
biased in favour of our own winner -- the dispersed family -- and
guarding against exactly that bias is the point of the discipline).
Implementation: search_eval.busiest_link_words now takes the maximum
over links AND node ports (one injection + one ejection port per die
at the link rate -- declared model, the bridge's own assumption);
`ports=False` reproduces the wire-only term for the B7 comparison
rows. PINS (2 new, suite 430 -> 432): single-flow degeneration
(port term == wire-only term, three geometries) and the
port-binding case (a dispersed hand-off's term equals one producer's
whole injected share). The two hand-computed examples now state
BOTH calibers. link_occupancy itself is NOT changed (blast radius),
and the 355M backend is verified bit-identical on all three stored
orderings -- the degeneration is why. RERUNS, all done, port-aware:
LADDER -- order UNCHANGED (random ... sequential) and the ratios
lift as predicted (random 0.3468 -> 0.3911, clustered 0.4587 ->
0.5251, sequential 0.9210 -> 0.9254); T SPREADS SHRINK exactly as
the corrected direction said: safe 1.0679 -> 1.0628, weak 1.9472 ->
1.8215, fast 1.2604 -> 1.2374; E column untouched (8.008%).
A4 COLUMN -- prefill GRS 1025.83 -> 1026.33 ms, the old-vs-new
deltas shrinking (0.87% -> 0.82% at GRS, 7.42% -> 7.01% at 0.1
GB/s); D2D total share 10.25% at GRS, inter-layer 1.15%.
DP -- single k = 1 1026.296 ms, evaluator identity re-pinned green.
A1 REGIONS -- classification unchanged (48 cells, zero uncertain,
zero rail gap; the packet-declared demo still opens its middle band
at 2.0/8.0/12.5 GB/s). SEATING INSTANCE -- GRS regret 0.9976 (0.24%
below the best named, was 0.7%), weak 0.9647 (3.5% below, WAS
11.4%): the pre-registered (i) LANDS -- pricing the port cut the
reported gains by roughly a factor of three, exactly because the SA
was winning on extreme dispersion the wire-only term did not
charge for. BAND FRONT -- (ii) LANDS TOO: GRS 1.8% band +4.24% (was
4.32) and the 3.6%/7.2% bands reach 0.00% at 1.81% latency paid
(was 2.00); WEAK 1.8% +6.12%, 3.6% +6.05%, 7.2% +4.24% (was 6.72 /
6.62 / 6.29) -- the weak front now BENDS rather than staying flat,
so the (b) verdict SOFTENS at the wide end: paying 4.7% of latency
buys back 3.5 of the 7.9 energy points, where before 6.5% bought
1.4. The trade is still real and still expensive at 1.8%, but it is
no longer "no width in range suffices". TWO BUGS CAUGHT BY THE
RERUN, both recorded: (1) search_linkage carried the ladder's rungs
as HARD-CODED constants, which went stale the moment the term
changed -- the first port rerun reported regret 1.0028/1.0351
against pre-port rungs; the script now READS ladder_v0.json, and the
lesson is general (a regret against a transcribed reference is
meaningless). (2) the band front's monotonicity guard FIRED on the
weak cell at ~1e-6 -- two SA runs from the same seeds at different
caps wandering apart; the fix makes the front monotone BY
CONSTRUCTION (a wider band is seeded with the narrower band's
minimum, feasible by nesting), not by loosening the guard.
ARTIFACT HASHES after the port revision: ladder_v0
cd06edefcde548940c72a49b334beaace775d9d5cacddec4d933a0513f972d25,
a4_column_v2
1ebd82fbe86de485c85177a9c41660604f5693bd82879493f2612db376a26cd5,
search_linkage
a7c563940897b1a2fcded86126bc7327fd8047b5359841d3c13d17f16960441d,
band_energy
251e35d050ade97a6f3939e964c2ab7be228ca92d357aac8f4c0b5a491275477,
certified_regions
ea53ff92635f6f5eff3b10031b14cdb2a9d06346f9c83ae210c74eb7aab9ece2,
b7_handoff_probe (wire-only comparison rows, unchanged)
7da511a788bc4dd3fda01dd63cf5e2ecd997114d151eb75ceecd9c65c39ff155.
Suite 432. B7 CLOSED (both halves). B5 OPENED 2026-09-15 (the joint-exact sub-item; safe to compute now
that the hand-off term is settled). PRE-REGISTRATION, before any
run. THE SHRUNK INSTANCE, declared in full: 4 blocks x 2 dies on a
3x3 = 9-die mesh (8 seats used, 1 spare -- so migration has room),
XY routing, the same hand-off term as the big instance (busiest over
links AND ports, post-F-B7), the same evaluator-identical cost rule
(each block's time = its compute plus its ENTRY hand-off; cutting is
free), the same pipe caliber (interval = max stage). Block compute
is UNIFORM, as the real homogeneous stack is, so the ONLY
seat-dependent and block-varying term is the hand-off -- the
coupling under test is exactly the real one. Size: 22,680 seatings x
8 cut sets = 181,440 joint states, EXHAUSTIVELY enumerable, so the
joint optimum is CERTIFIED, not searched. Two cells: the standard
bandwidth point and a weak-D2D point (hand-offs weighted up), as the
notes require. WHAT IS COMPARED: (1) the SEQUENTIAL solve, our
shipped method -- cuts from the DP on a reference seating, then SA
on seating at those fixed cuts; (2) DP TOP-K partitions, each given
its own SA (K = 3); (3) 1-2 rounds of ALTERNATION gamma <-> (alpha,
beta); all three against the certified joint optimum. REPORTED: the
gap's MEAN and WORST over seeds (5 RNG seeds per SA), per cell, plus
a budget-quality curve (best-so-far vs step) recorded on every SA
run. THE THREE-BRANCH CRITERION, pre-registered verbatim from the
notes, with the production-weave substitution stated: on packet-free
weaves the bracket degenerates to a point, so the 1.8% multi-start
NOISE BAND replaces "bracket width" as the yardstick. Branch A --
the sequential gap and the refinement gains are both far below the
headline gains (the seating instance's 3.5% at weak D2D) and below
the noise band: KEEP the current method, and the gap is reported as
a bounded method cost. Branch B -- light joint (top-K or one
alternation round) significantly changes the WINNER: ADOPT the
correction and re-run the affected exhibits. Branch C -- the result
is seed-sensitive, or the joint optimum RE-RANKS solutions the
sequential method ordered differently: the method is insufficient
and the split is reopened. Flips booked either way; no branch is the "hoped" one. ADDENDUM, pre-registered after the first run and before the
second: the first pass returned a gap of EXACTLY 1.0000 everywhere
-- and the reason makes the reading vacuous rather than reassuring.
In the frozen model cutting is FREE (the unpriced package seam
again), so the pipe optimum is always MAXIMUM DEPTH -- every block
its own stage, cuts (1,2,3) in the shrunk instance exactly as
k* = 32 in the real one -- and a maximal partition imposes no
grouping at all, so the cut layer cannot constrain the seating and
the split has nothing to cost. The measurement is therefore
structurally empty in this regime, which is a FINDING about the
model, not a verdict about the method. To measure the split where
it CAN cost something, the instance is re-run over a declared
SEAM-FEE sweep: a per-cut fee f in {0, 0.1, 0.25, 0.5, 1.0} x the
block compute time, which is the model extension already seated
after D.2. Expected, two-handed: at f = 0 the gap stays exactly
1.0000 (the degeneracy above -- an arithmetic check, not a result);
at fees large enough to make the optimal depth interior (2 or 3
stages) the partition starts to GROUP blocks, and grouping is what
couples the two layers, so a nonzero gap may appear -- its size is
the number B5 owes. If the gap stays at 1.0000 across the whole sweep, the split is cost-free on this instance for a stronger reason than "small", and that is branch A with a mechanism. B5 RESULTS (scripts/b5_joint_exact.py ->
analysis/b5_joint_exact.json, sha256
9dbe7b86fdef6153cf1aae5c540278e3018b9a1eee13af2f63e2685a068eb3a9): BRANCH A, WITH THE MECHANISM, and the
number is not merely small -- IT IS EXACTLY ZERO. The sequential
solve's gap to the CERTIFIED joint optimum is 1.0000 mean, 1.0000
worst, 1.0000 best, at both cells, over five RNG seeds; the DP
top-3 refinement gains 0.0000 and two rounds of gamma <-> (alpha,
beta) alternation gain 0.0000; seed spread 0.0000. THE FIRST PASS
WAS VACUOUS AND SAID SO: at fee 0 the pipe optimum is always
MAXIMUM DEPTH (cuts (1,2,3), exactly as k* = 32 on the real
instance), a maximal partition groups nothing, so the cut layer
cannot constrain the seating and the split has nothing to cost --
a finding about the model (the unpriced seam), not a verdict about
the method. THE SEAM-FEE SWEEP was therefore run to reach the
regime where grouping exists: at a per-cut fee of 1.0 x the block
compute the optimal depth DOES become interior (2 stages standard,
3 weak; at 2.0x likewise), so the partition genuinely groups
blocks -- AND THE GAP IS STILL EXACTLY 1.0000. THE REASON, checked
rather than assumed: at every fee tested the DP's cut choice on
the reference seating is IDENTICAL to the joint optimum's cut
choice ((1,2,3) at fees 0-0.5; (2,) standard and (2,3) weak at
1.0-2.0), and the joint-optimal SEATING re-priced under the DP's
cuts returns the joint value exactly. So on this instance the cut
decision is INVARIANT to the seating -- the seating shifts every
block's time by hand-off amounts far smaller than the compute term
that dominates the partition, so the partition that balances
compute is the partition that balances the total. That invariance
is the structural reason the split is free, and it is the same
homogeneity that makes balanced cutting optimal everywhere else in
this work. SCOPE, stated: this is a 4-block instance with uniform
compute; the invariance is exactly what would BREAK under capacity
heterogeneity or replication (the spec's own standing note on when
the DP earns its keep), so the zero gap is a statement about the
homogeneous regime the paper actually reports, not a general
theorem. The budget-quality curves are stored per SA run (every
20th step) and show the SA reaching its best within the first
~100 of 300 steps on this instance. NO FLIP: the pre-written branch A is the one that landed, for the stronger of the two reasons its text allowed. B5 CLOSED. B6 ARM THREE (the joint arm) IS
THEREFORE ANSWERED BY B5 and needs no separate run: arm three's
question is what joint optimisation adds over the sequential split,
and the certified answer on the enumerable instance is EXACTLY ZERO
at every fee tested -- so the headline gains stay attributed to arm
one (fixed gamma, search alpha/beta), arm two stays zero (the DP's
own solution is the uniform tiling), and arm three contributes
nothing to attribute. Recorded with its scope: the homogeneous
regime only, since the cut-decision invariance that makes it zero is
exactly what heterogeneity or replication would break. THE NOTES' LIST IS NOW COMPLETE: A1-A4 done, B5 done, B6 all three arms attributed, B7 both halves done. FIG.1 REBUILT TO THE ISOBAR SPEC 2026-09-15 (isobar_fig1_spec.md;
NEW FILE analysis/phase_diagram_isobar.png + .json, sha256 (superseded below)
-- the standing analysis/phase_diagram.png is UNTOUCHED, as
instructed; palette kept to the repo's own grey-band / amber-estimate
style rather than the spec's colour advice, also as instructed).
WHAT THE REBUILD CHANGES, each traceable to a spec clause: BOTH AXES
ARE RATES -- x = MVM row rate s = 1/t_row in Mrows/s (the RECIPROCAL
of the old axis, so every boundary, chip and label is recomputed, not
swapped), y = link bandwidth per direction. THREE REGIONS BY
PLACEMENT EXTREMA, not by organisation: max_P H < R compute /
fixed-cost dominated, min_P H <= R <= max_P H placement-dependent
dominance, min_P H > R communication dominated -- and the lower
region is NOT called placement-free, it is labelled "placement still
sets how severe". BOUNDARIES CARRY THE FIXED TERM: B_-(s) = A_min /
R(s), B_+(s) = A_max / R(s) with R(s) = N*s_ref/s + F, so they rise
and then FLATTEN where the non-scaling terms take over -- visible in
panel (b), and panel (a) keeps slope +1 because its fixed term is
0.36 us against 10.38 ms of compute (stated in the panel title rather
than left as a silent difference). PER-PANEL ENVELOPE QUANTIFIER, the
spec's certified/observed rule: panel (a) is the within-die
co-residency space, EXHAUSTIVE over its 70 seatings -> certified
envelope, B_+/B_- = 2.67x; panel (b) is the package, the seven named
seating rules -> observed envelope over P, B_+/B_- = 2.37x. Both
ratios are MEASURED on their own instance -- the old 1.4-2x is not
reused, per the spec's warning. CHIP PROVENANCE SPLIT: row rate is
known for all four, so all four get axis ticks with their status
(measured / derived / design-point); only chips with a bandwidth
coordinate get a point, hollow -- HERMES at its derived aggregated
per-link rate, Mythic and ISAAC as estimated bands with bars. Nothing
is placed at a fabricated height. PORT RULE STATED ON THE FIGURE (the
spec requires it): one injection + one ejection port per die AT THE
LINK RATE, so ports scale with B and H = A(p)/B holds with A taken
over links and ports. REVISED 2026-09-16 on review (three rounds): the repo's colour families instead of a greyscale misreading (slate blue = compute side, brick = communication side, cream band, bronze chips, charcoal envelope); estimated chip bands as capped error bars; the envelope as a capped bar with a two-line reading in words instead of a bare arrow; region labels centred in their regions and the band label set along the band's own slope; and the spec's OPTIONAL spread-contour layer added (5 / 20 / 50 %, denominator T_min over the same P stated in the legend). Layout verified collision-free by the renderer (zero overlapping text boxes). SECOND REVIEW ROUND 2026-09-16 (four items; answered with sources, then applied): (1) HERMES -- the 83.6 GB/s coordinate was the C37 aggregation in anchors.py ((418 links / 64 cores) x 0.4 GB/s x 32 arrays, all links of an equivalent 32-core group assumed concurrent), i.e. an AGGREGATE of ~208 physical links, exactly what the reviewer suspected; and it sat on the INTER-die panel although the published figure is a core-to-core (intra-die) link. Corrected: HERMES REMOVED from panel (b); placed on panel (a) at the PUBLISHED per-link 3.2 Gbit/s = 0.4 GB/s, no aggregation, at both published MVM latencies (4-phase 520 ns open, 1-phase 133 ns filled; which matches our 8-bit-input caliber is left to the text), labelled a hardware-derived reference point with the granularity caveat stated in the caption. anchors.py itself is NOT changed (the standing figures still use C37). ISAAC added to panel (a) as an architecture model at 32-bit flit x 1.2 GHz = 4.8 GB/s assuming one flit per cycle (parameters as cited by the reviewer; Table I not independently re-read here -- flagged). (2) ENVELOPE RATIOS vs the old 1.4-2x: the axis inversion does not touch B+/B- (= max_P A / min_P A, s-independent). The old 1.4-2x (METRICS row 'bandwidth-equivalent envelope ratio', observed over the anchor set) was the best/worst heaviest-block attribution on the block-chain family under the WIRE-ONLY term; the new 2.37x is max/min of the whole-stack busiest-resource words over the SEVEN NAMED seating rules (sequential 1314.8M / random 555.6M) under links+ports. DECOMPOSED on the same seven seatings (phase_diagram_isobar_envelope_decomp.json): wire-only 2.656x, links+ports 2.366x -- pricing the ports LOWERED the ratio (it raises the dispersed seatings' A more than the stacked ones'); so the change from 1.4-2x is the placement SET and the instance (the fully stacked 'sequential' rule is in P), not the axis and not the port term. 2.67x on panel (a) is the A3 ffn co-residency space, exhaustive, a different level entirely. The main text must carry these numbers with their sets, not the old summary. Endpoints now shown to 3 significant digits (18.2 -> 48.5, 4.04 -> 9.55) so the displayed ratio reproduces; 'certified' relabelled 'exhaustive over P; this instance & model'. (3) LEGEND now the definitions B- = min_P B_c(p), B+ = max_P B_c(p); the region text carries the meaning. Latency object stated on each panel: (a) one die's two co-resident operators, a sub-problem; (b) whole-model serial prefill. (4) LAYOUT: titles '(a) Intra-die placement' / '(b) Inter-die placement'; suptitle removed; grid lightened; one spread contour (20%); M1076 and ISAAC drawn as one shared ASSUMED range 0.4-8 GB/s with no nominal centre; the two EVALUATED configurations (0.4 and 12.5 GB/s at the NeuRRAM row rate) added to panel (b) with their own marker, tying the figure to the 3.53% / 0.24% search results; NeuRRAM axis marker kept as is (user's call). THIRD ROUND 2026-09-16 (three items, applied as suggested): the assumed ranges drawn as narrow translucent bands rather than centre-less error bars, names below, one shared 'Assumed bandwidth range' caption; the envelope as a thin double-headed arrow in the boundary grey with only the ratio beside it (endpoints and enumeration conditions in the caption; the white callout dropped); the two evaluated configurations as green hollow circles labelled 'NeuRRAM-based, 0.4 / 12.5 GB/s' with the legend saying what that means (NeuRRAM device rate, the two interconnect bandwidths) -- which also gives the chip its coordinate, so the axis-only NeuRRAM triangle and its caption are gone. FOURTH ROUND 2026-09-16, seven marker/label details applied to the large version (comm label aligned across panels, contour label embedded on the curve, ISAAC and the assumed ranges in the HERMES diamond-and-line style, white-filled evaluated points, captions lowered clear of the lines). PRINT VERSION 2026-09-16 as a SEPARATE file, analysis/phase_diagram_isobar_print.png, generator scripts/fig_phase_isobar_print.py (imports the large version's boundary, contour and palette code; the large version is unchanged): drawn at the double-column width 7.16 x 3.35 in with text at 7-8 pt AT FINAL SIZE rather than scaled down; the two instance boxes moved to the caption, only '70 placements' / '7 placement rules' left in-figure; chip captions cut to the name (HERMES keeps its phase line), the evaluated points to their bandwidths; legend cut to the two boundary definitions, the 20% contour, and the three chip entries the reviewer named. Layout collision-free by the renderer. Full caption: analysis/phase_diagram_isobar_caption.md. JSON sha256 6ba12a56d3b5ae7c5fb717bc02c4037dd8bbf89a6bc112cf652f9217c79a8d5d. DROPPED per the spec:
the d-family of width lines, the organisation/fabric comparison
lines, the collapse inset, the digital-anchor forest, calibration
markers, internal experiment numbers. READINGS at the reference rate:
within-die B_- 0.303 .. B_+ 0.808 GB/s; package B_- 0.603 .. B_+
1.427 GB/s -- so at the measured analog tier the package operating
point sits BELOW its own lower boundary at 0.4 GB/s (communication
dominated for every named seating) and above it at 12.5 (compute
dominated for every named seating), which is exactly the 60.1% vs
4.6% hand-off share the two search cells reported. NOT DONE, and not
invented: the optional (c) bandwidth-slice panel stays out of Fig.1
per the spec's default (it belongs in the search section, and its
honest form needs ONE fixed placement pair re-scored across
bandwidths rather than two independently-found search results).


Cell discipline: search experiments run only where the phase diagram has
play -- the fast device tier, the shared-medium tier, offload-decode, weak
D2D x spanning -- and the safe cell as the control. Running the search in the
(NeuRRAM x digital-link) cell reproduces 1.00x and proves nothing.

Dependencies: S1 on the v5 fixtures and O25's anchor columns; S3/S4 on P1's
cells; S6 on S3. S5/O6: RETIRED 2026-09-10 (C64-a) -- the collaborator
withdrew; the 47% figure is permanently unpublishable, 11% flat stays.

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
2. ~~**Soft-placement lever table at the anchors**~~ **DONE 2026-09-04
   (C49)**: every pre-registered direction held; A1 real = 1.000
   exhaustively by symmetry (uniformity proven by the exact five-scheme
   fit), A2 ceiling folds 1.609x/1.084x at 0.4 GB/s and dies above ~1-1.4
   GB/s; the inherited 1.31x superseded (v6 ledger), the 1.5-1.7x low-end
   claim confirmed; A1's 1.000 ADJUDICATED as structural
   degeneracy (C49-a: identical per-wire loads, zero freedom -- frozen
   by the MAPPING under three stated conditions, each reopening the
   space when it breaks; the mapping = the attribution framework's
   third hand, kept for the paper); in THIS configuration the
   searchable freedom concentrates at the die level (SUMMARY §2.7,
   soft_lever_table.md; the attribution-split row is ready for step 5).
   -- was: (half a day, closed
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
   PRE-REGISTRATION (2026-09-04, written before the run; review-amended):
   (a) CELL = A TRIPLE: whole-stack worst/best ratio (the headline),
   mechanism (busiest-wire) ratio, and the fixed-term share at that
   anchor x condition -- the share explains the gap between the two
   ratios in place. (b) TWO A-ROWS WITH DISTINCT SEMANTICS, never mixed
   in one cell: A1 "real, exhaustive" -- ONE JOINT seat permutation of
   the 8 macro bundles on the production 2x4 (8! = 40,320, exhaustive;
   bundle composition held at the shipped mapping -- DECLARED not
   covered; hub fixed: hardware placement); A2 "synthetic ceiling" --
   the C28 x4 heavy-talker stressor, seat swept over its 8-slot orbit
   (exhaustive), marked NOT A REALIZABLE SEATING. (c) EXPECTATIONS PER
   CELL, directions pre-written: A1 = 1.000 at EVERY anchor x condition
   (the fill-exact grid + uniform mapping is node-symmetric -- the
   C27/C28 corner=centre result restated at the anchors; if any cell
   deviates, that asymmetry is a finding); A2 mechanism ratio = 1.75x
   CONSTANT across ops, conditions and anchors (pure geometry); A2
   whole-stack ratio: monotone DECREASING in g, 1.00 above the knee,
   decode < prefill at every g (the write wall dilutes), largest cell =
   prefill at 0.4 GB/s; fixed share: monotone increasing in g within a
   condition, decode > prefill at every g. The three INHERITED numbers
   (1.31x at 0.4, 1.5-1.7x band low end, 1.00 above knee) predate the
   v6 accounting -- if the v6 ledger disagrees, that is a finding to
   record, not an error to fit. (d) Flow reconstruction self-check
   before any scan: uniform per-node flows must reproduce the stored
   per-op serial_s at the reference bandwidth to 1e-9, else stop.
   (e) B collects, never recomputes; C states the 1%/10% g-thresholds;
   the attribution-split row feeds step 5's robustness table.
   A3 ADDENDUM (2026-09-04, review; pre-registered BEFORE the run;
   one-day cap, declared close-out if exceeded): "natural non-uniformity
   (multi-operator co-residency)" -- the non-synthetic reopened-space
   probe A1's degeneracy theorem calls for. Production seating IS
   multi-projection co-residency: under offload the die keeps only the
   projection set, and the blocks tile INTEGRALLY at d=1024 (qkv 3
   macros / out_proj 1 / ffn1 4 / ffn2 4 of 8) -- per-macro flow density
   is naturally unequal, and the attention-half die has FOUR FREE slots
   (offload removed K/V): real seat choices, no stressor. METHOD,
   declared: block-exclusive reading of co-residency (each op's traffic
   on its own k macros at density x8/k -- exact for distinct-partition
   dims, stated); joint seatings exhaustive (attn die C(8,3)xC(5,1) =
   280, ffn die C(8,4) = 70; within-op seat order irrelevant by
   uniformity); compute/write kept from the stored share-basis ledger
   (A3 re-reads WIRE GEOMETRY only; the compute-parallelism fork
   between share- and block-readings is a stated boundary, and it
   cancels in the lever ratio since compute is seating-invariant).
   EXPECTATIONS, pre-written: A3 lever > 1.000 below the knee (the
   reopened-space claim -- the first REALIZABLE on-die lever); attn-die
   variance > ffn-die (free slots); monotone decreasing in g, 1.000
   above the knee, prefill > decode; magnitude pre-estimate from trunk
   volumes and the 2x4 column geometry: mechanism ratio order 1.1-1.8,
   whole-stack at 0.4 GB/s between ~1.05 and A2's 1.609 (prefill).
   Table and prose get the connector sentence: after offload what
   remains on the die IS this co-resident projection set -- the on-die
   space REOPENS in that configuration, evaluator unchanged.
   A3 DONE 2026-09-04 = C49-b: mech 3.00/2.67 (EXCEEDS the synthetic
   1.75 -- A2's "ceiling" now scoped to the uniform-mapping world),
   stack 1.434/1.057 at 0.4 GB/s; directions all held, the magnitude
   pre-estimate undershot and recorded as a finding.
3. ~~**Document round.**~~ **DONE 2026-09-04 (C50)**: DR table
   refreshed (DR-2 priced by the soft-lever table, DR-5 device-axis
   framing); SUMMARY §2.8 = the five-layer frame (EN+ZH); README
   extended; the two stale slow goldens re-derived WITH attribution
   (caliber mix 311,296 -> exact 12,288 value identity; 5/4 -> 12/11
   two-share-class spread on the 2x4) -- both suites green. TEX
   RE-SCOPED by the user (2026-09-04): only the local
   phase_diagram_report.tex absorbs findings (band-pricing section,
   five-layer validation with the reproduction subsection + figure);
   settings_and_assumptions.tex and company_report.tex NOT touched --
   their version-header/absorption items are retired from this step.
   -- was: DR-table refresh (real-bandwidth input returns to
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
4. **BookSim cross-check** (3-day timebox). ENVIRONMENT ADAPTED
   2026-09-04 (ahead of the box, on request): BookSim2 vendored under
   workspace/tools/ (un-tracked; one .gitignore line added), parser
   generated on the HOST (flex/bison live there; the container lacks
   them and nothing was installed anywhere), built in the container
   with g++ only; smoke-tested on the bundled 8x8 example AND the
   step-4 topology itself (6x6 mesh, DOR, 17-flit packets) -- recipe
   in tools/booksim2/BUILD_NOTES.md. PRE-REGISTRATION (2026-09-04,
   before any measurement run; review-ruled): CONVERSION TABLE -- flit
   payload 8 B (64 data bits; the 2 id bits are wire format), NoP
   channel cycle = 8 B / 5.5 GB/s = 1.4545 ns, hop = channel 12 cycles
   + router pipeline 2 cycles (each with JSSC provenance; not a
   rounding artifact; the -1.8% optimistic remainder recorded IN the
   table), packet_size 17; VC count / buffer depths / credit delay =
   BookSim defaults, DECLARED un-aligned parameters with their literal
   default values copied into the table (congestion-side only;
   shallower buffers push pessimistic). LAMBDA GUARD (ruling): the
   slack coefficient lambda = (T_book - T_opt)/(T_pess - T_opt) is
   REPORTED ONLY where the bracket width exceeds 10% of the completion
   time; narrow-bracket points report the absolute deviation
   (T_book - T_opt) instead -- the guard prevents a degenerate-domain
   false alarm. ARITHMETIC NOTE, recorded: the review predicted bar1
   lands narrow ("67.263 vs ~65.7, percent-level"); our computed
   brackets are WIDE at both T1 points in both calibers (whole-stack
   24.397/67.263, network 19.43/42.9 at bar1) and we cannot reproduce
   the 65.7 figure -- the guard is armed regardless and the data
   decides which points report lambda. CALIBER LABEL (ruling): BookSim
   injects unicasts; multicast flow sets are run as per-destination
   decompositions and their lambda carries the explicit label
   "unicast-decomposition caliber" (the bias is NOT one-signed: both
   T_book and the rails move); res3a's broadcast-heavy readout is
   interpreted under this limitation, and T1's point-to-point-dominant
   flows are the protagonist for this third reason. EXPECTATIONS
   (pre-written): wide-bracket points -- lambda toward the pessimistic
   end (silicon is partially pipelined; residual single-digit %), and
   lambda(bar5) > lambda(bar1) (the round-effect share grows with
   distance -- the distance-linear residual's direct check);
   narrow-bracket points -- absolute deviation at the propagation-term
   scale. Outside the bracket = a semantics discovery, formal reopen;
   ordering reversed = single-record investigation. RED LINE: identity
   gates not green by mid-day-2 -> close out per the C29 wording (the
   NoC column keeps its declared lower bound, coefficient marked
   pending). DAY-1 GATES: identity_optimistic (degenerate-latency
   BookSim == the NON-DEDUP serialization bound + propagation, tolerance
   declared at 5%) and identity_pessimistic (per-packet single runs sum
   == the round-serialized rail, 5%); the vendored file-traffic patch
   carries its own acceptance (one source, hand-counted completion).
   DAY-1 CLOSED 2026-09-04 (C51), gates GREEN: gate B exact
   (per-packet sum == 17 + 14h + 37, ratio 1.000000), gate A 1.0018 vs
   the declared reference. PRE-REGISTRATION AMENDMENTS from day 1
   (before any day-2 measurement): (i) hop split 10+4 (BookSim's default
   IQ pipeline measures 4 cycles/hop; overriding alloc delays trips a
   router assertion; total 14 cycles keeps the 20 ns provenance and the
   -1.8% remainder); (ii) vc_buf_size 34 moves from "un-aligned
   defaults" to ALIGNED (the default 8 cannot cover the 14-cycle BDP and
   credit-throttles ~2x; silicon sustains line rate per JSSC SII-C;
   insensitive 34 vs 64); (iii) injection caliber declared: one BookSim
   injection channel vs Simba's four NoC local ports -- reference and
   BOTH rails use max(channel bound, injection bound); (iv) EXPECTATION
   CORRECTION, flagged for review before day 2: BookSim pipelines
   freely and carries no protocol dependencies, so it measures the
   NETWORK-INTRINSIC share of the gap only -- its lambda should land
   NEAR THE OPTIMISTIC END (single-digit %), not near-pessimistic as
   pre-written; the round-serialization share of silicon's 2.5x lives
   ABOVE the network (protocol level). Day 2's product is therefore a
   TWO-COMPONENT decomposition: [bound -> BookSim] = network-intrinsic
   slack (measured), [BookSim -> silicon] = protocol/round-trip share
   (attributed) -- a stronger statement than one coefficient, pending
   the reviewer's sign-off since it reverses a pre-written expectation.
   DAY-2 PRE-REGISTRATION (2026-09-05, reviewer-signed decomposition
   frame; written before the runs). The gap is TWO STACKED LAYERS:
   [bound -> BookSim] = the NETWORK-INTERNAL share (queueing, flow
   control, flit competition -- free pipelining, no protocol
   dependencies) and [BookSim -> silicon] = the PROTOCOL share (small
   consumer buffers, per-block handshakes -- lives above the network,
   invisible to BookSim). Expectations in two halves: network-internal
   -- bar5's [bound -> BookSim] offset EXCEEDS bar1's (the
   distance-linearity signature checked inside the network layer),
   magnitude single-digit percent; protocol -- bar5's [BookSim ->
   silicon] carries the BULK of the measured 2.53x (quantified as
   2.53 / booksim_ratio, consistent with the T1 residual attribution).
   Per the ruling bar1 reports the absolute deviation where the guard
   classifies it narrow -- ARITHMETIC NOTE continued: in the bridge
   caliber our computed bar1 bracket is WIDE (width ~1.5x of
   completion), so the guard is expected NOT to trigger there; both
   quantities are reported per point and the guard's verdict is stated.
   The multicast-decomposition bias limitation rides res3a as ruled.
   PROPAGATION (day 3): the phase-diagram NoC correction line is
   labelled "network-internal; protocol share declared"; the validation
   chapter's fourth layer states the two-component attribution with the
   protocol share MEASURED as (silicon ratio) / (BookSim ratio); V3's
   input renamed "network-internal coefficient + declared protocol
   share". PROVENANCE TIGHTENING (ruling): the 7-cycle interface base
   is a BRIDGE-INTERNAL measured constant (BookSim, BDP-aligned
   config) with NO silicon counterpart claimed -- so labelled in the
   conversion table.
   STEP 4 CLOSED 2026-09-05 (C53; the 3-day box closed in 2):
   day-3 propagation done -- ANCHORS NoC-slack row (evidence status
   "cycle-accurate reference", network-internal vs declared protocol
   share), SUMMARY §2.8 layer-4 sentence (EN+ZH), the report's
   validation subsection carries the executed cross-check, the phase
   diagram's D2D panel carries the certification note (a corrected
   LINE needs a platform packet declaration -- not invented; DR-tier),
   V3's input renamed in step 5.
   DAY-2 CLOSED 2026-09-05 (C52), every amended expectation hit:
   net-internal bar1 +0.18% / bar5 +0.74% (bar5 > bar1, single-digit
   %), lambda ~0.001 at the optimistic end, protocol share = 2.530 /
   1.0056 = 2.516x THE BULK with a measured anchor; ordering bound <
   BookSim < closed pessimistic rail (2.40) < silicon (2.53) = the
   stacked layers, quantified. Day 3 (records propagation per the
   ruling) remains.
   Since C46 its task is
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
5. ~~**Robustness table**~~ **DONE 2026-09-05 (C54)**: 15 rows under
   pre-registered, review-amended criteria; digital-anchor region calls
   survive 5x + the worst-endpoint overlay; the honest reds pinned
   (R11 radius 1.36x, R12 margin 1.68x at the tiling-divergence site,
   R13 bracket dies at 5x). -- was: (half a day, closed form). Every published
   conclusion x model error 2x / 5x: does the region verdict survive a
   k-fold boundary shift on the log axis. One row for the attribution
   split itself: does the 1.4-2x software band survive or collapse to 1,
   and if it collapses, in which diagram cells the soft-placement
   narrative fails. NoC-paradigm input RENAMED per the C52 ruling: not
   "the lambda coefficient" but "the NETWORK-INTERNAL coefficient
   (+0.18-0.74%, measured) plus the DECLARED protocol share (2.516x on
   the Simba seating experiment)" -- the row asks which conclusions
   survive if the protocol share applies wherever the NoC paradigm
   does. The validation chapter's closer.
6. ~~**FREEZE.**~~ **FROZEN 2026-09-05 = tag v6 (C55)**: final
   read-through passed (wording deferred to the writing month by
   decision); both suites fully green on the final run (fast 300 /
   slow 311, each +1 xfail); citation snapshot exported
   (analysis/frozen_v6.md -- the writing month cites THAT page, not the
   moving workspace). -- was: Preconditions: fast AND slow suites fully
   green (step 3's goldens resolved first); the slow suite runs weekly
   and mandatorily before every freeze.
7. **After the freeze: the placement search milestone.** An evaluator API
   wrapping the existing pipelines (anchor column and device tier as
   arguments; `schedule_slack` honoured) -> baselines + greedy -> the
   search studies -> the proxy-optimization experiment over the pure
   soft space (macro attribution + die assignment / seating / ordering;
   the hub knob only in width >= 3 design exploration). Run only in the
   cells where the diagram has play (fast device, shared medium,
   offload-decode, weak D2D x spanning).
8. **After the freeze: static energy + peak concurrency** (closed-form,
   cheap; archive: O27). MECHANISM DONE 2026-09-08 (C57): idle_power_w
   platform input; structural crossovers (decode A-vs-B flips to
   offloaded at 0.085 W chip static -- parameter-free headline; prefill
   verdicts already aligned); share as a function; schedule-level
   concurrency counts + the verbatim boundary sentence. CLOSED 2026-09-08 (C57-a):
   the retrieval returned the honest answer -- neither chip publishes a
   numeric standby power (power_extracts.md, verbatim) -- so the share
   stays a FUNCTION and the point value stays a DR item; the two
   DERIVED active anchors bound the production die's active-class scale
   at 5.0-25.9 W, making the decode flip threshold 0.33-1.7% of scale:
   unless static < ~1% of active-class, decode's energy verdict follows
   the latency verdict (NeuRRAM's gating the one mechanism that could
   dip under).
   REVIEW ROUND 2026-09-08 (C57-b), three findings, all landed: (1) the
   5.0-25.9 W interval is a CROSS-TECHNOLOGY extrapolation (130 nm RRAM
   end vs 14 nm PCM end) -- kept, but labeled as the third provenance
   class, order-of-magnitude scaling only, never point conclusions;
   NeuRRAM end (~5.0 W) is PRIMARY in prose because the production die
   is the Wan device (a NeuRRAM scale-up), HERMES end is reference.
   (2) The 0.33-1.7% figure now carries its denominator caliber:
   denominator = full-stream peak active power; decode is the lowest-
   utilization regime, so against decode's own active power the ratio
   is an order of magnitude higher (exact value = the DR static point);
   the denominator-free anchor is the absolute 0.085 W flip + the
   NeuRRAM power-gating half-sentence. (3) The PEAK-CONCURRENCY WING
   was BUILT and PINNED at C57 (analyze_static_energy.py layer 3:
   schedule-level counts per operating mode, per-die calibrated dynamic
   rate 0.905 W, 48-die pipelined peak estimate 43.4 W, boundary
   sentence verbatim; test group 41) but was OMITTED from the closeout
   report -- verdict "done, not written up"; this sentence is the
   written-up record. Its three uses (filed from the user): (a) the
   power-delivery design input -- worst-instant demand, not average;
   (b) a function of placement/schedule, hence a candidate search
   CONSTRAINT dimension (prune "latency-optimal but over power
   budget"); (c) the reviewer's power-density question gets a column.
   O27 MAIN-BODY DISCIPLINE (filed 2026-09-08 from review, NOT yet
   executed): layered caliber -- the structural inference (static E =
   idle power x time, so ordering inherits the latency ordering) is
   parameter-free; the SHARE requires real idle-power inputs, never
   estimated here (two sources: platform DR values when they arrive, or
   literature anchors from NeuRRAM/HERMES whole-chip power breakdowns,
   entering under the anchor provenance discipline). Peak concurrency =
   a SCHEDULE-level count only (max simultaneously-active instances x
   silicon-calibrated unit price), with the boundary declared verbatim:
   "circuit-level peaks (di/dt, IR-drop) are OUT of scope; this
   platform outputs schedule-level concurrency for the power team as an
   input" -- the boundary sentence itself ships to the company.
   PRE-FLIGHT CHECK (2026-09-08, pre-registered BEFORE computing; the
   die-level ENERGY column that has never been surfaced): on the
   existing die-level seating/ordering sweep data, one added column of
   D2D energy -- zero mapper. CONVENTION CORRECTION to the review's
   formula: not naive bytes x unit price -- the repo's charge is flat
   (words x pJ at the reference hop, inside the CiMLoop account) plus
   the surplus overlay (words x pJ x (hops - ref)), so the TOTAL scales
   with average hops; the stored surplus_uJ per assignment
   (d2d_impact.json) already follows it, and the script's gate is to
   REPRODUCE those stored values from words x (hops-1) x pJ before
   adding anything. Three numbers per scenario (B1 48-die orderings,
   B2 2.7B seatings closed-form, B3 4-die probe): worst/best D2D
   energy ratio, D2D share of the system scenario energy, energy-vs-
   latency ordering concordance. EXPECTATIONS, two-handed: the review
   pre-wrote share ~ single-digit percent; OUR arithmetic from the
   stored words (24.64M x 10 pJ x hops) says SUB-percent (~0.1-0.6% of
   the 0.30 J prefill account) -- both filed, data decides. Ratio
   expectation: worst/best = avg-hops ratio (B1: 6.55x, arithmetic-
   implied). Concordance expectation, pre-flagged from the stored rows:
   NO anti-ordering (snake is best on both sides), but the max-vs-sum
   functional split ALREADY shows a latency TIE broken by energy
   (sequential-rows = snake in latency, 1.75x apart in D2D energy) --
   so the paper wording decision is expected to land on: "latency-
   optimized stays energy-free" holds, upgraded to die-level measured,
   PLUS energy as a declared tie-breaker dimension among latency-equal
   orderings. Output: the three numbers per scenario + a FIGURE;
   results are post-v6 -> separate result files, frozen_v6 page
   untouched, paper citations of the energy claim must upgrade
   explicitly.
   PRE-FLIGHT DONE 2026-09-08 (C56; d2d_energy_column.json/.png, group
   40). Reconciliation: ratio = avg-hops ratio CONFIRMED (B1 6.553x);
   share = OUR sub-percent hand (0.03-0.76% across all four scenario
   denominators; the review's single-digit-% hand missed); concordance
   = the draft's "no anti-ordering" OVERRULED by the data -- B3 shows a
   genuine off-optimum INVERSION (four-corners beats one-column on
   latency, costs more energy) and B2's style orderings diverge
   (row-fill energy-best vs clustered latency-reference, 8.3% apart on
   a sub-percent account) -- while the AT-OPTIMUM claim survives in
   every scenario (the latency-best choice is energy-best or within
   8% of a <1% account => system-level cost < 0.1%). PAPER WORDING
   DECISION (the pre-registered purpose): the "energy is flat" sentence
   becomes two-tier -- system-level "latency-optimized stays
   energy-free" UPGRADES to die-level measured; the D2D account's own
   orderings diverge (max- vs sum-functional), so energy enters as a
   DECLARED TIE-BREAKER dimension among latency-equal choices, and
   D2D energy can never be read off latency rank order.
9. **Kept, lower -- NOW EMPTY (the A group cleared it, 2026-09-08/09)**:
   the input-row split (O15) MEASURED, A2/C61 -- the load-relocation
   valve, the width law's exception now a measured row; long-context
   K/V (O14) CLOSED at the declaration tier, A3/C62-a (window mode +
   semantics note); whole-model joint seating (O16/O20) MEASURED under
   the static-spread hypothesis, A4/C62-b (+1.27% latency at GRS,
   geometry-qualified ~4% D2D share, S4 payload shipped); lower-level
   link energies (O1) CLOSED C58 at the derived-price tier; bus/h-tree
   wire energy (O8) CLOSED C59; registry growth (O19) torus + ring
   LANDED C60 (queue remainder -- express links, duplex split,
   FlooNoC-class, routing params -- stays low priority, on demand from
   the search side).
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


PRE-WRITING CHECKLIST (the writer's nine items, 2026-09-16; the reply
with sources is in the session record, items 2/7/8/9 are text). RUN
ORDER 5 -> 6 -> 7 -> 4 -> 3, each pre-registered here before its
number.

ITEM 5 PRE-REGISTRATION -- platform speed and search cost, MEASURED
(scripts/timing_probe.py -> analysis/timing_probe.json). Four
timings reported SEPARATELY, never blended: preprocessing (workload
construction, the seven named seatings), the full score (se.score on
the A4 seating, single caliber, GRS), the incremental step (one SA
step through SessionJ: propose + apply + J update, and the J update
alone, over a 400-step walk), and a whole seating leg (3 starts x
1200 steps) per cell; plus the hardware. EXPECTATIONS: the full
score is a whole-model per-op evaluation building die flows for 544
dies -- order 0.1-1 s; the incremental update touches only the
boundaries a move changes -- order 10-1000 us; the ratio is what
makes the search affordable. THE ABSTRACT'S 'microseconds' IS
DECIDED HERE: it is true only of the interface that measures in
microseconds, and the text must name that interface. No number
below is quoted without saying which of the four it is.
ITEM 5 RESULT (timing_probe.json; AMD EPYC 9254, 96 logical CPUs,
Python 3.10.12, single-threaded pure Python, perf_counter wall
clock): preprocessing -- workload construction 10 ms, the seven
named seatings 9 ms; FULL SCORE (se.score, A4 seating, single
caliber, GRS) median 37.0 ms, min 35.5; INCREMENTAL -- one SA step
(propose + apply + SessionJ update) median 1.37 ms, the J update
alone median 1.34 ms, min 0.52 ms, i.e. ~730 steps/s, full /
incremental = 28x; WHOLE SEARCH -- one seating leg of 3 starts x
1200 steps: 5.7 s (GRS), 5.9 s (weak), ~1.9 s per start. FINDING
F-T1: THE ABSTRACT'S 'MICROSECONDS' IS NOT TRUE OF ANY INTERFACE
THE 2.7B SEATING SEARCH USES -- the incremental update is
MILLISECONDS (0.5-1.4 ms per move, 544 dies, per-op flows rebuilt
for the boundaries a move touches). The text must say 'about a
millisecond per move' or name a different, smaller session (the
355M unit chain, not timed here). Expectations otherwise hit: the
full score is order 0.1 s, the ratio is what makes 1200-step legs
cost seconds.

ITEM 6 PRE-REGISTRATION -- fixed-pair bandwidth slice
(scripts/bw_slice_pair.py -> analysis/bw_slice_pair.json + .png).
TWO FIXED SEATINGS: the reference = random (seed 0, the strongest
named baseline at both cells) and the optimized = the weak-cell
search winner (search_linkage.json, seating_mesh_weak.best_pi);
the GRS winner is carried as a third column for cross-evaluation.
Re-scored, NOT re-searched, at 0.1 / 0.2 / 0.4 / 1 / 2 / 4 / 8 /
12.5 / 25 GB/s, single caliber, prefill. Per bandwidth: T_ref,
T_opt, H_ref, H_opt, r = H_ref/T_ref, eta = (H_ref - H_opt)/H_ref,
G = 1 - T_opt/T_ref. EXPECTATIONS (identities, so the check is
1e-9): G = eta * r exactly (R is seat-invariant); H * B constant per
seating (555.6M words for random, ports included); eta constant
across bandwidths for the fixed pair (both H scale as 1/B), so the
whole curve G(B) = eta * r(B) is the share curve alone. If eta is
NOT constant something in the evaluator depends on B beyond 1/B,
and that is a finding. Also reported: the weak winner scored at GRS
and the GRS winner at weak (are they the same seating? no -- the
search found different points; how much does each lose off its own
cell?).

ITEM 7 PRE-REGISTRATION -- the zero-span temperature. S6 sets
t0 = (max seed J - min seed J) / 20 per objective; an objective
that degenerates to a constant over the seed set (the bus
paradigm's objective, F in MATERIALS) gives t0 = 0, and
search_sa.anneal's rule at t = 0 is GREEDY: accept iff dJ < -1e-15,
so a tie (dJ = 0) is REJECTED and a constant objective leaves the
start untouched with accepted = 0. That is the intended reading --
'the objective cannot discriminate' -- and it is distinguishable
from a search failure precisely because accepted = 0 and best = start
exactly. PINNED as a test (tests/test_search_sa.py): a constant J at
t0 = 0 returns the start bit-identically with accepted == 0, and a
J with ties but a strict improvement available still takes it.
Written into SEARCH_SPEC as [AMENDED 17].

ITEM 4 PRE-REGISTRATION -- 544-die seating search statistics
(scripts/rerun_seating_seeds.py -> analysis/seating_seeds.json).
Distinguished explicitly: THREE START FAMILIES (clustered / snake /
random) x THREE INDEPENDENT SA SEEDS (0, 1, 2) per cell (GRS, weak)
= 18 runs of the standing schedule (1200 steps, alpha 0.996, t0 2 /
20 ms); plus the RANDOM BASELINE'S OWN DISTRIBUTION, seeds 0-4
scored at both cells. Reported: per (start, seed) endpoint; per
cell the endpoint distribution (min / median / max, spread %); the
random baseline's min / median / max; the gain RELATIVE TO THE
STRONGEST BASELINE = min over the seven named rules (seed 0) and the
five random seeds; and the budget-quality curve (best-so-far every
100 steps) per run. The standing 0.24% / 3.53% remain the record of
the runs already made (seed 0 at each start); the new gain is
reported beside them, not in place of them. EXPECTATIONS: GRS
endpoints within the 1.8% noise band of each other and of the
random baseline (the cell is nearly closed); weak endpoints spread
< 1% across seeds; random baseline spread at weak of a few %
(dispersed fills differ in their busiest port); the weak gain
against the strongest of 5 random seeds SMALLER than 3.53%.
ITEM 6 RESULT (bw_slice_pair.json sha256 0b9bb72a4b924479...; figure
bw_slice_pair.png). Every expectation hit, as identities: |G - eta*r
- residual| <= 1.5e-16 at all nine bandwidths; eta = 5.874% at EVERY
bandwidth (both H scale as 1/B, so the fixed pair's communication
improvement is bandwidth-free); H*B = 555.61M words for the
reference at every bandwidth (the port-inclusive busiest words,
exactly the ladder's A(random)); the seat-dependent part of R
(propagation) contributes |residual| <= 0.00018% -- negligible, so
'R seat-invariant' holds to that tolerance and G(B) = eta * r(B) IS
the communication-share curve scaled by one constant. Readings: G =
5.04% at 0.1 GB/s (r = 85.8%), 3.53% at 0.4 (r = 60.1%), 0.77% at 4
(r = 13.1%), 0.27% at 12.5 (r = 4.6%), 0.14% at 25 (r = 2.4%). Cross-
evaluation column: the GRS winner scored against random at every
bandwidth (in the JSON); it is a different seating from the weak
winner. This is the light experiment the figure spec asked for, and
it needs no search.

ITEM 7 RESULT: [AMENDED 17] written into SEARCH_SPEC; test a17 added
to tests/test_search_sa.py (constant J at t0 = 0 -> start returned
bit-identically, accepted == 0, proposed == steps; tied J with one
strict improvement -> the improvement is the only acceptance). Fast
suite 432 -> 433. No numbers change; the bus leg's reading is a
signature, not a regret.

ITEM 4 NOTE BEFORE THE RESULT: the first run enumerated the start
families in declaration order while seating_leg enumerates them
SORTED, so only clustered/s0 reproduced the standing run; the script
now uses the sorted order and s = 0 reproduces all three (the
record). The first run's numbers are superseded by the rerun below;
its one substantive reading -- endpoints converging to the same
discrete seating from different RNG streams (random/s1 = the
standing random run's 2228.64 ms exactly) -- is expected in a
discrete space and is not a finding.
ITEM 4 RESULT (seating_seeds.json sha256 573a4f0cc4911993...; figure
seating_seeds.png; 3 start families x 3 SA seeds x 2 cells = 18 runs
of the standing schedule; s = 0 reproduces the standing runs exactly:
963.34 / 963.37 / 963.47 and 2239.78 / 2228.64 / 2233.23 ms).
GRS: endpoints 963.12 / 963.34 / 963.73 ms (min / median / max),
spread 0.063%; random baseline seeds 0-4: 964.39 / 965.42 / 965.65,
spread 0.130%; STRONGEST BASELINE IS A RANDOM SEED (964.39, seed 3,
not the seed-0 fill the ladder carries); gain vs strongest 0.13%
(record vs seed 0: 0.24%). Everything inside the 1.8% noise band --
the cell is closed, as expected. WEAK: endpoints 2228.64 / 2233.23 /
2245.02 ms, spread 0.735% (expectation '< 1%' hit); random baseline
seeds 0-4: 2270.91 / 2303.02 / 2310.23, spread 1.73% (expectation 'a
few %' hit -- dispersed fills differ in their busiest port); the
strongest baseline is again a random seed (2270.91); GAIN VS THE
STRONGEST BASELINE 1.86% (expectation 'smaller than 3.53%' hit).
FINDING F-S4b: THE WEAK-CELL SEATING GAIN AGAINST THE STRONGEST
BASELINE IS 1.9%, NOT 3.5% -- the 3.53% record measured the search
against one random draw (seed 0), which happens to be the WORST of
five; against the best draw the gain roughly halves. Both numbers
are kept, each with its denominator (METRICS.md row to be added:
'seating gain vs strongest baseline', denominator = min over the
seven named rules and five random seeds). Budget-quality curves
(best-so-far per 100 evaluations, in the JSON and the figure): every
run is within 0.3% of its endpoint by 600 evaluations at GRS and by
800 at weak; the last 400 steps buy < 0.2%.
ITEM 3 PRE-REGISTRATION -- the search gain under an outside judge, on
a SHRUNK COMPLETE INSTANCE (scripts/b3_shrunk_rerank.py ->
analysis/b3_shrunk_rerank.json). The writer's ruling: shrink the
whole instance, keep the communication dependencies, the routing and
the port constraints, then rank the SAME candidates under our
evaluator and under BookSim; a sub-network cut out of the crowded
part could not speak for a whole placement. THE INSTANCE: the 2.7B
per-op structure verbatim (qkv 4 dies, attention 1, out 2, ffn1 5,
ffn2 5 per layer; R-split multicast; entry hand-off from the previous
layer), TWO layers = 34 dies seated on a 6x6 = 36-die mesh, XY
routing, one injection + one ejection port per die at the link rate;
9 boundaries per candidate. It is built by the standing machinery
(Workload2p7B on a 36-slot fabric with n_layers = 2), so the named
rules, score() and SessionJ run on it unchanged. VOLUME SCALE: the
hand-off volumes are 2.6-26.2M words per boundary (655k packets per
candidate); BookSim runs them at 1/16 (the heaviest boundary = 12,800
packets, 2.5 s; probed in b3_booksim_cost_probe.py), and the packet
clock is set so that the hand-off TIME is the nominal cell's: one
flit (8 B) per cycle at bandwidth B/16, i.e. cycle = 128/(B*1e9) s.
Our judge scores the UNSCALED volumes at the nominal B (identical
seconds). BookSim's cycle count is bandwidth-free, so ONE simulation
per candidate serves both cells. Each boundary is its own batch
(batch-1 serial semantics, the same per-boundary sum our term makes).
CANDIDATES (15, all on this instance): the seven named rules at seed
0; random seeds 1-4; SA winners from the three start families at the
weak cell and from the random start at GRS (standing schedule, 1200
steps, alpha 0.996; t0 = (max seed J - min seed J)/20 per cell, the
S6 rule, since the 2-layer objective is ~150 ms not ~1 s).
READINGS: per cell, Spearman and top-1 agreement between our T and
BookSim's T over all 15; per candidate the BookSim / ours ratio of
the hand-off sum (the term's looseness on a complete instance); and
THE PAIR THE ITEM IS ABOUT -- the weak-cell SA winner against the
STRONGEST random draw (chosen under our judge, as the paper does):
gain under ours, gain under BookSim, sign agreement; the same pair
at GRS. EXPECTATIONS: ours <= BookSim on every candidate's hand-off
sum (it is a bound); ratios inside 1.1-2.4 (B7's range) with the
header overhead 17/16 as the floor; Spearman >= 0.8; the weak-cell
winner beats the strongest random under BookSim too, by a SMALLER
margin than under ours (the S6 rerank compressed 1.85x to 1.26x); the
GRS pair inside the noise band under both. DECLARED IN ADVANCE: this
gives the 544-die reading representative outside evidence; the
544-die 3.53% (vs seed 0) and 1.86% (vs strongest) stay MODEL
PREDICTIONS. Flip rule: if BookSim reverses the weak-cell pair, that
is booked as a finding against the search claim, not explained away.
ITEM 3 RESULT (b3_shrunk_rerank.json sha256 cd39c9e8140d16471da73695d220922b44be4cb7cf12a7b87edd454f8a162a1d; 15 candidates, 9
boundaries each, BookSim at 1/16 volume, ~8 s per candidate). Held:
the bound holds on every candidate (BookSim / ours on the hand-off
sum 1.443..1.944, inside the pre-registered 1.1-2.4); the sign of the
pair agrees for the winner our tie-break selects; the GRS pair is
inside the noise band under both judges (0.14% / 0.52%). FAILED, and
booked as such: Spearman over the 15 candidates is 0.575 (pre-
registered >= 0.8), and 0.455 over the 11 non-search candidates
alone; the top-1 differs (both are search winners); and BookSim's
pair margin is LARGER than ours (8.84% vs 1.89%) rather than
smaller. Three findings, in the order they explain each other:

F-B3a THE PORT FLOOR. Under R-split multicast every consumer die's
ejection port carries the boundary's full volume V_b (P producers x
V_b/P), so the busiest-resource term is >= sum_b V_b for EVERY
seating, with equality iff no link exceeds V_b. Pinned as a test
(test_search_eval.py, port floor). On the shrunk instance all FOUR
search winners sit exactly on the floor (ours H = 78.64 ms = floor)
and are TIES under our judge; on the 544-DIE INSTANCE THE WEAK-CELL
WINNER SITS EXACTLY ON THE FLOOR TOO (523.0M busiest words = floor,
ratio 1.0000; random seed 0 = 1.062x, sequential 2.514x). So the
seating search's entire weak-cell gain (3.53% vs seed 0, 1.86% vs the
strongest draw) IS THE DISTANCE OF THE BASELINE FROM THE PORT FLOOR,
and the search's job under this term is exactly 'remove every link
loaded above V_b'. Below the floor the term has no resolution at all.

F-B3b THE TIE SET IS NOT EQUIVALENT. BookSim ranks the four floor-
sitting winners from 189.5 to 210.5 ms -- a 11% spread inside a set
our judge cannot order -- and against BookSim's OWN strongest random
draw (191.18 ms) the four read +0.88%, +0.11%, -4.30%, -10.08%. The
+8.84% pair margin above is an artefact of choosing the baseline
under our judge: random_s1 is our best draw and BookSim's worst
(209.5). The honest reading under the outside judge: the search's
advantage over the best random fill is at most ~1% and depends on
which floor-sitting winner the tie-break returns.

F-B3c RANKING POWER ON A COMPLETE INSTANCE. rho = 0.575 (0.455
without the ties) is far below B7 half B's 0.886 on a single cross-
traffic pattern. With ports priced most good seatings are at or near
the floor, so the ordering among them is decided by the term's
LOOSENESS (contention on links loaded up to V_b, header 17/16, hop
latency), not by the bound. The term is a bound that tells floor
from non-floor; it is not a ranking instrument among floor-sitters.
The B7 half-B 0.886 stands for its pattern; this number stands for
the complete instance, and the text must carry the latter next to
the former. Expectation-failure rule applied: nothing above is
explained away; the 544-die 3.53% / 1.86% remain model predictions
whose mechanism is now named (floor-reaching), and whose outside
validation is the ~1%-and-tie-dependent reading of F-B3b.

S7 PRE-REGISTRATION -- search settings chosen from the phase diagram
(design: analysis/search_setting_design.md; NOT RUN; awaiting the
writer's two declarations). THE RULE: fix the instance, then sample
bandwidth by declared multiples of ITS boundaries -- above 2B+,
in-band sqrt(B-B+), below B-/2 -- keeping 0.4 and 12.5 as labelled
legacy points; search ONCE and re-score the same batch at every point
(ordering is B-invariant under T = R + A/B, R seat-invariant to 2e-6,
pinned by item 6). TWO INSTANCES, split by the bottleneck's SOURCE,
not by bandwidth: A = the 544-die 2.7B stack (port-floor instance:
every search endpoint at A/floor = 1.0000, best random draw 1.032x,
B- 0.603 / B+ 1.427 GB/s); B = the fan-out cross-traffic load on the
same seating (shared-link instance: every rule 6.1-10.0x above the
port floor, ports never bind, A_min 18.29M random / A_max 30.00M
clustered, B- 0.0199 / B+ 0.0326 GB/s at V = 1e6). PREDICTIONS FOR A
(identities): G at 2B+ / sqrt / B-/2 = 1.02 / 2.31 / 3.92% vs seed 0
and 0.55 / 1.23 / 2.09% vs the strongest draw; ceilings 20.1 / 36.5 /
49.7%; no point opens room below the floor. EXPECTATIONS FOR B: the
search endpoint stays link-bound (A/floor >= 2) and beats the best
rule by > 1.8% in the communication term; at the legacy points r < 5%
so the whole-model gain is diluted below the noise band while the
term's gain is not -- reported side by side. FLIP RULE: an endpoint of
B on the port floor, or not beating the best rule, is a finding against
the search claim. TWO DECLARATIONS DUE BEFORE ANY RUN: (1) V for the
fan-out load -- 1e6 words (current, synthetic) or the layer's hidden
state 5.24M words (scales both boundaries by 5.24, leaves eta,
ceilings and spread unchanged); (2) whether instance B also gets a
shrunk complete run under the item-3 BookSim protocol (~3 min) or
rests on B7 half B (rho 0.886) and the S6 rerank (rho 1.000). Cost
once declared: re-scoring only for A; for B three SA seeds (2000
steps each, ~10 s) plus re-scoring.
S7 REVISED 2026-09-16 per the writer's synchronisation notes
(Isobar_search_experiment_notes.md; design doc updated in place). (i)
Instance A = whole-model bandwidth slices, re-scoring only, three
named references (random seed 0 / strongest draw / best rule), G =
r_ref * eta_achieved checked directly, eta_ceiling reported as a bound
not a gain. (ii) Instance B KEEPS V = 1e6 (synthetic, no tensor
provenance; scaling V scales A uniformly) and gets ITS OWN shrunk
BookSim re-evaluation; the earlier suggestion to re-declare V as the
hidden state is withdrawn -- the execution-phase correspondence would
have to be settled first and a volume change alone does not build a
real workload. B's boundaries are not a hardware anchor for the real
2.7B and B's one-shot batch is not spliced onto the 921 ms compute.
(iii) REMOVED from B's expectations: the 'A/floor >= 2' requirement
(reaching the port floor is a valid result) and the 1.8% threshold
(B uses its own seed / baseline distribution and the packet judge).
(iv) CODE-CALIBER CHECK recorded in the design doc section 3: V is
split V/17 per producer die at width 1 byte, every consumer die
receives every piece; B is ONE merged batch (A_merged = max_r sum_k);
A is 159 serial boundaries (A_serial = sum_k max_r) with R = layers
(compute scaling with device rate + K/V write + elementwise, fixed) +
propagation (<= 2e-6 of T); BookSim = one batch, all packets ready at
t = 0, one packet per node per cycle on a single injection channel,
completion = last delivery; extra statistics available: packet /
network / flit latency averages and hops average, no per-port
counters. RUNS: a_bandwidth_slices.py (A), b_fanout_search.py (B full,
3 seeds x 2000 steps from random + 1 clustered contrast),
b_shrunk_fanout_rerank.py (B shrunk, both judges). rerun_seating_seeds
now also stores each endpoint's seating (needed by the slices); its
values are unchanged by that, its hash is re-pinned below.
S7 RESULTS 2026-09-16 (hashes: a_bandwidth_slices.json 9edbd382ba78ff6b;
b_fanout_search.json dd4650e893aef0d4; b_shrunk_fanout_rerank.json
8335c7bdefe4720c; b3_shrunk_rerank.json RE-PINNED ac816866fed4df50
(now stores each SA winner's seating and BookSim's per-boundary
packet / network / flit latency and hop averages; every value
unchanged); seating_seeds.json RE-PINNED 3cf7038c993c9d3a (now stores
each endpoint's seating; values unchanged). Fast suite 434.

A -- BANDWIDTH SLICES (re-scoring, 20 candidates: 7 rules, 4 random
draws, 9 endpoints). Boundaries from P = the seven rules: B- 0.603,
B+ 1.427 GB/s (A_min 555.6M random, A_max 1314.8M sequential, R
921.20 ms, floor 523.0M). The identity G = r_ref * eta_achieved holds
DIRECTLY (T re-scored, not derived) at every point and reference to
the printed digits. Per reference: random seed 0 (= the best named
rule) eta_achieved 5.874% = eta_ceiling 5.87% -- the endpoint IS the
floor; strongest random draw (seed 3) eta 3.132% = ceiling 3.13%. G:
2B+ (2.855 GB/s) 1.02% / 0.53%; sqrt (0.928) 2.31% / 1.21%; B-/2
(0.302) 3.92% / 2.07%; 0.4: 3.53% / 1.86%; 12.5: 0.27% / 0.14% (vs
seed 0 / vs strongest). READING: at every bandwidth the search has
already taken ALL the headroom the analytic term can see; what varies
with B is only r_ref. Figure a_bandwidth_slices.png.

B -- FULL INSTANCE SEARCH (V = 1e6, 82 pairs, one merged batch, E2b
objective in words; t0 = span/20 = 0.586M words, alpha 0.996, 2000
steps, ~25 s per run). Three independent seeds from the random start
end at 16.35 / 16.24 / 16.24M (spread 0.72%); the clustered-start
contrast also reaches 16.24M. Every baseline and endpoint is LINK-
bound (link-only A == A with ports; port max = floor = 3.00M);
endpoints at A/floor 5.41. eta: +11.25% vs random seed 0, +8.61% vs
the strongest random draw (seed 4, 17.76M); the random draws span
17.76-19.24M (8.3%). READING: on the full instance the search removes
part of the shared-link contention and stays far above the port
floor; no packet judge at this size (intractable).

B -- SHRUNK COMPLETE INSTANCE UNDER TWO JUDGES (9 stages x 4 dies =
36 dies on 6x6, 13 pairs, V = 65,536 words, ~26.6k packets, merged
batch; 5 named rules, 5 random draws, 4 SA endpoints). Spearman
0.807 over 14 candidates; BookSim / ours 1.350..2.198; bound holds.
CAVEAT FIRST: on this grid the search endpoints ALL REACH THE PORT
FLOOR (A/floor 1.00, busiest = port) -- the shrunk instance does NOT
reproduce the full B's link-bound endpoint regime (5.41x), because 4
dies per stage on 36 slots leave room to route every pair below V
while 17 per stage on 576 do not. Under our judge every endpoint is
+25.0% vs the best random draw; under BookSim, against BookSim's own
best draw (random_s0): -5.61 / -5.13 / +2.64 / +6.56%; against our
best draw (random_s2): -0.01 / +0.44 / +7.80 / +11.51%. Top-1
differs (ours: a floor-tied endpoint; BookSim: the clustered-start
endpoint). READING: once the floor is reached the packet judge
splits the tie set both ways again, here by +-6%.

A -- TIE-SET DIAGNOSIS (item-3 instance, the two most different
floor-tied endpoints, snake-start 412,260 vs random-start 477,772
cycles). The single-die boundaries (attention in, out_proj in) are
cycle-identical (B/A = 1.00): no seating freedom, port-bound in both
judges. ALL the difference is on the 5 -> 5 die boundaries: ffn1@L0
1.33x, ffn2@L0 1.23x, ffn2@L1 1.37x (ffn1@L1 0.86x the other way).
BookSim's statistics: mean network latency 2289 -> 3067 cycles
(+34%; on ffn2@L0 1918 -> 4552), mean source-side wait (packet minus
network latency) 19,702 -> 23,225, hops 4.37 vs 4.39 (path length is
NOT the cause). So the discriminator inside the floor tie set is
DYNAMIC CONTENTION ON LINKS LOADED UP TO V -- exactly the load our
term treats as free (<= V costs nothing beyond the port). Per-port
arrival counters are not available in the bridge; this is what the
exposed statistics can say. Suggested (not run) analytic tie-breaker
for the writer's consideration: among floor-tied seatings prefer the
smaller total link occupancy or the fewer links at the floor value.

CONCLUSION (deliverable 4, also in search_setting_design.md sec. 6).
(1) A's further gain is limited by the PORT FLOOR of the R-split
mapping: the search endpoint sits on it at every bandwidth, the best
random draw is 3.1% above it in the communication term, and the
whole-model gain is that 3.1% (or 5.9% vs the seed-0 draw) times the
communication share -- 0.5-3.9% across the sampled band; nothing
below the floor is reachable by placement, only by the mapping. (2) B
removes SHARED-LINK contention: on the full instance the busiest
link's load falls 11.3% from the random fill and 8.6% from the best
draw while staying 5.4x above the floor; on the shrunk instance the
search removes all of it and lands on the floor. (3) The analytic
cost and the packet completion time support the same selection ONLY
DOWN TO THE FLOOR: whenever the search's endpoints are floor-tied
(A's endpoints everywhere; B's on the shrunk grid) BookSim orders the
tie set over +-6-11% and picks a different member, and against
BookSim's own best random draw the selected endpoint can lose (down
to -10% on A's shrunk instance, -5.6% on B's). Where the endpoints are
link-bound (B, full size) there is no packet judge at that size.

S8 PRE-REGISTRATION 2026-09-16 -- the writer's second-round notes
(Isobar_search_experiment_notes (1).md) with the three precisions
from review: (i) the pipe experiment tests 'does the selection and
gain change under the max-stage objective', NOT 'placement matters
more under pipelining' (no cross-stage shared network in the model);
(ii) intra+inter placement is NOT an existing capability -- beta does
not enter the whole-model score because the within-die communication
term is not wired in, which is 'not yet integrated', never 'measured
zero'; (iii) keeping 17 dies per stage in the shrunk BookSim instance
is the right shape, whether it keeps the link bottleneck is decided by
the result. Scope this round: port kappa sweep, 24x24 / 12x48
geometry, pipe-caliber search, 24x24 9x17 BookSim, tie-breaker
features and the objective ablation, intra-die integration on the A3
d=1024 data as a separate small task. Deferred: fork/gated-MLP
workloads, a finer pipeline timing model, BookSim multi-port.

CODE CHANGE, PINNED (test_s8_port_ratio_kappa): the hand-off term's
port capacity is now a parameter -- kappa = C_port / C_link, port
loads expressed in link-time units (divided by kappa), threaded as
W.port_ratio (default 1.0 = the standing model, bit-identical); kappa
-> inf recovers the wire-only term; a one-flow hand-off is unchanged
for any kappa. The load map behind the maximum is exposed
(resource_loads) for the tie-breaker features. SessionJ takes a
caliber. Every standing number is unchanged (suite must stay green).

S8-A PORT KAPPA x GEOMETRY (scripts/kappa_geometry_sweep.py ->
analysis/kappa_geometry_sweep.json + .png). Six cells: {24x24, 12x48}
x kappa in {1, 2, 4}; 576 slots, 544 occupied, the 2.7B per-op
mapping, XY, NeuRRAM rate. Per cell: the seven rules (seed 0) and
random seeds 1-4 re-generated ON THAT GRID; search = 3 start families
x 3 SA seeds, 1200 steps, alpha 0.996, t0 = span/20 over the seven
rungs at 0.4 GB/s (the S6 rule, so every cell gets its own scale);
each endpoint re-scored at 0.4 and 12.5. Read per cell: A_min/A_max
over P -> B-/B+ RECOMPUTED (the old 0.603/1.427 apply to 24x24
kappa=1 only); the port floor sum_b V_b / kappa and the endpoint's
binding resource (port-bound iff A == floor; link-bound iff A == the
wire-only sum); endpoint distribution; gain vs the strongest baseline
at both bandwidths; and, SEPARATELY, the hardware gain of kappa itself
(best baseline at kappa vs at kappa = 1, same grid), never folded into
the placement gain. EXPECTATIONS: at kappa = 1 the 24x24 cell
reproduces item 4 exactly; raising kappa lowers the floor by 1/kappa
and the endpoints follow it until a LINK binds, at which point the
endpoint becomes link-bound and the placement headroom above the
best baseline can GROW (the notes' hypothesis) -- or not; both are
reported; 12x48 has longer mean paths and a narrower bisection, so
the stacked rules get worse and the search's link-relief headroom
larger; no cell is required to show a gain.

S8-B PIPE CALIBER (scripts/pipe_caliber_search.py). What the pipe
caliber IS in the code: t_pipe = max over segments of (segment layers
x layer_s + the segment's own hand-off sum) -- a steady-state
initiation-interval estimate; no fill / drain, no microbatch count,
no cross-segment resource sharing, the cut fee zero; the segments are
the Pi's cuts, 32 single-layer segments for every generated seating
(the fixed pipeline strategy this round). Throughput = 1 / II. Cells:
24x24 at kappa = 1 and kappa = 4, 0.4 GB/s. Per cell: (1) baselines
and random draws under the pipe caliber; (2) the serial-selected
endpoints (S8-A) re-scored in pipe; (3) a search with the pipe
objective, 3 seeds from random. Read: does the ranking / the selected
seating change between calibers; the pipe gain vs the strongest
baseline (1 - II_search / II_ref) and the throughput gain; the two
calibers' selections cross-scored. Timed. THE CLAIM THIS CAN SUPPORT
is only 'selection under the max-stage objective', stated as such.

S8-C 24x24 SHRUNK FAN-OUT UNDER BOOKSIM (scripts/
b_shrunk_fanout_rerank.py, k = 24, 9 stages x 17 dies = 153 dies, 13
pairs, V scaled, recorded): the bottleneck type of baselines and
endpoints is READ, not imposed; if the search reaches the port floor
here too, that is the result.

S8-D TIE-BREAKER FEATURES (scripts/tie_features.py): on the four
floor-tied endpoints of the item-3 instance (BookSim order known:
snake 189.5 < clustered 191.0 < grs 199.4 < random 210.5 ms) and on
A's nine endpoints, read from resource_loads: total link occupancy,
the count of resources within 10% of the maximum, the second-busiest
load. Decide by discrimination first: if a feature does not separate
the floor-tied set in BookSim's order it is not added to the
ordering; if one does, it becomes a secondary key at a fixed
tolerance, validated on seeds it was not chosen on. Never 'pick by
BookSim then count it as analytic gain'.
S8-A RESULT (kappa_geometry_sweep.json sha256 8a2f0a326bfc086c; six
cells, 9 SA runs each, ~20 s per cell). EXPECTATION MISS, MINE: the
pre-registration said both 'kappa = 1 on 24x24 reproduces item 4' and
'every cell uses t0 = span/20'; the two are inconsistent (item 4 used
the declared 20 ms) and the run used span/20 (= 90.7 ms at 0.4 GB/s),
so the kappa = 1 cell reads 1.75% vs the strongest baseline (item 4:
1.86%), endpoints spread 1.31% (0.74%), best endpoint at A/floor
1.002 (1.000). That is schedule difference, not a finding; item 4
stays the record for the declared schedule, and every S8-A cell is
comparable to the others (same rule). RESULTS. Raising kappa halves
the port floor (523.0 -> 261.5 -> 130.7M link-time words) and the
endpoints become LINK-bound (A/floor 1.75 at kappa 2, 3.50 at kappa 4;
the strongest baselines likewise) -- and KAPPA = 2 AND KAPPA = 4 ARE
BIT-IDENTICAL in every reading on both grids: once ports run at twice
the link rate they never bind again, the package is link-limited and
B-/B+ stop moving (24x24: 0.535 / 1.420; 12x48: 0.515 / 1.285). Gain
vs the strongest baseline at 0.4 GB/s: 24x24 1.75% (kappa 1) -> 2.61%
(kappa >= 2); 12x48 2.52% -> 1.80/1.84%. At 12.5: 0.13 -> 0.18%; 0.19 ->
0.12%. So the notes' hypothesis -- the reference port setting hides
link-side placement headroom -- holds on the square grid by under one
point and NOT on the 12x48 grid, where the link-bound regime has a
stronger rule baseline (least_manhattan) and the search's margin over
it shrinks. Endpoint spread grows in the link-bound regime (1.1-1.3%
-> 3.9-4.3%): the search is noisier when links bind. Geometry alone
at kappa = 1: 12x48 gives the search 2.52% vs 1.75% on 24x24 (longer
paths punish the stacked rules; the strongest random draw is 1.048x
the floor vs 1.032x). THE HARDWARE GAIN OF KAPPA ITSELF, kept apart:
the best baseline improves 6.70% (24x24) / 8.03% (12x48) at 0.4 GB/s
and 0.51 / 0.62% at 12.5 when ports go to 2x the link rate, nothing
further at 4x -- larger than any placement gain in the table, and not
a placement result. ANSWER TO THE NOTES' FIRST QUESTION: the small
gain is only weakly determined by the reference port setting -- the
best case it opens is 2.6% against the strongest baseline, and on the
other geometry it closes.

S8-D RESULT (tie_features.json sha256 f0112337e3370299). On the
item-3 floor-tied set (BookSim order snake < clustered < grs-random <
random) NO feature separates in BookSim's direction: total link
occupancy rho = +0.40 (weak, 4 points), resources within 10% of the
max / at the max rho = -0.80 and second-busiest sum -0.80 -- the sign
OPPOSITE to the natural hypothesis (the BookSim-best endpoint has the
MOST resources at the floor value, 45 vs 37). 'At max' equals 'within
10%' everywhere: the near-max resources are exactly the consumer ports
at V_b plus the links at V_b, so the count is mostly the mapping. On
A's nine floor endpoints the features do vary (total occupancy 5.2%,
near-max count 18.6%, second-busiest 3.8%) but there is no packet
reference at that size. RULING per the pre-registration: no tie-
breaker is added to the ordering this round; the within-tie
difference BookSim sees is not captured by these load-map statistics,
consistent with the item-3 diagnosis (dynamic contention on links
below V, not the count of links at V).
S8-B RESULT (pipe_caliber_search.json sha256 b36d00515c871e4e; 24x24, 0.4 GB/s,
kappa 1 and 4; the pipe caliber = max over the 32 single-layer
segments of layer_s + that layer's hand-off sum, no fill/drain, no
cross-segment sharing; 1.45-1.55 ms per pipe step, the same cost as
single). THE SELECTION CHANGES WITH THE CALIBER: the strongest
baseline under single is random_s3, under pipe random_s1; baseline
rankings correlate 0.79 (kappa 1) / 0.83 (kappa 4); the best serial
endpoint and the best pipe endpoint are different seatings in both
cells. The pipe II of the strongest baseline is 1.09-1.10x the mean
layer time (T_single / 32): the busiest layer is ~9% above average.
FINDING F-P1 -- THE SUM IS THE BETTER SURROGATE EVEN FOR THE MAX:
re-scored in pipe, the SERIAL-objective endpoints beat the strongest
pipe baseline by 8.37% (kappa 1) / 4.91% (kappa 4), while a direct
PIPE-objective search of the same budget (3 seeds from random, 1200
steps, t0 = span/20 in II units) gains only 0.84% / 2.68% -- WORSE
than the serial endpoints re-scored, with the kappa-1 seeds ending on
one identical II (spread 0.00%) and the kappa-4 seeds spread 7.8%.
Mechanism, stated not proven: a max-over-layers objective is flat
under every move that does not touch the busiest layer (dJ = 0,
accepted as a random walk at t > 0), so SA has gradient on one layer
at a time; the sum objective moves every layer toward its floor and
therefore lowers the max as a by-product. Cross-scored in single, the
pipe endpoints are -0.58% (kappa 1) / +0.77% (kappa 4) vs the
strongest single baseline. ANSWER TO THE NOTES' SECOND QUESTION: the
existing pipe model opens NO new shared-resource contention (by
construction, stated in the design), it DOES change the selected
seating and the strongest baseline, and the practical rule it yields
is 'search on the sum, report under the max' -- valid only as a
statement about this steady-state II estimate.
S8 BUG, FOUND BY THE ABLATION AND FIXED 2026-09-16 (pinned:
test_s8_kappa_incremental_equals_full; suite 436). The kappa threading
reached Workload2p7B.boundaries() but NOT ScoreSession.update(), which
recomputes a move's affected boundaries by calling busiest_link_words
directly -- at kappa > 1 a session therefore mixed kappa-scaled cached
boundaries with UNSCALED recomputed ones, every recomputed boundary
jumped up, and from a good start every move was rejected (the ablation
showed it plainly: the 'ours' arm at kappa 4 returned its start for all
three seeds while the wire-only proxy, which never touches the session,
found a seating 11.9% better under ours' own T). Symptoms in the earlier
S8-A / S8-B numbers at kappa >= 2 (large endpoint spreads, gains from
the bad starts only, a negative pipe search) were this bug, not
findings. A SECOND PROTOCOL ERROR fixed at the same time: S8-A/B and the
ablation had used S6's t0 = span/20 rule on the A instance, ~4.5x
hotter than the declared 20 ms (item 4), turning most of the budget
into a random walk; the declared schedule is restored for the T
objective and every other objective runs at the same RELATIVE
temperature (20 ms x its rung span / ours' rung span). THE S8-A, S8-B
AND ABLATION RECORDS ABOVE ARE SUPERSEDED at kappa >= 2 (kappa = 1 is
unaffected by the bug; with the declared schedule it reproduces item 4
exactly: 1.86%, spread 0.73%, floor 1.000). Reruns in progress; their
results are recorded below when they land, replacing nothing silently.

S8-C STATUS: the 24x24 / 9 x 17 run was killed -- 571 s per candidate
(3,757 flows x 161 packets = 605k packets; my 60k estimate was a
flow-count error) and the batch duration parsed as 1 while packet
latency read 486k, i.e. the parse or the batch accounting fails at that
scale. Probes: single-source batches are exact to the flit up to 16k
packets; a 17 -> 17 R-split pair on k = 24 runs correctly at 2.9k /
11.6k / 46k packets (4 / 31 / 150 s). A 3-pair merged batch is being
run with the bridge's stdout captured to find the failure; the size
that keeps the shape (17 dies per stage, 13 pairs) is ~150k packets at
40 packets per flow (~6 min per candidate, ~1.4 h for 14) and only
worth running once the parse is understood.
S8-A RESULT, CORRECTED (bug fixed, declared schedule;
kappa_geometry_sweep.json sha256 c624443dde5b1349; supersedes the
earlier S8-A block). kappa = 1: 24x24 reproduces item 4 exactly (1.86%
vs the strongest baseline at 0.4 GB/s, 0.14% at 12.5, endpoints
spread 0.73%, endpoint on the port floor 1.000); 12x48: 2.69% /
0.20%, endpoint at 1.001x floor. kappa >= 2 (ports at 2x or 4x the
link rate; bit-identical between 2 and 4 -- ports never bind again):
THE SEARCH'S GAIN VS THE STRONGEST BASELINE RISES TO ~10% -- 24x24:
10.12% (kappa 2) / 9.92% (kappa 4) at 0.4 GB/s, 0.72 / 0.70% at 12.5;
12x48: 9.81 / 9.82% and 0.68 / 0.68% -- with the endpoints LINK-bound
at 1.50x (kappa 2) / 3.02x (kappa 4) the port floor and the strongest
baselines at 1.83x / 3.66x; endpoint spreads 1.2-2.4%. B-/B+ per cell:
24x24 0.603/1.427 (kappa 1), 0.535/1.420 (kappa >= 2); 12x48
0.608/1.301, 0.515/1.285. The hardware gain of kappa itself, apart:
the best baseline improves 6.70% (24x24) / 8.03% (12x48) at 0.4 and
0.51 / 0.62% at 12.5 going from kappa 1 to 2, nothing more at 4.
FINDING F-K1: THE REFERENCE PORT SETTING WAS HIDING THE LINK-SIDE
PLACEMENT HEADROOM. At kappa = 1 every good seating sits on the port
floor and the search can only close the baseline's 3% gap to it;
once ports run at >= 2x the link rate the busiest resource is a
shared link for every candidate, the strongest simple rule sits 1.8x
(kappa 2) above the new floor, and the search removes a third of
that excess -- about 10% of whole-model latency at 0.4 GB/s, under
1% at 12.5 where communication is 5% of the total. Geometry matters
little once links bind (9.8-10.1% on both grids); at kappa = 1 the
longer 12x48 paths give the search 2.69% vs 1.86%. ANSWER TO THE
NOTES' FIRST QUESTION, CORRECTED: the small gain IS largely a
consequence of the reference port setting -- one of the two
parameters the notes flagged as a placeholder -- and the placement
result at kappa >= 2 is a different regime, reported as such and not
as a hardware co-optimisation.

S8-B RESULT, CORRECTED (pipe_caliber_search.json sha256 ec4758ed7cacf44a;
supersedes the earlier S8-B block). Selection still changes with the
caliber (strongest baseline random_s3 under single, random_s1 under
pipe; rank correlation 0.79 / 0.83; the best serial and best pipe
endpoints differ in both cells). Re-scored in pipe, the serial
endpoints gain 10.89% (kappa 1) / 12.73% (kappa 4) vs the strongest
pipe baseline; the direct pipe-objective search at the same relative
temperature gains 6.70% (spread 6.3%) / 9.38% (spread 2.5%);
cross-scored in single the pipe endpoints read 1.17% / 4.38% vs the
strongest single baseline (the serial endpoints: 1.86% / 9.92%).
F-P1 STANDS WITH SMALLER MARGINS: the sum objective's endpoints beat
the max objective's own search under the max, and the max-objective
search is noisier. The mechanism paragraph in the superseded block
is unchanged. 1.46-1.63 ms per pipe step.
S8-U6 PRE-REGISTRATION -- intra-die cost integrated into a whole-model
objective on the data that exists (scripts/intra_die_integration.py ->
analysis/intra_die_integration.json). INSTANCE: the A3 co-residency
configuration (the 355M-class stack, d = 1024, attention offloaded,
production 2x4 macro mesh with glb centre), the ONLY instance with
stored within-die levers (soft_lever.json). PER-OP FORMULA, verbatim
from WithinDieJ.cost_of: t_op(beta) = write + prop + max(compute,
a3_ser(beta) x scale(g)), prop = stored latency - write - max(compute,
serial) -- so compute and write enter ONCE per op and prop is what the
stored latency had beyond them (asserted >= 0 for every op: the
double-count check). LAYER TIME T(beta) = fixed rest of the layer
(every op not on the two moved dies, same formula with its stored
serial) + C_attn(beta_attn) + C_ffn(beta_ffn); the stack is n_layers
identical layers, so layer shares are stack shares. READ PER ANCHOR g
in {0.1, 0.2, 0.4, 2.0, 8.0, 8.75} GB/s, prefill: the intra-die
communication-EXPOSED share of layer time (sum over ops of max(0, ser
x scale - compute) / T) at the shipped seating and at the exhaustive
best; the beta gain 1 - T(best)/T(shipped) and the band T(worst)/
T(best) -- the latter must reproduce the stored a3_stack_ratio rows
(identity anchor). THE FOUR GROUPS on this instance: rules = shipped
beta + sequential alpha; beta only; alpha only; both. What alpha can
do here is READ from the model, not assumed: the 355M-class chain
hands off one die to one die, and a one-flow hand-off's busiest
resource is its own volume for every seating (pinned degeneration),
so alpha moves only the propagation term (hops x 20 ns per hand-off)
and the energy column; its latency lever is bounded by (max hops -
min hops) x 20 ns x 47 hand-offs over the stack time, computed and
reported. If that bound is negligible the four groups collapse to
'beta only' in latency and the finding is the SEPARABILITY of the
current model: T(alpha, beta) = D2D(alpha) + sum_dies C(beta_die),
no coupling term (hand-off data entering a die is not distributed
over its macros), so the joint gain is the sum of the two -- which
licenses the two-level split on this model and names the coupling a
future model would need. 2.7B: NOT COVERED -- no within-die levers
exist for the A4 per-op mapping; recorded as 'not integrated', never
as 'no intra-die headroom'. The earlier 355M-instance suggestion is
withdrawn: this IS the 355M-class instance, and there is no other.
S8-U6 RESULT (intra_die_integration.json sha256 07cb65fc95291a67).
Double-count check passed (prop >= 0 for every op; compute and write
enter once). Identity anchor passed: the recomputed band T(worst)/
T(best) equals the stored a3_stack_ratio at every anchor to 1e-9.
Prefill, per anchor g: BETA GAIN (shipped contiguous -> exhaustive
best, whole layer = whole stack) 22.60% at 0.1 GB/s, 19.33% at 0.2,
9.52% at 0.4, 0.00% at 2.0 / 8.0 / 8.75 (the masked cell: no seating
exposes any serialization); the intra-die communication-EXPOSED share
of layer time at 0.4 is 26.7% at the shipped seating and 19.0% at the
best (80.7% -> 75.0% at 0.1); the two movable dies are ~60% of layer
time at every anchor. ALPHA ON THIS INSTANCE, read from the model:
the 355M-class chain hands off one die to one die, so alpha moves only
propagation -- total hops 47 (snake, clustered) to 209 (random), a
latency lever bounded by 0.0003% of the stack time -- and the energy
column. FINDING F-U6 (SEPARABILITY): on the current model T(alpha,
beta) = D2D(alpha) + sum_dies C(beta_die) + fixed, with no term
coupling a die's macro seating to the hand-offs entering it; the four
groups therefore collapse to 'beta only' in latency on this instance,
and on any instance the joint gain is the sum of the two levers.
This licenses the two-level split on this model and names exactly
what a coupled model would add (distributing an incoming hand-off
over the die's macros). 2.7B: NOT COVERED (no within-die levers for
the A4 mapping) -- 'not integrated', not 'no headroom'. ANSWER TO THE
NOTES' THIRD QUESTION: on the one instance where beta is priced,
intra-die placement adds 9.5% of latency at 0.4 GB/s (up to 22.6% at
0.1) on top of whatever inter-die placement gives, additively; the
inter-die lever on that same instance is nil in latency by the
one-flow degeneration; the two levers have never been priced together
on one instance, and cannot be until the 2.7B mapping gets within-die
levers.

S8 OBJECTIVE ABLATION RESULT (objective_ablation.json sha256
8a5a548dcb0ac337; 24x24, 0.4 GB/s, random start, 3 seeds, 1200
steps, ours at the declared 20 ms and every proxy at the same relative
temperature; every endpoint re-scored under ours' T_single and the pipe
II). kappa = 1: ours 1.83% vs the strongest baseline; wire-only (ports
unpriced) 1.78%, regret 1.0006; word-hops (distance / total traffic)
-0.68%, regret 1.026; max-hops (propagation only) -0.95%, regret 1.028.
kappa = 4: ours 10.96%; wire-only 10.35% (1.007); word-hops 0.97%
(1.112); max-hops 0.98% (1.112). So (a) the LOSS THE RESOURCE-AWARE
OBJECTIVE AVOIDS against the distance / hop proxies is 2.6-2.8% of
latency at kappa 1 and 11.2% at kappa 4 -- the proxies cannot even
beat the strongest simple rule at kappa 1; (b) PRICING THE PORTS
matters little to the SEARCH (0.06 / 0.69%) even though it mattered
to the reported gain against the outside judge -- the two are
different questions; (c) under the pipe II the ours endpoints gain
10.05% / 13.63%, the proxies' endpoints lose (-5.9 / -8.3%). ANSWER TO
THE NOTES' FOURTH QUESTION, analytic half: the search improves on the
strongest baseline stably (3 seeds within 0.1-1.1%) at every kappa,
by 1.8% at the reference ports and ~10-11% once links bind; the
packet-judge half stands where item 3 left it (agreement down to the
floor; the link-bound regime's packet check is S8-C, pending).
S8-C SCALE PINNED: the 24x24 merged batch is exact at 71k packets (6
pairs, 137,789 cycles, 58 s) and at 154k packets (13 pairs at V/4,
349,201 cycles, 138 s); the failure ('Overall min batch duration = 1'
with packet latency 486k) appeared only at 605k packets (13 pairs at
the full V). Where between 154k and 605k the batch accounting breaks
is not bisected further; S8-C runs at V = 87,500 words per pair = 40
packets per flow, 154k packets per candidate. STARTUP / DRAIN SHARE at
that size, to be read from the result as the notes require: a flow's
serialization is 40 x 17 = 680 flits against ~46 hops x 14 = 644
cycles of pure latency on the longest paths -- comparable, so the
run's packet-latency and network-latency averages are reported next
to the batch duration and the reading is labelled 'short-flow
regime' if network latency dominates. Full run: 14 candidates x ~140
s + 4 SA runs, in the background.
S8-C RESULT (b_fanout_24x24_rerank.json sha256 c635d4272c4f6d04; 24x24, 9 stages
x 17 dies = 153 dies, 13 pairs +2/+4/+8, V = 87,500 words per pair =
40 packets per flow, ~154k packets per candidate, one merged batch;
4 named rules, 5 random draws, 4 SA endpoints; ~130-750 s per
candidate). THE SHAPE IS PRESERVED: every candidate is LINK-bound
(A/floor 1.47-7.43; the search endpoints 1.47-1.51, the random draws
2.06-2.33, the stacked rules 6.3-7.4), so this IS the full instance
B's regime, unlike the 6x6 shrink. Spearman 0.962 over 14
candidates; BookSim / ours 1.442-2.107 (bound holds); the strongest
random draw is THE SAME under both judges (random_s4); top-1 differs
only between two endpoints 0.1% apart under BookSim (71,423 vs
71,513 cycles). THE SEARCH'S GAIN UNDER THE PACKET JUDGE, against the
best random draw: +30.95 / +30.86 / +17.12 / +11.97% for the four
endpoints (ours: +26.67 / +28.57 / +26.67 / +28.57%). All four beat
the baseline under BookSim; the magnitudes spread more than ours'
(the two 0.396M-word endpoints read 31% and 17%). Startup / drain,
as required: the endpoint's mean network latency is
5514 cycles against a batch duration of 71423
(7.7%), packet latency (incl. source wait) 28123 --
serialization dominates; NOT a short-flow regime. FINDING F-C1: IN THE
LINK-BOUND REGIME THE ANALYTIC COST AND THE PACKET COMPLETION TIME
SUPPORT THE SAME SELECTION -- same best baseline, every endpoint
ahead of it under both judges, rank correlation 0.96 -- whereas on
the port floor (item 3, the 6x6 shrink) they parted company. The
term is a ranking instrument where links bind and a floor detector
where ports bind; both statements are now measured, on instances
that preserve the respective regime. ANSWER TO THE NOTES' FOURTH
QUESTION, packet half: yes, in the link-bound regime the independent
re-evaluation supports the selected seating, by +12-31% against the
best random draw; in the port-bound regime it does not order the
tie set (item 3).

S9 PRE-REGISTRATION 2026-09-17 -- the closing round (Isobar_search_
experiment_notes (2).md): the paper's MAIN CONFIGURATION is kappa = 2,
and the headline search result is the ~10% whole-model latency
reduction at fixed hardware; kappa = 1 and 4 are sensitivity.
MAIN CONFIGURATION, frozen: the 2.7B weight-resident instance (d 2560,
32 layers, per-op mapping qkv 4 / attention 1 / out 2 / ffn1 5 / ffn2
5 dies per layer), 544 of 576 dies on a 24x24 mesh, XY, NeuRRAM-
derived row rate, serial prefill whole-model latency as the main
objective (batch 1, S = 512), link bandwidth 0.4 GB/s per link per
direction (main) and 12.5 (high-bandwidth contrast), kappa = 2 --
each die's injection and ejection capacities are independent
resources of kappa x B (0.8 GB/s each at the 0.4 point, 25 each at
12.5); kappa is the ratio of effective terminal capacity to one
link's, not a port count and not a sum. Search protocol = S8-A's
(SessionJ on T_single at 0.4, 3 start families x 3 independent SA
seeds, 1200 steps, alpha 0.996, t0 = the declared 20 ms). Baseline
set = the seven named rules at seed 0, random seeds 1-4, and the A4
default fill, all re-scored at the main configuration.
THE HEADLINE STATISTIC, declared before export: the standing protocol's
output is 'best over the three start families' for one seed; with
three seeds that gives three outputs, and the headline G is their
MEDIAN, with min and max beside it; 'best of nine' is reported as a
separate, labelled number and is NOT the headline. G = 1 -
T(selected) / T(strongest baseline), same workload, hardware,
execution and objective; the gain vs the A4 default fill is exported
separately as the cost of the deployment choice. The old 3.53% /
0.24% / any '45%' are not carried over.
TASKS. A (scripts/main_config_export.py -> analysis/main_config_
results.json + .md): every layout at the main configuration, both
bandwidths, both phases (decode = one token attending over the S =
512 cache, batch 1), with config identity, real inputs, cost
decomposition, resource loads, baseline identity, protocol, seed
statistics, runtime. B (fig_phase_isobar.py with ISOBAR_KAPPA=2 ->
phase_diagram_isobar_k2.png; the kappa = 1 figures stay as the
sensitivity version): the package panel's seven-rule A(p; kappa=2),
B-/B+, envelope ratio, 20% spread, the two physical bandwidth points'
regions; the intra-die panel unchanged (its constants do not see
kappa -- checked in code). EXPECTATION: each rule's A falls or stays,
both boundaries fall or stay, the envelope ratio need not be
preserved (kappa = 1: 2.37x). Then the fixed-pair bandwidth slice at
kappa = 2 (bw_slice_k2.py): the strongest baseline and the selected
endpoint across 0.4, 12.5 and 2B+, sqrt(B-B+), B-/2 of the NEW
boundaries plus 0.2 and 2.0; T, H, G, r, eta; G = eta r as identity.
C (objective_ablation.py, ABL_KAPPAS=2, endpoints' seatings stored):
E0 vs the distance / hop proxies at the main configuration, same
space / start / seeds / budget / relative temperature; the kappa = 4
ablation keeps its label (reuse would need the generation protocol
shown equal; the proxies' generation ignores kappa, ours' does not
along the path, so the main-configuration arms are rerun, not
inferred). D: the BookSim bridge's ability to express kappa = 2 is
checked and either used on the frozen layouts (E0 selection,
strongest baseline, E1 selection) or the interface gap and the
minimal change are recorded; kappa = 1 is never written up as a
reproduction of the kappa = 2 experiment; S8-C stands as the method
validation on the synthetic fan-out batch. E: A3 re-evaluated with a
denominator that includes the package hand-offs of its own chain (two
one-flow hand-offs per layer at 0.4 GB/s, kappa-invariant by the
one-flow degeneration) -- whether 9.5% moves is decided by that
number; decode = one re-evaluation of the main candidates (ranking
vs prefill, communication share); a decode search only if the
ranking changes materially. Every percentage is exported with its
absolute times and denominator.
S9 RESULTS 2026-09-17 (hashes: main_config_results.json 14aef79132b48ed8;
phase_diagram_isobar_k2.json 947b56cb0bc39311; bw_slice_k2.json
ca08e2ef67aa2b31; objective_ablation_k2.json e9952f2f7466060a;
intra_die_integration.json 8ab3b135deadc0b2 (re-pinned: now carries the
package-inclusive denominator, earlier fields unchanged). Suite 436.)

TASK A -- THE MAIN CONFIGURATION, FROZEN AND EXPORTED
(main_config_results.md is the paper table). Prefill, 0.4 GB/s,
kappa 2: strongest baseline random_s3 at 2118.71 ms;
per-seed best-over-starts 1914.07 (sa_random_s0), 1908.82 (sa_random_s1), 1904.24 (sa_random_s2) ms;
HEADLINE G = 9.91% (median of the three seeds, selected layout
sa_random_s1 at 1908.82 ms), range 9.66-10.12%,
best-of-nine 10.12% (sa_random_s2, labelled, not the headline);
vs the A4 default fill 54.5% (the default is the stacked
fill at 4193 ms); communication share 56.5% at the
strongest baseline -> 51.7% at the selected layout; every
layout link-bound (A/floor 1.5 endpoints, 1.8 random draws). 12.5 GB/s:
G = 0.70% (0.68-0.72%), communication share 4.0%.
DECODE (one token over the 512-token cache, batch 1), 0.4 GB/s:
strongest random_s3 26.53 ms, G = 1.57% (1.52-1.59%),
communication share 8.8%; 12.5: G = -0.21% (strongest
least_manhattan; inside noise). Ranking prefill vs decode over all 21 layouts:
Spearman 0.987; the prefill-selected layout is #2
in decode -- the two phases scale the same placement cost by a
common factor, so NO decode search (the pre-registered rule).
Config identity and real inputs exported in the JSON (d 2560 / d_ff
10240 / 32 layers / 32 heads; S = 512; per-layer compute 24.66 ms,
write 2.86 ms, elementwise 1.26 ms in prefill; row time
10.14 us; 20 ns/hop, 10 pJ/word; search t0 20 ms, 2.6 s per run).

TASK B -- PHASE DIAGRAM AT KAPPA 2 (phase_diagram_isobar_k2.png,
_print_k2.png). Seven-rule package envelope: A_min 492.8M (random),
A_max 1308.6M (sequential), ratio 2.656x (kappa 1: 2.366x --
the ratio ROSE because the ports had been capping the dispersed
rules' A; at kappa 2 the envelope equals the wire-only one, 2.656);
B- 0.535, B+ 1.421 GB/s at the NeuRRAM rate (kappa 1: 0.603 / 1.427;
both fell or stayed, as pre-registered); 0.4 GB/s below B-, 12.5
above B+. Intra-die panel unchanged (2.67x; its constants do not
read kappa -- confirmed in package_A's docstring and by the identical
readout). FIXED-PAIR SLICE (random_s3 vs sa_random_s1, kappa 2):
eta = 17.53% at every point; G / r: 0.2 GB/s 12.66% / 72.2%,
B-/2 11.57% / 66.0%, 0.4 9.91% / 56.5%, sqrt(B-B+)
6.55% / 37.4%, 2.0 3.62% / 20.6%, 2B+ 2.71% / 15.5%,
12.5 0.70% / 4.0%; identity |G - eta r - residual| <= 2.8e-16.

TASK C -- OBJECTIVE ABLATION AT THE MAIN CONFIGURATION (random start,
3 seeds, 1200 steps, ours at 20 ms, proxies at the same relative
temperature; all endpoints re-scored at kappa 2). Ours: best 1886.5 ms
(10.96% vs the strongest baseline; median 1911.0); wire-only
10.19% (regret 1.0086); word-hops 0.85% (regret
1.1135, loss avoided by ours 11.35%); max-hops 0.98%
(regret 1.1121, 11.21%). Under the pipe II the ours endpoints
gain 13.63%, the proxies lose. The kappa = 4 ablation's numbers
coincide to the digit (ports never bind at kappa >= 2 for any
candidate on the path), which is now MEASURED, not inferred; it
keeps its label. The ablation's own 'ours' arm (10.96% best) is a
different protocol from the headline (random start only, other
seeds) and is not the headline.

TASK D -- BOOKSIM AT KAPPA 2: NOT EXPRESSIBLE with the current bridge
or the stock knobs. The patched BookSim gives each node ONE injection
and ONE ejection channel at the network channel width (the declared
injection caliber); the configurable knobs are subnets (replicates
the whole network, links included -- kappa unchanged), c
(concentration: several nodes SHARE one router's terminal -- kappa
falls, not rises), injection_rate / injection_process (offered load,
not capacity) and input_speedup / output_speedup (crossbar port
expansion inside the router, not terminal bandwidth). A cycle-to-
seconds rescale does not change kappa. MINIMAL CHANGE, not made this
round: in KNCube / the file-traffic batch manager, allocate kappa
injection and kappa ejection channels per node (router radix +kappa
each side) with the source's packets round-robined over its injection
channels -- a network-construction patch, not a config change. Per
the notes' 6.3: tasks A/B/C/E completed on the analytic side; S8-C
(kappa 1, synthetic fan-out batch, rho 0.962, +12-31%) stands as the
method validation; the kappa = 1 packet checks are NOT written up as
a reproduction of the kappa = 2 experiment.

TASK E -- A3 WITH ITS CHAIN'S PACKAGE HAND-OFFS IN THE DENOMINATOR
(two one-flow hand-offs per layer, V = 512 x 1024 words, 2.62 ms per
layer at 0.4 GB/s, kappa-invariant): the package term is 5.3% of
the layer at 0.4, and the beta gain reads 9.02% instead of 9.52%
(0.1 GB/s: 22.28% vs 22.60%; 0.2: 18.79% vs 19.33%; >= 2: 0). So
9.5% -> 9.0% with the package in the denominator; both are layer-
level numbers of the 355M-class instance and neither is added to the
2.7B whole-model 9.9%. DECODE: see task A (one re-evaluation; ranking
preserved at 0.987; no search).

S10 2026-09-17 -- the review-closing notes (Isobar_search_experiment_
notes.md, third version), code-side tasks only; no new search, no
model change. Hashes: main_config_results.json 70c420e27bdf3c2e (re-pinned:
random-sample statistics and the percentage ledger added; every earlier
value unchanged); mechanism_table.json 2cbe03e33e8a5570;
intra_die_correspondence.json 20f6692b7e9c6463. Suite 436.
TASK A1 (main_config_results.md): the random sample is the five declared
seeds, prefill 0.4 GB/s kappa 2: 2153.11, 2128.21, 2145.74, 2118.71, 2151.96 ms, median 2145.74,
min 2118.71 (random_s3), max 2153.11 (random), spread 1.62%; the strongest
baseline among rules + draws is random_s3. Search: per-seed best-over-
starts 1928.63 (s0) / 1908.82 (s1) / 1904.24 (s2) ms, all from the
random start; median 1908.82 (the headline layout), range
1904.24-1928.63. The LEDGER lists every paper percentage with its
numerator layout, denominator layout, absolute times and statistic;
the 54.5% vs the default fill uses the SAME median-selected layout
(1908.82 / 4192.5 ms at kappa 2). The A4 default fill IS the sequential
rule (identical loads, hotspots and latency), recorded.
TASK A2 (mechanism_table.md): total word-hops, per-boundary busiest link
and port / kappa, binding, A by boundary type, hotspots, for the default
fill, five rules, random s0, the strongest draw and the headline layout.
MECHANISM, from the loads: R-split multicast makes a 5 -> 5 hand-off 25
flows of 1.05M words; the distance-driven rules reach 4.1-4.2G word-hops
(2.9 hops) but stack 10-25 of those flows on the link between two
compact groups (sequential / default: all 25 on one link, 26.21M;
clustered 10; nmap 10-12; least_manhattan 10-15), while the random
fills at 22.6-22.8G word-hops (16 hops) stack 8-10 and therefore have
the lower busiest-resource sum (479-493M vs 494-652M). The search keeps
the dispersion (15.4 hops) and de-stacks the rest: 5 flows on the
busiest ffn2 links (5.24M = 2x the port floor), 55 of 159 boundaries at
'busiest link = port floor', A 479 -> 395M (-17.5% of the term, -9.9%
of the model); the reduction sits in ffn2 (181 -> 158M), attention (93
-> 69) and out_proj (69 -> 47); qkv is at its floor for every layout.
nmap_greedy is described by what the code does (words x centroid
distance, NMAP's construction + one-sweep structure, no per-link
capacity term) and NOT as 'ignoring congestion'; the original's
bandwidth-constrained formulation is flagged for the writer to verify.
TASK B (intra_die_correspondence.md): Fig. 1(a) and the A3 text case
ARE THE SAME INSTANCE -- gpt2-medium class, d 1024, d_ff 4096, S 512,
the 2x4 macro mesh with glb centre, the same NeuRRAM row time (10.14
us). Fig. 1(a) is the ffn die alone (ffn1 (512,1024,4096) on 4 slots +
ffn2 (512,4096,1024) on 4, 70 seatings; 2.67x = A_max 8.389M / A_min
3.146M busiest macro-link words; B- 0.303 / B+ 0.808 GB/s at that
rate); the text's 9.02% is the whole layer (attn die 280 seatings +
ffn die 70 + fixed rest 19.01 ms + the chain's two package hand-offs
2.62 ms at 0.4 GB/s): 49.597 -> 45.125 ms. HOW THE LOCAL COST ENTERS
THE LAYER: per op write + prop + max(compute, serialization(beta) x
scale) -- the max model -- so the panel's H-vs-R boundaries are the
masking thresholds exactly: above B+ every seating compute-bound (gain
0 at >= 2 GB/s, measured), below B- every seating serialization-bound,
0.4 inside the band. Per-op state at 0.4: shipped has all four ops
serialization-bound (qkv 6.99 vs 5.19 ms compute, out 5.24, ffn1 5.24,
ffn2 10.49); the exhaustive best makes both attn ops compute-bound (3.50,
0.00) and trades ffn1 up (7.86) to bring ffn2 down (5.24) -- the joint
optimum minimizes the sum of the two maxima, not each. 2.67x and 9.02%
are different quantities of one instance and are not converted into
each other.
TASK C (baseline_provenance.md): original work -> implemented rule ->
optimized quantity -> resource information -> adaptation -> what is not
implemented, for sequential (= default), snake, clustered (Gemini's
named strategy, not Gemini's mapper), least_manhattan (SIAM's rule, not
its framework), nmap_greedy (NMAP's structure on a distance-weighted
cost, the bandwidth constraint not implemented), heaviest_first (LPT
lineage), random (five declared seeds). No rule prices links or ports.

F-FIG1a CORRECTION 2026-09-17 (review's numeric check on the intra-die
panel). THE ERROR: Fig. 1(a) drew its boundaries as B_+- = A_min,max /
(N/s + F) with N = 10.384 ms, the SUM of the two ffn ops' compute, while
A was the busiest SINGLE op's serialization words (mech = max over ops)
and the A3 cost model is per-op max(compute_op, ser_op) with compute_op
= 5.192 ms for each op. So the panel compared one op's serialization
with two ops' compute and placed both boundaries a factor 2 too low
(0.303 / 0.808 GB/s); the 20% spread contour used the sum-model formula
S = (A_max - A_min)/(B R + A_min), which is not the max model's spread.
Verified from the enumeration before changing the figure: per-op compute
5.1917 ms each; A_min 3.1457M / A_max 8.3886M (ratio 2.6667, unchanged);
correct thresholds B- = A_min / c = 0.6059, B+ = A_max / c = 1.6158
GB/s; at 0.4 GB/s 0 of 70 seatings are fully compute-bound, at 2.0 all
70 are; max-model spread over the 70 seatings 100% at 0.4, 50% at 0.808,
31% at 1.0, 0 at 1.616 (and above). THE FIX (fig_phase_isobar.
intra_die_model / intra_die_curves, shared by the print script): the
intra-die panel is now built from the enumeration under the max model
-- boundaries B_c(beta) = A(beta) / c(s) with c the PER-OP compute
(masking thresholds; slope +1, the write + prop term does not enter the
switch), the 20% contour solved by bisection per s on (T_max - T_min)/
T_min with T(beta) = fixed + sum_ops max(c(s), ser_op/B) over the 70
seatings. Readings now: B- 0.606, B+ 1.616, spread-20% at
1.154 GB/s at the NeuRRAM rate; 2.67x unchanged; 0.4 GB/s BELOW B-
(communication dominated: every seating has an exposed op, the seating
sets how severe -- consistent with the per-op table where the
exhaustive best still has both ffn ops serialization-bound), 2.0 GB/s
above B+ (all masked -- consistent with the measured zero gain at >= 2).
The package panel was never affected: its cost model IS the sum. All
four figures regenerated (phase_diagram_isobar{,_k2}{,_print}.png);
phase_diagram_isobar_k2.json 68e1f14536723d5f, phase_diagram_isobar.json
c7d45dd589317adb; intra_die_correspondence.json re-pinned 4e71d2a5be1652bf
(its 'local state at 0.4' now reads 'below B-' from the numbers).
SUPERSEDED STATEMENTS: 'within-die B- 0.303 .. B+ 0.808' in the Fig.1
rebuild record and 'B- 0.303 / B+ 0.808 ... 0.4 inside the band' in
S10 task B; the 9.02% layer gain and the 2.67x envelope are untouched.
Suite 436.

S10 SECTION 6 -- DYNAMIC ENERGY OF THE FROZEN LAYOUTS 2026-09-17
(energy_export.json c6448eaf1958fa15, energy_export.md; main_config_results.json
re-pinned 174e9f09ec54464f with energy columns and dE ledger rows, every
earlier value unchanged). THE MODEL AS CODED: E = n_layers x sum_ops
E_op (per-op CiMLoop records, array compute and writes) + n_layers x
E_elementwise (glb + arithmetic of the digital unit) + E_d2d, with
E_d2d = sum over flows of payload words x max(XY hops, 1) x 10 pJ/word
(a flat one-hop charge on every delivered word plus the surplus
beyond reference_hops = 1; die_flow_surplus_energy); the coefficient is
the midpoint of Simba's measured GRS band (0.82-1.75 pJ/bit, Zimmer et
al. JSSC 2020); static power is NOT modelled (idle_power_w = None);
energy is independent of B and kappa. Recomputing E_comm from words x
max(hops,1) x pJ matches the evaluator to 8e-16; the seven rules' E
equals ladder_v0's e_J (kappa 1) exactly, as it must. SEAT-INVARIANT
TERMS: E_ops 2.270 J, E_elementwise 0.0265 J, E_d2d flat 0.0142 J;
only the surplus (hops beyond one) moves with the seating.
ANSWERS (main configuration, prefill, vs the strongest latency
baseline random_s3, E 2.5229 J of which communication 0.2259 J = 8.96%):
(1) the headline layout sa_random_s1 (-9.91% latency) has E 2.5163 J:
dE = +0.26% (a small REDUCTION), communication energy +2.94%; all
nine endpoints lie between +0.10% and +0.56% -- the latency search carries
no energy penalty on this configuration, and the effect is small
because communication is ~9% of dynamic energy for the dispersed
layouts. (2) The distance rules DO turn their short paths into a
communication-energy advantage: E_comm 0.0412 / 0.0424 / 0.0410 J
(least_manhattan / nmap / clustered) vs 0.2259 J, i.e. 81-82% less communication
energy, which is 7.32 / 7.28 / 7.33% of SYSTEM dynamic energy -- bought
at 1.79 / 3.96 / 20.37% more latency than random_s3 (and 11-33% more than the
headline layout). The E-best layout of the set is clustered (2.3379 J);
the sequential / default fill is neither (2.3937 J, +97.9% latency).
So on this configuration placement moves dynamic energy by up to ~7%
(compact vs dispersed) and the latency-selected layout sits at the
dispersed end with a 0.3% energy edge over its own baseline: the
trade-off is real between families and absent within the search's
family. (3) A3's 9.02% layer latency gain has NO modelled energy
counterpart: the macro link carries no pJ/word and the d = 1024 per-op
records carry no energy, so intra-die energy is 'not modelled', never
'zero'; what it would need is stated in the export.

CORRECTION 2026-09-17 to the S10 task A1 text above: the per-seed
best-over-starts values at the main configuration are 1914.07 (s0,
random start) / 1908.82 (s1) / 1904.24 (s2) ms, as main_config_results.json
records; the '1928.63' written in the A1 paragraph was a transcription
error (the exported table and the headline 9.91% were never affected).
The range against the strongest baseline stays 9.66 to 10.12%.

PROGRESS REPORT (5) 2026-09-17: analysis/phase_diagram_report.tex
rewritten in full to the DAC outline v2 (the writer's instruction names
the tex explicitly). Baseline replaced: Progress Report (4) of 09/15.
Content: the phase diagram at the main configuration with both panels on
their own execution models, the platform with its energy model and
validation table, the deployment optimisation with the unified main
table, the mechanism, the intra-die layer result, the energy table, the
objective ablation, the bandwidth slice, the kappa / geometry / decode
sensitivity, the baseline provenance, and four open items. New figures
for it: seating_seeds_k2.png (the main search's budget-quality curves,
the same nine runs as the main configuration's endpoints) and
mechanism_ablation.png (path length vs bottleneck load; the same-budget
ablation). No LaTeX toolchain is available here; the file passed a
structural check (balanced environments, every figure file present,
every tabular row matching its column count, no dash characters).
PROGRESS REPORT (5), FORM CLARIFIED 2026-09-17: the tex is a PROGRESS
REPORT in the previous reports' manner (what was done in the period,
what was found, what it means, what remains), written in the stance of
the DAC outline v2; the outline served to align narrative, data and
conclusions, not as the document's structure. Sections: the hand-off
term and the port ratio; the phase diagram redrawn; the main
configuration (choice of kappa, protocol, unified results); the
mechanism and the baseline provenance; the intra-die level; the
objective ablation; sensitivity incl. the pipeline caliber as a
project-record item; dynamic energy; validation and efficiency; the map
of results into the paper and the open items. 7 figures, 8 tables, no
dash characters, structural checks passed; no LaTeX toolchain here.
NUMBERING CORRECTION 2026-09-17: the compiled report that precedes this
one is Report (2) (the 09/15 tex; the '(4)' in that file's own title was
wrong), so the new tex is PROGRESS REPORT (3). It reports the progress
since 09/15: the hand-off term with ports and the port ratio, the
certified region classification and the soft-lever ceiling, the
enumerated solver check, the phase diagram rebuilt, the main
configuration and its statistics, the mechanism, the intra-die layer
result, the objective ablation, the sensitivity set, dynamic energy, and
the validation and efficiency rows. Title and cross-references updated.BASELINE CORRECTION AND FULL REWRITE 2026-09-17: the compiled report that
precedes this one is Progress Report (2) dated 08/20/2026 (the PDF the
writer supplied: platform, system model, two perspectives, two ratios,
"placement-aware search the natural next step"). The 09/15 tex was a
working draft and never a report; the note above that called it Report
(2) is withdrawn. analysis/phase_diagram_report.tex is therefore
rewritten as PROGRESS REPORT (3) covering 08/20 to 09/17 in full:
(1) the phase diagram (one cost model for both perspectives, the device
axis and the fast edge with the fixed-terms figure, the measured width
family with its flip and the boundary table, the diagram at kappa = 2
with per-panel execution models, the certified / observed quantifiers,
hardware references incl. the HERMES headroom, G = eta r); (2) the
evaluator and solver (hand-off term with ports, the port floor,
incremental scoring, the annealer, the partition DP and the exact B5
check, the exhaustive intra-die solver, run time); (3) validation (Simba
silicon, the HERMES accounting check, the BookSim bridge and its
conversion table, the ranking checks incl. the referee rerank and the
24x24 fan-out task, the scope sentence); (4) the search (the kappa = 1
ladder table and figure, the referee experiment with the three condition
axes, the choice of kappa from the geometry sweep, the frozen protocol and
budget curves, the unified table, statistics and decode, the mechanism
and the provenance table); (5) the intra-die layer result and the
separability of the two levels; (6) the objective ablation; (7) the
bandwidth slice, geometry, port ratio, decode, and the pipeline caliber
as a project-record item; (8) dynamic energy; (9) the map into the paper
and four open items. 11 figures (device_fixed_terms, scaling_law_vds,
phase_diagram_isobar_k2, simba_validation, ladder_v0, search_s6,
kappa_geometry_sweep, seating_seeds_k2, mechanism_ablation, bw_slice_k2,
the TikZ workflow), 10 tables. Every number re-read from
main_config_results.md, mechanism_table.md, energy_export.md,
bw_slice_k2.json, ladder_v0.json, kappa_geometry_sweep.json,
b5_joint_exact.json, b7_s6_rerank.json, scaling_law_summary.json and the
FIXLIST entries C31 / C32 / S6 / S8 / S9 / S10; the ladder and kappa
captions were checked against the rendered images. Structural check
passed: 0 dash characters (no em, en or double hyphen), environments
balanced, every figure file present, every tabular row matching its
column count, every reference resolved. No LaTeX toolchain here; not
compiled.
REPORT (3) REVISION 2026-09-18 (four writer items): (1) the parameter
table (tab:params) and the other text-heavy tables set on p-columns with
tabcolsep 4pt so that every table sits inside the 15.9 cm text width
(sums 15.55 cm); the main table, the intra-die table and the energy
table given shorter headers and labels with the meanings in the
captions. (2) The Simba validation figure in colour for the report:
scripts/fig_simba_validation_color.py, same live data as
analyze_simba_validation.py, repository palette (slate measured bars,
green optimistic rail, brick pessimistic rail, navy / amber / green per
layer on T3), titles and annotations without the internal record tags;
output analysis/simba_validation_color.png; the greyscale figure and its
script untouched. (3) The objective-ablation panel of
mechanism_ablation.png redrawn: three seed bars per objective in the
objective's colour with the best value labelled, replacing the
best-seed bar with seed dots; data unchanged. (4) The closing section
now states the next steps (the paper, further refinement of the
simulator and search, measured calibration) in place of the list of
open technical items; abstract and introduction pointers updated.
Structural checks passed again (0 dashes, environments balanced, figures
present, tabular rows matching, references resolved). Not compiled here.
VECTOR MAIN FIGURE 2026-09-18: scripts/fig_phase_isobar.py and
scripts/fig_phase_isobar_print.py now also write a PDF next to the PNG
(phase_diagram_isobar{_SFX}.pdf, phase_diagram_isobar_print{_SFX}.pdf),
from the same figure object, with pdf.fonttype 42 so the text is
embedded TrueType and stays selectable. Regenerated at ISOBAR_KAPPA=2:
the PNGs and the JSON came out byte-identical to the committed ones
(git reports no change); the PDFs contain no raster objects (0 image
XObjects, 3 embedded fonts, no Type 3), page boxes 12.8 x 5.0 in (large)
and 7.16 x 3.35 in (print). The PDFs fall under the analysis/* ignore
rule and are not whitelisted; add them to .gitignore's whitelist if they
are to be committed.
FIG. 1 REGION LABELS 2026-09-18 (review item 4): panel (a) is a per-op
max model, so its in-figure region labels now say exposed / masked
instead of dominated: "communication masked" above B+, "placement
decides what is exposed" in the band, "communication exposed (placement
sets how severe)" below B- (the words "for every placement" dropped on
review as redundant); the
print version uses "communication masked" / "placement decides" /
"communication exposed". Panel (b), a serial sum, keeps the dominated
wording. Implemented as a labels argument of draw_panel / panel
(LABELS_SUM default, LABELS_MAX for panel (a)) in fig_phase_isobar.py
and fig_phase_isobar_print.py; all four PNGs and both PDFs regenerated
at kappa 1 and 2; JSON unchanged. phase_diagram_isobar_caption.md
records the wording.
ISAAC LINK RATES CORRECTED 2026-09-18 (reviewer item, verified against
the paper). The reviewer stated that ISAAC publishes a 32-bit, 1 GHz
on-chip link (4.0 GB/s) and a 6.4 GB/s off-chip link in Table I. VERIFIED
by re-reading Shafiee et al., ISCA 2016 (users.cs.utah.edu/~rajeev/pubs/
isca16.pdf, text extracted here): Sec. VIII-B says "we estimate that the
inter-tile link bandwidth requirement never exceeds 3.2 GB/s. We
therefore conservatively assume a 32-bit link operating at 1 GHz" = 4.0
GB/s; Sec. VIII-A says "the c-mesh flit width is set to 32 bits"; Table I
lists "Router flit size 32, num port 8 (shared by 4 tiles)" and "Hyper Tr
links/freq 4/1.6GHz ... link bw 6.4 GB/s". The figure's 4.8 GB/s came
from multiplying the 32-bit flit by 1.2 GHz, which is the TILE clock
("ISAAC Tile at 1.2 GHz", Table I header), not the link clock; the C36
note "no per-link figure published" was also wrong. Both were flagged as
un-re-read in the 2026-09-16 entry above, and are now closed.
APPLIED: anchors.py ISAAC gains ondie_gbps_per_link 4.0 and d2d_gbps 6.4
with sourced status strings (the 0.4-8 band is kept, and its status still
starts with "estimated", for the standing device-plane figure and its
test). fig_phase_isobar.py and fig_phase_isobar_print.py: panel (a) ISAAC
moves 4.8 -> 4.0 GB/s and becomes a FILLED (published) marker; panel (b)
ISAAC leaves the shared assumed range and becomes a published point at
6.4 GB/s, so Mythic M1076 is now the only assumed range there. All four
PNGs and both PDFs regenerated at kappa 1 and 2; JSON unchanged.
READINGS: at ISAAC's row rate panel (a)'s band is 3.90-10.40 GB/s, so the
point stays inside the band and no argument changes; panel (b)'s band is
1.94-5.14 GB/s, so the published 6.4 GB/s sits just ABOVE B+ where the
old assumed range had spanned the band. Suite 436 passed after the
anchors change. Docs synced: ANCHORS.md row, phase_diagram_isobar_
caption.md (marker paragraph + a correction note), and the report tex
(Table 2 now has two ISAAC link rows, and the reference paragraph).
PAPER FIGURE SET v1 2026-09-18: six candidate figure groups and their
standalone panels built into a NEW tree,
analysis/figures_dac2027/20260918_v1/{panels,composites,data,preview},
by a new generator scripts/plot_dac2027_v1.py (--run-id selects the
directory; --only re-runs one group). No existing figure path is written:
the manifest carries a sha256 inventory of the 77 figures already in
analysis/ so a later run can show they are unchanged. Every panel ships as
PDF (vector, fonttype 42) + SVG (text kept as text) + PNG preview; every
panel's numbers ship as JSON/CSV in data/.
GROUPS: Fig. 1 the two-level phase diagram (redrawn from the isobar
module's own data functions into new files, plus separate (a)/(b)
panels); Fig. 2 the platform workflow, schematic, with a two-producer
worked example; Fig. 3 external references (Simba T1 ladder; the 13-
candidate fan-out ranking against BookSim, rho 0.962); Fig. 4 deployment
gain (latency split into R and H for eight layouts, the latency/energy
scatter over all 21 frozen layouts, the A3 layer bars); Fig. 5 the
mechanism on the real fabric (three layouts' directed link loads for the
SAME stage ffn2@L2 on the real 24x24 grid, one shared colour scale in
required link service time at 0.4 GB/s, ports reported separately as
readings, plus the objective ablation); Fig. 6 the conditions (bandwidth
slice, kappa x geometry, prefill vs decode).
DATA: Fig. 5's loads are extracted live through search_eval.resource_loads
on rebuilt layouts (clustered / random_s3 / sa_random_s1 /
least_manhattan) and reproduce the mechanism table exactly at that stage
(busiest link 10.49 / 8.39 / 5.24 / 6.29 M words); links, ports and
endpoints are exported per layout as CSV with coordinates.
STATISTICS: the ablation panel uses the recorded denominator (each arm's
best endpoint over the resource-aware objective's best, 1886.5 ms),
reproducing +11.4% / +11.2%; the kappa panel recomputes one statistic for
every cell (median over 3 seeds of best-over-starts vs that cell's
strongest evaluated baseline).
ALSO CORRECTED: the report tex said the fan-out ranking covered 14
candidates; the JSON has 13 (sequential, snake, clustered, dispersed,
5 randoms, 4 search endpoints) and rho 0.9615 is the n = 13 value.
FIGURE AUDIT OF analysis/ 2026-09-18 (77 figures reviewed against the
current frozen conclusions; four parallel reviews, each required to quote
its evidence from FIXLIST / SUMMARY / METRICS / MATERIALS / the live tex).
DELETED (6; all six were git-tracked, so `git checkout` restores them):
 - seating_seeds.png: kappa = 1 budget curves from the 3.53% era, with no
   kappa in the title; superseded by seating_seeds_k2.png, which is the
   figure the report uses.
 - bw_slice_pair.png: the kappa = 1 fixed-pair slice (eta 5.874%,
   G 3.53% at 0.4); superseded by bw_slice_k2.png.
 - scale_combined.png: its own suptitle is the retired F-L1 claim, "every
   latency lever hides behind compute (zero-overlap end <= 3%)", against
   today's 1.97x spread on the production instance and F-L5's 6.8%.
 - scale_tier_2p7b.png: drew all three 2.7B seatings at exactly 1.00x,
   the sentence the 09-15 rerun ordered rewritten or withdrawn.
 - phase_diagram_gray.png: deleted as an unreferenced twin, then
   RECREATED by analyze_phase_diagram.py in the same run (that script
   writes both files); it now carries the corrected ISAAC markers, so it
   is kept.
 - corner_flip.png: re-run under the current model it is three flat lines
   at exactly 1.00 (corner_flip.json: flips_gbps empty for all three
   conditions), i.e. an empty exhibit; the measurement stays in the JSON.
REDRAWN after correcting hard-coded on-figure text that asserted a retired
claim (data was current; only the caption lagged):
 - contention_by_layout.png: "moving the glb to a corner funnels more
   macros' traffic onto one wire" -> the measured 1.00x on the 2x4
   production grid, with the 3x3 comparison named.
 - d2d_regimes.png: the single-pass panel's "transfer hides behind the
   stack's compute" now says it holds on THIS small chain and not on the
   production instance.
 - d2d_assignment_impact.png: suptitle said "same 24 dies" while the data
   is the 48-die configuration (a leftover of the 24-to-48 change).
 - offload_contention.png: the "removes the two shields" framing and the
   self-refuting decode panel title (the 2.26x/4.35x reading was the C25
   unit error and is retired).
 - placement_energy_latency.png, placement_link_loads.png: the O8
   artifact text "energy set by MEAN hop count" / "variants with the same
   mean hop count cost the same energy", retired at C59 when the
   per-scheme wire models broke the tie.
 - placement_impact_onchip.png, placement_impact_offload.png: "energy
   does not care" -> the spread named as over those three chain-like
   seatings only (S10 measures up to ~7% compact vs dispersed).
 - a_bandwidth_slices.png: title now names its cell (the port-floor
   instance at kappa = 1), which is what makes "achieved gain = the
   port-floor ceiling" true.
 - phase_diagram.png (+ its gray twin): analyze_phase_diagram.py now
   draws ISAAC as a published point (inter-tile 4.0 GB/s, off-chip
   6.4 GB/s) instead of the 0.4-8 GB/s assumed band; anchors.py keeps the
   band for the device-plane figure and its test.
KEPT AS IS: the remaining figures, including the deliberately declared
ones (device_plane's HERMES C37 aggregate; ladder_v0 at kappa = 1, which
the report labels as such). NOT ACTED ON, reported instead: SUMMARY.pdf is
a 2026-07-01 render of a document rewritten on 09-17 with no generator and
no citation, and it is untracked, so deleting it would be unrecoverable;
sweep_axis_d2d_probe.png and resnet18_settings_compare.png have no record
either way. analysis/ladder_v0.md still describes the pre-port version of
its own PNG (ppm panel, F-L1/F-L2) and needs rewriting.
PAPER FIGURE SET v2 2026-09-21 (review notes v2 of 09-19), a NEW tree
analysis/figures_dac2027/20260921_v2 from a new generator
scripts/plot_dac2027_v2.py; v1 and every pre-existing figure untouched.
FIG. 5 REPLACED: the 24x24 single hand-off (10 endpoints on 576 slots) is
dropped as the mechanism figure. New controlled instance: the real
ffn1 -> ffn2 hand-off of the 2.7B mapping (5 producer dies, 5 consumer
dies, 25 flows of 1.05 M words, 26.2 M words) placed on a 4x4 die mesh
(ic.Mesh, xy, hub centre) with 6 empty slots, flows built by
search_eval._one_boundary_flows and loads by resource_loads at kappa = 2,
0.4 GB/s. Layouts: compact fill (row-major consecutive slots), random
seeds 0-4 (best = seed 3), and the annealer (swap / migrate, Metropolis,
1200 steps, alpha 0.996, t0 = 10% of the start's cost, starts = compact
and random seed 0, seeds 0-2, best over starts per seed, median seed
shown). Readings: busiest resource 20.97 / 15.73 / 10.49 ms, all
link-bound (8 / 6 / 4 flows on one link); the port floor is 6.55 ms and
never binds; every search run reached 10.49 ms. These are hand-off
service costs on this instance and are NOT the 24x24 stage readings of v1
(26.2 / 21.0 / 13.1 ms), which belong to the 544-die layouts. Drawn as a
node graph (P1-P5 / C1-C5, both directions as offset lines, unused links
faint, busiest resource ringed with flows and ms). (d) the main-config
objective ablation as a dot plot from zero: excess over the best
resource-aware endpoint (1886.5 ms); best proxy +11.4% / +11.2%.
FIG. 2 now carries a real fragment of that instance (8 flows x 1.05 M
words on one link = 21.0 ms; a consumer port 5.24 M words / 2 = 6.55 ms)
and the three aggregation rules. FIG. 3: titles state what each panel
validates; rho recomputed on the 13 candidates drawn WITH average ranks =
0.953 (the recorded 0.962 used ordinal ranks over two tied analytic
values); 154,037 packets is one candidate's batch. FIG. 4: (a) legend
"Non-communication / Package communication", tick strips for the 5
random fills and 9 endpoints, 9.91% between the two bars, 54.5% vs
4192.54 ms; (b) per-rule attribution (Least Manhattan -7.3% energy /
+1.8% latency; Clustered +20.4% latency), families stacked / heuristics
/ random / search, snake named; (c) "Whole-layer impact of intra-die
assignment", "Contiguous assignment", 9.02% as a vertical bracket, the
fixed rest incl. package transfers kept. FIG. 6: (a) "Bandwidth response
of fixed placements" with r, eta and G on one percent axis and ticks at
0.4 / 0.872 / 12.5; (b) "Port capacity and mesh geometry", the port-floor
sentence replaced by "port capacity limits the remaining gain", statistic
recomputed per cell from the runs (per seed best of 3 starts, then median
and min-max over seeds). Formal captions in captions.md, author notes in
figure_index.md, nothing of either inside a figure. Not committed.
PHASE DIAGRAM, REFERENCE-LINE VARIANT 2026-09-21 (writer's request after
the anchor discussion): fig_phase_isobar.py gains ISOBAR_REFS=lines,
writing phase_diagram_isobar{_kN}_refs.{png,pdf,json} as SEPARATE files;
the standing figures are unchanged. Panel (b) changes: (1) the two
evaluated bandwidths 0.4 and 12.5 GB/s are horizontal dashed reference
lines across device speeds, since they are bandwidth tiers and not a
NeuRRAM property; (2) the two NeuRRAM-based circles stay at the NeuRRAM
row rate and are joined by a vertical line, the two configurations
evaluated at one device rate; (3) the M1076 assumed 0.4-8 GB/s range is
replaced by ONE hollow diamond at (0.157 Mrows/s, 1.0 GB/s): the
product page's PCIe interface capability of 2 GB/s (io_gbps, new
registry field with its status) matched to the model's port capacity,
kappa x B = B_IO, so B = 1.0 GB/s at kappa = 2. A projection, labelled
"M1076-derived, I/O-matched"; not a published link rate. Legend rewritten
accordingly. The ISAAC label moves left of its marker in this variant to
clear the 12.5 GB/s line.
REFERENCE-LINE VARIANT, REVISED 2026-09-21 (same file names): the two tier
lines are muted purple-grey (0.9 pt, 75% opacity, dashed), run a little
past the right frame and are bracketed OUTSIDE it by a vertical
double-headed arrow with "12.5 GB/s" above and "0.4 GB/s" below, so no
number sits inside the plot; the ISAAC label is back at its standing
position; the two NeuRRAM circles keep their per-point labels plus the
joining line; the M1076 label sits below-right of its marker, clear of
the solid boundaries.
PHASE DIAGRAM FINAL FORM 2026-09-21: the reference-tier treatment is now
the DEFAULT of fig_phase_isobar.py and fig_phase_isobar_print.py (the
previous form is reachable with ISOBAR_REFS=old into *_old files, for
comparison only); all four standing files regenerated at kappa 1 and 2,
the *_refs trial files removed. Final decisions, all writer's: the two
evaluated bandwidths 0.4 / 12.5 GB/s as muted purple-grey dashed tiers
across device speeds, values inside the frame, a slate double-headed
arrow (the envelope arrow's style) just outside the right frame touching
both lines, labelled "Reference bandwidth span"; the two NeuRRAM circles
joined vertically, labels straight above / below; M1076 as ONE hollow
diamond at (0.157 Mrows/s, 1.0 GB/s), its published 2 GB/s PCIe I/O
capability matched to kappa x B (io_gbps in anchors.py, pinned by
test_m1076_io_capability_and_projection; suite 438); the ISAAC label a
little lower; the 20% contour label without a backing box; legend
rewritten as marker SEMANTICS with no chip names: lines on the left
(boundaries B-/B+ merged into one entry, 20% spread, the two tiers),
markers on the right (filled diamond = published parameter projected
onto this instance; hollow diamond = derived or alternative-mode value,
i.e. HERMES 4-phase and the M1076 projection; circle + line =
configurations evaluated here), six single-height rows so the columns
align. Synced: v2 figure set Fig. 1 (fig1_phase_diagram and panels,
caption), the report tex (reference paragraph + a "Mythic M1076 I/O" row
replacing "Assumed package range"), phase_diagram_isobar_caption.md,
ANCHORS.md, SUMMARY.en.md / SUMMARY.md. Not committed.
FIG. 2 REDESIGNED 2026-09-22 (writer's discussion): (a) four coloured
regions with distinct roles: Given inputs (workload; mapping, tiling and
dependencies, given, not generated here; hardware and execution
configuration), the Simulation core as ONE evaluation (logical flows ->
routed paths under the fixed XY rule, not optimised -> link and port
loads per hand-off -> latency and dynamic energy, with the compute /
write / digital-unit costs entering the aggregation separately and the
placement drawn as an INPUT box), Phase analysis (calls the same
evaluation, double arrow) and Deployment search (receives the candidate's
latency; returns a revised placement into the placement box and a revised
partition into the flows, which are regenerated). (b) "how two flows
become resource costs" with a symbolic payload V: two independent flows
routed under XY share one directed link (2V), link service bound 2V/B,
endpoint port bound V/(kappa B) = V/(2B), cumulative traffic 4V byte-hops;
peak demand enters timing, cumulative traffic enters energy; illustrative.
Drawn in inch coordinates at the 7.16 in column width, 6-8 pt text, arrows
above the region fills. Files fig2_platform_workflow (composite),
fig2a_platform, fig2b_two_flows in the v2 tree; caption updated.
FIG. 2, SECOND REDESIGN 2026-09-22 (writer's review of the first): 70/30
split. (a) the flow as four tinted regions without borders: Given inputs
(workload; operator tiling and tensor dependencies, given; hardware and
execution configuration entering routing, accounting and aggregation
through ONE configuration line); Evaluation of one candidate, top to
bottom, with the candidate deployment (gamma, alpha, beta) as a dashed
INPUT box, logical communication from gamma, routing under alpha and
beta by the fixed XY rule, link and port loads per hand-off, "resource
bounds and execution-aware aggregation", latency and dynamic energy;
Phase analysis calling the evaluation (double arrow); Deployment search
with block partition and die-group sizing (DP) and die / macro placement
(annealing / enumeration), latency in and the next candidate back to the
candidate box. (b) replaces the step-by-step single-layout example with
the contrast "equal hop cost, different contention": the same two flows
(3 + 1 hops, 4V byte-hops, port bound V/(2B)) placed so that they share a
directed link (max load 2V, bound 2V/B) or do not (V, V/B), which is why
the evaluator keeps per-resource loads and why distance or word-hop
proxies cannot separate the two. Restrained palette (warm grey, slate,
sand, sage), hairline node edges, 5.5-6.8 pt text at the column width.
FIG. 2(b), THIRD FORM 2026-09-22 (writer's review of the two-layout
contrast: a classroom example that only says "a shared link adds up"):
panel (b) is now one complete evaluation profile of a real hand-off,
"From placement to resource costs", in three layers at the same 30% width.
(1) The source of the traffic in one line: the ffn1 -> ffn2 hand-off of
the 2.7B mapping, 5 producers x 5 consumers, 25 transfers of 1.05 M words.
(2) The Fig. 5 instance's compact fill on the 4x4 die mesh, evaluated live
by the evaluator's own flow and load code (_one_boundary_flows,
resource_loads, Mesh xy): every link direction coloured and widened by its
cumulative load after all 25 transfers are routed, empty slots faint, the
busiest link ringed and labelled once (8 flows, 8.4 M words, 21.0 ms at
0.4 GB/s), and the five routes of one producer (P4, the longest routed
fan-out) as dotted lines so the logical fan-out is seen entering the
network. (3) A low bar profile of the service time L_e / B of all 15 used
link directions, busiest first, in the same colour scale, against the port
bound max L_p / (kappa B) = 6.6 ms; the tallest bar carries the same ring
as the hotspot and the label "-> latency term"; the 64.0 M word-hops of the
same evaluation stand beside it as "-> dynamic energy". Reads: the load
concentrates on a few links, the hand-off is link-bound, the evaluator
extracts its latency term from that link. Numbers in
data/fig2b_placement_to_costs.json; panel fig2b_placement_to_costs; the
fig2b_two_flows and fig2b_contention_contrast panels are withdrawn.
Caption updated. Note: a --only fig2 run rewrites captions.md and
manifest.json with only this figure's entries; the full set is regenerated
before the next commit.
FIG. 2(b) STYLE PASS 2026-09-22 (author's review): producers and consumers
share one colour and differ by shape only (square / round); link loads on
a blue -> violet -> red ramp (light to heavy) shared by the bars; every
segment carries a pale base band so idle links are a background, not a
line; loaded lanes 1.6-3.4 pt; the bar profile is aligned to the mesh's
left and right edges; the hotspot label is reduced to "8 flows / 8.4 M
words" (the service time is read from the bar profile); the fan-out routes
are white dotted lanes.
DOCUMENTATION FREEZE 2026-09-22 (markdown only, by instruction). The
results stand frozen at the main configuration (S9 / S10, the ISAAC and
M1076 corrections of 09-18 / 09-21 included). Rewritten for readers: the
root README (what cimsim is, the frozen results table, what one evaluation
computes, how to run, the repository map), formulation.md (now the cost
model as frozen: objects, the hand-off term over links and ports, the
port floor, R + H, the intra-die overlap model, dynamic energy, the phase
diagram's boundaries, G = eta r, the search) and workspace/README.md (the
workspace map). New folder guides: analysis/README.md,
analysis/figures_dac2027/README.md, scripts/README.md (every module by
role), tests/README.md, models/README.md, models/fabric/README.md,
tools/README.md, tutorials/README.md, outputs/README.md. Removed as
superseded reports: analysis/PROGRESS.md (its conclusions 1 and 5 were the
retired F-L1 position) and analysis/SUMMARY.Extn.md (the pre-platform I/O
cost model on BERT-100M); both remain in git history. SUMMARY.en.md and
SUMMARY.md carry a status block naming the frozen documents as the
authority; METRICS.md's old 1.4-2x envelope row is replaced by the two
frozen bands and its kappa = 1 rows are labelled as sensitivity cells;
SEARCH_SPEC.en.md carries a status line. Non-markdown changes needed for
this freeze are listed for approval in the session, not applied.
FIG. 2(b) FOURTH FORM 2026-09-22 (writer's review, Gemini heat-map idiom):
"Resource accounting". Only the occupied rows of the 4x4 instance are
drawn (3x4; the code asserts that no XY route enters the idle top row, so
the 15 used directions, the 8-flow hotspot and the 64.0 M word-hops are
unchanged). Each physical link is two lanes, one per direction: a thin
dark line when idle, a bar coloured by cumulative load when used, fixed
lane width, blue -> violet -> red shared with the bar profile. The fan-out
routes and the ring are gone; the hotspot is marked e* with "8 flows /
8.4 M words" and the tallest bar with "e* 21.0 ms" (its link service
bound). The bar profile takes the freed height (1.02 in), the port bound
is labelled beside its line, the x axis reads "Directed links, sorted",
the cumulative traffic is the bare "64.0 M word-hops" and its relation to
the communication dynamic energy is in the caption. The title block is
"RESOURCE ACCOUNTING / FFN1 -> FFN2 . 5->5 dies . 25 transfers"; the
mapping and the per-transfer payload moved to the caption. Text 5.0-6.2 pt
at the drawn 2.06 in width.
FREEZE, APPROVED NON-MARKDOWN CHANGES 2026-09-22: .gitignore whitelists
analysis/README.md, outputs/README.md and tools/README.md (the tools rule
changed from a directory pattern to `workspace/tools/*` so a file inside
can be re-included; booksim2 stays ignored); analysis/SUMMARY.pdf (a
2026-07-01 render of a document rewritten since) and the two old report
sources company_report.tex and settings_and_assumptions.tex deleted;
phase_diagram_report.tex (Progress Report 3) kept. Local work notes
removed as superseded: DIRECTION.en.md (a 09-01 direction memo, never
referenced) and frozen_v6.md (the v6 citation snapshot of 09-05, whose
numbers the S9 freeze replaced). The script-written readout tables
(a2_row_split, a4_full_model, the weave and price readouts, soft_lever,
robustness, phase_diagram_table, SIMBA_PREREG, ROBUSTNESS_CRITERIA) are
current inputs of standing analyses and stay.
FIG. 2(b) STYLE PASS 2 2026-09-22 (author's review): one type scale (title
6.2 pt bold, node labels 5.2 pt bold, every other text 5.6 pt, ticks
5.2 pt, one text colour); nodes white with a dark edge and black labels;
each lane drawn as a road (dark rim, white inside when idle, load colour
inside when used) running centre to centre under the nodes so no gap is
left at round nodes; the bar profile back to 0.60 in high.
FIG. 2(b) STYLE PASS 3 2026-09-22 (author's review): node pitch 0.38 in,
node edge 1.0 pt (heavier than the 0.5 pt road rim), node labels 6.0 pt
centred on the cap height; e* set in plain text (mathtext had switched
the font); the hand-off line aligned to the mesh's left edge and the
vertical whitespace tightened; the load ramp is blue -> red with the
violet interval narrowed so the hotspot is the only saturated red.
FIG. 2(b) STYLE PASS 4 2026-09-22 (author's review): the load ramp runs
from a true blue (#2a7de1) to the hotspot red (#c41e1e) with a short
lavender middle; the hotspot reading "e* 8 flows . 8.4 M words" sits under
the mesh and a bare e* marks the lane, which frees the left margin; the
bar profile spans the full mesh width with the port-bound label lifted
above the short bars; the mesh is centred in the panel.
FIG. 2(b) STYLE PASS 5 2026-09-22 (author's review): the load colours are
the ten-step RdBu ramp (16,70,128 ... 109,1,31). Used as a plain
sequential ramp its white middle fell on the 10.5 ms lanes (7 of 15) and
made them vanish against the idle white lanes, so the ramp is centred on
the port bound (TwoSlopeNorm, white = 6.6 ms): lanes below the port bound
are blue and cannot bind, lanes above are red, the hotspot is the deepest
red; the caption says so. Lanes 3.4 pt at +-0.040 in, empty slots drawn at
full node size with the thin rim, node pitch 0.42 in, mesh and bar profile
enlarged to fill the panel (bars 0.78 in high, full mesh width).
FIG. 2(b) STYLE PASS 6 2026-09-22 (author's review): the cumulative
traffic reads "Total routed traffic / 64.0 M word-hops"; producer nodes
are rounded squares at 0.92 of the circle radius (a square reads larger
than a circle of the same size); node pitch 0.40 in; the e* mark sits on
the left of the hot lane, the side the lane itself is on.
FIG. 2(b) STYLE PASS 7 2026-09-22 (author's review): node labels 6.4 pt,
node edge 0.85 pt, node pitch 0.38 in (shorter links), the bar profile
raised to 0.38 in so the two plots sit closer.
FIG. 2(b) COMPARISON VARIANT 2026-09-22 (author's request, the standing
panel untouched): fig2b_placement_to_costs_alt with node radius 0.105 in,
node edge 0.70 pt, node pitch 0.34 in, and idle lanes filled with the
ramp's zero colour (dark blue) instead of white; the bar profile follows
the narrower mesh and its e* reading is set on two lines to stay clear of
the traffic label. Drawn by _fig2b(alt=True).
FIG. 2(b) VARIANT, PASS 2 2026-09-22: node labels in regular weight, idle
lanes in a light desaturated blue (#b4c3d3) instead of the ramp's dark
end, no lane rims (plain colour bars), a short colour bar to the right of
the mesh with ticks at 0, the port bound and the hotspot (ms). The
standing panel is unchanged.
FIG. 2(b) VARIANT, PASS 3 2026-09-22: the idle lanes are the zero colour
of a variant ramp (LOAD_BR_ALT) whose blue end is lightened and
desaturated to (62,104,150) yet stays the darkest blue, so idle < 2.6 ms
< ... on one scale; node labels 6.8 pt regular (the regular weight read
smaller than the standing panel's 6.4 pt bold); the colour bar is 0.46 in
high and bottom-aligned with the mesh; the bar profile spans the mesh plus
the colour bar. The standing panel is unchanged.
FIG. 2(b) VARIANT, PASS 4 2026-09-22: the variant ramp's blue end moved
to #2D75A5 = (45,117,165) (the author's choice), still the
darkest blue on the scale.
FIG. 2(b) VARIANT, PASS 5 2026-09-22: the variant ramp's first peach stop
deepened to (247,203,180) so the 7.9 ms lanes read as pink rather than
near-white; lanes 3.9 pt at +-0.044 in.
USER GUIDE 2026-09-22: a reader-facing integration guide added at the
repository root, docs/ (README plus ten pages: setup, concepts, hardware,
workload, evaluate, search, phase diagram, external checks, results and
figures, scope and FAQ). Every command and Python snippet in it was run
in the container on the frozen tree and reproduces the frozen readings
(438 tests; clustered 2550.35 ms; strongest baseline random_s3 2118.71 ms;
headline 9.91 percent, best of nine 10.12 percent; package band 0.535 to
1.421 GB/s; BookSim gate ratio 1.001). No code changed. Gaps the guide
states rather than hides: the evaluator has no command-line entry (the
snippets are the entry), Workload2p7B reads one fixed account file (the
guide gives a subclass that reads another), and the D2D energy and
propagation constants of the evaluator are module constants.
FIG. 2(b) VARIANT, PASS 6 2026-09-22: the variant ramp's blue end is the
midpoint of #2D75A5 and the next stop, (47,120,174). The colour bar is
drawn by hand (one 512-sample raster strip through the same TwoSlopeNorm
inside a framed inset axes) because matplotlib's colorbar mesh under a
TwoSlopeNorm left its fill and outline misaligned in the PDF and SVG;
checked by rasterising both at 12x (fill and frame coincide).
FIG. 2(b) VARIANT, PASS 7 2026-09-22: node edge 0.85 pt, empty-slot edge
0.4 pt, node labels 6.5 pt. Regenerated with the host's latency-bench
environment (the plotting script needs only matplotlib and numpy; the
container was unresponsive under a load average of ~40).
FIG. 2(b) VARIANT, PASS 8 2026-09-22: node labels 6.0 pt bold; the dark
lane rims are back on in the variant (for comparison against the rimless
pass).
COMMAND LINE 2026-09-22 (author's request, after the user guide): a
unified entry, scripts/cimsim_cli.py, with the subcommands baseline
(the seven rules to a deployment JSON), evaluate (score, decomposition
and a per-hand-off table with the binding resource), search (the
annealer with the frozen protocol as defaults: starts, seeds, 1200
steps, alpha 0.996, the per-bandwidth temperature; headline statistic
and strongest-baseline comparison as in main_config_export), phase (the
package band B-, B+ at the fabric's device rate and the classification
of given bandwidths, JSON and a one-panel figure) and booksim (one
hand-off of a deployment through the bridge at a volume scale). Common
options: --fabric, --workload (any per-operator account), --kappa,
--phases, --caliber, --device-scale, --d2d-pj-per-word, --d2d-ns-per-hop
(the last two override search_eval's module constants). The CLI wraps
the platform's functions and adds no model. Fabric schema: a level may
declare `ports: {ratio: kappa}` (Level.port_ratio, validated >= 1);
mlx300_multidie576.yaml declares 2.0 on the die level, read only by the
CLI as its default kappa (the experiment scripts set W.port_ratio, so no
frozen number moves). Tests: tests/test_cli.py (group 56) pins the CLI
against the frozen readings (clustered 2550.352 ms at kappa 2 and 0.4
GB/s; band 0.535 to 1.421 GB/s) and the port-ratio field. The guide's
pages 03 to 08 now give the commands, with their outputs as run.
FIG. 2(b) VARIANT, PASS 9 2026-09-22: lane rim 0.4 pt, lane width 3.65 pt.
FIG. 2(b) FINAL FORM 2026-09-22: the comparison variant becomes the
standing panel and the variant switch is removed. Node pitch 0.34 in,
node radius 0.105 in, node edge 0.85 pt (empty slots 0.4 pt), node labels
6.0 pt bold; lanes 3.65 pt at +-0.044 in with a 0.4 pt rim; one ramp,
the RdBu ten-step with the blue end at (47,120,174) as the idle-lane
colour and the first peach stop at (247,203,180), centred on the port
bound; a hand-drawn 0.46 in colour bar bottom-aligned with the mesh; the
bar profile spans mesh plus colour bar; the e* reading on the tallest bar
lifted by 1.2 ms. The fig2b_placement_to_costs_alt files are withdrawn.
captions.md and manifest.json: the other figures' entries, wiped by the
--only fig2 runs, restored from HEAD; only the fig2 entries are new.
FIG. 2(a) REDESIGN 2026-09-22 (writer's label review + author's style
brief): drawn in the reference flowchart idiom, four tinted zones with
dashed borders and centred bold titles, filled step boxes with white text,
white data boxes, one blue -> teal palette (the author's colour card: deep
72,80,152 for titles, blue 70,96,173 for the core steps, mid 90,150,204
for phase analysis, teal 128,205,187 for search, sky 104,180,206 for the
input edges; no red, orange or green). Labels as reviewed: Inputs =
Workload / Model, sequence length; Operator tiling & dependencies;
Hardware & execution settings with the routing rule, capacities, device
speed and execution mode as small type inside the box. Isobar evaluation
core = Deployment configuration (Partition & placement, dashed input) ->
Extract logical transfers (Sources, destinations, volumes) -> Route &
accumulate loads (Fixed routing; link & port loads) -> Evaluate
communication costs (Service time from loads; traffic energy) ->
Aggregate execution costs (Overlap on chip; serial hand-offs) -> Latency
& dynamic energy, with a side box "Compute, write & digital costs" fed by
the hardware settings and entering the aggregation. Phase analysis =
Sweep device rate & bandwidth -> Extract phase boundaries, a two-headed
arrow to the core labelled configurations / cost estimates. Deployment
search = Partition & group sizing (DP) -> Die placement (SA) / Macro
assignment (enumeration), latency in, "updated deployment" back to the
configuration box. The gamma/alpha/beta symbols and "not optimised" are
gone from the figure. Caption (a) rewritten to match; (b)'s title colour
follows the same palette.
SUMMARY REWRITE 2026-09-22 (author's request): SUMMARY.en.md and the
local SUMMARY.md rewritten whole to the paper's stance instead of the
stage-by-stage account: the question and the stance (placement is a
phase), the instrument, the phase diagram (boundaries, device axis and
fast edge, width family, the diagram at kappa 2, G = eta r), the
deployment search (port floor, evaluator and solver, the named rules and
the referee, the port-ratio choice, the frozen protocol), the results at
the main configuration (headline table, mechanism, intra-die level,
objective ablation, bandwidth slice and cells, dynamic energy), the
validation table, the earlier findings the diagram rests on (energy
denominators, the on-die network at the NeuRRAM tier, scheme dependence,
the K/V write, offload, die-to-die, the mapping as the third hand, value
energy, regime tags), scope, platform inputs, running the platform
(the command line) and the document index. Stage codes and correction
history are left to this record; superseded readings are not restated.
The two files carry the same content. Previous versions are in git.
FIG. 2(a) SECOND PASS 2026-09-22 (writer's arrow review + author's colour
note): palette without the purple-leaning blue: inputs green (165,197,130)
on the left, core steps mid blue (90,150,204), phase analysis teal
(128,205,187), search olive (214,207,103), titles dark slate. Arrows:
configurations / cost estimates run between the phase-analysis zone and
the core zone's boundary at the header level (module to module, not to
the configuration box); latency runs from the output box into the
search zone; "updated deployment" leaves the search zone's boundary and
ends on the Deployment configuration box; the compute, write and digital
costs box now takes a branch from the operator tiling as well as the
hardware settings (collected at one junction), and the hardware line to
routing and communication costing runs under that box and up the core's
left margin, with a bridge where it crosses the side box's arrow. Small
type: "Service bounds & communication energy", "Compute-communication
overlap; serial hand-offs". The panel is now built from one layout spec
(_fig2a_spec) with two renderers: matplotlib and an editable draw.io
export, panels/fig2a_platform.drawio (mxGraph XML, 192 px per inch,
fonts scaled the same way, line jumps on the crossed edge). captions.md
and manifest.json restored around the fig2 entries after the --only run.

FIG. 2(a) HAND-DRAWN FORM 2026-09-22. The author redrew panel (a) in
draw.io (fig2a.drawio.svg); the embedded diagram model is transcribed
into _fig2a_spec in draw.io pixels (zones, boxes, polyline arrows, the two
italic labels) and the matplotlib renderer now maps pixels onto the
5.02 x 2.90 in panel (about 249 px per inch, so 20 px type is 5.8 pt and
16 px is 4.7 pt, text shrunk to its box when the fallback font runs
wider). Layout as drawn: Deployment configuration (Partition & placement)
above User Configuration (Workload; Operator tiling & dependencies;
Hardware & execution settings) on the left; the evaluation core's five
filled steps and the white Latency & Dynamic energy box in the middle;
Phase analysis and Deployment search on the right; "Latency" from the
core to the search zone, "Updated deployment" from the search zone round
the top to the Deployment configuration zone, the user configuration
along the bottom into the search zone. The two short core<->phase
arrows carry no labels, as in the drawing; the bottom arrow ends at the
search zone's bottom centre. panels/fig2a_platform.drawio is emitted
from the same spec. Composite with the standing (b) regenerated;
captions.md and manifest.json restored around the fig2 entries.

FIG. 2 COMPOSITE PASS 2026-09-22. Panel letters now sit on the first text
row of each panel (the "Updated deployment" label in (a), the title in
(b)) instead of floating above both. Panel (b) enlarged in place: mesh
pitch 0.34 -> 0.38 in, node radius 0.105 -> 0.117 in, lanes 4.0 pt, colour
bar 0.52 in, bar profile 0.94 in tall with 30% headroom for the e*
reading; the mesh moved up under the title so the FFN1 -> FFN2 line and
the mesh are 0.12 in apart. Type sizes unchanged.

FIG. 2 COMPOSITE PASS 2 2026-09-22. Composite 7.16 x 3.00 in (was 2.90):
the extra 0.10 in lets the panel letters sit clear above (a)'s "Updated
deployment" row, tops level with (b)'s title. (b) is 2.10 in wide at
x = 5.06 and scaled once more about its top-left corner (pitch 0.41 in,
node radius 0.126 in, lanes 4.3 pt, colour bar 0.56 in, profile 1.01 in
tall); the title-to-mesh gap is kept. Type sizes unchanged.

FIG. 2 COMPOSITE PASS 3 2026-09-22. Wider gap between the panels and (b)
scaled once more about its top-left (pitch 0.443 in, node radius 0.136 in,
lanes 4.6 pt, colour bar 0.60 in, profile 0.98 in). The 7.16 in width is
fixed, so (a) is rendered at 4.72 in (its type falls from 5.8/4.7 pt to
about 5.4/4.4 pt) and (b) takes 2.24 in from x = 4.92; the visible gap
between the panels is about 0.24 in. Composite height back to 3.00 in;
(a) is centred below the panel-letter row.

FIG. 2 COMPOSITE PASS 4 2026-09-22. (a) back at its 5.02 in rendering
(type 5.8/4.7 pt); the composite is 7.46 x 3.00 in, (b) 2.24 in wide from
x = 5.22 with a 0.20 in gap. The page layout scales the figure to the
column, so only the proportions matter.

FIG. 3 REFRAME 2026-09-22 (reviewer: the figure should say what changed
and what is being checked, and carry Fig. 2 forward). (a) "Silicon:
placement-induced latency change": two seating glyphs (6x6 chiplet grid,
the four seated chiplets filled) show the two ends of the ladder, the
adjacent block (2 hops) and the corners (10 hops), with the arrow between
them; the three series are now named by their place in the platform,
"Measured silicon (Shao et al.)", "Isobar service bound (busiest link;
comm. costs)" and "Isobar execution estimate (+ packet round trips;
aggregate)", i.e. the communication-cost stage and the aggregation stage
of Fig. 2(a), the latter being the pessimistic rail of the packet
bracket; the y label says each series is relative to its own adjacent
seating. (b) "BookSim: independent validation of layout selection": the
full 13-candidate scatter stays, and an inset enlarges the region around
the reference random fill with the four search endpoints labelled
"12-31% faster under BookSim"; the rank correlation (rho 0.953, average
ranks) moves to a corner as supporting evidence and y = x stays a guide.
Caption and index row rewritten to the two questions. NOTE for the
outline: paper_numbers.md and search_setting_design.md still quote rho
0.962 (ordinal ranks over two tied analytic values); the figure prints
0.953 (average ranks, same 13 candidates); one value should be chosen.

FIG. 3 TEXT PASS + CARD-COLOUR VARIANT 2026-09-23 (reviewer). Titles
"(a) SIMBA: placement sensitivity" / "(b) BookSim: layout selection";
(a) legend cut to "Measured silicon" / "Resource-service bound" / "Isobar
execution estimate" (mechanism in the caption), glyph heading
"Four-chiplet placements", y label "Relative latency"; (b) x/y labels
"Relative analytical cost" / "Relative BookSim batch time", inset label
"Search endpoints, 12-31% lower batch time". Caption keeps the
normalization denominators and adds the resolving-power reading (the
endpoints lie within 3% of each other analytically but spread 27% under
BookSim). Comparison variant composites/fig3_external_validation_alt:
the same panels in the Fig. 2(a) card colours (measured #416c93, bound
#418b78, estimate #8d8944; families stacked #416c93, heuristics #8d8944,
random grey, search #418b78) via the F3_PALS switch; the standing figure
keeps the set palette. Full set regenerated (61 products).

FIG. 3 VARIANT RECOLOURED 2026-09-23: the card variant now uses the
card's own swatches rather than the darkened tones (measured / stacked
fills (72,80,152); bound / search endpoints (165,197,130); estimate /
heuristics (243,222,103); random fills grey). The dashed estimate line is
1.7 pt in this variant so the yellow reads on white, and the inset label
is set in ink. Full set regenerated.

FIG. 3 VARIANT, LIGHT TRIO 2026-09-23: the card variant now uses the
card's light swatches darkened by 8%: blue (96,166,190) for measured /
stacked fills, green (152,181,120) for bound / search endpoints, yellow
(224,204,95) for estimate / heuristics; random fills grey. Full set
regenerated.

FIG. 3 PASS 2026-09-23: the reference random fill is no longer ringed or
labelled (it stays an ordinary grey point at (1, 1); the caption still
names it as the denominator); the two panels now share one axes width
and height (_same_box after tight_layout, left panel keeps its left edge,
right panel its right edge). Both the standing figure and the card
variant.

FIG. 3 FINAL COLOURS 2026-09-23: the card palette (light blue / green /
yellow, each darkened 8%) is now the standing Fig. 3 and the comparison
variant is removed (fig3_external_validation_alt deleted, 60 products).
The yellow marks carry more weight so the three series read evenly: the
estimate's diamonds have a 1.6 pt edge on a 1.7 pt dashed line, and the
heuristics triangles are 7 pt (6.5 pt in the legend).

FIG. 4 REVIEW PASS 2026-09-23. (a) bar names "Best random (of 5)" and
"Search (representative)"; the tick strips are replaced by an inset dot
plot on one 1880-2180 ms axis with the five random fills (best random
edged) and the nine search endpoints (representative edged) and the
9.91% arrow between the two anchors, so "every endpoint below every
random fill" is visible; the 54.5% arrow stays under the bars; legend
moved up beside the heuristic bars. (b) all percentages now share one
base, stated in the panel ("changes relative to best random"): only
Search (-9.91% latency, -0.26% energy) and Least Manhattan (-7.3%
energy, +1.8% latency) carry numbers; Clustered's +20.4% and the green
summary box are gone. Caption adds that Least Manhattan is 13.0% slower
than the representative search and that the search's dynamic energy is
+5.1% against the default, so 54.5% and -0.26% are different
comparisons. (c) wider column (width ratios 1.9 / 1.75 / 1.4), ticks
"Contiguous" / "Enumerated optimum", the 49.60 -> 45.13 ms values at
the bar tops with a -9.02% arrow between them, y range doubled to clear
the legend; caption names it the independent intra-die instance of
Fig. 1(a), one layer over two dies, distinct from the 2.7B system of (a)
and (b). Full set regenerated.

FIG. 4 CARD COLOURS + REVIEW PASS 2 2026-10-01. Palette switched to the
author's card (F4): families blue (96,166,190) / yellow (224,204,95) /
green (152,181,120), random fills grey; bar segments (70,96,173) for
package communication and a tint of (104,180,206) for the rest; (c)
stacks (104,180,206) attention, (243,222,103) FFN, light grey other;
text in the same hues darkened for legibility. (b) Least Manhattan's
label gets a leader to its own triangle (NMAP greedy sits next to it).
(c) tick "Optimal" (the full enumeration is named in the caption),
legend above the plot area in a reserved strip (sub-gridspec 0.22 /
0.78), y axis 0-65 ms so the stacks fill the panel. Caption: the
representative is per seed the best of three starts then the median of
seeds, while the inset shows all nine endpoints; (a) and (b) are the
2.7B 544-die main instance, (c) the separate two-die layer instance.
Full set regenerated; not committed.

FIG. 4 COLOUR PASS 2026-10-01: (a)'s non-communication segment now uses
the same light grey as (c)'s "other costs" (#dfe4e8), so one colour means
"fixed cost" in both panels; package communication softened from
(70,96,173) to the card's (90,150,204); heuristics triangles in (b) in
the card's olive yellow (214,207,103) darkened 8% and drawn at 6 pt so
they read on white.

FIG. 4 COLOUR PASS 2 2026-10-01: one blue (104,180,206) for package
communication in (a), the stacked fills in (b) and the attention die in
(c); heuristics in (b) in the card's teal (128,205,187) darkened 8% (text
in its dark tone); bars drawn without white edges so they meet the
spines; the sample inset raised clear of the 54.5% arrow; the Search
label in (b) moved inside the axes; (c)'s -9.02% arrow higher, in grey
with ink text (no green in that panel).

FIG. 4 COLOUR PASS 3 2026-10-01: heuristics in the card's deep blue
(70,96,173) desaturated to (88,104,160) so it is not confused with the
teal of the stacked fills; the light colours a step heavier (blue
(94,162,185), green (140,168,108), yellow (224,204,95)); the 54.5%
label now sits above its arrow like the other arrow labels, and the
axes bottom margin shrinks accordingly.

FIG. 4 COLOUR PASS 4 2026-10-01: back to the Fig. 3 trio (blue (96,166,190),
green (152,181,120), yellow (224,204,95)) for stacked fills / package
communication / attention die, search endpoints and FFN die; heuristics
keep the desaturated deep blue (88,104,160).

FIG. 4 COLOUR PASS 5 2026-10-01: colours as before the "heavier" pass,
i.e. the card swatches themselves (blue (104,180,206) in every panel,
yellow (243,222,103) FFN die, green (152,181,120) search), heuristics in
the desaturated deep blue (88,104,160). This is the standing form.

FIGS. 1-3 PASS 2026-10-01 (author). Fig. 1: every type size one point
above the standing print form (FS bumped around the print generator's
main(), the standalone phase_diagram_isobar_print_k2 untouched). Fig. 2:
the Deployment search zone in the clear yellow of Fig. 4 ((243,222,103)
boxes and edge, a tint for the zone, arrows (201,181,61)) instead of the
olive card tone. Fig. 3: the row is filled (0.42 in gap for the right
y label) with the right panel 0.2 in wider than the left so the two read
as equal, y range 0.9-2.72 in (a), 0.6-5.0 in (b), the inset kept clear
of the dispersed heuristic; figure height 0.42 of the width.

FIGS. 1-3 PASS 2 2026-10-01 (author's correction). Fig. 1: the type is
now the standing (non-print) figure's effective size plus one point
(title / axis 6.5, ticks 6, text and legend 5.5, ratio 5.6 pt), not the
print form plus one; the composite render also trims the print layout's
bottom margin from 30% to 22% so the panels gain the room the smaller
legend frees. Fig. 2: Deployment search in a lighter, clearer yellow
((249,239,124) boxes and edge, (254,252,233) zone, arrows (212,192,74));
panel (b) scaled up once more (pitch 0.47 in, radius 0.144 in, lanes
4.9 pt, panel 2.32 in wide, composite 7.54 x 3.00 in) and its profile's
x axis placed on the flowchart's zone bottom line (0.17 in). Fig. 3: the
inter-panel gap stays at 0.50 in and the left panel is 0.5 in narrower
than the right; the inset moved right so its tick numbers no longer sit
on the main y axis.

FIG. 1 BACK TO THE STANDING FORM 2026-10-01: Fig. 1 is rendered by the
standing (non-print) generator fig_phase_isobar.py (12.8 x 5.0 in, scaled
to the column by the page layout) with every type size one point larger
(explicit fontsize kwargs and the rc defaults bumped by 1 pt around its
main(), the generator itself untouched); the print form is no longer
used for the figure set. FIG. 2: the evaluation core's zone fill
lightened from (238,244,250) to (245,249,253).

FIG. 1 + FIG. 2 PASS 2026-10-01 (author). Fig. 1 (standing generator
fig_phase_isobar.py edited): the 20% contour label gets a background in
the colour of the region it sits on (the band's yellow in (a)), the
envelope arrow of (a) moved from s = 6 to s = 15 Mrows/s so it clears
the band label, chip labels reduced to name + number (HERMES 0.4 GB/s,
ISAAC 4.0 / 6.4 GB/s, M1076 1 GB/s, NeuRRAM 0.4 / 12.5 GB/s; sources
stay in the caption); the figure-set render is two points larger than
the generator's type. Fig. 2: Deployment search in the teal of the
Deployment configuration it produces ((128,205,187) boxes and edge,
(235,247,244) zone, arrows (65,139,120)), so the search -> updated
deployment -> configuration loop is one colour; the yellow is gone.

FIG. 1 + FIG. 2 PASS 2 2026-10-01 (author). Fig. 1: chip labels on one
line as "name, bandwidth" (HERMES, 0.4 GB/s with its two-mode note on a
second line). Fig. 2: Deployment search in a deep teal of its own
((72,150,132) boxes with white text, (233,245,241) zone, arrows
(47,107,92)), distinct from the light teal of Deployment configuration
so the two zones do not read as one module.

FIG. 1 NUDGE 2026-10-01 (author): in (b) the two NeuRRAM labels are
left-aligned from s_ref / 1.21 so each circle sits under the middle of
the word; ISAAC's label raised to 1.30x its bandwidth, clear of the
upper boundary; the band label moved from s = 3.2 to 2.1 Mrows/s; the
M1076 label a little up and to the right.

FIG. 5 REDRAW 2026-10-01 (author: "redo it the way we settled the
traffic figure; (d) carries no information"). (a)-(c) now use the
Fig. 2(b) idiom: every physical link is two lanes with a dark rim,
filled by the service time on one shared ramp centred on the port bound
(0 / 6.55 / 21.0 ms, idle lanes at the ramp's zero), white nodes with
black bold labels (producers rounded squares, consumers circles, empty
slots thin), e* on the busiest link, readings "e* N flows . X ms" and
the word-hops under each mesh, one hand-drawn colour bar beside (c);
titles in the card family colours; the overall header line moved into
the caption. (d) is a strip chart on the latency axis: four objectives
(resource-aware, links only, word-hops, max hops) x three seeds, best
seed edged, each row labelled with its best latency and its change
against the best random fill (dashed at 2119 ms): -11.0%, -10.2%,
-0.9%, -1.0%, so the proxies are seen to search to no better than a
random fill while dropping the port term costs 0.8 points. Caption and
data/fig5_ablation.json (by_objective, best_random_fill_ms) rewritten
accordingly. Composite 7.16 x 4.20 in.

FIG. 5 ONE-ROW FORM 2026-10-01 (author + reviewer). The three meshes sit
close together in one block (pitch 0.29 in, nodes r = 0.085 in so the
lanes dominate), on a Fig.-5 ramp whose idle side is muted and whose hot
end is a vivid red (LOAD_F5, centred on the port bound); titles
"Compact / Random / Resource-aware" (seeds in the caption); the busiest
link carries its flow count, and under each mesh the busiest-link
service time is the bold line with the routed traffic beneath, aligned
across the three; one shared colour bar "Link service time (ms)" and the
node key (producer / consumer / empty slot) under the block; header
"(a)-(c) 4x4 mechanism example". (d) "Objective ablation, 544-die
system": a vertical dot plot, Full / Links only / Word-hops / Max hops
on x, latency overhead (%) over the full objective's best seed on y,
three seeds as hollow circles and the best seed as a filled diamond
(+0.9%, +11.4%, +11.2%); the best-random reference and the per-row
sentences are gone. Composite 7.16 x 2.35 in. DATA NOTE: the ablation
is its own batch (one start = random seed 0, three annealer seeds, 1200
steps per objective; objective_ablation_k2.json), so its full-objective
endpoints (1886.5 / 1911.0 / 1911.3 ms) are not the Fig. 4 runs
(three start families, best start per seed: 1904.2 / 1908.8 / 1914.1
ms); the caption now says so and the overheads are within-batch.

FIG. 5 PASS 2026-10-01 (author): (d) shrunk to a 1.35 x 1.5 in panel on
the right (two-line tick labels, no legend: the caption says hollow
circles are seeds and the diamond the best seed); the ramp's blue side
back to a medium blue (150,186,216)/(140,184,220) with the hot end kept
vivid; the (a)-(c) titles in ink, same size and baseline as "(d)
Ablation, 544-die system", so the four letters sit on one line; the
"4x4 mechanism example" note moved into the key row. Composite 6.10 x
2.25 in.

FIG. 5 PASS 2026-10-01 (author): colour bar and node key on one row
under the meshes; the "4x4 mechanism example" note dropped; the busiest
link marked e* again (flow counts are in the caption); the ms readings
a little lower; (d) smaller still (1.15 in wide), its title on the
(a)-(c) title line and its tick labels ending on the colour bar's label
line, no x-axis title. Composite 5.95 x 2.25 in.

FIG. 5 PASS 2026-10-01 (author): the colour bar / node key row raised
(readings 0.22 in above it); (d) shortened so a 0.14 in gap separates
its title from the axes while its tick labels still end on the colour
bar's label line. Composite 5.95 x 2.13 in.

FIG. 5 PASS 2026-10-02 (author): the ramp is now sequential, idle blue
-> peach -> vivid red with no neutral stop, so no lane reads as grey
(the diverging ramp's whitish centre had put the 2- and 3-flow lanes
near the port bound into grey); the norm is linear 0-21 ms and the bar
ticks 0 / 10 / 20 (the 6.6 ms port-bound tick belonged to Fig. 2(b)'s
story, not this one). (d) moved 0.38 in closer to (c) and widened to
1.50 in. Caption: flow counts of e* given there.
Ramp stops pinned to this instance's flow counts (0 / 0.125 / 0.25 /
0.5 / 0.75 / 1 of 21 ms): one-flow lanes a light blue, two-flow lanes
peach, so no lane sits in a neutral tone.

FIG. 5 PASS 2026-10-02 (author): the ramp's blue now runs to about
8.5 ms (0.4 of the bar) with two blue stops before the peach, so the
light lanes vary within blue; the red end unchanged. (d) labels: "ref."
under its diamond, the links-only value above-right, the two proxy
values under their diamonds; x range trimmed so nothing crosses the
right spine.
Ramp pass 2: the idle end deepened to (104,156,200) and the blue-to-peach
turn moved left to about 7 ms, so the one- and two-flow lanes separate
within blue.
Ramp pass 3: the blue-to-peach turn back at about 5 ms (a quarter of the
bar), the deeper idle blue kept.

FIG. 5 TALL VARIANT 2026-10-02 (author, for comparison): composites/
fig5_mechanism_and_ablation_tall, 3.40 x 3.90 in, (a) (b) on the first
row and (c) (d) on the second, colour bar and node key along the bottom;
same drawers, ramp and numbers. The one-row composite stays the standing
form.

FIG. 5 TALL VARIANT PASS 2026-10-02 (author): (b) 0.18 in from (a); the
colour bar and the node key stacked to the right of (b); (d)'s x axis on
(c)'s mesh bottom, its right edge on the figure's right content edge,
title on (c)'s title line. 3.65 x 3.42 in. The one-row composite is
unchanged.
Tall variant pass 2: the colour bar is a short vertical strip (0.06 x
0.61 in, ticks 0 / 10 / 20, "ms") beside (b) with a compact key
(producer / consumer / empty) under it; figure 3.05 x 3.42 in.
Tall variant pass 3: the key is smaller (4.6 pt, 0.04 in marks) and sits
lower under the bar; (d)'s right edge is now measured from the rendered
key and bar tick labels, so it ends on the figure's true right content
edge, with its x axis still on (c)'s mesh bottom.
Tall variant pass 4: all four titles at 7 pt; (d)'s ticks 5 pt, y label
5.6 pt, in-panel labels 5.2 pt; its right edge 0.06 in short of the
measured content edge so it reads flush.
Tall variant pass 5: (d) and its title shifted about 0.15 in to the left.

ZERO-MARGIN EXPORT 2026-10-02 (author): every PDF / SVG / PNG of the set
is cropped to the drawn ink with no padding (savefig.pad_inches = 0 and
a content bounding box that, for the inch-coordinate panels, is the
union of the artists and inset axes rather than the panel frame), so
the file's width is the figure's width in LaTeX. Fig. 1's composite and
its two cropped panels likewise. Composite sizes: Fig. 1 12.40 x 4.91,
Fig. 2 7.52 x 2.93, Fig. 3 6.92 x 2.77, Fig. 4 7.37 x 4.58, Fig. 5
5.76 x 2.00 (tall 2.85 x 3.21), Fig. 6 6.92 x 2.49 in.

FIG. 6 REVIEW PASS 2026-10-02. (a) is two stacked panels on one
bandwidth axis: r and eta above (0-80%), G alone below (0-15%) with its
9.91 / 6.55 / 0.70% readings beside the points and "G = eta . r" in the
panel; legend labels "r: Communication share", "eta: Communication
reduction", "G: Whole-model latency reduction" (the pair's identity is
in the caption). The shading is "Crossover envelope" with B- and B+
marked at its edges and the caption says it is Fig. 1(b)'s band for the
seven rules, not a boundary of this pair; the midpoint tick reads 0.87.
(b) keeps the two curves, drops the two mechanism notes and the legend
title (protocol in the caption), y label "Latency reduction (%)",
legend "24 x 24 mesh" / "12 x 48 mesh"; the caption states it is a new
search per cell, unlike (a), and that the flat gain beyond kappa = 2
says nothing by itself about ports binding. Widths 60 / 40. Card
palette: r deep blue, eta light blue, G and the 24x24 mesh green, the
12x48 mesh light blue, envelope in the card yellow at 30%.
WORKLOAD REUSE 2026-10-02 (the Fig. 6(b) study; scripts/workload_reuse.py
-> analysis/workload_reuse/): the frozen headline layout sa_random_s1
re-scored and a fresh normalized-temperature search (T / T_base, t0 =
20 ms / 2118.71 ms, 3 x 3, 1200 steps) at prefill S = 128 / 512 / 1024 and
decode over a 128 / 512 / 1024-token cache, main configuration otherwise.
S = 2048 infeasible under the frozen grouping (attention K/V arrays 20.97M
cells against the die's 16.78M). Invariance pinned numerically: H scales
by exactly S / 512 in prefill and is identical across decode cache lengths
for all 21 layouts, R is layout-independent, the ordering of the 21
layouts is the same at every workpoint. Readings: reuse gain 9.36 / 9.91 /
10.04 percent (prefill 128 / 512 / 1024, communication share 53.4 / 56.5 /
57.3 percent) and 1.57 percent at every decode length; the workpoint
searches never beat the frozen layout (prefill 9.00 / 9.91 / 10.04 percent
medians, decode 1.05 to 1.10 percent), so Reuse + search falls back to the
frozen layout everywhere. Accounts at S = 128 and 1024 are DERIVED from the
S = 512 mapper account (compute = rows x per-row time, write = min(rows,
256) x T_SET, declared in the files); scripts/run_2p7b_block_S.py produces
the measured accounts when the container is reachable (docker socket
permission lost after the 2026-09-29 host reboot). The 512 workpoint
reproduces the frozen 9.91 / 1.57 percent and the frozen search endpoints
bit for bit under the normalized objective.

FIG. 6 REBUILT 2026-10-02 (reviewer's two-panel brief; experiment by the
run agent in analysis/workload_reuse/). (a) Bandwidth response, one
panel: G as the main curve with 9.91 / 6.55 / 0.70% beside the points,
eta as the level dotted line, r annotated at 0.2, 0.87 and 12.5 GB/s,
the crossover envelope shaded with B- / B+ at its foot, "G = eta . r".
(b) Placement reuse across workloads: prefill (128 / 512 / 1024 tokens)
and decode (128 / 512 / 1024 cache tokens) side by side on their own y
scales; per workload the frozen sa_random_s1 re-scored (Reuse, green),
the appended search's median and seed range (light blue, hollow) and
Reuse + search (ink diamond, labelled), which falls back to the frozen
layout at every point. Reads: prefill 9.36 / 9.91 / 10.04%, decode
1.57% throughout; the caption states the invariance (every hand-off
volume scales with the token count, so the 21 layouts keep one ranking:
dilution, not mismatch), the 2048 infeasibility and the derived
128 / 1024 accounts. The port-capacity / geometry panel is out of
Fig. 6 and kept as panels/fig6x_port_geometry with its CSV. New data
product data/fig6_placement_reuse.csv. Widths 46 / 54; card palette.

FIG. 6 THREE-PANEL FORM 2026-10-02 (reviewer): (a) the bandwidth curve
on the left (44% of the width); on the right, two 2 x 3 matrices on one
0-12% single-hue ramp (card light blue -> deep teal, shared colour bar):
(b) port capacity x mesh geometry, median latency reduction in each
cell with the seed min-max beneath (1.8 / 9.9 / 9.7 over 24x24, 2.7 /
9.8 / 9.8 over 12x48); (c) workload and placement reuse, the frozen
layout's reduction at 128 / 512 / 1024 prefill tokens (9.36 / 9.91 /
10.04%) and decode cache tokens (1.57% each); the appended searches are
not drawn (summary in data/fig6_placement_reuse.csv). Composite
7.16 x 2.58 in, cropped 6.8 x 2.5. The standalone fig6x port panel is
replaced by panels/fig6b_port_geometry and fig6c_placement_reuse.

FIG. 6 RIGHT PANELS 2026-10-02 (reviewer, after the matrices): (b) paired
dots, one row per kappa, the two geometries offset (24x24 green circle,
12x48 light-blue square), median with the seed min-max bar and the value
beside each point; (c) dumbbells, one row per length, decode (deep blue
square) and prefill (green circle) joined by a grey connector, values at
the ends. The two panels share one 0-12% axis "Latency reduction (%)";
no colour bar, no "%" after the numbers. Layout unchanged (a 44% left,
b over c right).

FIG. 6 PASS 2026-10-06 (author). Composite narrowed to 5.64 x 2.47 in
(cropped; was 6.89 x 2.71) on an inch layout: (a) 2.52 in wide, the right
column 2.12 in; (a) and (b) share their top edge and all three titles use
one style (8 pt, left-aligned, same pad), so the (a) and (b) titles sit on
one baseline. Two hues only, green and light blue (darker tones of the
same hues for text): the deep blue is gone from decode and from the r
notes, which are now grey and stacked above the G value at 0.87 and
12.5 GB/s; "9.91%" anchored to the upper right of its own point. (b): the
in-panel "median; bars: seed min-max" note removed (the caption carries
the statistic), legend moved into the free right end of the kappa = 1
row, values set after the min-max bar. (c): real dumbbells, two equal
7 pt circles (decode light blue, prefill green) joined by a grey bar,
each value above its dot, legend in a top band, y label "Tokens".

FIG. 6 PASS 2026-10-06 (author, second). One line width (1.4 pt) and one
marker size (4.5) in all three panels, as in Fig. 3; the dumbbell
connector at the same 1.4 pt in grey. (a) draws r, eta and G again as
three lines on one 0-80% axis (r dashed grey squares, eta dotted light
blue diamonds, G solid green circles), the r notes gone; G's values at
0.4 (under its dot), 0.87 (above) and 12.5 GB/s (right of it, x axis to
32 GB/s for the room). (b) drops the seed min-max bars, which at this
scale were no longer than a marker (ranges <= 0.46 points); the caption
states the seed spread. Right column narrowed to 1.60 in with titles
"(b) Ports and geometry" / "(c) Reuse across workloads" so they fit;
gap between (a) and the right column 0.46 in; title pad 6.5 pt in all
three; legends of (b) and (c) in a top row, "Tokens" as the row-label
header of (c). Composite 4.93 x 2.51 in (cropped). Standalone (b)/(c)
exports now use the composite's axes size.

FIG. 6 PASS 2026-10-06 (author, third). (a): the legend is small (5.5 pt,
markers scaled 0.8) with "G = eta . r" as its title, placed right of the
envelope between the r line and the band labels; "Crossover envelope"
and B- / B+ moved to the top of the band (B- and B+ in its corners);
three colours for the three lines (r the card's desaturated deep blue
(88,104,160), eta light blue, G green). (c): the dumbbell connector is a
thin 0.8 pt line in a darker grey (153,163,170); title "(c) Workload
reuse". (b)/(c): right column 1.25 in; legends 5.5 pt with markers scaled
0.8, raised to sit just above the axes. Composite cropped to 4.62 x 2.51 in.
(a) legend pass: 4.5 pt (title "G = eta . r" too), markers scaled 0.7,
back in the top right corner; it now clears the envelope and B+.

FIG. 6 PASS 2026-10-06 (author, fourth). Marker shapes balanced by area:
circles 4.5, squares 4.0, diamonds 3.7 (a square or diamond at the
circle's nominal size reads larger); the r line 1.15 pt. (b) brings the
seed min-max back as capped bars in the darker tone of each hue
(1.2 pt, caps 3 pt), with small centres (circle 2.2, square 2.0) so the
bars show; the spread is at most 0.46 points, so where it is near zero
(kappa = 1) the two caps merge into one tick through the dot. Caption and
index row say dot = median, bar = min-max.
Fig. 6 pass, fifth: (b) back to plain points without the seed bars
(caption and index row reverted); dots in (b) and (c) unified at circle
4.0 / square 3.5; the r squares in (a) 3.5.

FIG. 1 LEGEND 2026-10-06 (author): three columns of two rows instead of
two columns of three, the line keys (boundaries, 20% spread, bandwidth
tiers) on the first row and the marker keys (published, derived,
evaluated configurations) on the second; labels shortened ("boundaries
B-, B+ over the placement set", "published parameter, projected",
"derived or alternative-mode value"); plain-text subscripts so every
label has the same height and the rows line up across the columns;
the panels keep their size and position; the one legend row saved comes off the figure height (5.0 -> 4.8 in). Edited in the
standing generator fig_phase_isobar.py; its own output
analysis/phase_diagram_isobar_k2.{png,pdf} re-rendered so it matches the
code (it also picks up the Oct 1 label edits).
Fig. 1 legend, second pass: row spacing 0.9 -> 0.45 and the legend 0.16 in
closer under the axis titles (gap 0.28 -> 0.12 in in the figure set);
the panels unchanged (5.309 x 3.325 in, 0.30 in top margin), the saved
height taken off the figure (4.8 -> 4.6 in).
V3 SUPPLEMENTARY CAMPAIGN 2026-10-08 to 10-12 (author's request; plan in
analysis/v3/v3_experiment_plan.md, record in analysis/v3/NOTES.md and the
generated analysis/v3/REPORT.md): the cross-configuration, scaling,
tiling, workpoint, discriminability, ablation, timing, confirmation and
reuse experiments behind outline V3. Protocol: random pools of 100 (500
for confirmation) saved whole; starts = strongest named rule, strongest
random of the pool, random seed 0; 5 seeds (10 new for confirmation);
budget max(1200, ceil(1200 n/544)); normalized objective T/T_base with
t0 = 0.0094396. Code: scripts/v3_sweep.py (driver; cost grid by the
separable model with the ordering check), v3_measure_accounts.py and
v3_attention_calib.py (mapper accounts for 52 (d, dh, d_ff, S) points),
v3_discrim.py (candidate libraries, tie groups, BookSim, ablations),
v3_timing.py, v3_reuse.py, v3_report.py. Platform changes: run_op gains
strict_traffic (the traffic guard can be recorded instead of raised when
only compute, write and energy are needed); the tiler's split preference
(tiling_dims) threads through inventory, boundaries, baselines and the
CLI; the BookSim bridge gains a port ratio via cmesh concentration (c
terminals per die, packets spread over terminal pairs), the ejection
bound, wavefront allocators for concentrated runs, and runs the binary
locally when executable; vendored patch 0002 makes cmesh honour the
channel latency knob. Finding behind the protocol: kappa = 1 is the
port-bound corner (every good seating on the port floor), so every
comparison is made at the main port ratio; the kappa = 1 E3 runs are
kept apart under analysis/v3/e3/. docker-compose.yaml: restart
unless-stopped.
Confirmation list overwrite 2026-10-12: v3_report.py rewrote
analysis/v3/confirm_specs.json with its automatic top 5 every time it
ran, so the five specs appended by hand on 10-09 were dropped before the
second confirmation launch (which therefore added nothing) and the two
reuse runs that depended on them failed with KeyError. The generator now
writes its list to confirm_specs_auto.json and never overwrites an
existing confirm_specs.json; the five configurations were run on 10-12
(all ten confirmations in analysis/v3/confirm/). v3_reuse.py gains --out
so a 500-fill rerun of the reference (analysis/v3/e6_reuse_500/) does
not overwrite the 100-fill record. REPORT.md gains the confirmation and
reuse tables and the figure data index points at the kappa 2 E3 set.
