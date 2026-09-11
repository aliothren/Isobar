# Writing-materials library

Measured instances registered for the paper's argument, each with its
generator script and figure. Entries are CONDITION-BOUND exhibits — the
claim each carries is stated with the condition attached, never as a
bare constant. (Opened at C64-c per the ladder-v0 review; the report
red-lines apply: entries carry results and mechanisms, no test history
or internal numbering in any outward use.)

## The condition-bound flip: one seating, best-to-worst under a traffic change

The SAME clustered seating (literal rectangle tiling, 32 stages × 17
dies on the 24×24 grid) is the BEST of the seven named baselines on the
busiest die wire under pure-chain traffic (6.2M words; wide rectangle
borders disperse the single hand-off) and the WORST under many-to-many
fan-out traffic, every stage an equal volume to stages +2/+4/+8 (30.0M
words vs snake 28.0M, sequential 22.2M, random 18.3M; the mid-grid seam
between rectangle columns saturates uniformly, five wires at 30.0M
each). The ordering across seatings INVERTS with the pattern: compact
wins the chain, dispersed wins the cross-traffic.

Use: (a) S6 evidence material — distance/compactness proxy objectives
(E1 family) rank correctly under one traffic pattern and invert under
another; an objective's validity domain is condition-bound
(SEARCH_SPEC §7 [AMENDED 11]). (b) The literature tie-in: the same
sentence of the clustered baseline's source paper both defines the
strategy and predicts this failure mode, and the measurement reproduces
both halves on cue (excerpt in `baseline_traces.md`).

Generator: `scripts/check_c_crosstraffic.py`. Figure:
`analysis/check_c_crosstraffic.png`.
