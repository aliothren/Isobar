# External Dependencies (not committed to this repo)

These are external tools/repos used by CiMLoop but **deliberately excluded from
git** (via `.gitignore`). They are read-only / re-clonable and are not part of
our own work, so we record their exact versions here for reproducibility instead
of committing them.

## Standalone NeuroSim (ground-truth validation tool)

- **Used by**: `workspace/tutorials/demo_speed_accuracy.ipynb`
  (reproduces the CiMLoop-vs-NeuroSim speed/accuracy comparison, paper Table II / Fig. 6).
- **We do not modify it** — it is only run as an independent ground truth.
- **Repo**: https://github.com/tanner-andrulis/DNN_NeuroSim_V1.3.git
- **Branch**: master
- **Pinned commit**: `bdac598da25aa5987217cf72921d7238b03827e8`
  (2024-04-15, "Merge branch 'neurosim:master' into master")

### How to re-clone the exact version
```bash
cd workspace/tutorials
git clone https://github.com/tanner-andrulis/DNN_NeuroSim_V1.3.git
cd DNN_NeuroSim_V1.3
git checkout bdac598da25aa5987217cf72921d7238b03827e8
make            # builds the C++ NeuroSim
```

## Upstream CiMLoop

This repo is forked/derived from MIT-EMZE CiMLoop. Upstream is kept as the
`upstream` git remote for pulling updates:

- **Upstream**: https://github.com/mit-emze/cimloop.git
- Our fork origin: https://github.com/aliothren/cimsim.git
