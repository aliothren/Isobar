# 10 Scope and FAQ

## What the model prices, and what it does not

Priced, and part of every result:

- matrix compute and weight write on the calibrated ReRAM macro, per
  operator, from the mapper;
- the digital vector unit's time and energy for the non-matrix
  operators, from declared lanes, clock and per-op energies;
- hand-off communication between operator sets on the declared die mesh
  under XY routing: busiest link or port load, propagation over the
  longest path, flat energy per word plus the distance surplus;
- inside a die, the macro-level serialization of the two co-resident
  operators against their own compute, on the exhaustively enumerated
  assignment.

Not priced in this version:

- static (idle) power; the energy is dynamic only;
- a package seam fee at a pipeline cut; cutting is free, so the serial
  and pipeline calibers differ only through the interval;
- energy of the intra-die assignment (its cost is latency only);
- batching; the account is batch 1 with serial prefill;
- adaptive or non-XY routing, and link-level flow control (the term is
  the occupancy bound; BookSim supplies the queueing view, page 08);
- thermal, area and yield.

Fixed conventions: R-split multicast at every hand-off (each producer
die ships its piece to every consumer die); partial sums at two words
per element; the attention operator on one die or offloaded whole;
ports at a declared multiple of the link rate.

## Frequently met errors

**`illegal deployment: ...`** from `evaluate` (`illegal Pi` from
`score`). The deployment seats a set on the wrong number of dies, reuses
a slot, or names a set the account does not have. The message gives the
reason; `baseline` writes a legal deployment to compare against.

**`ValueError` from `from_yaml` naming a field.** The fabric failed
validation; the message says which rule (mesh smaller than
`per_parent`, both `ns_per_hop` and `ns_per_mm`, `schedule_slack` below
1, an unknown `device_class`).

**The row time in the fabric does not match the macro** (a
`verify_cycle` error on a mapper run). The `device` block must agree
with the CiMLoop macro named under `cimloop:`; the check exists so a
fabric cannot declare a speed its macro does not have. Use
`device_class: digital_throughput` only for an abstract digital engine.

**Numbers differ from the documents by a few percent after editing a
script.** Stale bytecode; clear `__pycache__` in the container (page
01). If they still differ, run the tests: the failing test names the
artifact that moved.

**A script cannot write into `analysis/`, or the host editor cannot
save.** Ownership; `chown` inside the container (page 01).

**The BookSim gate tests are skipped.** The binary is not built;
page 08.

**`ISOBAR_KAPPA` unset draws the kappa 1 diagram.** The main
configuration is kappa 2; set the variable. The same holds for
`SEAT_KAPPA` and `ABL_KAPPAS` on their scripts.

**The evaluator ignores `CIMSIM_FABRIC`.** By design: the command line
takes `--fabric`, and `Workload2p7B` takes the fabric as an argument
(page 03). `CIMSIM_FABRIC` steers the mapper-side scripts and the anchor
registry's unit conversions.

## Questions

**Can I evaluate a model that is not the 2.7B class?** Yes, after one
mapper run that writes its account (page 04), provided the block
structure is the standard five-operator chain. Other block structures
need code.

**Can I change the bandwidth of one link only?** Not in the evaluator;
`--bandwidth` is one rate for the die level. Per-link rates are a code
change in `resource_loads`.

**Can I run the search on decode, or on both phases?** Yes:
`search --phases decode` or `--phases prefill,decode` (the weighted sum);
the frozen results search prefill and re-score decode on the found
seats.

**How long do things take?** A full score about 40 ms, an incremental
one about 1.3 ms, one anneal of 1200 steps a few seconds, the six-cell
sweep a few minutes, a mapper account run an hour or more, the fast
test suite one to three minutes.

**Which numbers are certified and which observed?** `analysis/METRICS.md`
labels every published ratio: exhaustive (the intra-die band, the
70-seating enumeration) or searched (the package results). A searched
number is a lower bound on what the space holds.

**Where do I record a change?** `analysis/FIXLIST.en.md`, newest at the
end, with the number before and after and the reason; and
`tests/CHANGELOG.md` when a pinned value moves.
