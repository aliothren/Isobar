"""Interconnect schemes: HOW data physically travels, as a selectable input.

The fabric config says what the levels are and how many instances each has;
a Placement says which instance sits in which slot. Neither says how a word
actually gets from one to another -- whether it has a private wire, shares a
bus, is routed across a mesh, or climbs a tree. That is the SCHEME, and on a
platform meant to retarget across designs it has to be an input, not a
hardcoded assumption. It is selected per level in models/fabric/*.yaml:

    link: {topology: mesh, params: {routing: xy, multicast: replicated}, ...}

Every scheme answers exactly three questions, and all three cost paths
(propagation latency, distance energy, contention) derive from them:

    hops(a, b)   -> distance in the level's OWN SLOT units
    path(a, b)   -> the shared resources a flow occupies (contention)
    resources()  -> those resources' ids

Units. A scheme works in slot units (the level's own grid). The propagation
term multiplies by fabric.pitch(level) to reach global leaf-grid units; the
energy term uses mean hops directly. Both reproduce the pre-W2 constants
exactly for `star` -- see tests/test_interconnect.py.

Nodes are indexed 0..N-1; HUB is the parent's aggregation point. The interface
takes (a, b) rather than assuming hub-centric traffic because inter-die
hand-offs are node-to-node, so D2D reuses this unchanged.

Naming: the switch-style network is called `switch`, never "crossbar" -- in
this project a crossbar is always the ReRAM array.
"""
from typing import Dict, List, Optional, Sequence, Tuple

HUB = -1
Slot = Tuple[float, float]


def _manh(a: Slot, b: Slot) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class Interconnect:
    """Base class. Subclasses declare PARAMS and implement hops/path."""

    NAME: str = "base"
    #: param name -> (required?, description). Anything else is rejected.
    PARAMS: Dict[str, Tuple[bool, str]] = {}
    #: Physical default: point-to-point links are FULL-DUPLEX -- one wire set
    #: per direction, so up- and down-traffic never share bandwidth (every
    #: published anchor in ANCHORS.md is quoted per link, ONE direction). A
    #: shared medium (bus) is half-duplex. Overridable per link via the
    #: common param `duplex` (O22).
    DUPLEX: bool = True

    def __init__(self, slots: Sequence[Slot], params: Optional[dict] = None):
        self.slots = [tuple(map(float, s)) for s in slots]
        self.params = dict(params or {})
        validate_params(self.NAME, self.params, where=self.NAME)
        self._setup()

    # ----------------------------------------------------------- overridable
    def _setup(self) -> None:
        pass

    def coord(self, node: int) -> Slot:
        return self.hub_coord() if node == HUB else self.slots[node]

    def hub_coord(self) -> Slot:
        """Where the aggregation point sits. Default: the centroid of the nodes
        (a virtual point -- fine for schemes that do not route through a node)."""
        n = len(self.slots)
        return (sum(s[0] for s in self.slots) / n,
                sum(s[1] for s in self.slots) / n)

    def hops(self, a: int, b: int) -> float:
        raise NotImplementedError

    def path(self, a: int, b: int) -> List[str]:
        raise NotImplementedError

    @property
    def duplex(self) -> bool:
        return bool(self.params.get("duplex", self.DUPLEX))

    def path_directed(self, a: int, b: int) -> List[Tuple[str, str]]:
        """path() with a DIRECTION tag per resource, so a full-duplex link
        can keep the two directions apart. Tree-like default: every
        resource of a hub->node route is "dn"; the node->hub route RETRACES
        it with the tags flipped ("up") -- the reduction tree mirrors the
        distribution tree, so both directions of one op meet on the same
        wires (this is what keeps the pre-O22 accounting exactly
        reproducible with duplex=False; routing-algorithm asymmetries such
        as XY-vs-YX replies belong to O19). A node-to-node route climbs
        a's side ("up") and descends b's side ("dn"). Schemes with oriented
        segments (mesh) override. Empty tag = no direction (shared medium)."""
        if a == HUB:
            return [(r, "dn") for r in self.path(a, b)]
        if b == HUB:
            return reverse_directed(self.path_directed(HUB, a))
        up = set(self.path(a, HUB))
        return ([(r, "up") for r in self.path(a, HUB)]
                + [(r, "dn") for r in self.path(HUB, b) if r not in up])

    def resources(self) -> List[str]:
        seen = []
        for i in range(len(self.slots)):
            for r in self.path(HUB, i):
                if r not in seen:
                    seen.append(r)
        return seen

    def router_hops(self, a: int, b: int) -> float:
        """The ROUTER-CROSSING COUNT of one transfer (C60, review clause 1:
        what per-router packet constants consume). Default: identical to
        hops() -- on every unfolded point-to-point scheme count and length
        coincide. A folded scheme (torus, ring) overrides: a wrap route
        crosses 1 router over 2 slot pitches of wire, and quietly reading
        the folded length as a router count would be the silent caliber
        mismatch this accessor exists to prevent."""
        return self.hops(a, b)

    def energy_hops(self, a: int, b: int) -> float:
        """The ENERGY-side wire length of one transfer, in slot units (C59/O8).

        Default: identical to hops() -- for point-to-point schemes (star,
        mesh) the wire actually driven IS the route, so the two sides share
        one number and every pre-C59 account is reproduced bit for bit.
        Schemes where the driven wire is not the route override: a bus swings
        the WHOLE line's capacitance per transfer regardless of endpoints, a
        physical H-tree's wires lengthen toward the root. Latency and
        contention keep reading hops(); only energy pricing reads this."""
        return self.hops(a, b)

    # ----------------------------------------------------------- aggregates
    def max_hops(self) -> float:
        """Worst-case hub->node distance: the parallel branches' critical path."""
        return max((self.hops(HUB, i) for i in range(len(self.slots))), default=0.0)

    def mean_hops(self) -> float:
        """Mean hub->node distance (the LATENCY-side statistic; until C59 the
        energy re-pricing also read this -- it now reads mean_energy_hops)."""
        n = len(self.slots)
        return sum(self.hops(HUB, i) for i in range(n)) / n if n else 0.0

    def mean_energy_hops(self) -> float:
        """Mean hub->node ENERGY wire length: what the re-pricing scales by
        since C59 (equal to mean_hops for every point-to-point scheme)."""
        n = len(self.slots)
        return sum(self.energy_hops(HUB, i) for i in range(n)) / n if n else 0.0


