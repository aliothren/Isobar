# 07 The phase diagram

The phase diagram answers, for your hardware, whether placement decides
the cost. Its two axes are the device's row-processing rate and the link
bandwidth per direction; its two boundaries are the placement extrema of
the communication cost: below the lower one every placement is
communication-bound, above the upper one communication is masked by
compute and the fixed terms, between them placement decides which side
of the balance a deployment lands on.

## Draw it for the main configuration

```bash
ISOBAR_KAPPA=2 python3 scripts/fig_phase_isobar.py
```

Outputs `analysis/phase_diagram_isobar_k2.png`, `.pdf` and `.json`. The
JSON holds the boundaries, the region classification of the evaluated
bandwidths, and the reference points. The print version for the paper
figure set is `scripts/fig_phase_isobar_print.py` with the same
variable. Runtime is under a minute; with `ISOBAR_KAPPA` unset the
package panel reads the pinned kappa 1 ladder instead of recomputing.

The right panel is the package level: the seven named seating rules on
the 2.7B instance give the band. The left panel is one die: all 70
macro seatings of the ffn die, enumerated, so that band is exhaustive
over its placement set.

## The band for your hardware

The boundaries are B_minus(s) = A_min / R(s) and B_plus(s) = A_max / R(s)
with A the busiest-resource words of the fastest and slowest placement
in the set and R(s) the non-communication time at device rate s. The
command line computes them for any fabric and account from the seven
named rules, reads them at the fabric's own device rate, and says on
which side each bandwidth of interest falls:

```bash
python3 scripts/cimsim_cli.py phase --bandwidths 0.4,12.5 --out analysis/band.json --png analysis/band.png
```

```
fabric mlx300-multidie576 | account gpt-2.7B-class | kappa 2 | phase prefill | 7 placements
busiest-resource words: min 4.928e+08 (random), max 1.309e+09 (sequential), ratio 2.656
at the fabric's device rate 0.0986 Mrows/s: B- 0.535 GB/s, B+ 1.421 GB/s (x2.66)
  0.4 GB/s: communication dominated for every placement
  12.5 GB/s: communication masked for every placement
```

The JSON carries the two boundary curves over the device axis, the
placement set's words, and the classification; `--png` draws the band
with the bandwidths marked at the fabric's rate. `--rules` changes the
placement set, `--kappa`, `--fabric`, `--workload` and `--device-scale`
the setting. On a fabric variant this is the first thing to run: it
says whether a search is worth its minutes.

## Reference chips

The diagram carries the published link rates of HERMES and ISAAC and the
I/O-matched projection of the M1076, each with a status (measured,
derived, estimated) and a source, from the registry in
`scripts/anchors.py`. To add a chip of your own:

1. Add a `ChipPoint` to the `CHIPS` list with its row time
   (`t_mvm_s`, and `t_mvm_status` measured or derived, with the
   derivation written out), its on-die and die-to-die rates
   (`ondie_gbps`, `d2d_gbps`) or bands, and a `source`. A published
   per-physical-link rate goes in `ondie_gbps_per_link` and is
   aggregated to the model's per-macro granularity by the normalization
   rule in the class docstring.
2. Record it in `analysis/ANCHORS.md` with the same status words.
3. Add a test in `tests/test_anchor_registry.py` that pins the values
   you transcribed, so a later edit cannot move them silently.

The figure scripts draw every chip in `CHIPS` that has both
coordinates; a chip with a row time but no published bandwidth is
placed on the axis, not at a guessed height.

## The bandwidth sweeps behind it

The per-axis sweeps that the diagram condenses (on-die bandwidth, die
to die for the 355M and 2.7B chains, the offload link, the partial-sum
width) are `scripts/sweep_axes.py`; the device-plane classification is
`scripts/analyze_phase_diagram.py` and `scripts/certified_regions.py`.
They re-score stored per-operator components in closed form and need no
mapper run. Their readouts are in `analysis/SUMMARY.en.md`.
