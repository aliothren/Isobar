# Numbers for the paper (S9, 2026-09-17)

Every entry: workload · hardware configuration · level · denominator · statistic. Sources: FIXLIST S9 and the JSON artifacts named there.

## Main result

| # | number | workload | hardware / execution | level | denominator | statistic |
|---|---|---|---|---|---|---|
| 1 | **9.9%** latency reduction | 2.7B, batch 1, S = 512, prefill | 24×24 mesh, XY, 544/576 dies, NeuRRAM row time, 0.4 GB/s, κ = 2 | whole model | strongest baseline (random_s3, 2119 ms) | median of 3 seeds (best over 3 starts); range 9.7–10.1% |
| 2 | 54% | same | same | whole model | A4 default (stacked) fill, 4193 ms | same |
| 3 | 0.70% | same | same at 12.5 GB/s | whole model | strongest baseline | same |
| 4 | 1.57% | decode: 1 token over 512-token cache | same at 0.4 GB/s | whole model | strongest baseline | same; no decode search (ranking 0.987) |

## Sensitivity and mechanism

| # | number | meaning | denominator | source |
|---|---|---|---|---|
| 5 | 1.86% / 9.9% / 9.92% | gain at κ = 1 / 2 / 4 | that cell's strongest baseline | kappa_geometry_sweep, main_config_results |
| 6 | 6.7% | hardware gain of κ 1→2 itself (best baseline), not placement | κ = 1 best baseline | kappa_geometry_sweep |
| 7 | 9.8% | gain on the 12×48 geometry, κ = 2 | that cell's strongest baseline | kappa_geometry_sweep |
| 8 | 2.66× | package envelope B₊/B₋, κ = 2 (κ = 1: 2.37×) | min over 7 rules | phase_diagram_isobar_k2 |
| 9 | B₋ 0.535 / B₊ 1.421 GB/s | placement-dependent band at the NeuRRAM rate, κ = 2 | — | same |
| 10 | η = 17.5%, r = 56.5% → G = 9.9% | fixed pair at 0.4 GB/s; G = η·r identity | reference = random_s3 | bw_slice_k2 |
| 11 | 11.4% / 11.2% | loss avoided vs distance / hop proxies at κ = 2 | resource-aware endpoint | objective_ablation_k2 |
| 12 | 2.67×; B₋ 0.606 / B₊ 1.616 GB/s | intra-die envelope (A3 ffn die, exhaustive) and its per-op masking thresholds at the NeuRRAM rate; 0.4 GB/s below B₋, ≥ 1.62 above B₊ | min / max over 70 seatings ÷ per-op compute | phase_diagram_isobar (F-FIG1a) |
| 13 | 9.0% (9.5% without package term) | intra-die β gain, 355M-class layer at 0.4 GB/s | shipped seating's layer time | intra_die_integration |
| 14 | ρ 0.962; +12–31% | packet judge on the synthetic fan-out batch (κ = 1, 24×24, 17 dies/stage) | best random draw under BookSim | b_fanout_24x24_rerank |
| 15 | 1.34 ms / 37 ms / ~2 s | incremental score / full score / one 1200-step run, 2.7B, 544 dies | — | timing_probe, kappa_geometry_sweep |

Not to be combined: #14 is a communication-batch time, not the 2.7B whole model; #13 is layer-level on another instance; #6 is hardware, not placement.

## Provenance and mechanism pointers (S10)

- Every percentage above has a ledger row in `main_config_results.md` (numerator layout, denominator layout, absolute ms, statistic); #2's denominator, the A4 default fill, is the sequential rule (identical loads), 4192.5 ms at κ = 2.
- The random sample is the five declared seeds (0–4), spread 1.6% at 0.4 GB/s (2118.7–2153.1 ms); the strongest baseline random_s3 is its minimum. The headline is not a gain over the random median.
- Why random beats the adapted rules and the search beats random: `mechanism_table.md` (flows stacked on the busiest ffn2 link: 25 → 10 → 8–10 → 5; word-hops 4 G vs 22 G).
- Fig. 1(a) and the A3 case are one instance (gpt2-medium class, d 1024, S 512, 2×4 macro mesh): `intra_die_correspondence.md` gives the identity table, per-op states at 0.4 GB/s, and how max(compute, serialization) makes the panel's boundaries the masking thresholds.
- Baseline scope: `baseline_provenance.md`.

## Dynamic energy (S10 section 6; `energy_export.md`)

| # | number | meaning | denominator | source |
|---|---|---|---|---|
| 16 | +0.26% (range +0.10…+0.56% over 9 endpoints) | system dynamic energy change of the headline layout vs the strongest baseline; communication energy +2.94% | random_s3, 2.5229 J | energy_export |
| 17 | 9.0% / 1.8% | communication share of dynamic energy, dispersed (random_s3) / compact rules | that layout's E | energy_export |
| 18 | +7.33% energy, 20.4% latency | clustered (E-best of the set) vs random_s3: the compact-vs-dispersed trade-off | random_s3 | energy_export |
| 19 | not modelled | intra-die (A3) energy: no pJ/word on the macro link, no per-op energy for d = 1024 | — | energy_export |

Model: E = per-op CiMLoop energy + elementwise (digital unit) + payload words × max(XY hops, 1) × 10 pJ/word (Simba GRS band midpoint); static power not modelled; independent of B and κ. Named "dynamic energy" throughout.
