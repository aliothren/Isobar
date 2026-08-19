"""Physical fabric: the schema and loader for models/fabric/*.yaml.

The YAML holds the concrete chip data (levels, counts, grids, link params);
this module holds the abstraction: dataclasses, validation, the cross-check
against a run's stats, and grid-slot coordinates. Pure python -- imports on
host and container alike (yaml is loaded lazily inside from_yaml).

Authority direction: the fabric config is the source of truth for physical
structure; the stats-derived counts (crossbar_stats.hierarchy) are demoted to a
consistency check via verify_against_stats().
"""
import os
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

_DEFAULT_YAML = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "models", "fabric", "mlx300.yaml")


@dataclass(frozen=True)
class Link:
    """The network connecting a level's instances to their parent's hub."""
    name: str
    ns_per_hop: float
    pj_per_word: Optional[float] = None      # None = priced elsewhere / not priced
    cimloop_component: Optional[str] = None  # calibrated component (re-priced by distance)
    reference_hops: Optional[float] = None
    calibration: Optional[str] = None        # DR tag for the placeholder
    # T2 static-contention input (link_occupancy); None = unlimited (no stall).
    # Owned by OUR analytic tier, never pushed into Timeloop (ownership rule:
    # network links -> T2, storage/hub bandwidth -> T1 via Level.hub_bandwidth).
    bandwidth_words_per_cycle: Optional[float] = None
    # Which communication SCHEME connects this level's instances to their hub.
    # "star" (private link per node) is the degenerate default and reproduces the
    # pre-W2 behaviour exactly. Every scheme takes its OWN parameter set, so they
    # live in `params` rather than as flat fields; scripts/interconnect.py owns
    # the registry and validates them.
    topology: str = "star"
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Level:
    name: str
    per_parent: int = 1
    mesh: Optional[Tuple[int, int]] = None   # (X, Y) grid inside the parent
    link: Optional[Link] = None
    # T1: this level's HUB storage read/write bandwidth (words/cycle), pushed
    # into the Timeloop spec (e.g. the die's glb). None = unlimited.
    hub_bandwidth_words_per_cycle: Optional[float] = None
    # Physical centre-to-centre distance between adjacent slots of THIS level's
    # grid, in micrometres. Platform input (example default in the shipped
    # configs); nothing consumes it yet -- it exists so hop counts have a
    # declared physical meaning, and so ns_per_hop / hop_scale can later be
    # DERIVED (delay ~ length or length^2, energy ~ wire capacitance ~ length)
    # instead of hand-filled per level. None = not stated.
    slot_pitch_um: Optional[float] = None


