# Dynamic energy of the frozen layouts (S10 section 6)

Main configuration: 2.7B, S = 512 prefill, 544/576 dies on 24×24, XY; κ = 2, 0.4 GB/s (energy is independent of B and κ). E = E_ops + E_elementwise + E_d2d; E_d2d = payload words × max(hops, 1) × 10 pJ/word (flat 1-hop charge + surplus beyond 1 hop); hops = XY route length; coefficient = midpoint of Simba's measured GRS band (0.82–1.75 pJ/bit). Static power not modelled. Seat-invariant terms: E_ops 2.270 J, E_elementwise 0.0265 J, E_d2d flat 0.0142 J.

| layout | T (ms) | E total (J) | E comm (J) | comm share | payload words (M) | word-hops (G) | mean hops | ΔT vs random_s3 | ΔE vs random_s3 | ΔE_comm vs random_s3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| default_A4 | 4192.5 | 2.3937 | 0.0967 | 4.04% | 1420.8 | 9.67 | 6.81 | -97.88% | +5.12% | +57.20% |
| sequential | 4192.5 | 2.3937 | 0.0967 | 4.04% | 1420.8 | 9.67 | 6.81 | -97.88% | +5.12% | +57.20% |
| snake | 4106.7 | 2.3537 | 0.0567 | 2.41% | 1420.8 | 5.67 | 3.99 | -93.83% | +6.71% | +74.90% |
| clustered | 2550.4 | 2.3379 | 0.0410 | 1.75% | 1420.8 | 4.10 | 2.88 | -20.37% | +7.33% | +81.87% |
| nmap_greedy | 2202.7 | 2.3393 | 0.0424 | 1.81% | 1420.8 | 4.24 | 2.98 | -3.96% | +7.28% | +81.25% |
| least_manhattan | 2156.6 | 2.3382 | 0.0412 | 1.76% | 1420.8 | 4.12 | 2.90 | -1.79% | +7.32% | +81.76% |
| heaviest_first | 2409.8 | 2.4394 | 0.1424 | 5.84% | 1420.8 | 14.24 | 10.03 | -13.74% | +3.31% | +36.95% |
| random | 2153.1 | 2.5251 | 0.2282 | 9.04% | 1420.8 | 22.82 | 16.06 | -1.62% | -0.09% | -0.98% |
| random_s1 | 2128.2 | 2.5225 | 0.2256 | 8.94% | 1420.8 | 22.56 | 15.88 | -0.45% | +0.01% | +0.16% |
| random_s2 | 2145.7 | 2.5226 | 0.2257 | 8.95% | 1420.8 | 22.57 | 15.88 | -1.28% | +0.01% | +0.12% |
| random_s3 | 2118.7 | 2.5229 | 0.2259 | 8.96% | 1420.8 | 22.59 | 15.90 | +0.00% | +0.00% | +0.00% |
| random_s4 | 2152.0 | 2.5300 | 0.2331 | 9.21% | 1420.8 | 23.31 | 16.40 | -1.57% | -0.28% | -3.16% |
| sa_clustered_s0 | 1922.3 | 2.5155 | 0.2185 | 8.69% | 1420.8 | 21.85 | 15.38 | +9.27% | +0.29% | +3.29% |
| sa_clustered_s1 | 1918.0 | 2.5173 | 0.2203 | 8.75% | 1420.8 | 22.03 | 15.51 | +9.47% | +0.22% | +2.48% |
| sa_clustered_s2 | 1921.8 | 2.5123 | 0.2153 | 8.57% | 1420.8 | 21.53 | 15.15 | +9.30% | +0.42% | +4.71% |
| sa_random_s0 | 1914.1 | 2.5203 | 0.2234 | 8.86% | 1420.8 | 22.34 | 15.72 | +9.66% | +0.10% | +1.15% |
| sa_random_s1 | 1908.8 | 2.5163 | 0.2193 | 8.72% | 1420.8 | 21.93 | 15.43 | +9.91% | +0.26% | +2.94% |
| sa_random_s2 | 1904.2 | 2.5161 | 0.2191 | 8.71% | 1420.8 | 21.91 | 15.42 | +10.12% | +0.27% | +3.02% |
| sa_snake_s0 | 1921.8 | 2.5138 | 0.2169 | 8.63% | 1420.8 | 21.69 | 15.26 | +9.30% | +0.36% | +4.02% |
| sa_snake_s1 | 1942.1 | 2.5118 | 0.2148 | 8.55% | 1420.8 | 21.48 | 15.12 | +8.34% | +0.44% | +4.91% |
| sa_snake_s2 | 1930.4 | 2.5087 | 0.2117 | 8.44% | 1420.8 | 21.17 | 14.90 | +8.89% | +0.56% | +6.29% |

Check: E_comm recomputed from words × max(hops,1) × pJ matches the evaluator to 7.8e-16 (relative).
E-best layout in this set: clustered (2.3379 J, ΔT -20.37%).

**Intra-die (A3): not modelled** — the macro link carries no pJ/word (calibration DR-4 is latency-only) and the 355M-class per-op records carry no energy; the A3 seating changes latency only. A layer dynamic-energy change for the 9.02% latency gain cannot be reported from the current model; it would need a glb↔macro link energy coefficient and a per-op energy record for the d = 1024 instance.
