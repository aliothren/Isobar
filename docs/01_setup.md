# 01 Setup

## What you need

- Docker with Compose. The image is the public CiMLoop image
  `timeloopaccelergy/timeloop-accelergy-pytorch`, pulled on first start.
- The repository checked out on the host. The `workspace/` folder is
  mounted into the container at `/home/workspace`.
- Nothing else. The simulator's own code is pure Python on top of the
  image's Timeloop, Accelergy and Python packages. BookSim (page 08) is
  built once from source inside the container and is optional.

## Start the container

From the repository root on the host:

```bash
DOCKER_ARCH=amd64 USER_UID=$(id -u) USER_GID=$(id -g) docker compose up -d
```

Use `DOCKER_ARCH=arm64` on Apple silicon. The service is called `tutorial`
in `docker-compose.yaml`, so the container is `cimloop-tutorial-1` when the
Compose project is named after the folder `cimloop`. Check with
`docker ps`. Port 8888 is exposed for the Jupyter server the image starts;
nothing in this guide needs it.

Open a shell in the container:

```bash
docker exec -it cimloop-tutorial-1 bash
cd /home/workspace
```

All later pages assume this shell and this directory.

## Confirm the installation

```bash
python3 tests/run_tests.py
```

Expected: a `PASS` line per test and the summary
`443 passed, 0 failed, 0 expected-fail (known gaps), 0 XPASS, 0 skipped`
(the count is that of the frozen tree; the suite grows with the code).
The fast suite takes one to three minutes depending on the host's load.
Add `--slow` to also run one real mapper job and the BookSim identity
gates; that takes minutes and needs the BookSim binary for the last group
(the gate tests are skipped, not failed, when the binary is absent).

If the summary reports failures on a fresh checkout, the working tree and
the frozen artifacts in `analysis/` are out of step. Do not proceed on
that tree; see page 10.

## Two rules that save an afternoon

**Ownership.** Files the container writes belong to root on the host, so
the host editor cannot save over them. Inside the container run

```bash
chown -R $(id -u):$(id -g) /home/workspace/analysis
```

(or the folder in question) before editing on the host. The compose file
passes your user and group ids in for this purpose.

**Stale bytecode.** Python keeps compiled files in `__pycache__`. When a
script is edited on the host and the cached file is newer by the
container's clock, the old code runs. Before running an edited script:

```bash
find /home/workspace/scripts -name __pycache__ -exec rm -rf {} +
```

## Layout inside the container

| path | content |
|---|---|
| `/home/workspace/scripts/` | the platform modules and every experiment script |
| `/home/workspace/models/fabric/` | the fabric files, page 03 |
| `/home/workspace/analysis/` | results, records, figures; also the place to put your own scratch scripts (ignored by git) |
| `/home/workspace/tests/` | the guardrail suite |
| `/home/workspace/tools/booksim2/` | BookSim, if built |
| `/home/workspace/outputs/` | Timeloop mapper output directories |

## Running a snippet

The pages that follow give short Python snippets. Save one as, for
example, `analysis/my_probe.py` and run `python3 analysis/my_probe.py`.
Every snippet starts with

```python
import sys
sys.path.insert(0, "/home/workspace")
```

so that `from scripts import ...` resolves.
