# Configuration sweep (fixed layouts re-priced; GPU baselines A100 21.64 s / 5474 J, Thor 24.83 s / 1899 J)

432 points: model × macros per die {4,8,16,32} (OPT-13B also 8 macros with column-split QKV) × 4 device row rates × 4 mesh bandwidths × 3 K/V bandwidths. Full data: `sweep/sweep_all.csv`. Each cell is "request time s / speed-up ×"; energy changes only with the macros per die and the split and is listed in the first table.

## OPT-13B vs. A100: capacity and energy (independent of rate and bandwidth)

| macros/die | split | CIM dies / grid | E_request (J) | J/token | GPU/CIM energy | energy saving |
| --- | --- | --- | --- | --- | --- | --- |
| 16 | colrow | 1160 / 35x35 | 36.44 | 0.0356 | 150× | 99.33% |
| 32 | colrow | 640 / 26x26 | 33.17 | 0.0324 | 165× | 99.39% |
| 4 | colrow | 4400 / 67x67 | 73.35 | 0.0716 | 75× | 98.66% |
| 8 | colrow | 2200 / 47x47 | 46.52 | 0.0454 | 118× | 99.15% |
| 8 | col | 2400 / 49x49 | 44.89 | 0.0438 | 122× | 99.18% |

## OPT-13B vs. A100: macros per die × mesh bandwidth (NeuRRAM rate, K/V 25.6 GB/s)

| die_macros | 0.4 | 1.6 | 4.0 | 12.5 |
| --- | --- | --- | --- | --- |
| 4 | 52.07 / 0.42× | 21.82 / 0.99× | 15.77 / 1.37× | 14.21 / 1.52× |
| 8 | 33.56 / 0.64× | 17.11 / 1.26× | 13.82 / 1.57× | 12.91 / 1.68× |
| 16 | 24.76 / 0.87× | 14.87 / 1.45× | 12.90 / 1.68× | 12.29 / 1.76× |
| 32 | 16.54 / 1.31× | 12.79 / 1.69× | 12.04 / 1.80× | 11.74 / 1.84× |

## OPT-13B vs. A100: device rate × mesh bandwidth (8 macros, K/V 25.6 GB/s)

| device_rate | 0.4 | 1.6 | 4.0 | 12.5 |
| --- | --- | --- | --- | --- |
| neurram_10.14us | 33.56 / 0.64× | 17.11 / 1.26× | 13.82 / 1.57× | 12.91 / 1.68× |
| isaac_1.6us | 32.06 / 0.67× | 15.61 / 1.39× | 12.33 / 1.76× | 11.42 / 1.89× |
| hermes_4phase_0.52us | 31.87 / 0.68× | 15.43 / 1.40× | 12.14 / 1.78× | 11.23 / 1.93× |
| hermes_1phase_0.133us | 31.81 / 0.68× | 15.36 / 1.41× | 12.07 / 1.79× | 11.16 / 1.94× |

## OPT-13B vs. A100: K/V bandwidth × mesh bandwidth (8 macros, NeuRRAM rate)

| kv_gbps | 0.4 | 1.6 | 4.0 | 12.5 |
| --- | --- | --- | --- | --- |
| 25.6 | 33.56 / 0.64× | 17.11 / 1.26× | 13.82 / 1.57× | 12.91 / 1.68× |
| 51.2 | 28.83 / 0.75× | 12.39 / 1.75× | 9.10 / 2.38× | 8.19 / 2.64× |
| 136.0 | 25.89 / 0.84× | 9.44 / 2.29× | 6.15 / 3.52× | 5.25 / 4.12× |

## OPT-13B vs. A100: fastest settings (HERMES 1-phase rate, K/V 136 GB/s), macros per die × mesh

| die_macros | 0.4 | 1.6 | 4.0 | 12.5 |
| --- | --- | --- | --- | --- |
| 4 | 42.65 / 0.51× | 12.40 / 1.74× | 6.35 / 3.41× | 4.79 / 4.52× |
| 8 | 24.14 / 0.90× | 7.69 / 2.81× | 4.40 / 4.92× | 3.49 / 6.19× |
| 16 | 15.34 / 1.41× | 5.45 / 3.97× | 3.48 / 6.22× | 2.87 / 7.53× |
| 32 | 7.12 / 3.04× | 3.37 / 6.42× | 2.62 / 8.26× | 2.32 / 9.32× |

## OPT-13B column-split QKV (8 macros): device rate × mesh bandwidth (K/V 25.6 GB/s)

| device_rate | 0.4 | 1.6 | 4.0 | 12.5 |
| --- | --- | --- | --- | --- |
| neurram_10.14us | 18.41 / 1.18× | 13.36 / 1.62× | 12.35 / 1.75× | 11.96 / 1.81× |
| isaac_1.6us | 16.91 / 1.28× | 11.86 / 1.82× | 10.85 / 1.99× | 10.46 / 2.07× |
| hermes_4phase_0.52us | 16.72 / 1.29× | 11.67 / 1.85× | 10.66 / 2.03× | 10.27 / 2.11× |
| hermes_1phase_0.133us | 16.65 / 1.30× | 11.61 / 1.86× | 10.60 / 2.04× | 10.21 / 2.12× |

