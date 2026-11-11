# Per-operator cost ledger

Model gpt2-medium, S = 512, 24 layers; basis: co-residency shares (48-die seating); wiring scheme mesh_centre, link bandwidth 16,384 words/cycle (platform input); accounting: direction-split full-duplex links (bus shared); partial sums 2 words; O7 bracket both ends; busiest-wire occupancy = the lower bound of any schedule for the given routing × the schedule slack 1.
One row per item, nothing merged; items marked **not modelled, not counted** are not modelled by the platform.

## prefill

### Operator types, whole-model shares -- attention on chip

| operator type | whole-model energy (mJ) | energy share | whole-model latency (ms, perfect overlap) | latency share | whole-model latency (ms, zero overlap) | note |
|---|---|---|---|---|---|---|
| Q/K/V projection (qkv_proj) | 49.775 | 16.7% | 124.60 | 15.1% | 129.05 |  |
| attention scores QKᵀ (qk^t, with K write) | 63.413 | 21.2% | 137.69 | 16.7% | 146.59 |  |
| attention weighting AV (av, with V write) | 34.336 | 11.5% | 176.95 | 21.4% | 181.40 |  |
| output projection (out_proj) | 19.056 | 6.4% | 124.60 | 15.1% | 126.83 |  |
| FFN first layer (ffn1) | 64.170 | 21.5% | 124.60 | 15.1% | 129.05 |  |
| FFN second layer (ffn2) | 58.999 | 19.7% | 124.60 | 15.1% | 133.50 |  |
| softmax (digital unit) | 4.843 | 1.6% | 6.29 | 0.8% | 6.29 |  |
| GELU (FFN activation, digital unit) | 1.703 | 0.6% | 4.72 | 0.6% | 4.72 |  |
| LayerNorm ×2 (digital unit) | 1.202 | 0.4% | 1.97 | 0.2% | 1.97 |  |
| residual add ×2 (digital unit) | 1.169 | 0.4% | 0.39 | 0.0% | 0.39 |  |
| embedding lookup (off-chip read, once per model) | 0.026 | 0.0% | 0.00 | 0.0% | 0.00 | off-chip port bandwidth not set (fabric.offchip_bandwidth_words_per_cycle): priced, not timed |
| LM head (matmul, last token, once per model) | 0.080 | 0.0% | 0.01 | 0.0% | 0.01 |  |
| counted total (matmuls + digital-unit operators + off-chip reads) | 298.773 | 100.0% | 826.44 | 100.0% | 859.82 | denominator of the shares |

### Operator types, whole-model shares -- attention offloaded (end to end: on chip + off-chip unit)

| operator type | whole-model energy (mJ) | energy share | whole-model latency (ms, perfect overlap) | latency share | whole-model latency (ms, zero overlap) | note |
|---|---|---|---|---|---|---|
| Q/K/V projection (qkv_proj) | 49.775 | 23.3% | 124.60 | 24.0% | 129.05 |  |
| attention scores QKᵀ (qk^t, with K write) | offloaded to the off-chip unit (see the "attention on the off-chip unit" row) | | offloaded to the off-chip unit (see the "attention on the off-chip unit" row) | | |  |
| attention weighting AV (av, with V write) | offloaded to the off-chip unit (see the "attention on the off-chip unit" row) | | offloaded to the off-chip unit (see the "attention on the off-chip unit" row) | | |  |
| output projection (out_proj) | 19.056 | 8.9% | 124.60 | 24.0% | 126.83 |  |
| FFN first layer (ffn1) | 64.170 | 30.0% | 124.60 | 24.0% | 129.05 |  |
| FFN second layer (ffn2) | 58.999 | 27.6% | 124.60 | 24.0% | 133.50 |  |
| softmax (digital unit) | offloaded to the off-chip unit (see the "attention on the off-chip unit" row) | | offloaded to the off-chip unit (see the "attention on the off-chip unit" row) | | |  |
| GELU (FFN activation, digital unit) | 1.703 | 0.8% | 4.72 | 0.9% | 4.72 |  |
| LayerNorm ×2 (digital unit) | 1.202 | 0.6% | 1.97 | 0.4% | 1.97 |  |
| residual add ×2 (digital unit) | 1.169 | 0.5% | 0.39 | 0.1% | 0.39 |  |
| embedding lookup (off-chip read, once per model) | 0.026 | 0.0% | 0.00 | 0.0% | 0.00 | off-chip port bandwidth not set (fabric.offchip_bandwidth_words_per_cycle): priced, not timed |
| attention on the off-chip unit (QKᵀ + softmax + AV, K/V in the unit memory) | 17.566 | 8.2% | 12.64 | 2.4% | 12.64 |  |
| LM head (matmul, last token, once per model) | 0.080 | 0.0% | 0.01 | 0.0% | 0.01 |  |
| counted total (matmuls + digital-unit operators + off-chip reads) | 213.746 | 100.0% | 518.14 | 100.0% | 538.17 | denominator of the shares |

### Per-operator totals (one layer / × layers; the per-operator data do not depend on the condition)

| operator | kind | total energy (µJ) | whole-model energy (mJ) | latency, perfect overlap (ms) | latency, zero overlap (ms) | whole-model latency, perfect overlap (ms) | network-bound |
|---|---|---|---|---|---|---|---|
| qkv_proj | static | 2,073.95 | 49.775 | 5.1919 | 5.3773 | 124.60 | no |
| qk^t | dynamic | 2,642.21 | 63.413 | 5.7371 | 6.1080 | 137.69 | no |
| av | dynamic | 1,430.66 | 34.336 | 7.3730 | 7.5584 | 176.95 | no |
| out_proj | static | 793.99 | 19.056 | 5.1919 | 5.2846 | 124.60 | no |
| ffn1 | static | 2,673.75 | 64.170 | 5.1919 | 5.3773 | 124.60 | no |
| ffn2 | static | 2,458.31 | 58.999 | 5.1919 | 5.5627 | 124.60 | no |
| softmax | elementwise | 201.79 | 4.843 | 0.2621 | 0.2621 | 6.29 | no |
| gelu | elementwise | 70.97 | 1.703 | 0.1966 | 0.1966 | 4.72 | no |
| layernorm | elementwise | 50.08 | 1.202 | 0.0819 | 0.0819 | 1.97 | no |
| residual | elementwise | 48.72 | 1.169 | 0.0164 | 0.0164 | 0.39 | no |
| embedding | offchip_read | 26.21 | 0.629 | 0.0000 | 0.0000 | 0.00 | no |
| attention_unit | offloaded_unit | 731.91 | 17.566 | 0.5265 | 0.5265 | 12.64 | no |
| lm_head | static | 80.28 | 1.927 | 0.0103 | 0.0110 | 0.25 | no |

Whole-model total: energy 318.788 mJ; latency 839.32 ms (perfect overlap) / 872.71 ms (zero overlap).