# --------------------------------------------------------------------------- #
class Star(Interconnect):
    """Private link per node to a hub at the centroid -- the pre-W2 model.

    Physically this is an idealized switch with unlimited internal bandwidth:
    no two flows ever share a resource, so it is the LOWER BOUND on contention
    and the natural default (adding it changes nothing).
    """

    NAME = "star"
    PARAMS = {}

    def hops(self, a: int, b: int) -> float:
        """hub<->node: the private link. node<->node: THROUGH the hub switch
        (a star has no direct wires between nodes), so the two link lengths
        sum. First consumer: die-to-die traffic under a central-switch D2D."""
        if a == HUB or b == HUB or a == b:
            return _manh(self.coord(a), self.coord(b))
        return (_manh(self.coord(a), self.hub_coord())
                + _manh(self.hub_coord(), self.coord(b)))

    def path(self, a: int, b: int) -> List[str]:
        if a != HUB and b != HUB and a != b:      # via the hub: both links busy
            return [f"{self.NAME}:link{a}", f"{self.NAME}:link{b}"]
        node = b if a == HUB else a
        return [f"{self.NAME}:link{node}"]


# --------------------------------------------------------------------------- #
class Mesh(Interconnect):
    """2-D grid of routers with deterministic dimension-order routing.

    This is the scheme that finally couples PLACEMENT to CONTENTION: a flow to a
    distant node traverses intermediate SEGMENTS, and segments near the hub are
    crossed by many flows at once, so where a node sits decides which wire it
    congests. (With `star` every node has a private wire and permuting a
    placement provably changes nothing -- see tests/test_contention_scope.py.)

    Segments are FULL-DUPLEX since O22: path_directed() tags each traversal
    "+"/"-" and link_occupancy keys resources per direction (the physical
    two-wires-per-segment norm; `duplex=False` reproduces the pre-O22 shared
    account and survives only as an explicit comparison knob in tests).
    [C63-a: this docstring previously still claimed undirected segments --
    the stale sentence that misled the O19 batch plan's duplex item.]

    A node co-located with the hub traverses no segment at all, which is the
    right answer and is why `hub` placement is a real modelling choice.
    """

    NAME = "mesh"
    PARAMS = {
        "routing": (False, "xy (default) | yx -- dimension order; o1turn = "
                           "the balanced-order model, DECLARED as the parity "
                           "rule (even-indexed sources route XY, odd YX; the "
                           "50/50-split oracle needs fractional paths this "
                           "interface does not carry -- C63-f)"),
        "hub": (False, "center (default) | corner | node:<i> -- where the "
                       "parent's aggregation point attaches"),
        "multicast": (False, "native (a shared slice crosses a segment once, "
                             "default) | replicated (unicast NoC: once per "
                             "destination)"),
        "reply": (False, "retrace (default: node->hub retraces the down "
                         "route) | yx: replies ride the OPPOSITE dimension "
                         "order -- the common real-NoC form; up load lands "
                         "on segments the down route never uses (C63-f; "
                         "the asymmetry noted since O22, now a knob)"),
    }

    def _setup(self):
        self.routing = self.params.get("routing", "xy")
        if self.routing not in ("xy", "yx", "o1turn"):
            raise ValueError(f"mesh: routing must be xy, yx or o1turn, "
                             f"got {self.routing}")
        self.reply = self.params.get("reply", "retrace")
        if self.reply not in ("retrace", "yx"):
            raise ValueError(f"mesh: reply must be retrace or yx, "
                             f"got {self.reply}")
        self.multicast = self.params.get("multicast", "native")
        if self.multicast not in ("native", "replicated"):
            raise ValueError(f"mesh: multicast must be native or replicated")
        self._hub = self._resolve_hub(self.params.get("hub", "center"))

    def _resolve_hub(self, spec) -> Slot:
        if isinstance(spec, str) and spec.startswith("node:"):
            return self.slots[int(spec.split(":", 1)[1])]
        if spec == "corner":
            return (min(s[0] for s in self.slots), min(s[1] for s in self.slots))
        if spec != "center":
            raise ValueError(f"mesh: unknown hub spec '{spec}'")
        # snap the centroid to the nearest grid point -- a router sits on the
        # grid, unlike star's virtual centroid
        cx = sum(s[0] for s in self.slots) / len(self.slots)
        cy = sum(s[1] for s in self.slots) / len(self.slots)
        return (float(round(cx)), float(round(cy)))

    def hub_coord(self) -> Slot:
        return self._hub

    def hops(self, a: int, b: int) -> float:
        return _manh(self.coord(a), self.coord(b))

    def _order_for(self, src_node) -> str:
        """The dimension order one flow uses. o1turn (C63-f): the declared
        parity rule -- even-indexed sources XY, odd YX (HUB counts even)."""
        if self.routing != "o1turn":
            return self.routing
        return "xy" if (src_node is None or src_node == HUB
                        or int(src_node) % 2 == 0) else "yx"

    def _route(self, src: Slot, dst: Slot, order_kind: str = None) -> List[Slot]:
        """Grid points visited, dimension-order."""
        kind = order_kind or (self.routing if self.routing != "o1turn"
                              else "xy")
        x0, y0 = int(round(src[0])), int(round(src[1]))
        x1, y1 = int(round(dst[0])), int(round(dst[1]))
        pts = [(x0, y0)]
        order = ((x1, "x"), (y1, "y")) if kind == "xy" \
            else ((y1, "y"), (x1, "x"))
        cx, cy = x0, y0
        for target, axis in order:
            step = 1 if target > (cx if axis == "x" else cy) else -1
            while (cx if axis == "x" else cy) != target:
                if axis == "x":
                    cx += step
                else:
                    cy += step
                pts.append((cx, cy))
        return pts

    def path(self, a: int, b: int) -> List[str]:
        return [r for r, _ in self.path_directed(a, b)]

    def path_directed(self, a: int, b: int) -> List[Tuple[str, str]]:
        """Segments are canonical (lo-hi); the tag records which way this
        route traverses each: "+" = lo->hi, "-" = hi->lo. Opposite-direction
        traffic on a full-duplex segment occupies different wires. A
        node->hub route retraces the hub->node route by default; with
        reply="yx" it rides the opposite dimension order instead (C63-f)."""
        if b == HUB and a != HUB:
            if self.reply == "retrace":
                return reverse_directed(self.path_directed(HUB, a))
            base = self._order_for(a)
            up_kind = "yx" if base == "xy" else "xy"
            pts = self._route(self.coord(a), self.coord(b), up_kind)
            out = []
            for p, q in zip(pts, pts[1:]):
                lo, hi = sorted((p, q))
                out.append((f"{self.NAME}:seg{lo}-{hi}",
                            "+" if p == lo else "-"))
            return out
        pts = self._route(self.coord(a), self.coord(b),
                          self._order_for(a if a != HUB else b))
        out = []
        for p, q in zip(pts, pts[1:]):
            lo, hi = sorted((p, q))
            out.append((f"{self.NAME}:seg{lo}-{hi}", "+" if p == lo else "-"))
        return out

    def resources(self) -> List[str]:
        seen = []
        for i in range(len(self.slots)):
            for r in self.path(HUB, i):
                if r not in seen:
                    seen.append(r)
        return seen


