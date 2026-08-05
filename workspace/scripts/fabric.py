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


@dataclass(frozen=True)
class Level:
    name: str
    per_parent: int = 1
    mesh: Optional[Tuple[int, int]] = None   # (X, Y) grid inside the parent
    link: Optional[Link] = None


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
        return self

    def verify_against_stats(self, hier: dict) -> None:
        """Cross-check against crossbar_stats.hierarchy() output (cumulative
        instance counts parsed from a run). Raises on mismatch: the config is
        the authority, a run that disagrees with it is misconfigured."""
        expected = {"n_macros": self.count_below("macro"),
                    "n_cores": self.count_below("core"),
                    "n_crossbars": self.count_below("crossbar")}
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
                      calibration=link.get("calibration")) if link else None,
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