### prefill · qkv_proj(static,P=512,C=1,024,M=3,072,N=1)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| conversion | component adc | 362.00 µJ | 17.45% |  |
| buffer | component chip2chip_data_staging | 0.00 µJ | 0.00% |  |
| off-chip port | component chip2chip_link | 14.44 µJ | 0.70% |  |
| analog compute | component cim_unit | 29.00 µJ | 1.40% |  |
| analog compute | component column_drivers | 0.00 µJ | 0.00% |  |
| buffer | component glb | 697.00 µJ | 33.61% |  |
| other | component here_to_fix_a_bug | 0.00 µJ | 0.00% |  |
| buffer | component input_buffer | 100.00 µJ | 4.82% |  |
| analog compute | component integrator | 484.00 µJ | 23.34% |  |
| analog compute | component inter_1bit_x_1bit_mac_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_column_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_core_in_macro_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_crossbar_in_core_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_macro_in_die_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_row_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| buffer | component output_buffer | 29.50 µJ | 1.42% |  |
| on-die network | component router | 15.84 µJ | 0.76% |  |
| analog compute | component row_drivers | 39.10 µJ | 1.89% |  |
| conversion | component sample | 106.00 µJ | 5.11% |  |
| conversion | component shift_add | 15.10 µJ | 0.73% |  |
| analog compute | component virtual_bitwise_mac | 0.00 µJ | 0.00% |  |
| analog compute | component weight_drivers | 0.00 µJ | 0.00% |  |
| analog compute | component wordline_cap | 167.00 µJ | 8.05% |  |
| analog compute | component wordline_drivers | 0.00 µJ | 0.00% |  |
| on-die network | placement distance repricing increment router | 7.92 µJ | 0.38% | mean hops / reference hops = 1.500 |
| write | K/V write programming energy | 0.00 µJ | 0.00% | static operators do not write |
| write | weight rewrite energy (temporal rewrite policy) | 0.00 µJ | 0.00% | no rewrite in this configuration |
| D2D | die-to-die hand-off surplus energy (hops beyond the flat charge) | 0.00 µJ | 0.00% | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| other | unattributed residual (CiMLoop total − sum of the component rows) | 7.05 µJ | 0.34% | CiMLoop's operator total = the summary table's per-compute energy (finite precision) × computes; its difference from the exact sum of the components' Energy (total) lines is that table's rounding (≤0.5%); reported totals keep the CiMLoop convention |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| compute | array compute (Timeloop cycles) | 5.1917 ms |  |
| write | K/V write (serial, before compute) | 0.0000 ms | static operators do not write |
| on-die network | busiest-wire occupancy (serialization) | 0.1854 ms | occupancy, not exposure; = the lower bound of any schedule for the given routing × the schedule slack (platform input schedule_slack, currently 1) |
| on-die network | network exposure (perfect-overlap end = max(compute, occupancy) − compute) | 0.0000 ms | the end reported by default |
| on-die network | network exposure (zero-overlap end = occupancy) | 0.1854 ms | upper end of the overlap bracket |
| propagation | distance propagation delay | 0.0002 ms |  |
| D2D | die-to-die hand-off transfer (hidden state produced by this operator) | 0.0000 ms | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### prefill · qk^t(dynamic,P=512,C=64,M=512,N=16)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| conversion | component adc | 242.00 µJ | 9.16% |  |
| buffer | component chip2chip_data_staging | 0.00 µJ | 0.00% |  |
| off-chip port | component chip2chip_link | 35.54 µJ | 1.35% |  |
| analog compute | component cim_unit | 2.84 µJ | 0.11% |  |
| analog compute | component column_drivers | 0.00 µJ | 0.00% |  |
| buffer | component glb | 1,672.00 µJ | 63.28% |  |
| other | component here_to_fix_a_bug | 0.00 µJ | 0.00% |  |
| buffer | component input_buffer | 6.28 µJ | 0.24% |  |
| analog compute | component integrator | 323.00 µJ | 12.22% |  |
| analog compute | component inter_1bit_x_1bit_mac_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_column_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_core_in_macro_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_crossbar_in_core_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_macro_in_die_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_row_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| buffer | component output_buffer | 78.60 µJ | 2.97% |  |
| on-die network | component router | 13.98 µJ | 0.53% |  |
| analog compute | component row_drivers | 4.53 µJ | 0.17% |  |
| conversion | component sample | 70.50 µJ | 2.67% |  |
| conversion | component shift_add | 10.10 µJ | 0.38% |  |
| analog compute | component virtual_bitwise_mac | 0.00 µJ | 0.00% |  |
| analog compute | component weight_drivers | 0.00 µJ | 0.00% |  |
| analog compute | component wordline_cap | 111.00 µJ | 4.20% |  |
| analog compute | component wordline_drivers | 0.00 µJ | 0.00% |  |
| on-die network | placement distance repricing increment router | 6.99 µJ | 0.26% | mean hops / reference hops = 1.500 |
| write | K/V write programming energy | 52.43 µJ | 1.98% |  |
| write | weight rewrite energy (temporal rewrite policy) | 0.00 µJ | 0.00% | no rewrite in this configuration |
| D2D | die-to-die hand-off surplus energy (hops beyond the flat charge) | 0.00 µJ | 0.00% | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| other | unattributed residual (CiMLoop total − sum of the component rows) | 12.42 µJ | 0.47% | CiMLoop's operator total = the summary table's per-compute energy (finite precision) × computes; its difference from the exact sum of the components' Energy (total) lines is that table's rounding (≤0.5%); reported totals keep the CiMLoop convention |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| compute | array compute (Timeloop cycles) | 5.1917 ms |  |
| write | K/V write (serial, before compute) | 0.5453 ms |  |
| on-die network | busiest-wire occupancy (serialization) | 0.3708 ms | occupancy, not exposure; = the lower bound of any schedule for the given routing × the schedule slack (platform input schedule_slack, currently 1) |
| on-die network | network exposure (perfect-overlap end = max(compute, occupancy) − compute) | 0.0000 ms | the end reported by default |
| on-die network | network exposure (zero-overlap end = occupancy) | 0.3708 ms | upper end of the overlap bracket |
| propagation | distance propagation delay | 0.0002 ms |  |
| D2D | die-to-die hand-off transfer (hidden state produced by this operator) | 0.0000 ms | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### prefill · av(dynamic,P=512,C=512,M=64,N=16)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| conversion | component adc | 60.40 µJ | 4.22% |  |
| buffer | component chip2chip_data_staging | 0.00 µJ | 0.00% |  |
| off-chip port | component chip2chip_link | 18.91 µJ | 1.32% |  |
| analog compute | component cim_unit | 2.84 µJ | 0.20% |  |
| analog compute | component column_drivers | 0.00 µJ | 0.00% |  |
| buffer | component glb | 1,087.00 µJ | 75.98% |  |
| other | component here_to_fix_a_bug | 0.00 µJ | 0.00% |  |
| buffer | component input_buffer | 25.10 µJ | 1.75% |  |
| analog compute | component integrator | 80.70 µJ | 5.64% |  |
| analog compute | component inter_1bit_x_1bit_mac_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_column_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_core_in_macro_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_crossbar_in_core_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_macro_in_die_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_row_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| buffer | component output_buffer | 19.60 µJ | 1.37% |  |
| on-die network | component router | 12.68 µJ | 0.89% |  |
| analog compute | component row_drivers | 9.05 µJ | 0.63% |  |
| conversion | component sample | 17.60 µJ | 1.23% |  |
| conversion | component shift_add | 2.52 µJ | 0.18% |  |
| analog compute | component virtual_bitwise_mac | 0.00 µJ | 0.00% |  |
| analog compute | component weight_drivers | 0.00 µJ | 0.00% |  |
| analog compute | component wordline_cap | 27.90 µJ | 1.95% |  |
| analog compute | component wordline_drivers | 0.00 µJ | 0.00% |  |
| on-die network | placement distance repricing increment router | 6.34 µJ | 0.44% | mean hops / reference hops = 1.500 |
| write | K/V write programming energy | 52.43 µJ | 3.66% |  |
| write | weight rewrite energy (temporal rewrite policy) | 0.00 µJ | 0.00% | no rewrite in this configuration |
| D2D | die-to-die hand-off surplus energy (hops beyond the flat charge) | 0.00 µJ | 0.00% | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| other | unattributed residual (CiMLoop total − sum of the component rows) | 7.59 µJ | 0.53% | CiMLoop's operator total = the summary table's per-compute energy (finite precision) × computes; its difference from the exact sum of the components' Energy (total) lines is that table's rounding (≤0.5%); reported totals keep the CiMLoop convention |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| compute | array compute (Timeloop cycles) | 5.1917 ms |  |
| write | K/V write (serial, before compute) | 2.1811 ms |  |
| on-die network | busiest-wire occupancy (serialization) | 0.1854 ms | occupancy, not exposure; = the lower bound of any schedule for the given routing × the schedule slack (platform input schedule_slack, currently 1) |
| on-die network | network exposure (perfect-overlap end = max(compute, occupancy) − compute) | 0.0000 ms | the end reported by default |
| on-die network | network exposure (zero-overlap end = occupancy) | 0.1854 ms | upper end of the overlap bracket |
| propagation | distance propagation delay | 0.0002 ms |  |
| D2D | die-to-die hand-off transfer (hidden state produced by this operator) | 0.0000 ms | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### prefill · out_proj(static,P=512,C=1,024,M=1,024,N=1)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| conversion | component adc | 121.00 µJ | 15.24% |  |
| buffer | component chip2chip_data_staging | 0.00 µJ | 0.00% |  |
| off-chip port | component chip2chip_link | 6.05 µJ | 0.76% |  |
| analog compute | component cim_unit | 9.67 µJ | 1.22% |  |
| analog compute | component column_drivers | 0.00 µJ | 0.00% |  |
| buffer | component glb | 307.00 µJ | 38.67% |  |
| other | component here_to_fix_a_bug | 0.00 µJ | 0.00% |  |
| buffer | component input_buffer | 25.10 µJ | 3.16% |  |
| analog compute | component integrator | 161.00 µJ | 20.28% |  |
| analog compute | component inter_1bit_x_1bit_mac_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_column_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_core_in_macro_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_crossbar_in_core_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_macro_in_die_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_row_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| buffer | component output_buffer | 39.30 µJ | 4.95% |  |
| on-die network | component router | 8.69 µJ | 1.09% |  |
| analog compute | component row_drivers | 9.77 µJ | 1.23% |  |
| conversion | component sample | 35.20 µJ | 4.43% |  |
| conversion | component shift_add | 5.03 µJ | 0.63% |  |
| analog compute | component virtual_bitwise_mac | 0.00 µJ | 0.00% |  |
| analog compute | component weight_drivers | 0.00 µJ | 0.00% |  |
| analog compute | component wordline_cap | 55.70 µJ | 7.02% |  |
| analog compute | component wordline_drivers | 0.00 µJ | 0.00% |  |
| on-die network | placement distance repricing increment router | 4.34 µJ | 0.55% | mean hops / reference hops = 1.500 |
| write | K/V write programming energy | 0.00 µJ | 0.00% | static operators do not write |
| write | weight rewrite energy (temporal rewrite policy) | 0.00 µJ | 0.00% | no rewrite in this configuration |
| D2D | die-to-die hand-off surplus energy (hops beyond the flat charge) | 0.00 µJ | 0.00% | die link without a bandwidth (shipped default): transfer time counted as 0 |
| other | unattributed residual (CiMLoop total − sum of the component rows) | 6.14 µJ | 0.77% | CiMLoop's operator total = the summary table's per-compute energy (finite precision) × computes; its difference from the exact sum of the components' Energy (total) lines is that table's rounding (≤0.5%); reported totals keep the CiMLoop convention |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| compute | array compute (Timeloop cycles) | 5.1917 ms |  |
| write | K/V write (serial, before compute) | 0.0000 ms | static operators do not write |
| on-die network | busiest-wire occupancy (serialization) | 0.0927 ms | occupancy, not exposure; = the lower bound of any schedule for the given routing × the schedule slack (platform input schedule_slack, currently 1) |
| on-die network | network exposure (perfect-overlap end = max(compute, occupancy) − compute) | 0.0000 ms | the end reported by default |
| on-die network | network exposure (zero-overlap end = occupancy) | 0.0927 ms | upper end of the overlap bracket |
| propagation | distance propagation delay | 0.0002 ms |  |
| D2D | die-to-die hand-off transfer (hidden state produced by this operator) | 0.0000 ms | die link without a bandwidth (shipped default): transfer time counted as 0 |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### prefill · ffn1(static,P=512,C=1,024,M=4,096,N=1)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| conversion | component adc | 483.00 µJ | 18.06% |  |
| buffer | component chip2chip_data_staging | 0.00 µJ | 0.00% |  |
| off-chip port | component chip2chip_link | 18.74 µJ | 0.70% |  |
| analog compute | component cim_unit | 38.70 µJ | 1.45% |  |
| analog compute | component column_drivers | 0.00 µJ | 0.00% |  |
| buffer | component glb | 892.00 µJ | 33.36% |  |
| other | component here_to_fix_a_bug | 0.00 µJ | 0.00% |  |
| buffer | component input_buffer | 100.00 µJ | 3.74% |  |
| analog compute | component integrator | 646.00 µJ | 24.16% |  |
| analog compute | component inter_1bit_x_1bit_mac_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_column_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_core_in_macro_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_crossbar_in_core_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_macro_in_die_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_row_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| buffer | component output_buffer | 39.30 µJ | 1.47% |  |
| on-die network | component router | 17.42 µJ | 0.65% |  |
| analog compute | component row_drivers | 39.10 µJ | 1.46% |  |
| conversion | component sample | 141.00 µJ | 5.27% |  |
| conversion | component shift_add | 20.10 µJ | 0.75% |  |
| analog compute | component virtual_bitwise_mac | 0.00 µJ | 0.00% |  |
| analog compute | component weight_drivers | 0.00 µJ | 0.00% |  |
| analog compute | component wordline_cap | 223.00 µJ | 8.34% |  |
| analog compute | component wordline_drivers | 0.00 µJ | 0.00% |  |
| on-die network | placement distance repricing increment router | 8.71 µJ | 0.33% | mean hops / reference hops = 1.500 |
| write | K/V write programming energy | 0.00 µJ | 0.00% | static operators do not write |
| write | weight rewrite energy (temporal rewrite policy) | 0.00 µJ | 0.00% | no rewrite in this configuration |
| D2D | die-to-die hand-off surplus energy (hops beyond the flat charge) | 0.00 µJ | 0.00% | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| other | unattributed residual (CiMLoop total − sum of the component rows) | 6.68 µJ | 0.25% | CiMLoop's operator total = the summary table's per-compute energy (finite precision) × computes; its difference from the exact sum of the components' Energy (total) lines is that table's rounding (≤0.5%); reported totals keep the CiMLoop convention |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| compute | array compute (Timeloop cycles) | 5.1917 ms |  |
| write | K/V write (serial, before compute) | 0.0000 ms | static operators do not write |
| on-die network | busiest-wire occupancy (serialization) | 0.1854 ms | occupancy, not exposure; = the lower bound of any schedule for the given routing × the schedule slack (platform input schedule_slack, currently 1) |
| on-die network | network exposure (perfect-overlap end = max(compute, occupancy) − compute) | 0.0000 ms | the end reported by default |
| on-die network | network exposure (zero-overlap end = occupancy) | 0.1854 ms | upper end of the overlap bracket |
| propagation | distance propagation delay | 0.0002 ms |  |
| D2D | die-to-die hand-off transfer (hidden state produced by this operator) | 0.0000 ms | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### prefill · ffn2(static,P=512,C=4,096,M=1,024,N=1)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| conversion | component adc | 483.00 µJ | 19.65% |  |
| buffer | component chip2chip_data_staging | 0.00 µJ | 0.00% |  |
| off-chip port | component chip2chip_link | 11.58 µJ | 0.47% |  |
| analog compute | component cim_unit | 38.70 µJ | 1.57% |  |
| analog compute | component column_drivers | 0.00 µJ | 0.00% |  |
| buffer | component glb | 641.00 µJ | 26.07% |  |
| other | component here_to_fix_a_bug | 0.00 µJ | 0.00% |  |
| buffer | component input_buffer | 25.10 µJ | 1.02% |  |
| analog compute | component integrator | 646.00 µJ | 26.28% |  |
| analog compute | component inter_1bit_x_1bit_mac_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_column_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_core_in_macro_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_crossbar_in_core_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_macro_in_die_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_row_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| buffer | component output_buffer | 157.00 µJ | 6.39% |  |
| on-die network | component router | 18.13 µJ | 0.74% |  |
| analog compute | component row_drivers | 39.10 µJ | 1.59% |  |
| conversion | component sample | 141.00 µJ | 5.74% |  |
| conversion | component shift_add | 20.10 µJ | 0.82% |  |
| analog compute | component virtual_bitwise_mac | 0.00 µJ | 0.00% |  |
| analog compute | component weight_drivers | 0.00 µJ | 0.00% |  |
| analog compute | component wordline_cap | 223.00 µJ | 9.07% |  |
| analog compute | component wordline_drivers | 0.00 µJ | 0.00% |  |
| on-die network | placement distance repricing increment router | 9.06 µJ | 0.37% | mean hops / reference hops = 1.500 |
| write | K/V write programming energy | 0.00 µJ | 0.00% | static operators do not write |
| write | weight rewrite energy (temporal rewrite policy) | 0.00 µJ | 0.00% | no rewrite in this configuration |
| D2D | die-to-die hand-off surplus energy (hops beyond the flat charge) | 0.00 µJ | 0.00% | die link without a bandwidth (shipped default): transfer time counted as 0 |
| other | unattributed residual (CiMLoop total − sum of the component rows) | 5.53 µJ | 0.23% | CiMLoop's operator total = the summary table's per-compute energy (finite precision) × computes; its difference from the exact sum of the components' Energy (total) lines is that table's rounding (≤0.5%); reported totals keep the CiMLoop convention |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| compute | array compute (Timeloop cycles) | 5.1917 ms |  |
| write | K/V write (serial, before compute) | 0.0000 ms | static operators do not write |
| on-die network | busiest-wire occupancy (serialization) | 0.3708 ms | occupancy, not exposure; = the lower bound of any schedule for the given routing × the schedule slack (platform input schedule_slack, currently 1) |
| on-die network | network exposure (perfect-overlap end = max(compute, occupancy) − compute) | 0.0000 ms | the end reported by default |
| on-die network | network exposure (zero-overlap end = occupancy) | 0.3708 ms | upper end of the overlap bracket |
| propagation | distance propagation delay | 0.0002 ms |  |
| D2D | die-to-die hand-off transfer (hidden state produced by this operator) | 0.0000 ms | die link without a bandwidth (shipped default): transfer time counted as 0 |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### prefill · softmax(elementwise,elements=4,194,304,after=qk^t)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| buffer | glb read/write (3 passes × 4,194,304 elements) | 194.66 µJ | 96.47% | glb access energy per word from the CiMLoop calibration of the same die (ffn1 run: 15.47 pJ/word) |
| digital unit | digital-unit arithmetic (add / mul / lookup) | 7.13 µJ | 3.53% | per element 2 adds + 1 muls + 1 lookups; generic example values (Horowitz ISSCC 2014; sized to array output rate) |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| digital unit | digital-unit compute (16,777,216 operations ÷ 64 lanes × 1 GHz) | 0.2621 ms | serial with the adjacent matmuls (stated assumption) |
| on-die network | busiest-wire occupancy (serialization) | 0.0000 ms | the digital unit sits next to the glb and does not use the on-die network (assumption) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### prefill · gelu(elementwise,elements=2,097,152,after=ffn1)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| buffer | glb read/write (2 passes × 2,097,152 elements) | 64.89 µJ | 91.43% | glb access energy per word from the CiMLoop calibration of the same die (ffn1 run: 15.47 pJ/word) |
| digital unit | digital-unit arithmetic (add / mul / lookup) | 6.08 µJ | 8.57% | per element 2 adds + 3 muls + 1 lookups; generic example values (Horowitz ISSCC 2014; sized to array output rate) |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| digital unit | digital-unit compute (12,582,912 operations ÷ 64 lanes × 1 GHz) | 0.1966 ms | serial with the adjacent matmuls (stated assumption) |
| on-die network | busiest-wire occupancy (serialization) | 0.0000 ms | the digital unit sits next to the glb and does not use the on-die network (assumption) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### prefill · layernorm(elementwise,elements=1,048,576,after=qkv_proj)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| buffer | glb read/write (3 passes × 1,048,576 elements) | 48.66 µJ | 97.17% | glb access energy per word from the CiMLoop calibration of the same die (ffn1 run: 15.47 pJ/word) |
| digital unit | digital-unit arithmetic (add / mul / lookup) | 1.42 µJ | 2.83% | per element 3 adds + 2 muls + 0.000976562 lookups; generic example values (Horowitz ISSCC 2014; sized to array output rate) |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| digital unit | digital-unit compute (5,243,904 operations ÷ 64 lanes × 1 GHz) | 0.0819 ms | serial with the adjacent matmuls (stated assumption) |
| on-die network | busiest-wire occupancy (serialization) | 0.0000 ms | the digital unit sits next to the glb and does not use the on-die network (assumption) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### prefill · residual(elementwise,elements=1,048,576,after=out_proj)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| buffer | glb read/write (3 passes × 1,048,576 elements) | 48.66 µJ | 99.89% | glb access energy per word from the CiMLoop calibration of the same die (ffn1 run: 15.47 pJ/word) |
| digital unit | digital-unit arithmetic (add / mul / lookup) | 0.05 µJ | 0.11% | per element 1 adds + 0 muls + 0 lookups; generic example values (Horowitz ISSCC 2014; sized to array output rate) |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| digital unit | digital-unit compute (1,048,576 operations ÷ 64 lanes × 1 GHz) | 0.0164 ms | serial with the adjacent matmuls (stated assumption) |
| on-die network | busiest-wire occupancy (serialization) | 0.0000 ms | the digital unit sits next to the glb and does not use the on-die network (assumption) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### prefill · embedding(offchip_read,words=524,288)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| off-chip | off-chip read of 524,288 words × DRAM energy per word | 26.21 µJ | 100.00% |  |