@dataclass(frozen=True)
class Fabric:
    name: str
    levels: List[Level] = field(default_factory=list)
    cimloop: dict = field(default_factory=dict)

    # ------------------------------------------------------------- access
    def level(self, name: str) -> Level:
        for lv in self.levels:
            if lv.name == name:
                return lv
        raise KeyError(f"fabric {self.name} has no level '{name}'")

    def count_below(self, name: str) -> int:
        """Cumulative instances of `name` inside one top-level instance."""
        n = 1
        for lv in self.levels:
            n *= lv.per_parent
            if lv.name == name:
                return n
        raise KeyError(f"fabric {self.name} has no level '{name}'")

    def pitch(self, name: str) -> int:
        """Leaf-grid units spanned by ONE slot step at `name`'s level.

        The product of every mesh BELOW it. This is the bridge between the two
        coordinate systems the cost paths use: an interconnect works in a level's
        own slot units, the propagation-latency term wants global leaf-grid units,
        and leaf_distance == slot_distance * pitch exactly (the nesting is an
        affine map, so Manhattan distance scales). Verified against the legacy
        constants: macro pitch 6 (2.0 slots -> 12), core 3 (1.0 -> 3),
        crossbar 1 (2.0 -> 2).
        """
        seen = False
        p = 1
        for lv in self.levels:
            if seen and lv.mesh is not None:
                p *= lv.mesh[0]
            if lv.name == name:
                seen = True
        if not seen:
            raise KeyError(f"fabric {self.name} has no level '{name}'")
        return p

    def grid_shape(self) -> Tuple[int, int]:
        """Full leaf-grid dimensions: per-axis product of every mesh."""
        gx = gy = 1
        for lv in self.levels:
            if lv.mesh is not None:
                gx *= lv.mesh[0]
                gy *= lv.mesh[1]
        return gx, gy

    def slots(self, name: str) -> List[Tuple[int, int]]:
        """Grid coordinates a level's instances occupy in their parent,
        row-major fill order (matches the legacy nested floorplan)."""
        lv = self.level(name)
        if lv.mesh is None:
            raise ValueError(f"level '{name}' has no mesh")
        mx, _ = lv.mesh
        return [(i % mx, i // mx) for i in range(lv.per_parent)]

    # ------------------------------------------------------------- checks
    def validate(self) -> "Fabric":
        for lv in self.levels:
            if lv.per_parent < 1:
                raise ValueError(f"{lv.name}: per_parent must be >= 1")
            if lv.mesh is not None and lv.mesh[0] * lv.mesh[1] < lv.per_parent:
                raise ValueError(
                    f"{lv.name}: mesh {lv.mesh} has fewer slots than "
                    f"per_parent {lv.per_parent}")
        # physical slot pitch: positive, and non-decreasing toward the top
        # (a parent level's grid step spans at least its child's)
        pitched = [lv for lv in self.levels if lv.slot_pitch_um is not None]
        for lv in pitched:
            if lv.slot_pitch_um <= 0:
                raise ValueError(f"{lv.name}: slot_pitch_um must be > 0")
        for upper, lower in zip(pitched, pitched[1:]):   # top -> bottom
            if upper.slot_pitch_um < lower.slot_pitch_um:
                raise ValueError(
                    f"slot_pitch_um not monotone up the tree: {upper.name} "
                    f"({upper.slot_pitch_um}) < {lower.name} "
                    f"({lower.slot_pitch_um})")
        # unit costs must be non-decreasing toward the top of the tree
        links = [lv.link for lv in self.levels if lv.link is not None]
        for upper, lower in zip(links, links[1:]):      # levels are top -> bottom
            if upper.ns_per_hop < lower.ns_per_hop:
                raise ValueError(
                    f"ns_per_hop not monotone up the tree: {upper.name} "
                    f"({upper.ns_per_hop}) < {lower.name} ({lower.ns_per_hop})")
            if (upper.pj_per_word is not None and lower.pj_per_word is not None
                    and upper.pj_per_word < lower.pj_per_word):
                raise ValueError(
                    f"pj_per_word not monotone up the tree: {upper.name} "
                    f"({upper.pj_per_word}) < {lower.name} ({lower.pj_per_word})")
        # each level's scheme validates its own parameter set
        from scripts import interconnect
        for lv in self.levels:
            if lv.link is not None:
                interconnect.validate_params(lv.link.topology, lv.link.params,
                                             where=lv.name)
        return self

    def verify_against_stats(self, hier: dict) -> None:
        """Cross-check against crossbar_stats.hierarchy() output (cumulative
        instance counts parsed from a run). Raises on mismatch: the config is
        the authority, a run that disagrees with it is misconfigured.

        Counts are PER DIE: a CiMLoop run always models one die, so a
        multi-die fabric (die.per_parent > 1) must not inflate the expectation.
        """
        dies = self.count_below("die")
        expected = {"n_macros": self.count_below("macro") // dies,
                    "n_cores": self.count_below("core") // dies,
                    "n_crossbars": self.count_below("crossbar") // dies}
        for key, exp in expected.items():
            got = hier.get(key)
            if got != exp:
                raise ValueError(
                    f"fabric {self.name} says {key}={exp} but the run's stats "
                    f"say {got} -- CiMLoop spec and fabric config diverged")


def from_yaml(path: str = _DEFAULT_YAML) -> Fabric:
    import yaml
    with open(path) as f:
        raw = yaml.safe_load(f)["fabric"]
    levels = []
    for lv in raw["levels"]:
        link = lv.get("link")
        levels.append(Level(
            name=lv["name"],
            per_parent=int(lv.get("per_parent", 1)),
            mesh=tuple(lv["mesh"]) if lv.get("mesh") else None,
            link=Link(name=link["name"],
                      ns_per_hop=float(link["ns_per_hop"]),
                      pj_per_word=(None if link.get("pj_per_word") is None
                                   else float(link["pj_per_word"])),
                      cimloop_component=link.get("cimloop_component"),
                      reference_hops=(None if link.get("reference_hops") is None
                                      else float(link["reference_hops"])),
                      calibration=link.get("calibration"),
                      bandwidth_words_per_cycle=(
                          None if link.get("bandwidth_words_per_cycle") is None
                          else float(link["bandwidth_words_per_cycle"])),
                      topology=link.get("topology", "star"),
                      params=dict(link.get("params") or {})) if link else None,
            hub_bandwidth_words_per_cycle=(
                None if lv.get("hub_bandwidth_words_per_cycle") is None
                else float(lv.get("hub_bandwidth_words_per_cycle"))),
            slot_pitch_um=(None if lv.get("slot_pitch_um") is None
                           else float(lv.get("slot_pitch_um"))),
        ))
    return Fabric(name=raw["name"], levels=levels,
                  cimloop=raw.get("cimloop", {})).validate()


_CACHE = {}


def default() -> Fabric:
    """The active fabric config, loaded once per path.

    Defaults to models/fabric/mlx300.yaml; the CIMSIM_FABRIC environment
    variable selects another config file for a whole process tree -- the lever
    for running the same experiments on a fabric variant, e.g.
        CIMSIM_FABRIC=/home/workspace/models/fabric/mlx300_2x4.yaml python3 ...
    """
    path = os.path.abspath(os.environ.get("CIMSIM_FABRIC", _DEFAULT_YAML))
    if path not in _CACHE:
        _CACHE[path] = from_yaml(path)
    return _CACHE[path]