# --------------------------------------------------------------------------- #
class Torus(Mesh):
    """Wrap-around mesh, FOLDED by default (C60 / A7 ruling 4).

    The wrap link is not a free equal-length wire in 2D packaging: the
    standard build FOLDS the torus, and the price is that EVERY hop on a
    folded axis is 2 slot pitches of physical wire. Hence the split the
    folded torus forces for the first time (review clause 1):

      * hops(a, b)        -> PHYSICAL length in slot units (per axis
                             min(direct, wrap) x the axis fold factor) --
                             what the ns_per_mm latency chain and the C58
                             price-per-length energy machinery consume.
      * router_hops(a, b) -> the CROSSING COUNT (per axis min(direct,
                             wrap)) -- what per-router packet constants
                             consume. On every unfolded point-to-point
                             scheme the two coincide.

    An axis of width <= 2 gets no wrap links and no folding: the torus
    degenerates to the mesh there (on the 2x4 macro grid the payoff axis
    is the 4-wide one). `idealized: true` builds equal-length wrap links
    (fold factor 1) and is labeled what it is -- an idealization.
    """

    NAME = "torus"
    PARAMS = {**Mesh.PARAMS,
              "idealized": (False, "true = equal-length wrap links (fold "
                                   "factor 1, an IDEALIZATION); default "
                                   "false = folded, per-axis link length 2")}

    def _setup(self):
        super()._setup()
        self.idealized = bool(self.params.get("idealized", False))
        xs = [int(round(s[0])) for s in self.slots]
        ys = [int(round(s[1])) for s in self.slots]
        self._lo = (min(xs), min(ys))
        self._w = (max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)
        self._wraps = tuple(w >= 3 for w in self._w)
        self._fold = tuple((2.0 if (wr and not self.idealized) else 1.0)
                           for wr in self._wraps)

    def _axis_count(self, axis: int, c0: int, c1: int) -> float:
        d = abs(c0 - c1)
        if self._wraps[axis]:
            d = min(d, self._w[axis] - d)
        return float(d)

    def router_hops(self, a: int, b: int) -> float:
        (x0, y0), (x1, y1) = self.coord(a), self.coord(b)
        return (self._axis_count(0, int(round(x0)), int(round(x1)))
                + self._axis_count(1, int(round(y0)), int(round(y1))))

    def hops(self, a: int, b: int) -> float:
        (x0, y0), (x1, y1) = self.coord(a), self.coord(b)
        return (self._axis_count(0, int(round(x0)), int(round(x1))) * self._fold[0]
                + self._axis_count(1, int(round(y0)), int(round(y1))) * self._fold[1])

    def _route(self, src: Slot, dst: Slot, order_kind: str = None) -> List[Slot]:
        """Dimension-order route with a per-axis wrap decision; the wrap
        jump appears as one step from the edge slot to the opposite edge.
        order_kind (C63-f): the caller's dimension order (reply/o1turn)."""
        kind = order_kind or (self.routing if self.routing != "o1turn"
                              else "xy")
        pts = [(int(round(src[0])), int(round(src[1])))]
        cx, cy = pts[0]
        tx, ty = int(round(dst[0])), int(round(dst[1]))
        order = ((0, tx), (1, ty)) if kind == "xy" else ((1, ty), (0, tx))
        for axis, target in order:
            cur = cx if axis == 0 else cy
            w, lo = self._w[axis], self._lo[axis]
            d = abs(cur - target)
            direct = (not self._wraps[axis]) or d <= w - d
            step = (1 if target > cur else -1) if direct \
                else (-1 if target > cur else 1)
            while cur != target:
                cur = lo + (cur - lo + step) % w
                if axis == 0:
                    cx = cur
                else:
                    cy = cur
                pts.append((cx, cy))
        return pts