Latency:

| group | item | value | note |
|---|---|---|---|
| off-chip | off-chip read transfer | 0.0000 ms | off-chip port bandwidth not set (fabric.offchip_bandwidth_words_per_cycle): priced, not timed |

### prefill · attention_unit(offloaded_unit,macs=536,870,912,kv_read_words=1,048,576)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| off-chip unit | unit compute (536,870,912 MACs + softmax 16,777,216 operations) × 1 pJ | 553.65 µJ | 75.64% | DR-9: generic public figures (ANCHORS.md) |
| off-chip unit | K/V memory read/write (1,048,576 writes + 1,048,576 reads) | 104.86 µJ | 14.33% |  |
| link | die↔unit link (Q out, K/V out, attention output back) | 73.40 µJ | 10.03% | priced over the mean 3.5 hops from the dies to the attach point (these words are not in the CiMLoop account) |

Latency:

| group | item | value | note |
|---|---|---|---|
| link | Q + K/V out (die → unit) | 0.1258 ms |  |
| off-chip unit | unit compute (including the fixed per-call overhead) | 0.2768 ms |  |
| off-chip unit | K/V memory read/write (reads the whole stored context) | 0.0819 ms | serial with compute (assumption) |
| link | attention output back (unit → die) | 0.0419 ms |  |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### prefill · lm_head(static,P=1,C=1,024,M=65,536,N=1)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| conversion | component adc | 15.10 µJ | 18.81% |  |
| buffer | component chip2chip_data_staging | 0.00 µJ | 0.00% |  |
| off-chip port | component chip2chip_link | 0.56 µJ | 0.69% |  |
| analog compute | component cim_unit | 1.21 µJ | 1.51% |  |
| analog compute | component column_drivers | 0.00 µJ | 0.00% |  |
| buffer | component glb | 26.39 µJ | 32.87% |  |
| other | component here_to_fix_a_bug | 0.00 µJ | 0.00% |  |
| buffer | component input_buffer | 1.57 µJ | 1.96% |  |
| analog compute | component integrator | 20.20 µJ | 25.16% |  |
| analog compute | component inter_1bit_x_1bit_mac_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| other | component inter_chip_in_system_spatial | 0.00 µJ | 0.00% |  |
| analog compute | component inter_column_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_core_in_macro_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_crossbar_in_core_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_macro_in_die_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_row_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| buffer | component output_buffer | 1.25 µJ | 1.56% |  |
| on-die network | component router | 0.37 µJ | 0.46% |  |
| analog compute | component row_drivers | 1.22 µJ | 1.52% |  |
| conversion | component sample | 4.40 µJ | 5.48% |  |
| conversion | component shift_add | 0.63 µJ | 0.78% |  |
| analog compute | component virtual_bitwise_mac | 0.00 µJ | 0.00% |  |
| analog compute | component weight_drivers | 0.00 µJ | 0.00% |  |
| analog compute | component wordline_cap | 6.96 µJ | 8.67% |  |
| analog compute | component wordline_drivers | 0.00 µJ | 0.00% |  |
| on-die network | placement distance repricing increment router | 0.19 µJ | 0.23% | mean hops / reference hops = 1.500 |
| off-chip port | placement distance repricing increment chip2chip_link | 0.17 µJ | 0.22% | mean hops / reference hops = 1.312 |
| write | K/V write programming energy | 0.00 µJ | 0.00% | static operators do not write |
| write | weight rewrite energy (temporal rewrite policy) | 0.00 µJ | 0.00% | no rewrite in this configuration |
| D2D | die-to-die hand-off surplus energy (hops beyond the flat charge) | 0.00 µJ | 0.00% | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| other | unattributed residual (CiMLoop total − sum of the component rows) | 0.07 µJ | 0.08% | CiMLoop's operator total = the summary table's per-compute energy (finite precision) × computes; its difference from the exact sum of the components' Energy (total) lines is that table's rounding (≤0.5%); reported totals keep the CiMLoop convention |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| compute | array compute (Timeloop cycles) | 0.0101 ms |  |
| write | K/V write (serial, before compute) | 0.0000 ms | static operators do not write |
| on-die network | busiest-wire occupancy (serialization) | 0.0007 ms | occupancy, not exposure; = the lower bound of any schedule for the given routing × the schedule slack (platform input schedule_slack, currently 1) |
| on-die network | network exposure (perfect-overlap end = max(compute, occupancy) − compute) | 0.0000 ms | the end reported by default |
| on-die network | network exposure (zero-overlap end = occupancy) | 0.0007 ms | upper end of the overlap bracket |
| propagation | distance propagation delay | 0.0002 ms |  |
| D2D | die-to-die hand-off transfer (hidden state produced by this operator) | 0.0000 ms | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

