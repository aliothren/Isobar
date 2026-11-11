# External simulators: BookSim 2

This page builds the BookSim 2 cycle-level network simulator (Jiang et al., ISPASS 2013) and checks that Isobar can use it. BookSim is needed only for the validation against packet-level simulation (`scripts/run_booksim_libraries.py`, Figs. 3(b) and 4). It is not redistributed in this repository.

Paths in this page are relative to `workspace/`, except where a command block says it starts from the repository root.

## Requirements

- git, make, a C++ compiler (g++), flex and bison. On Debian or Ubuntu: `sudo apt install git make g++ flex bison`.
- Build on the **host** (recommended). The CiMLoop container image has no flex or bison; see "Building for the container" below.

The build used for the paper is upstream commit `28f43299f1706a3160ffac721ca461d74eb6e618` (2017-06-27) with the two patches in `scripts/booksim_patches/`. It was rebuilt with g++ 15.2, flex 2.6.4 and bison 3.8.2 and reproduces the paper's BookSim results.

## Build

```bash
# from the repository root
cd workspace/tools
git clone https://github.com/booksim/booksim2.git
cd booksim2
git checkout 28f43299f1706a3160ffac721ca461d74eb6e618
cd src
patch -p0 < ../../../scripts/booksim_patches/0001-file-traffic-batch.patch
patch -p0 < ../../../scripts/booksim_patches/0002-cmesh-channel-latency.patch
make -j4
./booksim                     # prints "Usage: ./booksim configfile... [param=value...]"
```

The binary is now at `tools/booksim2/src/booksim`, where `scripts/booksim_bridge.py` looks for it. The patches add only two features:

- `traffic = file(<path>)`: exact per-pair batch traffic from a file of `source destination count` lines. Destinations are served round-robin, and the per-source packet counts replace BookSim's uniform batch size.
- `mesh_channel_latency = N`: wire cycles per hop for the mesh and concentrated-mesh topologies (stock BookSim uses 1).

## Check the integration with Isobar

```bash
# from workspace/, on the machine where BookSim was built
python3 scripts/booksim_bridge.py --check
```

Expected output:

```
BookSim batch: 21813 cycles (expected 21813) -> OK
```

The check sends a small batch through `booksim_bridge.run_batch` on a 6 × 6 concentrated mesh: three flows, file-driven traffic, 10-cycle channels. A different cycle count means a different BookSim version or a missing patch.

## How Isobar calls BookSim

`scripts/booksim_bridge.py` converts the flows of a hand-off into a BookSim batch run and reads back the completion time. The settings follow Simba's package network:

- 8-byte flits and 17-flit packets (128-byte payload);
- 10 channel + 4 router cycles per hop;
- 34-flit virtual-channel buffers;
- a concentrated mesh with 4 terminals per node, so a die's injection and ejection capacity is 4 link channels;
- wavefront allocators;
- all packets injected at time 0.

The bridge runs the binary directly when it can. Otherwise it calls it inside the container with `docker exec isobar`; the variable `ISOBAR_CONTAINER` names another container.

## Building for the container

If you want to run BookSim inside the CiMLoop container, build it there. Because `workspace/` is mounted into the container, the parser files that flex and bison generate on the host are visible in the container:

```bash
# host, from the repository root: clone, check out and patch as above, then generate the parser
cd workspace/tools/booksim2/src
flex config.l && bison -y -d config.y        # creates lex.yy.c, y.tab.c and y.tab.h in this directory
```

```bash
# container, from /home/workspace
cd tools/booksim2/src && make -j4            # the Makefile uses the generated files and does not call flex or bison
cd /home/workspace && python3 scripts/booksim_bridge.py --check
```

On a machine without the shared folder, copy `lex.yy.c`, `y.tab.c` and `y.tab.h` into `tools/booksim2/src/` there before running `make`.
