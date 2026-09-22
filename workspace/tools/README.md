# tools: external simulators

`booksim2/` is the BookSim 2 cycle-level interconnection network simulator,
built from source inside the container (`BUILD_NOTES.md` records the
build). It is the external judge of the hand-off term: `scripts/booksim_bridge.py`
converts a hand-off's flows into a BookSim traffic file under a declared
conversion table (8-byte flits, 17-flit packets, a 14-cycle hop, buffers
sized to the bandwidth-delay product) and reads back the batch completion
time. BookSim gives each node one terminal channel at link width, so it can
judge the port ratio kappa = 1 only; the kappa = 2 main results are the
system model's own.