## decode

### Operator types, whole-model shares -- attention on chip

| operator type | whole-model energy (mJ) | energy share | whole-model latency (ms, perfect overlap) | latency share | whole-model latency (ms, zero overlap) | note |
|---|---|---|---|---|---|---|
| Q/K/V projection (qkv_proj) | 0.098 | 14.7% | 0.25 | 1.7% | 0.26 |  |
| attention scores QKᵀ (qk^t, with K write) | 0.124 | 18.7% | 13.33 | 90.0% | 13.35 |  |
| attention weighting AV (av, with V write) | 0.067 | 10.1% | 0.45 | 3.1% | 0.46 |  |
| output projection (out_proj) | 0.038 | 5.7% | 0.25 | 1.7% | 0.25 |  |
| FFN first layer (ffn1) | 0.126 | 18.9% | 0.25 | 1.7% | 0.26 |  |
| FFN second layer (ffn2) | 0.115 | 17.3% | 0.25 | 1.7% | 0.27 |  |
| softmax (digital unit) | 0.009 | 1.4% | 0.01 | 0.1% | 0.01 |  |
| GELU (FFN activation, digital unit) | 0.003 | 0.5% | 0.01 | 0.1% | 0.01 |  |
| LayerNorm ×2 (digital unit) | 0.002 | 0.4% | 0.00 | 0.0% | 0.00 |  |
| residual add ×2 (digital unit) | 0.002 | 0.3% | 0.00 | 0.0% | 0.00 |  |
| embedding lookup (off-chip read, once per model) | 0.000 | 0.0% | 0.00 | 0.0% | 0.00 | off-chip port bandwidth not set (fabric.offchip_bandwidth_words_per_cycle): priced, not timed |
| LM head (matmul, last token, once per model) | 0.080 | 12.0% | 0.01 | 0.1% | 0.01 |  |
| counted total (matmuls + digital-unit operators + off-chip reads) | 0.667 | 100.0% | 14.81 | 100.0% | 14.88 | denominator of the shares |

