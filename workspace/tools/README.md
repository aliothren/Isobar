# tools: external simulators

`booksim2/` is BookSim 2, the cycle-level interconnection network simulator (Jiang et al., ISPASS 2013). It is not committed (see [`../../EXTERNAL_DEPENDENCIES.md`](../../EXTERNAL_DEPENDENCIES.md)). Build it from the upstream source with the two patches in `scripts/booksim_patches/`; `BUILD_NOTES.md` inside it records the build. The patches add:

- `traffic = file(<path>)`: exact per-pair batch traffic;
- `mesh_channel_latency = N`: wire cycles per hop for the mesh and concentrated-mesh topologies.

`scripts/booksim_bridge.py` converts a hand-off's flows into a BookSim batch run and reads back the completion time:

- 8-byte flits, 17-flit packets;
- 10 channel + 4 router cycles per hop;
- 34-flit virtual-channel buffers;
- a concentrated mesh with c = 4 terminals per node, so a die's injection and ejection capacity is 4 link channels;
- wavefront allocators.

The analytic side of the comparison uses κ = 4 for the offload libraries and κ = 2 for the on-chip library (`scripts/v3_discrim.py`, `analysis/v3/e3_offload`, `analysis/v3/e3_k2`).
