# 01 Setup

## Container (CiMLoop measurements)

The CiMLoop stages (per-operator accounts, the intra-die instance, the LM head) run in the public CiMLoop image `timeloopaccelergy/timeloop-accelergy-pytorch`. From the repository root:

```bash
DOCKER_ARCH=amd64 USER_UID=$(id -u) USER_GID=$(id -g) docker compose up -d
docker exec -it -u $(id -u):$(id -g) cimloop-tutorial-1 bash
cd /home/workspace
```

`docker-compose.yaml` mounts `workspace/` at `/home/workspace`. It also mounts `/data/yuxinr/cimloop` at the same path, because `workspace/analysis/v4` and `workspace/outputs` are symbolic links into `/data`, so the links resolve inside the container. Mapper outputs and the large records are written to the local disk `/data`, not the network home directory. Run as your own user (`-u`) so the files stay yours. Clear `__pycache__` inside the container before running a script edited on the host.

## Host (everything else)

Evaluation, search, the deployment experiments, the exports, the figures and the GPU comparison are pure Python with numpy, pyyaml and matplotlib. They run on the host as well:

```bash
/home/yuxinr/miniforge3/envs/far/bin/python scripts/v7_fig5_fig6_results.py      # from workspace/
```

On a host without `pytimeloop`, `scripts/__init__.py` leaves `scripts.utils` unset, so the evaluation modules import normally.

## BookSim 2

The validation libraries need the BookSim 2 binary at `workspace/tools/booksim2/src/booksim`. The source is not committed. Fetch it, apply `scripts/booksim_patches/0001-file-traffic-batch.patch` and `0002-cmesh-channel-latency.patch`, and build it as described in [`workspace/tools/README.md`](../workspace/tools/README.md).

## Tests

```bash
python3 tests/run_tests.py          # container, from /home/workspace
```

The suite covers the platform modules (fabric, interconnect, traffic, evaluator, search) and the reference numbers of the 2.7B-class instance.