### Operator types, whole-model shares -- attention offloaded (end to end: on chip + off-chip unit)

| operator type | whole-model energy (mJ) | energy share | whole-model latency (ms, perfect overlap) | latency share | whole-model latency (ms, zero overlap) | note |
|---|---|---|---|---|---|---|
| Q/K/V projection (qkv_proj) | 0.098 | 5.6% | 0.25 | 12.3% | 0.26 |  |
| attention scores QKᵀ (qk^t, with K write) | offloaded to the off-chip unit (see the "attention on the off-chip unit" row) | | offloaded to the off-chip unit (see the "attention on the off-chip unit" row) | | |  |
| attention weighting AV (av, with V write) | offloaded to the off-chip unit (see the "attention on the off-chip unit" row) | | offloaded to the off-chip unit (see the "attention on the off-chip unit" row) | | |  |
| output projection (out_proj) | 0.038 | 2.2% | 0.25 | 12.3% | 0.25 |  |
| FFN first layer (ffn1) | 0.126 | 7.2% | 0.25 | 12.3% | 0.26 |  |
| FFN second layer (ffn2) | 0.115 | 6.6% | 0.25 | 12.3% | 0.27 |  |
| softmax (digital unit) | offloaded to the off-chip unit (see the "attention on the off-chip unit" row) | | offloaded to the off-chip unit (see the "attention on the off-chip unit" row) | | |  |
| GELU (FFN activation, digital unit) | 0.003 | 0.2% | 0.01 | 0.5% | 0.01 |  |
| LayerNorm ×2 (digital unit) | 0.002 | 0.1% | 0.00 | 0.2% | 0.00 |  |
| residual add ×2 (digital unit) | 0.002 | 0.1% | 0.00 | 0.0% | 0.00 |  |
| embedding lookup (off-chip read, once per model) | 0.000 | 0.0% | 0.00 | 0.0% | 0.00 | off-chip port bandwidth not set (fabric.offchip_bandwidth_words_per_cycle): priced, not timed |
| attention on the off-chip unit (QKᵀ + softmax + AV, K/V in the unit memory) | 1.290 | 73.5% | 1.01 | 49.8% | 1.01 |  |
| LM head (matmul, last token, once per model) | 0.080 | 4.6% | 0.01 | 0.5% | 0.01 |  |
| counted total (matmuls + digital-unit operators + off-chip reads) | 1.756 | 100.0% | 2.02 | 100.0% | 2.06 | denominator of the shares |

### Per-operator totals (one layer / × layers; the per-operator data do not depend on the condition)

| operator | kind | total energy (µJ) | whole-model energy (mJ) | latency, perfect overlap (ms) | latency, zero overlap (ms) | whole-model latency, perfect overlap (ms) | network-bound |
|---|---|---|---|---|---|---|---|
| qkv_proj | static | 4.08 | 0.098 | 0.0103 | 0.0107 | 0.25 | no |
| qk^t | dynamic | 5.19 | 0.124 | 0.5556 | 0.5563 | 13.33 | no |
| av | dynamic | 2.80 | 0.067 | 0.0188 | 0.0192 | 0.45 | no |
| out_proj | static | 1.58 | 0.038 | 0.0103 | 0.0105 | 0.25 | no |
| ffn1 | static | 5.26 | 0.126 | 0.0103 | 0.0107 | 0.25 | no |
| ffn2 | static | 4.81 | 0.115 | 0.0103 | 0.0110 | 0.25 | no |
| softmax | elementwise | 0.39 | 0.009 | 0.0005 | 0.0005 | 0.01 | no |
| gelu | elementwise | 0.14 | 0.003 | 0.0004 | 0.0004 | 0.01 | no |
| layernorm | elementwise | 0.10 | 0.002 | 0.0002 | 0.0002 | 0.00 | no |
| residual | elementwise | 0.10 | 0.002 | 0.0000 | 0.0000 | 0.00 | no |
| embedding | offchip_read | 0.05 | 0.001 | 0.0000 | 0.0000 | 0.00 | no |
| attention_unit | offloaded_unit | 53.76 | 1.290 | 0.0419 | 0.0419 | 1.01 | no |
| lm_head | static | 80.28 | 1.927 | 0.0103 | 0.0110 | 0.25 | no |

Whole-model total: energy 3.805 mJ; latency 16.06 ms (perfect overlap) / 16.14 ms (zero overlap).