## OPT-13B column-split QKV (8 macros): K/V bandwidth × mesh bandwidth (NeuRRAM rate)

| kv_gbps | 0.4 | 1.6 | 4.0 | 12.5 |
| --- | --- | --- | --- | --- |
| 25.6 | 18.41 / 1.18× | 13.36 / 1.62× | 12.35 / 1.75× | 11.96 / 1.81× |
| 51.2 | 13.68 / 1.58× | 8.63 / 2.51× | 7.62 / 2.84× | 7.23 / 2.99× |
| 136.0 | 10.74 / 2.02× | 5.69 / 3.80× | 4.68 / 4.63× | 4.29 / 5.04× |

## Gemma-7B vs. Thor: capacity and energy (independent of rate and bandwidth)

| macros/die | split | CIM dies / grid | E_request (J) | J/token | GPU/CIM energy | energy saving |
| --- | --- | --- | --- | --- | --- | --- |
| 16 | colrow | 616 / 25x25 | 8.14 | 0.0163 | 233× | 99.57% |
| 32 | colrow | 336 / 19x19 | 7.54 | 0.0151 | 252× | 99.60% |
| 4 | colrow | 2436 / 50x50 | 13.56 | 0.0271 | 140× | 99.29% |
| 8 | colrow | 1232 / 36x36 | 9.74 | 0.0195 | 195× | 99.49% |

## Gemma-7B vs. Thor: macros per die × mesh bandwidth (NeuRRAM rate, K/V 25.6 GB/s)

| die_macros | 0.4 | 1.6 | 4.0 | 12.5 |
| --- | --- | --- | --- | --- |
| 4 | 4.70 / 5.29× | 2.77 / 8.97× | 2.38 / 10.42× | 2.22 / 11.17× |
| 8 | 4.25 / 5.85× | 2.64 / 9.41× | 2.32 / 10.72× | 2.18 / 11.38× |
| 16 | 4.12 / 6.03× | 2.59 / 9.59× | 2.28 / 10.87× | 2.15 / 11.54× |
| 32 | 3.57 / 6.95× | 2.44 / 10.18× | 2.21 / 11.22× | 2.12 / 11.72× |

## Gemma-7B vs. Thor: device rate × mesh bandwidth (8 macros, K/V 25.6 GB/s)

| device_rate | 0.4 | 1.6 | 4.0 | 12.5 |
| --- | --- | --- | --- | --- |
| neurram_10.14us | 4.25 / 5.85× | 2.64 / 9.41× | 2.32 / 10.72× | 2.18 / 11.38× |
| isaac_1.6us | 3.72 / 6.67× | 2.11 / 11.76× | 1.79 / 13.88× | 1.65 / 15.01× |
| hermes_4phase_0.52us | 3.65 / 6.80× | 2.04 / 12.15× | 1.72 / 14.42× | 1.59 / 15.64× |
| hermes_1phase_0.133us | 3.63 / 6.84× | 2.02 / 12.29× | 1.70 / 14.62× | 1.56 / 15.87× |

## Gemma-7B vs. Thor: K/V bandwidth × mesh bandwidth (8 macros, NeuRRAM rate)

| kv_gbps | 0.4 | 1.6 | 4.0 | 12.5 |
| --- | --- | --- | --- | --- |
| 25.6 | 4.25 / 5.85× | 2.64 / 9.41× | 2.32 / 10.72× | 2.18 / 11.38× |
| 51.2 | 3.58 / 6.94× | 1.97 / 12.60× | 1.65 / 15.06× | 1.51 / 16.40× |
| 136.0 | 3.16 / 7.85× | 1.55 / 15.98× | 1.23 / 20.15× | 1.10 / 22.62× |

## Gemma-7B vs. Thor: fastest settings (HERMES 1-phase rate, K/V 136 GB/s), macros per die × mesh

| die_macros | 0.4 | 1.6 | 4.0 | 12.5 |
| --- | --- | --- | --- | --- |
| 4 | 2.99 / 8.29× | 1.07 / 23.27× | 0.68 / 36.43× | 0.52 / 47.59× |
| 8 | 2.55 / 9.75× | 0.94 / 26.51× | 0.61 / 40.40× | 0.48 / 51.67× |
| 16 | 2.42 / 10.27× | 0.89 / 27.94× | 0.58 / 42.60× | 0.45 / 55.09× |
| 32 | 1.88 / 13.22× | 0.75 / 33.32× | 0.52 / 47.88× | 0.42 / 58.65× |

## Extremes

- opt13b: slowest 52.07 s (4 macros colrow, neurram_10.14us, mesh 0.4, K/V 25.6; 0.42×), fastest 2.32 s (32 macros colrow, hermes_1phase_0.133us, mesh 12.5, K/V 136.0; 9.32×); points faster than the GPU: 211 / 240.
- gemma7b: slowest 4.70 s (4 macros colrow, neurram_10.14us, mesh 0.4, K/V 25.6; 5.29×), fastest 0.42 s (32 macros colrow, hermes_1phase_0.133us, mesh 12.5, K/V 136.0; 58.65×); points faster than the GPU: 192 / 192.