class Ring(Interconnect):
    """The 1D cycle over the placement order, FOLDED by default (C60).

    The die level's natural scheme for a neighbor-dominated pipeline: a
    stage talks to the next stage over one cycle edge. Folded build:
    every link is 2 slot pitches (uniform), so hops() returns 2x the
    crossing count and router_hops() the count itself; `idealized: true`
    keeps 1-pitch links. The hub (the package attach point) sits at a
    node (`hub: node:<i>`, default node 0)."""

    NAME = "ring"
    PARAMS = {"hub": (False, "node:<i> -- the attach node (default node 0)"),
              "idealized": (False, "true = 1-pitch links (an IDEALIZATION); "
                                   "default false = folded, every link 2")}

    def _setup(self):
        self.n = len(self.slots)
        self.idealized = bool(self.params.get("idealized", False))
        self._fold = 1.0 if self.idealized else 2.0
        spec = self.params.get("hub", "node:0")
        if not (isinstance(spec, str) and spec.startswith("node:")):
            raise ValueError(f"ring: hub must be node:<i>, got '{spec}'")
        self._hub_i = int(spec.split(":", 1)[1])

    def hub_coord(self) -> Slot:
        return self.slots[self._hub_i]

    def _idx(self, node: int) -> int:
        return self._hub_i if node == HUB else node

    def router_hops(self, a: int, b: int) -> float:
        d = abs(self._idx(a) - self._idx(b))
        return float(min(d, self.n - d))

    def hops(self, a: int, b: int) -> float:
        return self.router_hops(a, b) * self._fold

    def path_directed(self, a: int, b: int) -> List[Tuple[str, str]]:
        i, j = self._idx(a), self._idx(b)
        if i == j:
            return []
        d = (j - i) % self.n
        step = 1 if d <= self.n - d else -1          # shorter arc; tie -> "+"
        out, cur = [], i
        while cur != j:
            nxt = (cur + step) % self.n
            edge = cur if step == 1 else nxt          # edge k = k -> k+1
            out.append((f"{self.NAME}:seg{edge}", "+" if step == 1 else "-"))
            cur = nxt
        return out

    def path(self, a: int, b: int) -> List[str]:
        return [r for r, _ in self.path_directed(a, b)]

    def resources(self) -> List[str]:
        return [f"{self.NAME}:seg{k}" for k in range(self.n)]