### decode · qkv_proj(static,P=1,C=1,024,M=3,072,N=1)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| conversion | component adc | 0.71 µJ | 17.34% |  |
| buffer | component chip2chip_data_staging | 0.00 µJ | 0.00% |  |
| off-chip port | component chip2chip_link | 0.03 µJ | 0.69% |  |
| analog compute | component cim_unit | 0.06 µJ | 1.39% |  |
| analog compute | component column_drivers | 0.00 µJ | 0.00% |  |
| buffer | component glb | 1.39 µJ | 34.01% |  |
| other | component here_to_fix_a_bug | 0.00 µJ | 0.00% |  |
| buffer | component input_buffer | 0.20 µJ | 4.80% |  |
| analog compute | component integrator | 0.95 µJ | 23.16% |  |
| analog compute | component inter_1bit_x_1bit_mac_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_column_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_core_in_macro_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_crossbar_in_core_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_macro_in_die_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_row_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| buffer | component output_buffer | 0.06 µJ | 1.47% |  |
| on-die network | component router | 0.03 µJ | 0.76% |  |
| analog compute | component row_drivers | 0.08 µJ | 1.87% |  |
| conversion | component sample | 0.21 µJ | 5.04% |  |
| conversion | component shift_add | 0.03 µJ | 0.72% |  |
| analog compute | component virtual_bitwise_mac | 0.00 µJ | 0.00% |  |
| analog compute | component weight_drivers | 0.00 µJ | 0.00% |  |
| analog compute | component wordline_cap | 0.33 µJ | 7.98% |  |
| analog compute | component wordline_drivers | 0.00 µJ | 0.00% |  |
| on-die network | placement distance repricing increment router | 0.02 µJ | 0.38% | mean hops / reference hops = 1.500 |
| write | K/V write programming energy | 0.00 µJ | 0.00% | static operators do not write |
| write | weight rewrite energy (temporal rewrite policy) | 0.00 µJ | 0.00% | no rewrite in this configuration |
| D2D | die-to-die hand-off surplus energy (hops beyond the flat charge) | 0.00 µJ | 0.00% | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| other | unattributed residual (CiMLoop total − sum of the component rows) | 0.02 µJ | 0.39% | CiMLoop's operator total = the summary table's per-compute energy (finite precision) × computes; its difference from the exact sum of the components' Energy (total) lines is that table's rounding (≤0.5%); reported totals keep the CiMLoop convention |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| compute | array compute (Timeloop cycles) | 0.0101 ms |  |
| write | K/V write (serial, before compute) | 0.0000 ms | static operators do not write |
| on-die network | busiest-wire occupancy (serialization) | 0.0004 ms | occupancy, not exposure; = the lower bound of any schedule for the given routing × the schedule slack (platform input schedule_slack, currently 1) |
| on-die network | network exposure (perfect-overlap end = max(compute, occupancy) − compute) | 0.0000 ms | the end reported by default |
| on-die network | network exposure (zero-overlap end = occupancy) | 0.0004 ms | upper end of the overlap bracket |
| propagation | distance propagation delay | 0.0002 ms |  |
| D2D | die-to-die hand-off transfer (hidden state produced by this operator) | 0.0000 ms | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### decode · qk^t(dynamic,P=1,C=64,M=512,N=16)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| conversion | component adc | 0.47 µJ | 9.10% |  |
| buffer | component chip2chip_data_staging | 0.00 µJ | 0.00% |  |
| off-chip port | component chip2chip_link | 0.07 µJ | 1.34% |  |
| analog compute | component cim_unit | 0.01 µJ | 0.11% |  |
| analog compute | component column_drivers | 0.00 µJ | 0.00% |  |
| buffer | component glb | 3.30 µJ | 63.61% |  |
| other | component here_to_fix_a_bug | 0.00 µJ | 0.00% |  |
| buffer | component input_buffer | 0.01 µJ | 0.24% |  |
| analog compute | component integrator | 0.63 µJ | 12.17% |  |
| analog compute | component inter_1bit_x_1bit_mac_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_column_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_core_in_macro_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_crossbar_in_core_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_macro_in_die_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_row_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| buffer | component output_buffer | 0.16 µJ | 3.01% |  |
| on-die network | component router | 0.03 µJ | 0.53% |  |
| analog compute | component row_drivers | 0.01 µJ | 0.17% |  |
| conversion | component sample | 0.14 µJ | 2.66% |  |
| conversion | component shift_add | 0.02 µJ | 0.38% |  |
| analog compute | component virtual_bitwise_mac | 0.00 µJ | 0.00% |  |
| analog compute | component weight_drivers | 0.00 µJ | 0.00% |  |
| analog compute | component wordline_cap | 0.22 µJ | 4.20% |  |
| analog compute | component wordline_drivers | 0.00 µJ | 0.00% |  |
| on-die network | placement distance repricing increment router | 0.01 µJ | 0.26% | mean hops / reference hops = 1.500 |
| write | K/V write programming energy | 0.10 µJ | 1.97% |  |
| write | weight rewrite energy (temporal rewrite policy) | 0.00 µJ | 0.00% | no rewrite in this configuration |
| D2D | die-to-die hand-off surplus energy (hops beyond the flat charge) | 0.00 µJ | 0.00% | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| other | unattributed residual (CiMLoop total − sum of the component rows) | 0.01 µJ | 0.25% | CiMLoop's operator total = the summary table's per-compute energy (finite precision) × computes; its difference from the exact sum of the components' Energy (total) lines is that table's rounding (≤0.5%); reported totals keep the CiMLoop convention |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| compute | array compute (Timeloop cycles) | 0.0101 ms |  |
| write | K/V write (serial, before compute) | 0.5453 ms |  |
| on-die network | busiest-wire occupancy (serialization) | 0.0007 ms | occupancy, not exposure; = the lower bound of any schedule for the given routing × the schedule slack (platform input schedule_slack, currently 1) |
| on-die network | network exposure (perfect-overlap end = max(compute, occupancy) − compute) | 0.0000 ms | the end reported by default |
| on-die network | network exposure (zero-overlap end = occupancy) | 0.0007 ms | upper end of the overlap bracket |
| propagation | distance propagation delay | 0.0002 ms |  |
| D2D | die-to-die hand-off transfer (hidden state produced by this operator) | 0.0000 ms | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### decode · av(dynamic,P=1,C=512,M=64,N=16)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| conversion | component adc | 0.12 µJ | 4.22% |  |
| buffer | component chip2chip_data_staging | 0.00 µJ | 0.00% |  |
| off-chip port | component chip2chip_link | 0.04 µJ | 1.32% |  |
| analog compute | component cim_unit | 0.01 µJ | 0.20% |  |
| analog compute | component column_drivers | 0.00 µJ | 0.00% |  |
| buffer | component glb | 2.12 µJ | 75.87% |  |
| other | component here_to_fix_a_bug | 0.00 µJ | 0.00% |  |
| buffer | component input_buffer | 0.05 µJ | 1.76% |  |
| analog compute | component integrator | 0.16 µJ | 5.65% |  |
| analog compute | component inter_1bit_x_1bit_mac_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_column_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_core_in_macro_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_crossbar_in_core_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_macro_in_die_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_row_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| buffer | component output_buffer | 0.04 µJ | 1.42% |  |
| on-die network | component router | 0.02 µJ | 0.88% |  |
| analog compute | component row_drivers | 0.02 µJ | 0.63% |  |
| conversion | component sample | 0.03 µJ | 1.23% |  |
| conversion | component shift_add | 0.00 µJ | 0.18% |  |
| analog compute | component virtual_bitwise_mac | 0.00 µJ | 0.00% |  |
| analog compute | component weight_drivers | 0.00 µJ | 0.00% |  |
| analog compute | component wordline_cap | 0.05 µJ | 1.95% |  |
| analog compute | component wordline_drivers | 0.00 µJ | 0.00% |  |
| on-die network | placement distance repricing increment router | 0.01 µJ | 0.44% | mean hops / reference hops = 1.500 |
| write | K/V write programming energy | 0.10 µJ | 3.66% |  |
| write | weight rewrite energy (temporal rewrite policy) | 0.00 µJ | 0.00% | no rewrite in this configuration |
| D2D | die-to-die hand-off surplus energy (hops beyond the flat charge) | 0.00 µJ | 0.00% | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| other | unattributed residual (CiMLoop total − sum of the component rows) | 0.02 µJ | 0.58% | CiMLoop's operator total = the summary table's per-compute energy (finite precision) × computes; its difference from the exact sum of the components' Energy (total) lines is that table's rounding (≤0.5%); reported totals keep the CiMLoop convention |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| compute | array compute (Timeloop cycles) | 0.0101 ms |  |
| write | K/V write (serial, before compute) | 0.0085 ms |  |
| on-die network | busiest-wire occupancy (serialization) | 0.0004 ms | occupancy, not exposure; = the lower bound of any schedule for the given routing × the schedule slack (platform input schedule_slack, currently 1) |
| on-die network | network exposure (perfect-overlap end = max(compute, occupancy) − compute) | 0.0000 ms | the end reported by default |
| on-die network | network exposure (zero-overlap end = occupancy) | 0.0004 ms | upper end of the overlap bracket |
| propagation | distance propagation delay | 0.0002 ms |  |
| D2D | die-to-die hand-off transfer (hidden state produced by this operator) | 0.0000 ms | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### decode · out_proj(static,P=1,C=1,024,M=1,024,N=1)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| conversion | component adc | 0.24 µJ | 14.89% |  |
| buffer | component chip2chip_data_staging | 0.00 µJ | 0.00% |  |
| off-chip port | component chip2chip_link | 0.01 µJ | 0.75% |  |
| analog compute | component cim_unit | 0.02 µJ | 1.19% |  |
| analog compute | component column_drivers | 0.00 µJ | 0.00% |  |
| buffer | component glb | 0.63 µJ | 39.76% |  |
| other | component here_to_fix_a_bug | 0.00 µJ | 0.00% |  |
| buffer | component input_buffer | 0.05 µJ | 3.10% |  |
| analog compute | component integrator | 0.32 µJ | 19.88% |  |
| analog compute | component inter_1bit_x_1bit_mac_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_column_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_core_in_macro_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_crossbar_in_core_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_macro_in_die_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_row_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| buffer | component output_buffer | 0.08 µJ | 4.92% |  |
| on-die network | component router | 0.02 µJ | 1.07% |  |
| analog compute | component row_drivers | 0.02 µJ | 1.21% |  |
| conversion | component sample | 0.07 µJ | 4.34% |  |
| conversion | component shift_add | 0.01 µJ | 0.62% |  |
| analog compute | component virtual_bitwise_mac | 0.00 µJ | 0.00% |  |
| analog compute | component weight_drivers | 0.00 µJ | 0.00% |  |
| analog compute | component wordline_cap | 0.11 µJ | 6.88% |  |
| analog compute | component wordline_drivers | 0.00 µJ | 0.00% |  |
| on-die network | placement distance repricing increment router | 0.01 µJ | 0.54% | mean hops / reference hops = 1.500 |
| write | K/V write programming energy | 0.00 µJ | 0.00% | static operators do not write |
| write | weight rewrite energy (temporal rewrite policy) | 0.00 µJ | 0.00% | no rewrite in this configuration |
| D2D | die-to-die hand-off surplus energy (hops beyond the flat charge) | 0.00 µJ | 0.00% | die link without a bandwidth (shipped default): transfer time counted as 0 |
| other | unattributed residual (CiMLoop total − sum of the component rows) | 0.01 µJ | 0.86% | CiMLoop's operator total = the summary table's per-compute energy (finite precision) × computes; its difference from the exact sum of the components' Energy (total) lines is that table's rounding (≤0.5%); reported totals keep the CiMLoop convention |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| compute | array compute (Timeloop cycles) | 0.0101 ms |  |
| write | K/V write (serial, before compute) | 0.0000 ms | static operators do not write |
| on-die network | busiest-wire occupancy (serialization) | 0.0002 ms | occupancy, not exposure; = the lower bound of any schedule for the given routing × the schedule slack (platform input schedule_slack, currently 1) |
| on-die network | network exposure (perfect-overlap end = max(compute, occupancy) − compute) | 0.0000 ms | the end reported by default |
| on-die network | network exposure (zero-overlap end = occupancy) | 0.0002 ms | upper end of the overlap bracket |
| propagation | distance propagation delay | 0.0002 ms |  |
| D2D | die-to-die hand-off transfer (hidden state produced by this operator) | 0.0000 ms | die link without a bandwidth (shipped default): transfer time counted as 0 |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### decode · ffn1(static,P=1,C=1,024,M=4,096,N=1)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| conversion | component adc | 0.94 µJ | 17.96% |  |
| buffer | component chip2chip_data_staging | 0.00 µJ | 0.00% |  |
| off-chip port | component chip2chip_link | 0.04 µJ | 0.69% |  |
| analog compute | component cim_unit | 0.08 µJ | 1.44% |  |
| analog compute | component column_drivers | 0.00 µJ | 0.00% |  |
| buffer | component glb | 1.77 µJ | 33.66% |  |
| other | component here_to_fix_a_bug | 0.00 µJ | 0.00% |  |
| buffer | component input_buffer | 0.20 µJ | 3.73% |  |
| analog compute | component integrator | 1.26 µJ | 23.98% |  |
| analog compute | component inter_1bit_x_1bit_mac_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_column_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_core_in_macro_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_crossbar_in_core_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_macro_in_die_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_row_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| buffer | component output_buffer | 0.08 µJ | 1.48% |  |
| on-die network | component router | 0.03 µJ | 0.65% |  |
| analog compute | component row_drivers | 0.08 µJ | 1.45% |  |
| conversion | component sample | 0.28 µJ | 5.23% |  |
| conversion | component shift_add | 0.04 µJ | 0.75% |  |
| analog compute | component virtual_bitwise_mac | 0.00 µJ | 0.00% |  |
| analog compute | component weight_drivers | 0.00 µJ | 0.00% |  |
| analog compute | component wordline_cap | 0.43 µJ | 8.28% |  |
| analog compute | component wordline_drivers | 0.00 µJ | 0.00% |  |
| on-die network | placement distance repricing increment router | 0.02 µJ | 0.32% | mean hops / reference hops = 1.500 |
| write | K/V write programming energy | 0.00 µJ | 0.00% | static operators do not write |
| write | weight rewrite energy (temporal rewrite policy) | 0.00 µJ | 0.00% | no rewrite in this configuration |
| D2D | die-to-die hand-off surplus energy (hops beyond the flat charge) | 0.00 µJ | 0.00% | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| other | unattributed residual (CiMLoop total − sum of the component rows) | 0.02 µJ | 0.38% | CiMLoop's operator total = the summary table's per-compute energy (finite precision) × computes; its difference from the exact sum of the components' Energy (total) lines is that table's rounding (≤0.5%); reported totals keep the CiMLoop convention |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| compute | array compute (Timeloop cycles) | 0.0101 ms |  |
| write | K/V write (serial, before compute) | 0.0000 ms | static operators do not write |
| on-die network | busiest-wire occupancy (serialization) | 0.0004 ms | occupancy, not exposure; = the lower bound of any schedule for the given routing × the schedule slack (platform input schedule_slack, currently 1) |
| on-die network | network exposure (perfect-overlap end = max(compute, occupancy) − compute) | 0.0000 ms | the end reported by default |
| on-die network | network exposure (zero-overlap end = occupancy) | 0.0004 ms | upper end of the overlap bracket |
| propagation | distance propagation delay | 0.0002 ms |  |
| D2D | die-to-die hand-off transfer (hidden state produced by this operator) | 0.0000 ms | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### decode · ffn2(static,P=1,C=4,096,M=1,024,N=1)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| conversion | component adc | 0.94 µJ | 19.65% |  |
| buffer | component chip2chip_data_staging | 0.00 µJ | 0.00% |  |
| off-chip port | component chip2chip_link | 0.02 µJ | 0.47% |  |
| analog compute | component cim_unit | 0.08 µJ | 1.57% |  |
| analog compute | component column_drivers | 0.00 µJ | 0.00% |  |
| buffer | component glb | 1.25 µJ | 26.06% |  |
| other | component here_to_fix_a_bug | 0.00 µJ | 0.00% |  |
| buffer | component input_buffer | 0.05 µJ | 1.02% |  |
| analog compute | component integrator | 1.26 µJ | 26.22% |  |
| analog compute | component inter_1bit_x_1bit_mac_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_column_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_core_in_macro_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_crossbar_in_core_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_macro_in_die_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_row_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| buffer | component output_buffer | 0.31 µJ | 6.43% |  |
| on-die network | component router | 0.04 µJ | 0.74% |  |
| analog compute | component row_drivers | 0.08 µJ | 1.59% |  |
| conversion | component sample | 0.28 µJ | 5.72% |  |
| conversion | component shift_add | 0.04 µJ | 0.82% |  |
| analog compute | component virtual_bitwise_mac | 0.00 µJ | 0.00% |  |
| analog compute | component weight_drivers | 0.00 µJ | 0.00% |  |
| analog compute | component wordline_cap | 0.43 µJ | 9.05% |  |
| analog compute | component wordline_drivers | 0.00 µJ | 0.00% |  |
| on-die network | placement distance repricing increment router | 0.02 µJ | 0.37% | mean hops / reference hops = 1.500 |
| write | K/V write programming energy | 0.00 µJ | 0.00% | static operators do not write |
| write | weight rewrite energy (temporal rewrite policy) | 0.00 µJ | 0.00% | no rewrite in this configuration |
| D2D | die-to-die hand-off surplus energy (hops beyond the flat charge) | 0.00 µJ | 0.00% | die link without a bandwidth (shipped default): transfer time counted as 0 |
| other | unattributed residual (CiMLoop total − sum of the component rows) | 0.01 µJ | 0.29% | CiMLoop's operator total = the summary table's per-compute energy (finite precision) × computes; its difference from the exact sum of the components' Energy (total) lines is that table's rounding (≤0.5%); reported totals keep the CiMLoop convention |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| compute | array compute (Timeloop cycles) | 0.0101 ms |  |
| write | K/V write (serial, before compute) | 0.0000 ms | static operators do not write |
| on-die network | busiest-wire occupancy (serialization) | 0.0007 ms | occupancy, not exposure; = the lower bound of any schedule for the given routing × the schedule slack (platform input schedule_slack, currently 1) |
| on-die network | network exposure (perfect-overlap end = max(compute, occupancy) − compute) | 0.0000 ms | the end reported by default |
| on-die network | network exposure (zero-overlap end = occupancy) | 0.0007 ms | upper end of the overlap bracket |
| propagation | distance propagation delay | 0.0002 ms |  |
| D2D | die-to-die hand-off transfer (hidden state produced by this operator) | 0.0000 ms | die link without a bandwidth (shipped default): transfer time counted as 0 |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### decode · softmax(elementwise,elements=8,192,after=qk^t)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| buffer | glb read/write (3 passes × 8,192 elements) | 0.38 µJ | 96.47% | glb access energy per word from the CiMLoop calibration of the same die (ffn1 run: 15.47 pJ/word) |
| digital unit | digital-unit arithmetic (add / mul / lookup) | 0.01 µJ | 3.53% | per element 2 adds + 1 muls + 1 lookups; generic example values (Horowitz ISSCC 2014; sized to array output rate) |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| digital unit | digital-unit compute (32,768 operations ÷ 64 lanes × 1 GHz) | 0.0005 ms | serial with the adjacent matmuls (stated assumption) |
| on-die network | busiest-wire occupancy (serialization) | 0.0000 ms | the digital unit sits next to the glb and does not use the on-die network (assumption) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### decode · gelu(elementwise,elements=4,096,after=ffn1)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| buffer | glb read/write (2 passes × 4,096 elements) | 0.13 µJ | 91.43% | glb access energy per word from the CiMLoop calibration of the same die (ffn1 run: 15.47 pJ/word) |
| digital unit | digital-unit arithmetic (add / mul / lookup) | 0.01 µJ | 8.57% | per element 2 adds + 3 muls + 1 lookups; generic example values (Horowitz ISSCC 2014; sized to array output rate) |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| digital unit | digital-unit compute (24,576 operations ÷ 64 lanes × 1 GHz) | 0.0004 ms | serial with the adjacent matmuls (stated assumption) |
| on-die network | busiest-wire occupancy (serialization) | 0.0000 ms | the digital unit sits next to the glb and does not use the on-die network (assumption) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### decode · layernorm(elementwise,elements=2,048,after=qkv_proj)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| buffer | glb read/write (3 passes × 2,048 elements) | 0.10 µJ | 97.17% | glb access energy per word from the CiMLoop calibration of the same die (ffn1 run: 15.47 pJ/word) |
| digital unit | digital-unit arithmetic (add / mul / lookup) | 0.00 µJ | 2.83% | per element 3 adds + 2 muls + 0.000976562 lookups; generic example values (Horowitz ISSCC 2014; sized to array output rate) |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| digital unit | digital-unit compute (10,242 operations ÷ 64 lanes × 1 GHz) | 0.0002 ms | serial with the adjacent matmuls (stated assumption) |
| on-die network | busiest-wire occupancy (serialization) | 0.0000 ms | the digital unit sits next to the glb and does not use the on-die network (assumption) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### decode · residual(elementwise,elements=2,048,after=out_proj)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| buffer | glb read/write (3 passes × 2,048 elements) | 0.10 µJ | 99.89% | glb access energy per word from the CiMLoop calibration of the same die (ffn1 run: 15.47 pJ/word) |
| digital unit | digital-unit arithmetic (add / mul / lookup) | 0.00 µJ | 0.11% | per element 1 adds + 0 muls + 0 lookups; generic example values (Horowitz ISSCC 2014; sized to array output rate) |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| digital unit | digital-unit compute (2,048 operations ÷ 64 lanes × 1 GHz) | 0.0000 ms | serial with the adjacent matmuls (stated assumption) |
| on-die network | busiest-wire occupancy (serialization) | 0.0000 ms | the digital unit sits next to the glb and does not use the on-die network (assumption) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### decode · embedding(offchip_read,words=1,024)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| off-chip | off-chip read of 1,024 words × DRAM energy per word | 0.05 µJ | 100.00% |  |

