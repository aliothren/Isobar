# CIM configurations

One JSON per configuration (`<id>.json`): the record whose fixed mapping is used, the mesh bandwidth, the die variant, unit overrides, the model-end options and the request lengths. `resources.csv` (written by `scripts/summarize.py`) lists the actual resources of every configuration.

| id | model | dies / grid (backbone) | macros per die | mesh (GB/s per dir.) | hub / K/V | basis |
| --- | --- | --- | --- | --- | --- | --- |
| A0_ref | OPT-13B | 2200 / 47x47 | 8 | 0.4 | 12.5 GB/s / 25.6 GB/s | existing reference (e9_confirm prefill 512 representative) |
| A1_m16 | OPT-13B | 1160 / 35x35 | 16 | 0.4 | same | existing 16-macro confirmation (e10_confirm_cap) |
| A2_grs | OPT-13B | 2200 / 47x47 | 8 | 12.5 | same | A0 layout re-priced at the GRS tier (no re-search) |
| A3_m16_grs_kv | OPT-13B | 1160 / 35x35 | 16 | 12.5 | 12.5 GB/s / 51.2 GB/s | A1 layout at the GRS tier, K/V memory LPDDR5-class |
| A4_col | OPT-13B | 2400 / 49x49 | 8 | 0.4 | same | column-split QKV confirmation record (e10_confirm, tlcol): one 1-byte output row per layer into the unit instead of ten 2-byte partial-sum rows |
| A5_col_grs | OPT-13B | 2400 / 49x49 | 8 | 12.5 | same | A4 layout at the GRS tier |
| B0_ref .. B3 | Gemma-7B | 1232 / 36x36 (8 macros), 616 / 25x25 (16 macros) | | same pattern | | |

Common: central digital unit K = 1 (DR-9 reference: 2 TMAC/s, 1 pJ per MAC-equivalent op, 8 MB buffer, K/V 1 byte per element, 2 GB), kappa = 2, XY routing, 20 ns per hop, NeuRRAM-class device (10.14 us per input row), 8-bit weights / activations, 2-byte partial sums. The LM head is resident on extra CIM dies (OPT-13B 64, Gemma-7B 128 at 8 macros; vocab padded to a power of two) and evaluated for one row per generated token; the embedding (and OPT's learned positions) are read from the unit's memory at 50 pJ per word; the final norm and the argmax run on the digital unit; Gemma's RoPE is counted on the unit (3 MAC-equivalent ops per rotated element). Static weights are resident; nothing is rewritten between phases. Precision labels: `precision` field of each JSON. Sources of every value: `sources` field (literature tier / existing calibration / design assumption).
