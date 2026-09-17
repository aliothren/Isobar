# Fig. 1(a) vs the A3 intra-die case (S10 task B)

| item | Fig. 1(a) | §4.3 A3 case |
|---|---|---|
| model / d | gpt2-medium: d 1024, d_ff 4096 | same |
| co-resident operators (P, C, M at S = 512) | ffn1 (512, 1024, 4096), ffn2 (512, 4096, 1024) | attn die: qkv_proj (512, 1024, 3072), out_proj (512, 1024, 1024); ffn die: ffn1, ffn2 |
| macros / geometry / legal set | 8 slots, 2×4 mesh, glb centre; 70 joint seatings (ffn1 4 + ffn2 4) | same geometry; attn 280 + ffn 70, enumerated |
| device row rate | 0.0986 Mrows/s (10.14 µs/row, NeuRRAM) | same |
| intra-die link bandwidth | the y axis; B₋ 0.606 / B₊ 1.616 GB/s at that rate (per-op masking thresholds) | 0.4 GB/s (below B₋: communication dominated) |
| latency object | ffn die's local sub-problem; H vs R = masking switch of the max model | whole layer: attn + ffn dies + fixed rest (19.01 ms) + 2 package hand-offs (2.62 ms) |
| envelope / gain | 2.67× = A_max 8.389M / A_min 3.146M words (busiest macro-link words over the 70 seatings) | 9.02% = 1 − 45.125 / 49.597 ms (exhaustive best vs shipped contiguous, incl. package); 9.52% without the package term |

## Per-op local state at 0.4 GB/s (A3), shipped → exhaustive best

| die | op | compute (ms) | serialization shipped (ms) | serialization best (ms) | exposed shipped → best (ms) | state shipped → best |
|---|---|---:|---:|---:|---|---|
| attn | qkv_proj | 5.192 | 6.991 | 3.495 | 1.799 → 0.000 | serialization-bound → compute-bound |
| attn | out_proj | 5.192 | 5.243 | 0.000 | 0.051 → 0.000 | serialization-bound → compute-bound |
| ffn | ffn1 | 5.192 | 5.243 | 7.864 | 0.051 → 2.673 | serialization-bound → serialization-bound |
| ffn | ffn2 | 5.192 | 10.486 | 5.243 | 5.294 → 0.051 | serialization-bound → serialization-bound |

Fig. 1(a) is the ffn die of the A3 instance alone (70 seatings; the 2.67x is A_max/A_min of the ffn ops' busiest macro-link words); the text's 9.02% is the whole layer of the same instance (both dies, fixed rest, package hand-offs). Local cost enters the layer as write + prop + max(compute, serialization(beta) x scale) per op -- the max model -- so the panel's H-vs-R boundaries are exactly the masking thresholds: above B+ every seating is compute-bound (gain 0 at >= 2 GB/s, measured), below B- every seating is serialization-bound (0.1, 0.2 GB/s), and 0.4 GB/s lies BELOW B- = 0.606 GB/s: every one of the 70 seatings has an exposed op there, and the seating decides how severe (the exhaustive best still has ffn1 and ffn2 serialization-bound). The boundaries compare each op's serialization with ITS OWN compute (5.19 ms), the max model's switch.