Latency:

| group | item | value | note |
|---|---|---|---|
| off-chip | off-chip read transfer | 0.0000 ms | off-chip port bandwidth not set (fabric.offchip_bandwidth_words_per_cycle): priced, not timed |

### decode · attention_unit(offloaded_unit,macs=1,048,576,kv_read_words=1,048,576)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| off-chip unit | unit compute (1,048,576 MACs + softmax 32,768 operations) × 1 pJ | 1.08 µJ | 2.01% | DR-9: generic public figures (ANCHORS.md) |
| off-chip unit | K/V memory read/write (2,048 writes + 1,048,576 reads) | 52.53 µJ | 97.72% |  |
| link | die↔unit link (Q out, K/V out, attention output back) | 0.14 µJ | 0.27% | priced over the mean 3.5 hops from the dies to the attach point (these words are not in the CiMLoop account) |

Latency:

| group | item | value | note |
|---|---|---|---|
| link | Q + K/V out (die → unit) | 0.0002 ms |  |
| off-chip unit | unit compute (including the fixed per-call overhead) | 0.0005 ms |  |
| off-chip unit | K/V memory read/write (reads the whole stored context) | 0.0410 ms | serial with compute (assumption) |
| link | attention output back (unit → die) | 0.0001 ms |  |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |

