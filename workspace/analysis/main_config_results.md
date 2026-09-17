# Main configuration results (S9 task A)

2.7B-class (2560 / 10240 / 32 layers), batch 1, S = 512; 544 of 576 dies on a 24x24 mesh, XY; NeuRRAM-derived row time 10.14 µs; κ = 2 (injection and ejection each κ·B, independent); serial prefill. Search: 3 starts × 3 seeds, 1200 steps, α 0.996, t₀ = 20 ms, objective T_single at 0.4 GB/s, 2.6 s per run.

| layout | kind | T prefill 0.4 (ms) | H 0.4 (ms) | comm share (T) | A (M words) | A/floor | binding | T prefill 12.5 (ms) | T decode 0.4 (ms) | E dynamic (J) | E comm (J) | comm share (E) |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|
| sa_random_s2 | endpoint | 1904.24 | 983.04 | 51.6% | 393.2 | 1.504 | link | 952.65 | 26.113 | 2.5161 | 0.2191 | 8.71% |
| sa_random_s1 | endpoint | 1908.82 | 987.63 | 51.7% | 395.1 | 1.511 | link | 952.80 | 26.117 | 2.5163 | 0.2193 | 8.72% |
| sa_random_s0 | endpoint | 1914.07 | 992.87 | 51.9% | 397.1 | 1.519 | mixed | 952.97 | 26.131 | 2.5203 | 0.2234 | 8.86% |
| sa_clustered_s1 | endpoint | 1918.00 | 996.80 | 52.0% | 398.7 | 1.525 | link | 953.09 | 26.138 | 2.5173 | 0.2203 | 8.75% |
| sa_snake_s0 | endpoint | 1921.76 | 1000.57 | 52.1% | 400.2 | 1.531 | link | 953.21 | 26.143 | 2.5138 | 0.2169 | 8.63% |
| sa_clustered_s2 | endpoint | 1921.76 | 1000.57 | 52.1% | 400.2 | 1.531 | mixed | 953.21 | 26.144 | 2.5123 | 0.2153 | 8.57% |
| sa_clustered_s0 | endpoint | 1922.26 | 1001.06 | 52.1% | 400.4 | 1.531 | link | 953.23 | 26.147 | 2.5155 | 0.2185 | 8.69% |
| sa_snake_s2 | endpoint | 1930.45 | 1009.25 | 52.3% | 403.7 | 1.544 | link | 953.49 | 26.161 | 2.5087 | 0.2117 | 8.44% |
| sa_snake_s1 | endpoint | 1942.08 | 1020.89 | 52.6% | 408.4 | 1.562 | mixed | 953.86 | 26.182 | 2.5118 | 0.2148 | 8.55% |
| random_s3 | random | 2118.71 | 1197.51 | 56.5% | 479.0 | 1.832 | link | 959.52 | 26.534 | 2.5229 | 0.2259 | 8.96% |
| random_s1 | random | 2128.21 | 1207.01 | 56.7% | 482.8 | 1.846 | link | 959.82 | 26.551 | 2.5225 | 0.2256 | 8.94% |
| random_s2 | random | 2145.74 | 1224.54 | 57.1% | 489.8 | 1.873 | mixed | 960.38 | 26.587 | 2.5226 | 0.2257 | 8.95% |
| random_s4 | random | 2151.96 | 1230.77 | 57.2% | 492.3 | 1.883 | link | 960.58 | 26.598 | 2.5300 | 0.2331 | 9.21% |
| random | rule | 2153.11 | 1231.91 | 57.2% | 492.8 | 1.884 | link | 960.62 | 26.602 | 2.5251 | 0.2282 | 9.04% |
| least_manhattan | rule | 2156.64 | 1235.52 | 57.3% | 494.2 | 1.890 | mixed | 960.66 | 26.536 | 2.3382 | 0.0412 | 1.76% |
| nmap_greedy | rule | 2202.68 | 1281.56 | 58.2% | 512.6 | 1.960 | link | 962.14 | 26.626 | 2.3393 | 0.0424 | 1.81% |
| heaviest_first | rule | 2409.82 | 1488.65 | 61.8% | 595.5 | 2.277 | link | 968.80 | 27.069 | 2.4394 | 0.1424 | 5.84% |
| clustered | rule | 2550.35 | 1629.22 | 63.9% | 651.7 | 2.492 | link | 973.26 | 27.306 | 2.3379 | 0.0410 | 1.75% |
| snake | rule | 4106.67 | 3185.54 | 77.6% | 1274.2 | 4.873 | link | 1023.07 | 30.349 | 2.3537 | 0.0567 | 2.41% |
| default_A4 | default | 4192.54 | 3271.39 | 78.0% | 1308.6 | 5.004 | link | 1025.83 | 30.529 | 2.3937 | 0.0967 | 4.04% |
| sequential | rule | 4192.54 | 3271.39 | 78.0% | 1308.6 | 5.004 | link | 1025.83 | 30.529 | 2.3937 | 0.0967 | 4.04% |

## Headline statistics

| phase | B (GB/s) | strongest baseline | T_strongest (ms) | headline T (median of 3 seeds, ms) | G headline | G range (seeds) | G best-of-9 | G vs default fill | comm share (strongest → selected) |
|---|---:|---|---:|---:|---:|---|---:|---:|---|
| prefill | 0.4 | random_s3 | 2118.71 | 1908.82 (sa_random_s1) | **9.91%** | 9.66–10.12% | 10.12% (sa_random_s2) | 54.5% | 56.5% → 51.7% |
| prefill | 12.5 | random_s3 | 959.52 | 952.80 (sa_random_s1) | **0.70%** | 0.68–0.72% | 0.72% (sa_random_s2) | 7.1% | 4.0% → 3.3% |
| decode | 0.4 | random_s3 | 26.53 | 26.12 (sa_random_s1) | **1.57%** | 1.52–1.59% | 1.59% (sa_random_s2) | 14.4% | 8.8% → 7.4% |
| decode | 12.5 | least_manhattan | 24.20 | 24.25 (sa_snake_s0) | **-0.21%** | -0.22–-0.21% | -0.21% (sa_random_s1) | 0.4% | 0.3% → 0.3% |

