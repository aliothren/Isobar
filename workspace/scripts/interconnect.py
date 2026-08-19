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

    def resources(self) -> List[str]:
        seen = []
        for i in range(len(self.slots)):
            for r in self.path(HUB, i):
                if r not in seen:
                    seen.append(r)
        return seen

    # ----------------------------------------------------------- aggregates
    def max_hops(self) -> float:
        """Worst-case hub->node distance: the parallel branches' critical path."""
        return max((self.hops(HUB, i) for i in range(len(self.slots))), default=0.0)

    def mean_hops(self) -> float:
        """Mean hub->node distance: what the energy re-pricing scales by."""
        n = len(self.slots)
        return sum(self.hops(HUB, i) for i in range(n)) / n if n else 0.0


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

    Segments are undirected: our flow volumes already merge the down (input) and
    up (output) traffic of an edge, so the two directions share a resource. A
    full-duplex variant would split them; add a param when a consumer needs it.

    A node co-located with the hub traverses no segment at all, which is the
    right answer and is why `hub` placement is a real modelling choice.
    """

    NAME = "mesh"
    PARAMS = {
        "routing": (False, "xy (default) | yx -- dimension order"),
        "hub": (False, "center (default) | corner | node:<i> -- where the "
                       "parent's aggregation point attaches"),
        "multicast": (False, "native (a shared slice crosses a segment once, "
                             "default) | replicated (unicast NoC: once per "
                             "destination)"),
    }

    def _setup(self):
        self.routing = self.params.get("routing", "xy")
        if self.routing not in ("xy", "yx"):
            raise ValueError(f"mesh: routing must be xy or yx, got {self.routing}")
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

    def _route(self, src: Slot, dst: Slot) -> List[Slot]:
        """Grid points visited, dimension-order."""
        x0, y0 = int(round(src[0])), int(round(src[1]))
        x1, y1 = int(round(dst[0])), int(round(dst[1]))
        pts = [(x0, y0)]
        order = ((x1, "x"), (y1, "y")) if self.routing == "xy" \
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
        pts = self._route(self.coord(a), self.coord(b))
        out = []
        for p, q in zip(pts, pts[1:]):
            lo, hi = sorted((p, q))
            out.append(f"{self.NAME}:seg{lo}-{hi}")
        return out

    def resources(self) -> List[str]:
        seen = []
        for i in range(len(self.slots)):
            for r in self.path(HUB, i):
                if r not in seen:
                    seen.append(r)
        return seen


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

    def hops(self, a: int, b: int) -> float:
        return _manh(self.coord(a), self.coord(b))

    def path(self, a: int, b: int) -> List[str]:
        return [f"{self.NAME}:medium"]


# --------------------------------------------------------------------------- #
_REGISTRY: Dict[str, type] = {}


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
    spec = cls.PARAMS
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
