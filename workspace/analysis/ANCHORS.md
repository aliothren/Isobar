# Bandwidth Anchors — published NoC / D2D link specs with provenance

Purpose: the simulator's link bandwidths are platform inputs. Until the real
chip's values arrive, results are stated against PUBLISHED link specs from
fabricated (or post-layout) accelerators, so that "where real chips land on
our threshold curves" is a sourced statement, not a guess. Consumed by
`scripts/analyze_anchored_sweep.py`.

**Identity (O25).** Every anchor below is a DIGITAL accelerator's link --
Simba, ESP and FlooNoC NoCs on die, Simba's GRS package mesh die to die.
They are the upper bound of what fabricated interconnects deliver, not the
operating points of analog CIM chips: no fabricated analog CIM system
publishes an on-die link bandwidth (survey and registry mapping in "What
analog CIM systems publish" below). Every readout against these anchors is
therefore the digital-ecosystem column of the phase diagram (model scale x
device speed x transfer paradigm x link tier); the analog-reality column is
open item O25 and enters no external document until its rows exist.

## On-die NoC, per link, one direction

| tier | value | system | provenance | notes |
|---|---|---|---|---|
| **LOW — 8.75 GB/s** (70 Gb/s) | Simba chiplet-internal NoC | Zimmer et al., *A 0.32–128 TOPS Scalable MCM-Based DNN Inference Accelerator with Ground-Referenced Signaling in 16 nm*, IEEE JSSC 2020 | "At 0.72 V, each link of the NoC achieves 70-Gb/s bandwidth." Silicon-measured; a 16 nm inference chiplet — the closest published cousin to our die NoC. |
| **MID — 32 GB/s** (256 Gb/s) | ESP open-source SoC NoC, tile-to-tile | as reported in the FlooNoC comparison table (arXiv:2409.17606, Table; ESP: 12 nm FinFET, 16×16 mesh) | secondary source (FlooNoC's own comparison), noted honestly. |
| **HIGH — 80.6 GB/s** (645 Gb/s) | FlooNoC wide-link NoC | Fischer et al., *FlooNoC: A 645 Gbps/link 0.15 pJ/B/hop Open-Source NoC*, arXiv:2409.17606 | "achieve a bandwidth of 645 Gbps per link"; 0.15 pJ/B/hop; 12 nm post-layout (Occamy silicon sibling measured 584 Gbps). |

Also in the same comparison table: Celerity 96 Gb/s (16 nm silicon, 5×5
mesh), Ou et al. 45 Gb/s — bracketing LOW and MID.

Citation discipline: the ESP figure is a SECONDARY citation (FlooNoC's
comparison table). Before any external submission, either replace it with
the primary ESP publication's own number or keep the transitive citation
with an explicit "as reported in [FlooNoC]" footnote — do not cite it bare.

## Die-to-die (package), per link, one direction

| value | system | provenance | notes |
|---|---|---|---|
| **12.5 GB/s** (100 Gb/s) | Simba package GRS mesh | same JSSC 2020: "36 dice ... mesh network with 100 Gb/s interconnect in each link direction"; lanes run 11–25 Gb/s at **0.82–1.75 pJ/bit** | silicon-measured D2D on an organic substrate. **Adopted**: the die-link default energy is now 10 pJ/word = the midpoint of this measured band (6.6–14 pJ/word), replacing the earlier optimistic 5 pJ/word example |

## What analog CIM systems publish (survey 2026-08-27), and the registry tier each maps to

| system | fabric | published on-die link bandwidth | registry tier in this model |
|---|---|---|---|
| NeuRRAM (Wan et al., Nature 2022) | inter-core buffers and partial-sum accumulation on the board FPGA; no on-chip core network | none (chip IO, 130 nm) | hub-IO upper bound |
| TetraMem MX100 (arXiv 2410.14882) | 10 NPUs + RISC-V + DMA engine + shared SRAM (512 KB + 1 MB), 65 nm | none (shared medium) | bus, bandwidth at the T1 hub (`hub_bandwidth_words_per_cycle`) |
| HERMES 64-core (Le Gallo et al., Nat. Electron. 2023; arXiv 2212.02872) | on-chip network with per-core link controllers | not in the main text (supplement to check) | star (compile-time scheduled) |
| Mythic AMP M1076 / M1108 | per-tile 64 KB SRAM + NoC router | none (product material only) | star (compile-time scheduled) |
| Tsinghua multi-chip (Nat. Commun. 2025; Yao et al., Nature 2020) | 8 chips + FPGA hub, no chip-to-chip direct links | none (everything through the FPGA) | hub-IO / bus |
| Simba, ESP, FlooNoC, GRS (the anchors above) | digital NoCs and package links, 12-16 nm | 8.75 / 32 / 80.6 GB/s; 12.5 GB/s | mesh (digital ecosystem) |

Mapping rule: a DMA engine with shared SRAM is a shared medium whose
bandwidth is a T1 (hub) number in this model, not a T2 link; a compile-time
scheduled point-to-point fabric is the star scheme; a NoC is the mesh
scheme.

Structural estimate of the analog-reality tier -- `status = estimated`, NOT
an anchor, not read out anywhere until O25 adds the rows: on die 0.4-8 GB/s
(32-128 bit x 100-500 MHz), die to die 0.1-2 GB/s (board-level or older-node
direct links) -- 2-20x below the digital anchors on die, 1-2 orders below
GRS.

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

The unit carries the device (O17): a threshold in words/cycle is fixed by
the traffic; its GB/s value scales as 1/t_MVM -- one MVM per input row is 7
slices x 1.4486 us = 10.1 us here; ISAAC-class ~1.6 us (16 one-bit slices x
100 ns, 6x), HERMES-class ~130 ns (63.1 TOPS / 64 cores / 2*256*256, derived;
~76x). The words/cycle fields in the fabric configs (18,112 = 12.5 GB/s at
the 1.449 us rounding) are this cycle's conversion and move with it.

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
| lanes x clock | 64 x 1 GHz | sized to the die's array output rate: 256 arrays x 128 outputs per 1.449 us = 22.6 G results/s; 3-op softmax needs ~70 G ops/s |
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
end-to-end ones.