# --------------------------------------------------------------------------- #
class HTree(Interconnect):
    """k-ary tree rooted at the hub -- the classic CIM distribution network
    (ISAAC, NeuroSim's default) and the topology the collaborator's lambda-1
    reduction metric is the correct cost model for.

    Two things follow from the structure and neither has an analogue in `mesh`:

    * The ROOT edge is crossed by every flow, so it is the bottleneck by
      construction -- congestion here is about tree DEPTH and grouping, not
      Euclidean distance.
    * "Position" means WHICH SUBTREE a node is in. Two nodes under one parent
      talk over a single short edge; across parents they climb. That is why the
      placement OBJECTIVE differs by scheme: a mesh wants proximity, a tree
      wants shared parentage.

    `lambda_minus_1()` exposes the hypergraph connectivity metric directly: for
    a set of nodes (a reduction group), the number of merges needed at each
    depth is (distinct parents - 1). Multiply by per-depth weights to get the
    collaborator's Red(e).

    Leaves are assigned in slot order, so a Placement decides the grouping.
    """

    NAME = "h_tree"
    PARAMS = {
        "branching": (True, "k: children per internal node"),
        "level_length": (False, "per-depth wire length, root-first; defaults to "
                                "1 per level (a physical H-tree lengthens "
                                "toward the root, e.g. [4, 2, 1])"),
    }

    def _setup(self):
        self.k = int(self.params["branching"])
        if self.k < 2:
            raise ValueError("h_tree: branching must be >= 2")
        n = len(self.slots)
        self.depth = 1
        while self.k ** self.depth < n:
            self.depth += 1
        lens = self.params.get("level_length")
        self.level_length = ([float(x) for x in lens] if lens
                             else [1.0] * self.depth)
        if len(self.level_length) != self.depth:
            raise ValueError(f"h_tree: level_length needs {self.depth} entries "
                             f"for {n} nodes at branching {self.k}")

    def parent_at(self, node: int, depth: int) -> int:
        """Index of the ancestor `depth` levels below the root (depth 0 = root)."""
        return node // (self.k ** (self.depth - depth))

    def hops(self, a: int, b: int) -> float:
        """Levels climbed to the lowest common ancestor and back down."""
        if a == b:
            return 0.0
        if a == HUB or b == HUB:
            return sum(self.level_length)
        d = self.depth
        while d > 0 and self.parent_at(a, d - 1) != self.parent_at(b, d - 1):
            d -= 1
        climbed = self.depth - d
        return 2.0 * sum(self.level_length[self.depth - climbed:])

    def physical_level_length(self) -> List[float]:
        """C59 (O8): the ENERGY-side per-level wire lengths, root-first, in
        slot units. RULE: each branching step halves the subtree's linear
        span, and the wire length follows the span -- level l = extent /
        2**l, extent = the larger grid dimension of this level's slots. For
        the shipped lambda-1 host (macro 2x4, k=4, depth 2) this yields
        [2.0, 1.0], registered as LITERALS in
        anchors.HTREE_MACRO_LEVEL_LENGTH_SLOTS (ruling: the collaborator's
        solver must read the same table, no embedded formula); a test
        asserts rule == literals. The latency-side level_length is
        untouched (O8 ruled the latency side right)."""
        xs = [s[0] for s in self.slots]
        ys = [s[1] for s in self.slots]
        extent = max(max(xs) - min(xs) + 1.0, max(ys) - min(ys) + 1.0)
        return [extent / (2.0 ** level) for level in range(1, self.depth + 1)]

    def energy_hops(self, a: int, b: int) -> float:
        """hops() arithmetic over the PHYSICAL per-level lengths (C59)."""
        phys = self.physical_level_length()
        if a == b:
            return 0.0
        if a == HUB or b == HUB:
            return sum(phys)
        d = self.depth
        while d > 0 and self.parent_at(a, d - 1) != self.parent_at(b, d - 1):
            d -= 1
        climbed = self.depth - d
        return 2.0 * sum(phys[self.depth - climbed:])

    def path(self, a: int, b: int) -> List[str]:
        node = b if a == HUB else a
        if a != HUB and b != HUB:                 # node-to-node: up then down
            return sorted(set(self.path(HUB, a)) ^ set(self.path(HUB, b)))
        return [f"{self.NAME}:d{d}g{self.parent_at(node, d)}"
                for d in range(1, self.depth + 1)]

    def merges_by_depth(self, nodes: Sequence[int]) -> Dict[int, int]:
        """The (lambda-1) connectivity metric, decomposed by depth.

        lambda_d = distinct containers the node set touches at depth d
        (lambda_0 = 1, the root; lambda_depth = |nodes|, the leaves). Merging m
        partial sums takes m-1 merges in total; this splits them by the
        COARSEST boundary each one crosses:

            merges[d] = lambda_d - lambda_{d-1},   sum(merges) = |nodes| - 1

        which is exactly the collaborator's nested decomposition
        (pure_core = xcore - xmacro, ...) -- each merge is charged once, at its
        outermost boundary. A node set living inside one container costs 0 at
        every depth above it: the local reduction never leaves.

        The caller applies the weights, including 0 for any level where the
        reduction is free (an analog bitline sum inside a crossbar, a local
        shift-add inside a core).
        """
        out, prev = {}, 1
        for d in range(1, self.depth + 1):
            lam = len({self.parent_at(n, d) for n in nodes})
            out[d] = lam - prev
            prev = lam
        return out