### decode · lm_head(static,P=1,C=1,024,M=65,536,N=1)

Energy:

| group | item | value | share of the operator's energy | note |
|---|---|---|---|---|
| conversion | component adc | 15.10 µJ | 18.81% |  |
| buffer | component chip2chip_data_staging | 0.00 µJ | 0.00% |  |
| off-chip port | component chip2chip_link | 0.56 µJ | 0.69% |  |
| analog compute | component cim_unit | 1.21 µJ | 1.51% |  |
| analog compute | component column_drivers | 0.00 µJ | 0.00% |  |
| buffer | component glb | 26.39 µJ | 32.87% |  |
| other | component here_to_fix_a_bug | 0.00 µJ | 0.00% |  |
| buffer | component input_buffer | 1.57 µJ | 1.96% |  |
| analog compute | component integrator | 20.20 µJ | 25.16% |  |
| analog compute | component inter_1bit_x_1bit_mac_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| other | component inter_chip_in_system_spatial | 0.00 µJ | 0.00% |  |
| analog compute | component inter_column_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_core_in_macro_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_crossbar_in_core_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| on-die network | component inter_macro_in_die_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| analog compute | component inter_row_spatial | 0.00 µJ | 0.00% | no energy model (not priced) |
| buffer | component output_buffer | 1.25 µJ | 1.56% |  |
| on-die network | component router | 0.37 µJ | 0.46% |  |
| analog compute | component row_drivers | 1.22 µJ | 1.52% |  |
| conversion | component sample | 4.40 µJ | 5.48% |  |
| conversion | component shift_add | 0.63 µJ | 0.78% |  |
| analog compute | component virtual_bitwise_mac | 0.00 µJ | 0.00% |  |
| analog compute | component weight_drivers | 0.00 µJ | 0.00% |  |
| analog compute | component wordline_cap | 6.96 µJ | 8.67% |  |
| analog compute | component wordline_drivers | 0.00 µJ | 0.00% |  |
| on-die network | placement distance repricing increment router | 0.19 µJ | 0.23% | mean hops / reference hops = 1.500 |
| off-chip port | placement distance repricing increment chip2chip_link | 0.17 µJ | 0.22% | mean hops / reference hops = 1.312 |
| write | K/V write programming energy | 0.00 µJ | 0.00% | static operators do not write |
| write | weight rewrite energy (temporal rewrite policy) | 0.00 µJ | 0.00% | no rewrite in this configuration |
| D2D | die-to-die hand-off surplus energy (hops beyond the flat charge) | 0.00 µJ | 0.00% | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| other | unattributed residual (CiMLoop total − sum of the component rows) | 0.07 µJ | 0.08% | CiMLoop's operator total = the summary table's per-compute energy (finite precision) × computes; its difference from the exact sum of the components' Energy (total) lines is that table's rounding (≤0.5%); reported totals keep the CiMLoop convention |
| not modelled | internal structure of the off-chip unit (buffers, control, quantisation) | not modelled, not counted |  | priced through its black-box interface: rate, mean overhead, K/V memory, link |
| not modelled | distance energy of the core/crossbar links | not modelled, not counted |  | the component exists but has no energy model (input not provided); its rows below are 0 |
| not modelled | cross-die sharding of a long-context K/V beyond capacity (>~8k tokens) | not modelled, not counted |  | FIXLIST O14 |

Latency:

| group | item | value | note |
|---|---|---|---|
| compute | array compute (Timeloop cycles) | 0.0101 ms |  |
| write | K/V write (serial, before compute) | 0.0000 ms | static operators do not write |
| on-die network | busiest-wire occupancy (serialization) | 0.0007 ms | occupancy, not exposure; = the lower bound of any schedule for the given routing × the schedule slack (platform input schedule_slack, currently 1) |
| on-die network | network exposure (perfect-overlap end = max(compute, occupancy) − compute) | 0.0000 ms | the end reported by default |
| on-die network | network exposure (zero-overlap end = occupancy) | 0.0007 ms | upper end of the overlap bracket |
| propagation | distance propagation delay | 0.0002 ms |  |
| D2D | die-to-die hand-off transfer (hidden state produced by this operator) | 0.0000 ms | not at a unit boundary (the hand-off belongs to out_proj / ffn2) |
| not modelled | network queueing (load vectors with equal peaks are not distinguished) | not modelled, not counted | only the busiest wire's occupancy is taken; the overlap bracket gives both ends |
| not modelled | compute / memory overlap inside the off-chip unit | not modelled, not counted | assumes the unit's compute and K/V access are serial |
| not modelled | pipeline bubbles / imbalance | not modelled, not counted | the pipeline view assumes perfect microbatch pipelining |
