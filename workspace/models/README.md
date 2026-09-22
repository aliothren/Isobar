# models: CiMLoop's models and this work's fabric descriptions

This folder is CiMLoop's model tree, used unchanged for the per-operator
mapping and the calibrated macro, plus `fabric/`, which describes the
physical systems this work evaluates.

| folder | content |
|---|---|
| `arch/1_macro/` | published CiM macros as CiMLoop models, each with a guide notebook and tests; the ReRAM macro of this work is `wan_nature_2022` (NeuRRAM class, 256x256, 4-bit) |
| `arch/2_tile/` | tile level; `mlx_core.yaml` is this work's core: local buffers and 8 crossbars |
| `arch/3_chip/` | chip level; `mlx_die.yaml` is this work's die: an 8 MB global buffer, 8 macros with an inter-macro router, 4 cores per macro |
| `arch/4_system/` | system level; `ws_chip2chip_link.yaml` is the weight-stationary multi-die top level used here (weights programmed once, dies linked), as opposed to the `fetch_*` tops that re-stream weights every inference |
| `components/` | compound components and Accelergy plug-ins |
| `memory_cells/` | device models |
| `workloads/` | DNN and transformer layers; `gpt2_medium/` and `opt_2p7b/` are the two model classes of this work |
| `include/` | shared defines, the mapper settings, slicing and encoding helpers |
| `fabric/` | the physical fabric descriptions of this work, see [`fabric/README.md`](fabric/README.md) |
| `top.yaml.jinja2` | gathers the level files into one specification |

CiMLoop's own guide to these files, with its macro guides and the meaning
of the iso and free variable files, is in the upstream tree under
[`../../io_study/`](../../io_study/README.md).
