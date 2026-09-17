# Caption for `phase_diagram_isobar.png` / `phase_diagram_isobar_print.png` (Fig. 1)

Generators: `scripts/fig_phase_isobar.py` (large, reviewed) and
`scripts/fig_phase_isobar_print.py` (double-column, 7.16 in wide, text set
at 7-8 pt at final size; the instance descriptions below replace the two
in-figure boxes of the large version). Data: `analysis/phase_diagram_isobar.json`,
`analysis/phase_diagram_isobar_envelope_decomp.json`.

**Where communication leads, and where the placement decides it.** Both
axes are rates: the MVM row-processing rate s = 1/t_row (Mrows/s, faster
silicon to the right) and the link bandwidth per direction (GB/s). With the
communication cost H = A(p)/B for placement p and everything else
R(s) = N·s_ref/s + F, the two boundaries are B₋(s) = min_P A(p)/R(s) and
B₊(s) = max_P A(p)/R(s). Above B₊ every evaluated placement is
compute/fixed-cost dominated; below B₋ every evaluated placement is
communication dominated, and the placement still sets how severe; between
them which cost leads depends on the placement. The dotted contour is the
placement latency spread (T_max − T_min)/T_min over the same set P at 20%.
The vertical bar reads the envelope at one device speed: the placement rule
alone decides whether B₋ or B₊ is needed, a ratio max_P A / min_P A that is
independent of s.

**(a) Intra-die placement.** Latency object: one die's two co-resident
operators under attention offload (a sub-problem, not the whole model).
P = all 70 joint seatings of the two operators on the die's 8 macro slots
(2×4 macro mesh, XY routing, global buffer at the centre), enumerated, so
the envelope is exhaustive over P *for this instance and this analytic
cost model*. The fixed term is 0.36 µs against 10.38 ms of compute, so
both boundaries keep slope +1. Hardware-derived reference points (published
parameters projected onto this instance, not claims about where the real
chip sits): HERMES at its published core-to-core link rate, 3.2 Gbit/s =
0.4 GB/s per link, at the 4-phase (520 ns, open) and 1-phase (133 ns,
filled) MVM latencies; ISAAC as an architecture model, a 32-bit flit per
1.2 GHz NoC cycle = 4.8 GB/s, assuming one flit per cycle. One of our macro
links is a coarser resource than one HERMES physical link; these are
reference points, not operating points.

**(b) Inter-die placement.** Latency object: whole-model serial prefill of
the 2.7B stack, 544 of 576 dies occupied on a 24×24 die mesh with XY
routing; the hand-off cost is the busiest resource over links AND die
ports, one injection and one ejection port per die at the link rate. P =
the seven named die-seating rules; the envelope is observed over P, not a
bound over all legal placements. The K/V write and the digital unit do not
scale with device speed, so both boundaries flatten at the fast edge. The
two crosses are the configurations this paper's searches evaluated, 0.4
and 12.5 GB/s at the NeuRRAM row rate; the first lies below B₋ (every
named seating communication dominated, hand-off share 60% of latency at
the reference seating) and the second above B₊ (every named seating compute
dominated, share 4.6%), which is why the same seating search buys 3.5% of
latency at one and 0.24% at the other. Mythic M1076 and ISAAC share one
assumed exploration range of 0.4–8 GB/s (neither publishes a per-link
figure); NeuRRAM publishes a row rate but no link bandwidth and is marked
on the axis only.

**Legend terms.** *Hardware-derived reference*: a chip's published
parameters projected onto this instance's axes, the row rate from its
published MVM latency or peak throughput and the bandwidth from its
published per-link rate, with no aggregation across links; the point says
where those parameters fall on this instance's boundaries, not where the
real chip operates. *Assumed bandwidth range*: for chips that publish no
per-link figure, the same exploration range 0.4-8 GB/s is drawn for each,
spanning the published HERMES per-link rate at the low end and a
digital-NoC-class link at the high end. *Evaluated NeuRRAM-based system*:
the configurations this paper's searches actually ran, NeuRRAM's measured
row rate (10.14 us per row, 0.099 Mrows/s) with the two interconnect
bandwidths of the study, 0.4 GB/s (the HERMES-class per-link rate) and
12.5 GB/s (the GRS die-to-die link).