# --------------------------------------------------------------------------- #
class Bus(Interconnect):
    """One shared medium every node taps -- the opposite extreme from `star`.

    Contention is maximal: every flow occupies the same resource, so the bus
    serializes the WHOLE level's traffic regardless of who sits where. Distance
    still matters, but only for energy/latency per transfer (wire length to the
    driver), never for contention. Cheapest in area, worst in throughput.
    """

    NAME = "bus"
    PARAMS = {"driver": (False, "center (default) | corner | node:<i> -- where "
                                "the bus is driven from")}

    def _setup(self):
        spec = self.params.get("driver", "center")
        if isinstance(spec, str) and spec.startswith("node:"):
            self._drv = self.slots[int(spec.split(":", 1)[1])]
        elif spec == "corner":
            self._drv = (min(s[0] for s in self.slots),
                         min(s[1] for s in self.slots))
        elif spec == "center":
            n = len(self.slots)
            self._drv = (sum(s[0] for s in self.slots) / n,
                         sum(s[1] for s in self.slots) / n)
        else:
            raise ValueError(f"bus: unknown driver spec '{spec}'")

    def hub_coord(self) -> Slot:
        return self._drv

    DUPLEX = False                              # one shared medium

    def hops(self, a: int, b: int) -> float:
        return _manh(self.coord(a), self.coord(b))

    def energy_hops(self, a: int, b: int) -> float:
        """C59 (O8): every transfer swings the WHOLE line's capacitance, so
        the energy length is the full line -- the SERPENTINE model (ruling:
        a line threading all N slots is (N-1) slot pitches; the physically
        natural routing of a shared line over a grid, and deliberately the
        model HARSHER on bus than the bounding-box alternative). Endpoints
        and driver position are energy-irrelevant; both stay latency- and
        contention-relevant through hops()/path(). A replaceable example
        model: the real layout's line length swaps this constant."""
        return float(max(len(self.slots) - 1, 0))

    def path(self, a: int, b: int) -> List[str]:
        return [f"{self.NAME}:medium"]

    def path_directed(self, a: int, b: int) -> List[Tuple[str, str]]:
        return [(f"{self.NAME}:medium", "")]


