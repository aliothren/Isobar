"""S6 day 11 (C64-f): the referee family -- four arms on the ordering
instance, [AMENDED 12] inherited exactly (spec section 7).

  E0  truth: mu-weighted busiest-wire volume over the declared pattern
      mix mu = {chain 0.5, fanout 0.5} (day-7 line-load machinery per
      pattern; equal demonstration weights, declared, swappable).
  E1  the Hu-Marculescu distance proxy, faithful form: sum over the
      same mu-weighted pair set of V x Manhattan(stage centroids).
      Citation: Hu & Marculescu, "Energy-aware mapping for tile-based
      NoC architectures under performance constraints" (ASP-DAC 2003)
      -- the canonical comm x distance objective; C58 gives its
      validity domain (price proportional to length AND no contention
      axis; THIS instance has a contention axis, which is the point).
  E2  one-hot mu on CHAIN (the declared wrong-phase arm: the
      chain-optimal end is compact = the fanout-worst end).
  E3  E0's mix computed under the WRONG WEAVE = ring (O19 pool; bus
      declined -- its shared-medium busiest resource is seat-invariant,
      a flat arm cannot choose).

Arm isolation: the four evaluators share no tunable constants; V and
the pair set are the LOAD's declaration, not knobs. Runs are day 12;
this module ships the arms + the probe helpers.
"""
import os
import sys
from typing import Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dataclasses as dc

from scripts import check_c_crosstraffic as cx
from scripts import search_eval as se
from scripts import search_ordering as so

MU = {"chain": 0.5, "fanout": 0.5}          # the declared demonstration mix


def host_ring():
    """The 2.7B host at nominal 1 word/cycle with the die weave swapped
    to ring (the E3 condition; the weave is a condition, not a
    variable)."""
    W = se.Workload2p7B(die_weave=("ring", {}))
    levels = [dc.replace(l, link=dc.replace(l.link,
                                            bandwidth_words_per_cycle=1.0))
              if l.name == "die" else l for l in W.fab.levels]
    W.fab = dc.replace(W.fab, name="xtraffic-ring", levels=levels).validate()
    return W


class MixJ:
    """mu-weighted busiest-wire volume over the two declared patterns
    (each pattern its own line-load structure; both diff-driven)."""

    def __init__(self, W, mu: Dict[str, float] = None):
        self.mu = dict(mu or MU)
        self.legs = {}
        if self.mu.get("chain"):
            self.legs["chain"] = so.CrossTrafficJ(W, so.pairs_chain())
        if self.mu.get("fanout"):
            self.legs["fanout"] = so.CrossTrafficJ(W, so.pairs_fanout())

    def __call__(self, pi) -> float:
        return sum(w * self.legs[p](pi) for p, w in self.mu.items() if w)


def make_E0(W=None):
    return MixJ(W or cx.host(), MU)


def make_E2(W=None):
    return MixJ(W or cx.host(), {"chain": 1.0})


def make_E2b(W=None):
    """The fan-out one-hot arm (day-11 review): with BOTH one-hot
    directions run, "single-condition tuning does not transfer" is
    claimed in both directions, not a chosen one."""
    return MixJ(W or cx.host(), {"fanout": 1.0})


def make_E3():
    return MixJ(host_ring(), MU)


class DistanceProxyJ:
    """E1: the spec's literal form Sigma_e v_e x dist(e) -- every
    producer-die -> consumer-die flow of the SAME mu-weighted pair set
    as E0, priced at piece x Manhattan(a, b): total word-hops, price
    proportional to length, NO contention term (that absence IS the
    arm; C58's validity-domain statement). NOTE: a first draft priced
    stage-CENTROID distances instead -- gate R4 caught it collapsing
    under dispersion (a spread set's centroid sits mid-grid), a
    mis-implementation of Sigma_e v_e dist(e); replaced by the per-flow
    form BEFORE any arm ran (recorded in FIXLIST)."""

    def __init__(self, W, mu: Dict[str, float] = None):
        self.mu = dict(mu or MU)
        from scripts import placement as pm
        self.slots = pm.sequential_fill(W.fab).slots["die"]
        self.pairs = {"chain": so.pairs_chain(), "fanout": so.pairs_fanout()}

    def _pair_wordhops(self, A, B):
        piece = so.V / len(A)
        d = 0.0
        for a in A:
            xa, ya = self.slots[a]
            for b in B:
                xb, yb = self.slots[b]
                d += abs(xa - xb) + abs(ya - yb)
        return piece * d

    def __call__(self, pi) -> float:
        sets = cx.stage_sets(pi)
        tot = 0.0
        for pat, w in self.mu.items():
            if not w:
                continue
            for s, t in self.pairs[pat]:
                if s not in sets or t not in sets:
                    continue                # smaller probe instances
                tot += w * self._pair_wordhops(sets[s], sets[t])
        return tot


def make_E1(W=None):
    return DistanceProxyJ(W or cx.host(), MU)


ARMS = ("E0", "E1", "E2", "E2b", "E3")


def make_arm(name: str):
    return {"E0": make_E0, "E1": make_E1, "E2": make_E2,
            "E2b": make_E2b, "E3": make_E3}[name]()