## Random sample and search statistics (task A1)

| phase | B | random seeds (n=5) T (ms) | median | min (seed) | max (seed) | spread | search per-seed best-over-starts (ms) | median | range |
|---|---:|---|---:|---|---|---:|---|---:|---|
| prefill | 0.4 | 2153.11, 2128.21, 2145.74, 2118.71, 2151.96 | 2145.74 | 2118.71 (random_s3) | 2153.11 (random) | 1.62% | 1914.07 (sa_random_s0), 1908.82 (sa_random_s1), 1904.24 (sa_random_s2) | 1908.82 | 1904.24–1914.07 |
| prefill | 12.5 | 960.62, 959.82, 960.38, 959.52, 960.58 | 960.38 | 959.52 (random_s3) | 960.62 (random) | 0.11% | 952.97 (sa_random_s0), 952.80 (sa_random_s1), 952.65 (sa_random_s2) | 952.80 | 952.65–952.97 |
| decode | 0.4 | 26.60, 26.55, 26.59, 26.53, 26.60 | 26.59 | 26.53 (random_s3) | 26.60 (random) | 0.25% | 26.13 (sa_random_s0), 26.12 (sa_random_s1), 26.11 (sa_random_s2) | 26.12 | 26.11–26.13 |
| decode | 12.5 | 24.27, 24.27, 24.27, 24.27, 24.27 | 24.27 | 24.27 (random_s1) | 24.27 (random) | 0.01% | 24.25 (sa_snake_s0), 24.25 (sa_random_s1), 24.25 (sa_clustered_s2) | 24.25 | 24.25–24.25 |

## Ledger: every paper percentage from absolute values (task A1)

| quantity | numerator layout (ms) | denominator layout (ms) | value | statistic |
|---|---|---|---:|---|
| G headline, prefill, 0.4 GB/s | sa_random_s1 (1908.82) | random_s3 (2118.71) | 9.91% | median over 3 SA seeds of best-over-3-starts (the median seed's layout) |
| G best-of-nine, prefill, 0.4 GB/s | sa_random_s2 (1904.24) | random_s3 (2118.71) | 10.12% | min over 9 runs (labelled apart) |
| G vs default fill, prefill, 0.4 GB/s | sa_random_s1 (1908.82) | default_A4 (4192.54) | 54.47% | same selected layout as the headline |
| G headline, prefill, 12.5 GB/s | sa_random_s1 (952.80) | random_s3 (959.52) | 0.70% | median over 3 SA seeds of best-over-3-starts (the median seed's layout) |
| G best-of-nine, prefill, 12.5 GB/s | sa_random_s2 (952.65) | random_s3 (959.52) | 0.72% | min over 9 runs (labelled apart) |
| G vs default fill, prefill, 12.5 GB/s | sa_random_s1 (952.80) | default_A4 (1025.83) | 7.12% | same selected layout as the headline |
| G headline, decode, 0.4 GB/s | sa_random_s1 (26.12) | random_s3 (26.53) | 1.57% | median over 3 SA seeds of best-over-3-starts (the median seed's layout) |
| G best-of-nine, decode, 0.4 GB/s | sa_random_s2 (26.11) | random_s3 (26.53) | 1.59% | min over 9 runs (labelled apart) |
| G vs default fill, decode, 0.4 GB/s | sa_random_s1 (26.12) | default_A4 (30.53) | 14.45% | same selected layout as the headline |
| G headline, decode, 12.5 GB/s | sa_snake_s0 (24.25) | least_manhattan (24.20) | -0.21% | median over 3 SA seeds of best-over-3-starts (the median seed's layout) |
| G best-of-nine, decode, 12.5 GB/s | sa_random_s1 (24.25) | least_manhattan (24.20) | -0.21% | min over 9 runs (labelled apart) |
| G vs default fill, decode, 12.5 GB/s | sa_snake_s0 (24.25) | default_A4 (24.34) | 0.38% | same selected layout as the headline |
| dE dynamic energy, prefill, headline layout vs strongest baseline | sa_random_s1 (2.5163 J) | random_s3 (2.5229 J) | +0.26% | same layouts as the headline G; energy is B- and kappa-independent |
| dE dynamic energy, decode, headline layout vs strongest baseline | sa_random_s1 (0.0049 J) | random_s3 (0.0049 J) | +0.26% | same layouts as the headline G; energy is B- and kappa-independent |

Ranking prefill vs decode at 0.4 GB/s (Spearman over 21 layouts): 0.987; the prefill-selected layout ranks #2 in decode.

## Sensitivity (S8-A, same protocol; gain vs the strongest baseline of that cell)

| cell | 0.4 GB/s | 12.5 GB/s | endpoint binding |
|---|---:|---:|---|
| 24x24/k1 | 1.86% | 0.14% | port |
| 24x24/k2 | 10.12% | 0.72% | link |
| 24x24/k4 | 9.92% | 0.70% | link |
| 12x48/k1 | 2.69% | 0.20% | mixed |
| 12x48/k2 | 9.81% | 0.68% | link |
| 12x48/k4 | 9.82% | 0.68% | link |
