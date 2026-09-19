# Bandwidth Anchors — published NoC / D2D link specs with provenance

Purpose: the simulator's link bandwidths are platform inputs. Until the real
chip's values arrive, results are stated against PUBLISHED link specs from
fabricated (or post-layout) accelerators, so that "where real chips land on
our threshold curves" is a sourced statement, not a guess. Consumed by
`scripts/analyze_anchored_sweep.py`.

**Identity (O25).** Every anchor below is a DIGITAL accelerator's link --
Simba, ESP and FlooNoC NoCs on die, Simba's GRS package mesh die to die.
They are the upper bound of what fabricated interconnects deliver, not the
operating points of analog CIM chips (and UCIe-S 64 is one step further
out: an interconnect STANDARD's ceiling, status `spec`, C40). One analog
system now DOES publish a
link rate (C36, 2026-09-01): HERMES's chip spec table gives a maximum link
data-rate of 3.2 Gbit/s = 0.4 GB/s per PHYSICAL link (418 links, Parallel
Prism fabric) -- landing exactly on the analog-reality band's LOW end; the
band stays the CLASS estimate. Its phase-diagram COORDINATE is the C37
normalization: what the fabric supplies to a 32-array group (one of our
links' span) = (418/64) x 0.4 x 32 ~= 83.6 GB/s -- and the self-consistency
audit (need 1.93 vs supply 2.61 GB/s per core, ~1.36x headroom) makes
HERMES the first external silicon point validating the knee formula
(survey and registry mapping in "What analog CIM systems publish" below). Every readout against these anchors is
therefore the digital-ecosystem column of the phase diagram (model scale x
device speed x transfer paradigm x link tier); the analog-reality column is
the registry's estimated band (C26), read out beside the digital columns in
every sweep. **The registry is `scripts/anchors.py`** -- the only place a
bandwidth anchor, the device cycle or a chip point is defined; the tables
below are its rendering.

## The registry grid (paradigm x level), `python3 scripts/anchors.py`

| level | paradigm | anchor | value | words/cycle | status |
|---|---|---|---|---|---|
| on-die | digital-ecosystem | Simba 8.75 | 8.75 GB/s | 12,675 | measured |
| on-die | digital-ecosystem | ESP 32 | 32 GB/s | 46,354 | measured |
| on-die | digital-ecosystem | FlooNoC 80.6 | 80.6 GB/s | 116,755 | post-layout |
| die-to-die | digital-ecosystem | GRS 12.5 | 12.5 GB/s | 18,107 | measured |
| die-to-die | digital-ecosystem | UCIe-S 64 | 64 GB/s | 92,708 | spec |
| on-die | analog-reality | analog on-die 0.4-8 | 0.4-8 GB/s (band) | 579 .. 11,589 | estimated |
| die-to-die | analog-reality | analog D2D 0.1-2 | 0.1-2 GB/s (band) | 145 .. 2,897 | estimated |

Operating-point note (2026-09-02, Simba reproduction): Simba's placement
EXPERIMENTS ran GRS in its 11 Gb/s mode — 4 lanes x 11 Gb/s = 5.5 GB/s
per mesh-link direction (MICRO'19 §4.1). That 5.5 GB/s is the
reproduction operating point (worklist step 1) and enters the registry
with the simba.yaml preset; the GRS 12.5 row above stays what it is — the
link's demonstrated MAXIMUM capability and the phase diagram's D2D anchor
line. Two identities, both real: neither number "corrects" the other.

Every readout column set is the level's digital anchors followed by the two
ends of its analog-reality band (`anchors.columns(level)`); a sweep that
prints one column prints all of them. The estimated band's derivation:
on die, a 32-128-bit datapath at 100-500 MHz (65-130 nm digital periphery)
= 0.4 .. 8 GB/s; die to die, GPIO / LVDS-class or short SerDes-free
parallel links = 0.1 .. 2 GB/s per direction. It is an ESTIMATE of where
fabricated analog CIM fabrics sit (survey below), not an anchor; the chip's
own values (DR-2) replace it.

## Digital-ecosystem anchors (upper bound): on-die NoC, per link, one direction

| tier | value | system | provenance | notes |
|---|---|---|---|---|
| **LOW — 8.75 GB/s** (70 Gb/s) | Simba chiplet-internal NoC | Zimmer et al., *A 0.32–128 TOPS Scalable MCM-Based DNN Inference Accelerator with Ground-Referenced Signaling in 16 nm*, IEEE JSSC 2020 | "At 0.72 V, each link of the NoC achieves 70-Gb/s bandwidth." Silicon-measured; a 16 nm inference chiplet — the closest published cousin to our die NoC. |
| **MID — 32 GB/s** (256 Gb/s) | ESP-based SoC NoC, tile-to-tile | Jia et al., ESSCIRC 2022 (12 nm): 5 data NoC planes × 64 bit + 1 control plane × 32 bit, NoC measured at 800 MHz; the paper's own headline is 281 Gb/s tile-to-tile (all 6 planes) | PRIMARY since C36: 5 data planes × 64 b × 800 MHz = 256 Gb/s = 32 GB/s (the quantity FlooNoC's table quotes). Multi-plane aggregate, stated as such — one physical plane alone is 6.4 GB/s. |
| **HIGH — 80.6 GB/s** (645 Gb/s) | FlooNoC wide-link NoC | Fischer et al., *FlooNoC: A 645 Gbps/link 0.15 pJ/B/hop Open-Source NoC*, arXiv:2409.17606 | "achieve a bandwidth of 645 Gbps per link"; 0.15 pJ/B/hop; 12 nm post-layout (Occamy silicon sibling measured 584 Gbps). |

Also in the same comparison table: Celerity 96 Gb/s (16 nm silicon, 5×5
mesh), Ou et al. 45 Gb/s — bracketing LOW and MID.

Citation discipline -- RESOLVED (C36, 2026-09-01): the ESSCIRC 2022 text
(Jia et al., author-hosted copy) was read. The NoC is 5 data planes x 64
bit + 1 control plane x 32 bit at a measured 800 MHz; the paper's own
tile-to-tile maximum is 281 Gb/s (all six planes). The anchor's 32 GB/s =
the 5 data planes (256 Gb/s), exactly the quantity FlooNoC's comparison
quotes; a single physical plane is 6.4 GB/s. The anchor is now
primary-sourced with `status = measured`, and its derivation states the
multi-plane aggregation explicitly.

## Digital-ecosystem anchors: die-to-die (package), per link, one direction

| value | system | provenance | notes |
|---|---|---|---|
| **12.5 GB/s** (100 Gb/s) | Simba package GRS mesh | same JSSC 2020: "36 dice ... mesh network with 100 Gb/s interconnect in each link direction"; lanes run 11–25 Gb/s at **0.82–1.75 pJ/bit** | silicon-measured D2D on an organic substrate — the MAX-capability datum; the MICRO'19 placement experiments themselves ran the 11 Gb/s mode = 5.5 GB/s per direction (operating-point note above). **Adopted**: the die-link default energy is now 10 pJ/word = the midpoint of this measured band (6.6–14 pJ/word), replacing the earlier optimistic 5 pJ/word example |
| **64 GB/s** (512 Gb/s) | UCIe standard-package module | UCIe Consortium specification: x16 lanes × 32 GT/s per lane, per direction per module (C40) | an interconnect **STANDARD's ceiling** (status `spec`), one epistemic step past post-layout: no measured chip, though first 32 GT/s-per-lane silicon is announced (GUC, TSMC 3 nm + CoWoS). Bounds where packaged D2D is headed, not where analog CIM chips sit |

## What analog CIM systems publish (survey 2026-08-27), and the registry tier each maps to

| system | fabric | published on-die link bandwidth | registry tier in this model |
|---|---|---|---|
| NeuRRAM (Wan et al., Nature 2022) | inter-core buffers and partial-sum accumulation on the board FPGA; no on-chip core network | none (chip IO, 130 nm) | hub-IO upper bound |
| TetraMem MX100 (arXiv 2410.14882) | 10 NPUs + RISC-V + DMA engine + shared SRAM (512 KB + 1 MB), 65 nm | none (shared medium) | bus, bandwidth at the T1 hub (`hub_bandwidth_words_per_cycle`; the T1 axis is measured since C34 -- read the class at `sweep_axis_t1_hub.png`) |
| HERMES 64-core (Le Gallo et al., Nat. Electron. 2023; arXiv 2212.02872) | 418 physical links in a 5 Parallel Prism fabric, per-core link controllers | **published (C36)**: chip spec table, maximum link data-rate 3.2 Gbit/s = 0.4 GB/s per link -- it was in the arXiv methods all along (the earlier note blamed a paywalled supplement); lands on the analog band's low end | star (compile-time scheduled) |
| Mythic AMP M1076 / M1108 | per-tile 64 KB SRAM + NoC router | none (product material only) | star (compile-time scheduled) |
| Tsinghua multi-chip (Nat. Commun. 2025; Yao et al., Nature 2020) | 8 chips + FPGA hub, no chip-to-chip direct links | none (everything through the FPGA) | hub-IO / bus |
| Simba, ESP, FlooNoC, GRS (the anchors above) | digital NoCs and package links, 12-16 nm | 8.75 / 32 / 80.6 GB/s; 12.5 GB/s | mesh (digital ecosystem) |

Mapping rule: a DMA engine with shared SRAM is a shared medium whose
bandwidth is a T1 (hub) number in this model, not a T2 link; a compile-time
scheduled point-to-point fabric is the star scheme; a NoC is the mesh
scheme. What the model's max end means per tier (C29): for star and bus the
busiest-wire occupancy is EXACT (nothing shared / one resource); for mesh
and tree it is the least serialisation any schedule can reach for the
given routing, the missing piece being arbitration on shared segments;
`schedule_slack` (fabric input, >= 1, default 1) expresses a schedule that
cannot reach the bound.

**The NoC-paradigm slack, measured (C52; evidence status: CYCLE-ACCURATE
REFERENCE -- a simulator, not silicon; kept distinct from silicon rows).**
BookSim 2 (vendored, patched for exact per-pair batches; conversion table
in `scripts/booksim_bridge.py`, both identity gates green) ran the Simba
reproduction's seating flow sets on the 6x6 mesh: the batch completion
lands ON the busiest-wire bound -- +0.18% (adjacent seating) to +0.74%
(corner seating), the larger offset at the larger distance (the
distance-linearity signature inside the network layer). Reading, per the
signed decomposition frame: the bound's reachability is CERTIFIED by a
real router (schedule_slack's lower end is real, network-internally);
what the coefficient covers is the NETWORK-INTERNAL share only -- the
PROTOCOL share (consumer buffering, per-block handshake rounds; above
the network, invisible to a NoC simulator) is a DECLARED item, measured
against silicon as 2.530 / 1.0056 = 2.516x on the Simba seating
experiment. Ordering, quantified: bound < BookSim (1.006) <
round-serialized closed rail (2.40) < silicon (2.53).

The analog-reality tier is in the registry as the estimated band above
(2-20x below the digital anchors on die, 1-2 orders below GRS); since C36
its on-die LOW end coincides with the one published analog link rate
(HERMES, 0.4 GB/s per link).

## Chip points (the phase diagram, O29)

A real system is a point with a device-speed coordinate and a bandwidth
coordinate per level, each with its own status. NORMALIZATION (C37, the
V0 rules, stated in `anchors.ChipPoint`): the t coordinate is PER TOKEN
(one input row through the resident array stack) -- TOPS-derived row
times are tile-shape invariant, so no array-height folding; a bandwidth
coordinate is the chip fabric's aggregate supply to the array group one
of OUR links serves (a macro, 32 crossbars) -- published per-physical-link
rates are aggregated first, estimated bands are authored at our
granularity already. Digital NoCs are NOT chip points -- they have no honest
compute coordinate in this model -- and are drawn as horizontal bandwidth
lines (the anchors above) -- with ONE declared exception since C47:
Simba enters as the first DIGITAL chip point, its compute coordinate
supplied by the reproduction's equivalent-throughput device declaration
(C41); it sits on the plane as a chip, NOT as a device mark of the r=1
machinery. `anchors.CHIPS`:

| chip | tier | t_MVM | status / derivation | on-die bandwidth | status |
|---|---|---|---|---|---|
| NeuRRAM (2022) | hub-io | 10.14 us | measured: 7 encoded input slices x 1.4486 us (this model's calibrated macro) | -- | not published (board FPGA hub; hub-IO bound) |
| HERMES 64-core (2023) | star | 0.133 us | derived: 63.1 TOPS / 64 cores / (2 x 256 x 256) per row | ~83.6 GB/s (coordinate, C37) | per PHYSICAL link 0.4 GB/s published (spec table, C36); coordinate = aggregate supply to a 32-array group, (418/64) x 0.4 x 32; self-consistency: supply 2.61 vs need 1.93 GB/s per core, ~1.36x headroom |
| ISAAC (2016) | mesh | 1.6 us | design point: 16 one-bit slices x 100 ns | per inter-tile link 4.0 GB/s published; band 0.4-8 GB/s kept for the standing device-plane figure | PUBLISHED per-link (re-read 2026-09-18): "we estimate that the inter-tile link bandwidth requirement never exceeds 3.2 GB/s. We therefore conservatively assume a 32-bit link operating at 1 GHz" (Sec. VIII-B) = 4.0 GB/s; c-mesh flit width 32 bits (Sec. VIII-A); off-chip d2d = Table I "Hyper Tr links/freq 4/1.6GHz, link bw 6.4 GB/s" per link and direction (HyperTransport model from DaDianNao). The earlier note "no per-link figure" was WRONG |
| TetraMem MX100 | bus-T1 | -- | pending, BLOCKED on the source (C36, checked 2026-09-01): the SoC paper arXiv:2410.14882 publishes no TOPS or MVM rate; revisit on TetraMem's 22nm SoC publication | 0.4-8 GB/s | estimated (SRAM port width x clock; a T1 number here) |
| Mythic AMP M1076 | star | 6.38 us | derived (C36): 25 TOPS peak / 76 tiles / (2 x 1024 x 1024 per row); the 1024x1024 tile from 80M weights / 76 tiles | 0.4-8 GB/s | estimated (router width / clock not published) |
| Simba 36-chiplet (2019) | mesh | 0.497 us | derived (C47), DIGITAL chip point: one input row through a PE's resident 32 KiB = 2 x 32,768 ops / (128 ops/cycle x 1.03 GHz, the C41 experiment point); shape-invariant (576 PEs x 65,536 / 75.9 TOPS agrees) | ~560 GB/s (coordinate, C37) | per NoC link 8.75 GB/s published (JSSC §II-C); coordinate: a 256x256-array equivalent = 2 PEs -> 2 x 8.75 x 32; D2D = GRS 12.5 max / 5.5 as experimented; NOT a device mark (paradigm digital) |
| Tsinghua multi-chip (2025) | hub-io | -- | pending | -- | D2D 0.1-2 GB/s estimated (board-level links through the FPGA hub) |

**Device marks vs the swept surface (O17b / C31; four marks since C36).**
The chip points with a t_MVM value are the SILICON MARKS of the (t_MVM x
bandwidth) plane, served by `anchors.device_marks()` -- the only source a
plane figure may draw device marks from (group 27 checks). Each carries
its own status: NeuRRAM 10.14 us **measured**, Mythic M1076 6.38 us
**derived** (25 TOPS / 76 tiles / 2*1024*1024, C36), ISAAC 1.6 us
**design point**, HERMES 0.133 us **derived** (63.1 TOPS / 64 cores /
2*256*256). Everything between and beyond the marks on the device grid
(0.05-100 us) is a closed-form surface of the model -- like the
analog-reality band, an estimate to be read as such, not a measurement.

## Per-axis sweeps (O25 / C26): `python3 scripts/sweep_axes.py`

Closed-form re-scoring of the stored per-operator components on a log grid
(8 points per decade plus the anchor values and the 2^k words/cycle
points), both overlap ends, read at both paradigms' columns; figures
`analysis/sweep_axis_*.png`, data `analysis/phase_sweep.json`, pins in
`tests/test_anchor_registry.py` (group 23). Axes A-H are the NeuRRAM tier;
the plane below sweeps the device (O17b / C31). Headline readouts:

| axis | digital column | analog-reality band (estimated) |
|---|---|---|
| A on-die link (355M, prefill on chip; 2x4 default grid, C27) | 1.00x at Simba / ESP / FlooNoC, every scheme | 0.4 GB/s: star 1.00x, the three routed schemes 1.31x (mesh centre, mesh corner and the tree tie on the fill-exact grid), bus 3.33x; 8 GB/s: all 1.00x. Exact 1% crossings 0.195 / 0.782 / 0.782 / 0.782 / 1.89 GB/s, doubling 0.061 / 0.243 / 0.243 / 0.243 / 0.68 GB/s (on the 3x3 comparison grid the centred / corner rows read 0.586 / 0.977 and 0.182 / 0.304 GB/s). Knee operator: qk^T on the point-to-point schemes (ffn2 on the bus); ffn2 everywhere once the attention is offloaded |
| B1 die-to-die (355M, 48-die pipelined) | GRS: 1.00x every ordering, both conditions | on chip at 0.1 GB/s: mesh orderings 1.00x, bus 10.4x; offloaded at 0.1 GB/s: 12-19x (mesh), 70.5x (bus); at 2 GB/s: mesh 1.00x, bus 3.5x. The offload dividend needs > 1.2-1.9 GB/s (mesh 1% crossings) |
| B2 die-to-die (2.7B chain, O13) | GRS: 1.00x every seating | 1% crossings 1.02-1.72 GB/s, doubling 0.26-0.40 GB/s; 0.1 GB/s: 4.9-7.0x; 2 GB/s: 1.00x. ffn2's entry sets the busiest die link; with the on-die link at 0.4 GB/s the stack adds 1.19x on top |
| B3 die-to-die (4-die probe) | GRS: 1.00x | 1% at 0.40-0.81 GB/s, doubling at 0.20-0.40 GB/s |
| C die<->unit link (offload, end to end) | GRS: 1.01x prefill (518.1 ms = the ledger), 1.00x decode | 1% at 9.8 (prefill) / 5.0 (decode) GB/s; doubling at 0.098 / 0.050 GB/s; at 0.1 GB/s prefill 1.98x, decode 1.50x |
| H partial-sum width (1 vs 2 words) | -- | the 1% and doubling crossings roughly halve at 1 word (bus 1.17 vs 1.89 GB/s) |
| T1 die-buffer hub (O28, C34; value units, one shared port) | (the digital anchors are NoC links -- scale reference only) | knee ffn2 every condition; 1% at 2.27 / 2.33 GB/s (prefill on chip / offloaded); busiest-op net = compute at 2.42 GB/s; MX100-class (DMA + shared SRAM = THIS axis) reads 3.9-5.0x at the band's 0.4 GB/s, 1.00x at 8 GB/s. Identity: hub words = T2 bus words + the op's input once (ffn1 +6.25%). Timeloop's native throttling is counter units (x7 / x8x2; write port binds) -- validation only, group 29 |
| plane: (t_MVM x bandwidth), O17b (C31) | at HERMES (76.3x) the on-die r=1 boundary (prefill offloaded, busiest op ffn2) is 15.4 / 61.6 / 154 GB/s (star / routed / bus): Simba and ESP fall below the routed line, FlooNoC alone stays above; the 2.7B chain's boundary is 77 GB/s, 6.2x past GRS | boundary = closed form 0.202 / 0.808 / 2.02 GB/s x (10.14 us / t_MVM); the analog band 0.4-8 GB/s crosses the routed line at t_MVM ~ 1-20 us -- the swept thresholds land on the closed form to 1e-9 (group 27). Fixed: K/V write, digital unit, attention unit, link GB/s (a 76.3x device speeds decode 1.11x -- `device_fixed_terms.png`). Since C33 both panels carry the d FAMILY (one line per width tier, d = 1024 the production base; die level = tiler closed form, the d = 2560 line through the measured B2 mark; routed x4 verified d-independent) |


## Conversion into the simulator's unit

The simulator meters bandwidth in words/cycle: 1 word = one 8-bit value (an
activation, or one partial sum counted at 2 words), device cycle = 1.4486 µs
(calibrated array model) → **1 GB/s = 1,449 words/cycle**. Wire volumes are
values (C25): CiMLoop's bit-slice / bit / access counters are divided out in
`traffic.py`; before 2026-08-27 they were taken as words (14x / 48x).

| tier | GB/s | words/cycle |
|---|---|---|
| LOW (Simba on-die) | 8.75 | 12,675 |
| MID (ESP) | 32.0 | 46,354 |
| HIGH (FlooNoC) | 80.6 | 116,793 |
| D2D (Simba GRS) | 12.5 | 18,107 |
| D2D (UCIe-S spec) | 64.0 | 92,708 |

The unit carries the device (O17): a threshold in words/cycle is fixed by
the traffic; its GB/s value scales as 1/t_MVM -- one MVM per input row is 7
slices x 1.4486 us = 10.14 us here; ISAAC-class ~1.6 us (16 one-bit slices x
100 ns, 6x), HERMES-class ~130 ns (63.1 TOPS / 64 cores / 2*256*256, derived;
~76x). Since C30 (O17a) the device is the fabric's `device` block and the
registry's CYCLE_S / T_MVM_S ARE its values; bandwidths in the fabric configs
are declared in GB/s (`*_gbps`) and converted at load with that cycle (the
unit link 12.5 GB/s = 18,107 words/cycle), so a fabric with another device
re-labels every anchor consistently; every run checks the CiMLoop macro's
`GLOBAL_CYCLE_SECONDS` against the declaration.

**What is and is not substituted.** An anchor substitutes exactly ONE
number — the per-link bandwidth. The workload (GPT-2 medium, our mapper
runs), the chip architecture (8 macros x 4 cores x 8 crossbars of 256x256
ReRAM arrays), the device cycle (1.4486 us), and all traffic volumes remain
OUR chip's. Nothing else from Simba/ESP/FlooNoC (frequency, word width,
router design, die size) is imported. This is a one-variable sensitivity
substitution answering "if our die NoC's links delivered what fabricated
NoCs deliver, what happens" — not a simulation of those chips.

Note (O22/O23): the model's per-wire loads are likewise per direction (full-duplex point-to-point schemes; a bus is one shared medium) and count partial sums at 16 bits up the tree, so anchor bandwidths and modeled loads are compared like for like.

Caveats: per-link, one direction, headline rates (no protocol overhead
deducted); the model's wires are per direction as well (C17), so the
comparison is like for like. Process nodes differ
(12–16 nm vs our 130 nm device model) — the anchors bound what NoCs of
shipping accelerators deliver, they do not calibrate our wires.

## Digital vector unit (O24, platform input DR-8) -- generic example values

The non-matmul operators (softmax, GELU, LayerNorm, residual adds) run in a
digital vector unit next to the glb on every CIM design in the literature
(ISAAC/PRIME/PUMA-class tiles carry LUT activation units or a small
programmable vector unit; TPU v1 and Simba have fixed activation /
post-processing stages; transformer CIM chips such as TranCIM carry
dedicated softmax / LayerNorm engines). Until the company supplies its own:

| parameter | example default | source / rule |
|---|---|---|
| per-op energy, 16-bit add | 0.05 pJ | Horowitz, "Computing's energy problem", ISSCC 2014, 45 nm table (8-bit add 0.03, 16-bit 0.05, 32-bit 0.1 pJ) |
| per-op energy, 16-bit multiply | 0.6 pJ | same table (8-bit mult 0.2 pJ; 32-bit 3.1 pJ) -- interpolated example |
| table lookup (exp / tanh / rsqrt) | 1.0 pJ | small-SRAM read order of magnitude (same table: 8 KB SRAM 10 pJ per 64-bit word) -- example |
| lanes x clock | 64 x 1 GHz | sized to the die's array output rate: 256 arrays x 128 outputs per device cycle (1.4486 us) = 22.6 G results/s; 3-op softmax needs ~70 G ops/s |
| glb access energy | 15.47 pJ/word | CiMLoop-calibrated, ffn1 prefill fixture (892 uJ / 57.67 M scalar accesses) -- not an example |

`analyze_digital_sensitivity.py` sweeps lanes x clock so the real chip's
values can be read off the curve.

## External attention unit (O9, platform input DR-9) -- generic public figures

Under offload the attention (QK^T, softmax, AV, and the K/V) leaves the die
for an abstract NPU-class digital unit at the package attach point with its
own K/V memory. No internal structure is modeled; the interface is:

| parameter | default | source / rule |
|---|---|---|
| internal compute rate | 2 T MAC/s (4 TOPS INT8) | edge-NPU class: Google Edge TPU public figure, 4 TOPS INT8 at 2 W |
| internal average cost | 1.0 pJ per MAC, all-in | the same public figure, 2 TOPS/W (arithmetic alone would be ~0.25 pJ per 8-bit MAC, Horowitz ISSCC 2014) |
| per-call overhead | 0 | parameter present, no public default |
| K/V memory bandwidth | 25.6 GB/s | LPDDR4-class, two 32-bit channels at 3200 MT/s |
| K/V memory energy | 50 pJ per 8-bit word read or write | LPDDR4 published range ~4-8 pJ/bit (the code's existing off-chip constant) |
| K/V capacity | 2 GB | one LPDDR4 package; ~40k tokens of context for GPT-2 medium |
| die<->unit link | 12.5 GB/s per direction, 10 pJ per word per hop; energy priced at the die placement's mean hop count from the attention dies to the attach point (3.5 under the 48-die snake seating, routed grid, hub at the centre) | the same class as the die-to-die links (Simba GRS, above); the die side always carries the die placement -- the interface's reference hop count (1) is only the fallback for a direct call without a placement |
| units | 1, serving all layers | the layer count it serves sets the pipelined stage: 24 layers' attention per beat |

`analyze_offload_unit_sensitivity.py` sweeps rate x K/V bandwidth x units so
the real unit can be read off the curves; the die-side numbers (unit
infinitely fast, link infinitely wide) remain published beside the
end-to-end ones. Since C39 the unit's compute + K/V time is measured as
the OFFLOADED configuration's fixed floor on the device axis
(`device_fixed_terms.png`, four panels): 1.02 ms per decode token / 19.7
ms prefill at these generic values -- below the on-chip write wall (DR-5:
13.32 / 78.8 ms) at every device tier, which is what the real DR-9
numbers must keep beating; the two DR parameters set the two
configurations' ceilings.
