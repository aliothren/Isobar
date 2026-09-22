# 09 Results and figures

## Where the numbers are

| document | content |
|---|---|
| `analysis/main_config_results.md` | the main configuration: every layout on prefill and decode at both bandwidths, the headline statistics, and the ledger (numerator, denominator, absolute values, statistic) of every published percentage |
| `analysis/paper_numbers.md` | every number the paper uses, one line each |
| `analysis/METRICS.md` | the registry of published quantities and their denominators |
| `analysis/mechanism_table.md` | per-hand-off loads, hotspots and the binding resource per layout |
| `analysis/energy_export.md` | dynamic energy by term per layout |
| `analysis/ANCHORS.md` | every published bandwidth, device and I/O figure used as a reference, with source and status |
| `analysis/FIXLIST.en.md` | the chronological record of every change; when two documents disagree it says which is current |
| `analysis/SUMMARY.en.md` | the full account of the platform and its results |

The JSON files beside the documents carry the same numbers for programs;
the most used are listed in `analysis/README.md`.

## Regenerate the frozen results

In dependency order, from `/home/workspace`:

```bash
python3 scripts/kappa_geometry_sweep.py        # the search cells (minutes)
python3 scripts/main_config_export.py          # the main-configuration table and ledger
python3 scripts/mechanism_table.py             # the loads behind the ranking
python3 scripts/energy_export.py               # dynamic energy of the frozen layouts
ABL_KAPPAS=2 python3 scripts/objective_ablation.py
SEAT_KAPPA=2 python3 scripts/rerun_seating_seeds.py
python3 scripts/bw_slice_k2.py                 # the frozen pair across bandwidth
python3 scripts/search_withindie.py && python3 scripts/intra_die_integration.py
ISOBAR_KAPPA=2 python3 scripts/fig_phase_isobar.py
```

Every script overwrites its own outputs under `analysis/` and prints the
paths. Afterwards run the tests: they pin the frozen values, so a
regeneration that moves a number fails loudly, and `tests/CHANGELOG.md`
is where a legitimate move is recorded with its reason.

The mapper-side account (`scripts/run_2p7b_block.py`, page 04) and the
per-operator ledger (`scripts/op_breakdown.py`) are the only long runs;
everything above is closed-form on the frozen account.

## The paper figure set

```bash
python3 scripts/plot_dac2027_v2.py --run-id 20260921_v2              # all six figures
python3 scripts/plot_dac2027_v2.py --run-id 20260921_v2 --only fig5   # one of fig1..fig6
```

A run id is a directory under `analysis/figures_dac2027/`; the script
writes `composites/`, `panels/`, `data/`, `preview/`, `captions.md`,
`figure_index.md` and `manifest.json` into it. Use a new run id for a
new set; an existing set is never overwritten by a different id, and
the manifest records the checksums of the figures that pre-existed the
run. The captions and the per-figure record (claim, instance, layout
identifiers, statistic, denominator, sources) are written by the same
script, so a figure and its caption cannot drift apart.

The standing exhibit figures in `analysis/` are each written by the
script of the same base name (`grep -l <figure name> scripts/*.py` finds
it); `scripts/make_figures.py` drives the older mapper-side stages and
takes a `--tag` so a fabric variant's outputs sit beside the canonical
ones instead of replacing them.

## The tests as the guard

```bash
python3 tests/run_tests.py             # 443 tests, one to three minutes
python3 tests/run_tests.py --slow      # plus one mapper run and the BookSim gates
```

Groups follow the platform's history; the search groups (49 to 55) pin
the space, the evaluator, the annealer, the dynamic program, the
instances and the referee experiment, and `test_anchor_registry.py` pins
every reference figure as read from its source. A new result of yours
belongs in the same suite: pin the artifact it comes from, and note the
baseline in `tests/CHANGELOG.md`.
