# Bandwidth Anchors — published NoC / D2D link specs with provenance

Purpose: the simulator's link bandwidths are platform inputs. Until the real
chip's values arrive, results are stated against PUBLISHED link specs from
fabricated (or post-layout) accelerators, so that "where real chips land on
our threshold curves" is a sourced statement, not a guess. Consumed by
`scripts/analyze_anchored_sweep.py`.

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

## Conversion into the simulator's unit

The simulator meters bandwidth in words/cycle: 1 word = 8 bit, device cycle
= 1.4486 µs (calibrated array model) → **1 GB/s = 1,449 words/cycle**.

| tier | GB/s | words/cycle |
|---|---|---|
| LOW (Simba on-die) | 8.75 | 12,675 |
| MID (ESP) | 32.0 | 46,354 |
| HIGH (FlooNoC) | 80.6 | 116,793 |
| D2D (Simba GRS) | 12.5 | 18,107 |

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
deducted); our model treats a link as undirected (up+down share it), which
is conservative by up to 2× against duplex hardware. Process nodes differ
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
