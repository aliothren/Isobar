# Models

This folder holds the hardware and workload descriptions. There are two hardware descriptions with different jobs:

- [`fabric/`](fabric/) is read by Isobar ([`../scripts/fabric.py`](../scripts/fabric.py)). It describes the physical chip that the package model and the deployments use: how many macros a die has and how they are arranged, the on-die network, the analog device's row time, and the die's digital vector unit for element-wise operators.
- [`arch/`](arch/) is read by CiMLoop when it measures the per-operator costs (the accounts). It describes the same die at the level of storage, arrays and data converters.

Settings that appear in both, such as macros per die, the arrangement of macros and cores, and the device speed, must agree. Every CiMLoop run checks the device timing and the die hierarchy against the fabric and stops if they differ. [Hardware guide](../../docs/03_hardware.md) explains how to change them together.

The digital units that run attention and hold the K/V cache are **not** described here. Their parameters are in [`../scripts/offload.py`](../scripts/offload.py) (`REF_UNIT`) and the options of `run_experiments.py`.

| path | content | origin |
|---|---|---|
| [`fabric/`](fabric/) | Isobar's hardware files: the measurement die (`mlx300_multidie.yaml`), its 4-, 16- and 32-macro variants, the package the deployments start from (`mlx300_multidie576.yaml`), a single die (`mlx300.yaml`), Simba (`simba.yaml`) | this project |
| [`arch/1_macro/wan_nature_2022/`](arch/1_macro/wan_nature_2022/) | the NeuRRAM-class RRAM macro (Wan et al., Nature 2022) | CiMLoop, unchanged |
| [`arch/2_tile/mlx_core.yaml`](arch/2_tile/mlx_core.yaml), [`arch/3_chip/mlx_die.yaml`](arch/3_chip/mlx_die.yaml) | the core (input/output buffers and 8 arrays) and the die (global buffer, router, 8 macros of 4 cores) | this project |
| [`arch/4_system/ws_chip2chip_link.yaml`](arch/4_system/ws_chip2chip_link.yaml) | the top level of the CiMLoop description: dies with resident weights and a die-to-die link | CiMLoop, unchanged |
| [`arch/2_tile/`](arch/2_tile/), [`arch/3_chip/`](arch/3_chip/), [`arch/4_system/`](arch/4_system/), other files | generic CiMLoop levels (`input_output_bufs`, `large_router_glb`, `fetch_weights_lpddr4`, `_none`), used by `mlx_system.MLX_CONFIG` | CiMLoop, unchanged |
| [`components/`](components/), [`include/`](include/), [`memory_cells/`](memory_cells/), [`top.yaml.jinja2`](top.yaml.jinja2) | CiMLoop component models, shared definitions, the RRAM cell of the macro, the top-level template | CiMLoop, unchanged |
| [`workloads/opt_2p7b/`](workloads/opt_2p7b/) | operand value distributions of facebook/opt-2.7b; CiMLoop computes the energy of every account's analog operations from them | this project (`scripts/extract_value_histograms.py`) |
| [`workloads/gpt2_medium/`](workloads/gpt2_medium/) | value distributions of GPT-2 medium, used by the intra-die instance (`measure_intradie_instance.py`) | CiMLoop, unchanged |
| [`workloads/resnet18/`](workloads/resnet18/), `problem_base.yaml`, `default_problem.yaml` | problem-file templates: each CiMLoop operator run starts from the first ResNet-18 layer file and replaces its shape and value distributions | CiMLoop, unchanged |

**The two package levels.** CiMLoop's top level, `ws_chip2chip_link`, matters only when **one** operator is split over several dies. It then accounts, inside the account, for that operator's internal data movement between its dies. The traffic **between** operators (the hand-offs), its routing on the mesh, and the contention on links and ports are not computed by CiMLoop. Isobar's package model computes them in the deployment stage (`scripts/search_eval.py`) from the placement, using the `fabric/` files and the deployment options.

The CiMLoop files come from the CiMLoop release (Andrulis, Emer and Sze, ISPASS 2024; MIT license). Only the macro, levels and workloads Isobar uses are kept here.
