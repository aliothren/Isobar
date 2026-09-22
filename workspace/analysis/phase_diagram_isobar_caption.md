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
filled) MVM latencies; ISAAC at its own published inter-tile link figure,
"a 32-bit link operating at 1 GHz" (Sec. VIII-B) = 4.0 GB/s, sized there
from a benchmark requirement the paper estimates never exceeds 3.2 GB/s,
with the c-mesh flit width also 32 bits. One of our macro links is a
coarser resource than one HERMES physical link; these are reference
points, not operating points.

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
latency at one and 0.24% at the other. ISAAC's off-chip link IS published, in
Table I ("Hyper Tr links/freq 4/1.6GHz, link bw 6.4 GB/s", the
HyperTransport model taken from DaDianNao), so it is a point here at
6.4 GB/s per link and direction; that link is chip-to-chip on a board
rather than in-package die-to-die, and at ISAAC's row rate it sits just
above B₊. Mythic M1076 publishes no link rate; its hollow diamond is a
projection (2026-09-21): the product page's PCIe I/O capability of
2 GB/s matched to the model's port capacity, κB = B_IO, so B = 1.0 GB/s
at κ = 2, inside the band near B₋. The two evaluated bandwidths, 0.4 and
12.5 GB/s, are drawn as muted horizontal tiers across device speeds with
a "reference bandwidth span" bracket outside the frame, because they are
bandwidth tiers and not a NeuRRAM property; the two circles at the
NeuRRAM row rate, joined by a vertical line, are the two configurations
evaluated in this paper. Legend semantics: filled diamond = published
parameter projected onto this instance; hollow diamond = derived or
alternative-mode value projected the same way (HERMES 4-phase MVM,
M1076 I/O-matched); circle = configuration evaluated here.

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

## κ = 2 variant (`phase_diagram_isobar_k2.png`, `_print_k2.png`) — the paper's main configuration

Identical construction with the package panel's ports at **twice the link
rate** (κ = C_port / C_link = 2; injection and ejection independent). Only
the package panel changes: the seven-rule envelope widens to **2.66×**
(κ = 1: 2.37×) because the port cap had been holding the dispersed rules'
busiest-resource load at the port floor; B₋ / B₊ move to 0.535 / 1.421 GB/s
at the NeuRRAM rate (κ = 1: 0.603 / 1.427). The two evaluated
configurations keep their regions: 0.4 GB/s below B₋, 12.5 above B₊. The
intra-die panel does not read κ and is unchanged (2.67×). Envelope arrows
and contours are computed from the same seven rules; the search endpoints
of the main experiment lie inside the band's lower edge and are not used
to draw it.

## Correction to panel (a) (2026-09-17, F-FIG1a)

Panel (a)'s cost model is per-op: t = write + prop + max(compute,
serialization/B), so its boundaries are the **masking thresholds against
each op's own compute** (5.19 ms at the NeuRRAM rate): B₋ = A_min/c =
0.606 GB/s, B₊ = A_max/c = 1.616 GB/s (an earlier draft divided by the
two ops' summed compute and drew them at half these values). The 20%
contour is the max-model spread (T_max − T_min)/T_min over the 70
seatings, solved numerically (1.154 GB/s at the reference rate); it
reaches zero at B₊, where every seating is masked. The 2.67× envelope
is unchanged. At the A3 work point 0.4 GB/s the panel reads "below B₋":
every seating has an exposed op and the seating sets how severe, which
is what the per-op table of the A3 case shows; at ≥ 2 GB/s it reads
"above B₊", matching the measured zero gain.

**In-figure region labels (2026-09-18).** The two panels carry different
wording because they carry different execution models. Panel (b) is a
serial sum, so its regions say which cost *dominates*: "compute /
fixed-cost dominated", "placement decides which dominates",
"communication dominated (placement sets how severe)". Panel (a) is a
per-op max, so its regions say whether communication is *exposed*:
"communication masked" above B₊, "placement decides what is exposed" in
the band, "communication exposed (placement sets how severe)" below B₋. Below B₋ on panel (a) the
guarantee is that every seating has at least one exposed op, which is
not the same as the die's total latency being communication dominated.
The print version uses the short forms "communication masked" /
"placement decides" / "communication exposed".


**ISAAC source correction (2026-09-18).** An earlier version of this
figure put ISAAC on panel (a) at 4.8 GB/s, from "32-bit flit per 1.2 GHz
cycle"; 1.2 GHz is the ISAAC TILE clock (Table I header, "ISAAC Tile at
1.2 GHz"), not the link clock. The paper states the link itself: "we
estimate that the inter-tile link bandwidth requirement never exceeds
3.2 GB/s. We therefore conservatively assume a 32-bit link operating at
1 GHz" (Sec. VIII-B) = 4.0 GB/s, and Table I lists the off-chip link at
6.4 GB/s. Both panels now use those figures. The reading does not change
on panel (a): at ISAAC's row rate the band is 3.90 to 10.40 GB/s, so 4.0
and 4.8 are both inside it. On panel (b) the reading does change: an
assumed range that spanned the band (1.94 to 5.14 GB/s at that rate)
becomes a published point above it.