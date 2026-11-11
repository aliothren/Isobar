# Isobar on this branch

This branch is the development tree: it keeps every script, record and figure set of the work. The `release` branch holds the final framework reorganised for distribution, with its full user guide (setup, the model, hardware and accounts, experiments, validation, reproducing the paper, the GPU comparison):

```bash
git show release:docs/02_framework.md      # or: git switch release
```

The pages here cover what is specific to this branch:

| page | content |
|---|---|
| [01 Setup](01_setup.md) | the container with the `/data` mounts, the host environment, BookSim, the tests |
| [02 The final pipeline](02_final_pipeline.md) | the commands, units and files that produced every figure and table of the paper |

The model itself is described in [`../formulation.md`](../formulation.md) (cost model) and [`../workspace/analysis/SUMMARY.en.md`](../workspace/analysis/SUMMARY.en.md) (framework and results). The paper's numbers with their sources are in [`../workspace/analysis/paper_numbers.md`](../workspace/analysis/paper_numbers.md).

The earlier user guide (the single-model main configuration and `cimsim_cli.py`) is superseded by the final framework; it remains in the git history (`git show e3409c1:docs/README.md`).