# --------------------------------------------------------------------------- #
class CMesh(Mesh):
    """Concentrated mesh: k nodes share one router (C63-c, O19 item 3).

    The commercial NoC's common form -- router area is amortised over a
    tile of `concentration: [cx, cy]` nodes (k = cx x cy). Routers sit at
    tile centers; a flow crosses its PRIVATE access link (emitted only
    when the node is not co-located with its router center), rides the
    dimension-order route over the ROUTER grid -- the physical length of
    one router-grid step is the tile pitch (cx or cy slot units) -- and
    descends the destination's access link. `[1, 1]` degenerates to mesh
    exactly (pinned). The trade this weave prices: fewer routers, but k
    nodes FUNNEL into each -- the concentration factor the readout
    measures.
    """

    NAME = "cmesh"
    PARAMS = {**Mesh.PARAMS,
              "concentration": (False, "[cx, cy] router tile shape; "
                                       "[1, 1] degenerates to mesh")}

    def _setup(self):
        super()._setup()
        c = self.params.get("concentration", [1, 1])
        self.cx, self.cy = int(c[0]), int(c[1])
        if self.cx < 1 or self.cy < 1:
            raise ValueError("cmesh: concentration entries must be >= 1")

    def _router(self, coord: Slot) -> Tuple[int, int]:
        return (int(coord[0]) // self.cx, int(coord[1]) // self.cy)

    def _router_center(self, r: Tuple[int, int]) -> Slot:
        return (r[0] * self.cx + (self.cx - 1) / 2.0,
                r[1] * self.cy + (self.cy - 1) / 2.0)

    def _endpoint(self, node: int):
        """(router, access_distance). The HUB is ROUTER-RESIDENT (the GLB
        injects at its router directly, the mesh-consistent semantics), so
        it has no access link and no port share."""
        c = self.coord(node)
        r = self._router(c)
        if node == HUB:
            return r, 0.0
        return r, _manh(c, self._router_center(r))

    def hops(self, a: int, b: int) -> float:
        if a == b:
            return 0.0
        ra, da = self._endpoint(a)
        rb, db = self._endpoint(b)
        grid = (abs(ra[0] - rb[0]) * self.cx + abs(ra[1] - rb[1]) * self.cy)
        return da + grid + db

    def router_hops(self, a: int, b: int) -> float:
        """Router-grid CROSSINGS (C63-e addendum: item 3 left this
        un-overridden -- a backbone step crosses ONE router over a tile
        pitch of wire, so count != length; caught at hier_wide's contract
        time, the packet guard now lists cmesh too). Access wires cross
        no router."""
        if a == b:
            return 0.0
        ra, _ = self._endpoint(a)
        rb, _ = self._endpoint(b)
        return float(abs(ra[0] - rb[0]) + abs(ra[1] - rb[1]))

    def _attach(self, node: int, router, dist: float,
                side: str) -> List[Tuple[str, str]]:
        """A node's way onto its router: the PRIVATE access wire (when the
        node is off the router center) plus -- the concentration cost's
        actual carrier (C63-c amendment, filed BEFORE any readout ran) --
        the SHARED router LOCAL PORT: k tile nodes share one router's
        injection/ejection bandwidth, so the port resource is per tile and
        direction-tagged. Emitted for k > 1 (at k = 1 the tile is one node
        and mesh degeneration stays exact). The HUB attaches to no port."""
        out = []
        if node != HUB and dist > 0.0:
            out.append((f"{self.NAME}:acc{node}", side))
        if node != HUB and self.cx * self.cy > 1:
            out.append((f"{self.NAME}:rport{router}", side))
        return out

    def path_directed(self, a: int, b: int) -> List[Tuple[str, str]]:
        if a == b:
            return []
        ra, da = self._endpoint(a)
        rb, db = self._endpoint(b)
        out = self._attach(a, ra, da, "tx")
        cur = ra
        while cur != rb:
            step_axis = 0 if (self.routing == "xy" and cur[0] != rb[0]) \
                or (self.routing == "yx" and cur[1] == rb[1]) else 1
            nxt = list(cur)
            nxt[step_axis] += 1 if rb[step_axis] > cur[step_axis] else -1
            nxt = tuple(nxt)
            lo, hi = sorted((cur, nxt))
            out.append((f"{self.NAME}:seg{lo}-{hi}", "+" if cur == lo else "-"))
            cur = nxt
        out += self._attach(b, rb, db, "rx")
        return out

    def path(self, a: int, b: int) -> List[str]:
        return [r for r, _ in self.path_directed(a, b)]

    def resources(self) -> List[str]:
        seen = []
        for i in range(len(self.slots)):
            for r in self.path(HUB, i):
                if r not in seen:
                    seen.append(r)
        return seen


# --------------------------------------------------------------------------- #
class HierWide(CMesh):
    """FlooNoC-class hierarchical wide-link network (C63-e, O19 batch).

    CMesh topology below, a WIDE MULTI-CHANNEL BACKBONE above: FlooNoC's
    identity is multiple PHYSICAL channels rather than virtual ones, so
    each backbone segment carries `channels: W` parallel physical wires
    and a flow rides lane = (source node % W; HUB-sourced flows lane 0)
    -- deterministic and declared. The local tier is the cmesh attach
    (private access wire + the shared gateway port -- the concentration
    funnel a wide backbone cannot rescue, which is exactly what the
    fidelity readout measures). Degeneration chain: W = 1 == cmesh
    exactly; W = 1 and tile [1, 1] == mesh exactly. Wire price: cmesh's
    plus backbone x W (declared). The FlooNoC anchor bandwidth is PER
    PHYSICAL CHANNEL (declared caliber).
    """

    NAME = "hier_wide"
    PARAMS = {**CMesh.PARAMS,
              "channels": (False, "W physical channels per backbone "
                                  "segment (default 2); lane = source "
                                  "node %% W, HUB lane 0")}

    def _setup(self):
        super()._setup()
        self.channels = int(self.params.get("channels", 2))
        if self.channels < 1:
            raise ValueError("hier_wide: channels must be >= 1")

    def path_directed(self, a: int, b: int) -> List[Tuple[str, str]]:
        out = super().path_directed(a, b)
        if self.channels == 1:
            return out
        lane = 0 if a == HUB else int(a) % self.channels
        return [((r.replace(":seg", f":seg.c{lane}") if ":seg" in r else r),
                 t) for r, t in out]


# --------------------------------------------------------------------------- #
class Express(Mesh):
    """Mesh plus express links -- long shortcuts over the grid (C63-d).

    The uniform, station-free family (LOCKED in the pre-registration: no
    station-alignment degree of freedom): every row and column line
    carries an express link from every position c to c + s. An express
    link is s slot pitches of WIRE, so the physical distance of any route
    equals the plain Manhattan distance -- express never saves wire
    length; it saves ROUTER CROSSINGS (router_hops counts an express
    traversal as one; the C60 count/length split's third appearance --
    packet constants must read router_hops, the fabric guard enforces it)
    and LOCAL-SEGMENT CONTENTION (long flows ride the express channels
    and leave the unit segments to local traffic). The declared wire
    price: one extra length-s link per position per covered line --
    roughly doubling a line's wire on small grids; the price curve is
    the readout. `skip` >= the axis extent degenerates to mesh exactly.
    """

    NAME = "express"
    PARAMS = {**Mesh.PARAMS,
              "skip": (False, "express jump length s in slots (default 2); "
                              "s >= the axis extent means no links (mesh)")}

    def _setup(self):
        super()._setup()
        self.skip = int(self.params.get("skip", 2))
        if self.skip < 2:
            raise ValueError("express: skip must be >= 2")

    def hops(self, a: int, b: int) -> float:
        return _manh(self.coord(a), self.coord(b))     # wire length unchanged

    def router_hops(self, a: int, b: int) -> float:
        n = 0.0
        for _p, _q, _x in self._segments(a, b):
            n += 1.0
        return n

    def _segments(self, a: int, b: int):
        """(p, q, is_express) triples along the dimension-order greedy route."""
        if a == b:
            return
        cur = [int(round(self.coord(a)[0])), int(round(self.coord(a)[1]))]
        tgt = (int(round(self.coord(b)[0])), int(round(self.coord(b)[1])))
        order = (0, 1) if self.routing == "xy" else (1, 0)
        for axis in order:
            while cur[axis] != tgt[axis]:
                d = tgt[axis] - cur[axis]
                step = self.skip if abs(d) >= self.skip else 1
                step = step if d > 0 else -step
                p = tuple(cur)
                cur[axis] += step
                yield p, tuple(cur), abs(step) >= self.skip

    def path_directed(self, a: int, b: int) -> List[Tuple[str, str]]:
        out = []
        for p, q, xp in self._segments(a, b):
            lo, hi = sorted((p, q))
            kind = "xp" if xp else "seg"
            out.append((f"{self.NAME}:{kind}{lo}-{hi}", "+" if p == lo else "-"))
        return out

    def path(self, a: int, b: int) -> List[str]:
        return [r for r, _ in self.path_directed(a, b)]


# --------------------------------------------------------------------------- #
class Switch(Interconnect):
    """Non-blocking switch up to port bandwidth -- the weave that is
    placement-irrelevant BY CONSTRUCTION (C63-b, the O19 batch item 2).

    Real-world identity: package-level NVSwitch-class switches, fully
    custom die-to-die crossbar fabrics. (Repo naming rule: this class is
    `switch`, never "crossbar" -- a crossbar is always the ReRAM array.)

    Semantics: any port pair communicates at full port bandwidth with no
    shared internal resource, so WHERE a node sits cannot matter -- the
    ceiling reference against which every placement-sensitive weave is
    measured, and the fabric that buys off placement sensitivity outright.
    THE PRICE IS DECLARED HERE AND ENTERS NO ACCOUNT: internal wiring
    grows as N^2 (every port pair a path); this platform prices ports and
    declared end-to-end constants only -- the N^2 area/wiring cost is the
    identity's stated trade, for the "switch vs mesh" decision to weigh.

    Port bandwidth is the ONLY first-order parameter (the level's link
    bandwidth field). There is NO internal hop concept: hops(a, b) is the
    declared end-to-end constant (param `hops`, default 1.0; 0 for a = b),
    and energy_hops / router_hops inherit it -- energy is priced per port
    traversal at that constant. A flow a -> b occupies a's port (TX) and
    b's port (RX); the duplex split keys the two directions, so occupancy
    is per-port volume -- non-blocking up to port bandwidth, verbatim.
    """

    NAME = "switch"
    PARAMS = {"hops": (False, "declared end-to-end constant per transfer "
                              "(latency/energy caliber; default 1.0)")}

    def _setup(self):
        self._hops = float(self.params.get("hops", 1.0))

    def hops(self, a: int, b: int) -> float:
        return 0.0 if a == b else self._hops

    def _port(self, node: int) -> str:
        return f"{self.NAME}:port{'HUB' if node == HUB else node}"

    def path(self, a: int, b: int) -> List[str]:
        if a == b:
            return []
        return [self._port(a), self._port(b)]

    def path_directed(self, a: int, b: int) -> List[Tuple[str, str]]:
        if a == b:
            return []
        return [(self._port(a), "tx"), (self._port(b), "rx")]

    def resources(self) -> List[str]:
        return [self._port(HUB)] + [self._port(i)
                                    for i in range(len(self.slots))]


# --------------------------------------------------------------------------- #
_FLIP = {"dn": "up", "up": "dn", "+": "-", "-": "+", "": ""}


def reverse_directed(pairs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """The same route walked backwards: reversed order, direction tags
    flipped."""
    return [(r, _FLIP[t]) for r, t in reversed(pairs)]


_REGISTRY: Dict[str, type] = {}
#: accepted by every scheme
COMMON_PARAMS: Dict[str, Tuple[bool, str]] = {
    "duplex": (False, "full-duplex (per-direction wires) or shared; default "
                      "= the scheme's physical norm (bus: shared)"),
}


def register(cls: type) -> type:
    _REGISTRY[cls.NAME] = cls
    return cls


def schemes() -> List[str]:
    return sorted(_REGISTRY)


def validate_params(topology: str, params: dict, where: str = "") -> None:
    """Raise unless `params` is exactly what `topology` accepts."""
    cls = _REGISTRY.get(topology)
    if cls is None:
        raise ValueError(f"{where}: unknown topology '{topology}'; "
                         f"available: {schemes()}")
    spec = {**COMMON_PARAMS, **cls.PARAMS}
    unknown = set(params) - set(spec)
    if unknown:
        raise ValueError(f"{where}: topology '{topology}' does not take "
                         f"{sorted(unknown)}; accepts {sorted(spec)}")
    missing = [k for k, (req, _) in spec.items() if req and k not in params]
    if missing:
        raise ValueError(f"{where}: topology '{topology}' requires {missing}")


def build(fabric, level_name: str, placement) -> Interconnect:
    """The scheme for one fabric level, on a given placement (slot units)."""
    lv = fabric.level(level_name)
    if lv.link is None:
        raise ValueError(f"level '{level_name}' has no link to build a scheme for")
    slots = placement.slots[level_name]
    return _REGISTRY[lv.link.topology](slots, lv.link.params)


register(Star)
register(Mesh)
register(HTree)
register(Bus)
register(Torus)
register(Ring)
register(Switch)
register(CMesh)
register(Express)
register(HierWide)

#: schemes whose folded build splits router count from physical length --
#: fabric validation refuses packet parameters on these levels (C60 clause 1)
FOLDED_SCHEMES = ("torus", "ring", "express", "cmesh", "hier_wide")
