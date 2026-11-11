"""Placement: WHO occupies WHICH grid slot, made an explicit object.

fabric.py answers "where the slots are" (mesh geometry per level); a Placement
answers "which logical instance sits in which slot". Until now that assignment
was the implicit byproduct of enumeration order in crossbar_comm's nested
floorplan; here it becomes data that can be constructed, verified, serialized,
exchanged with the search side, and compared through one cost path.

Semantics
---------
slots[level] is one table per fabric level that has a mesh: logical instance i
(within its parent) -> (x, y) grid slot. For levels with many parents (cores,
crossbars) the same table is reused inside every parent (one pattern
replicated); per-parent tables are not supported.

A different arrangement of the same instances (e.g. 8 macros in a line) is a
different HARDWARE arrangement, not a placement: express it as a fabric variant
(macro mesh (8, 1)) with a sequential placement.

Pure python; imports on host and container alike.
"""
import json
from dataclasses import dataclass
from typing import Dict, List, Tuple

Slot = Tuple[int, int]


@dataclass(frozen=True)
class Placement:
    fabric_name: str
    slots: Dict[str, List[Slot]]

    # ------------------------------------------------------------- checks
    def verify(self, fabric) -> "Placement":
        """Raise unless this placement is legal on `fabric`."""
        if self.fabric_name != fabric.name:
            raise ValueError(
                f"placement is for fabric '{self.fabric_name}', got '{fabric.name}'")
        meshed = {lv.name: lv for lv in fabric.levels if lv.mesh is not None}
        unknown = set(self.slots) - set(meshed)
        if unknown:
            raise ValueError(f"slots for unknown/mesh-less level(s): {sorted(unknown)}")
        missing = set(meshed) - set(self.slots)
        if missing:
            raise ValueError(f"missing slot table for level(s): {sorted(missing)}")
        for name, lv in meshed.items():
            table = self.slots[name]
            if len(table) != lv.per_parent:
                raise ValueError(
                    f"{name}: {len(table)} slots for {lv.per_parent} instances")
            if len(set(table)) != len(table):
                raise ValueError(f"{name}: slot assigned twice")
            mx, my = lv.mesh
            for (x, y) in table:
                if not (0 <= x < mx and 0 <= y < my):
                    raise ValueError(f"{name}: slot ({x},{y}) outside mesh {lv.mesh}")
        return self

    # ------------------------------------------------------------- coords
    def _mesh_levels(self, fabric):
        return [lv for lv in fabric.levels if lv.mesh is not None]

    def leaf_coords(self, fabric) -> Dict[int, Slot]:
        """Global (x, y) of every leaf instance, keyed by its nested-order id.

        Composes the per-level slots positionally: descending one level scales
        the coordinate by that level's mesh and adds the instance's slot --
        identical math to the nested row-major floorplan.
        """
        levels = self._mesh_levels(fabric)
        coords, gid = {}, 0

        def descend(i, gx, gy):
            nonlocal gid
            if i == len(levels):
                coords[gid] = (gx, gy)
                gid += 1
                return
            lv = levels[i]
            for (sx, sy) in self.slots[lv.name]:
                descend(i + 1, gx * lv.mesh[0] + sx, gy * lv.mesh[1] + sy)

        descend(0, 0, 0)
        return coords

    def level_coords(self, fabric, name: str) -> List[Tuple[float, float]]:
        """Centroid of each instance of `name` (over its descendant leaves),
        in nested order across parents."""
        levels = self._mesh_levels(fabric)
        names = [lv.name for lv in levels]
        if name not in names:
            raise KeyError(f"no meshed level '{name}'")
        depth = names.index(name) + 1
        leaves_per = 1
        for lv in levels[depth:]:
            leaves_per *= lv.per_parent
        leaf = self.leaf_coords(fabric)
        out = []
        for start in range(0, len(leaf), leaves_per):
            xs = [leaf[g][0] for g in range(start, start + leaves_per)]
            ys = [leaf[g][1] for g in range(start, start + leaves_per)]
            out.append((sum(xs) / len(xs), sum(ys) / len(ys)))
        return out

    # ------------------------------------------------------------- io
    def to_json(self) -> str:
        return json.dumps({"fabric": self.fabric_name,
                           "slots": {k: [list(s) for s in v]
                                     for k, v in self.slots.items()}}, indent=1)


def from_json(text: str, fabric) -> Placement:
    raw = json.loads(text)
    p = Placement(fabric_name=raw["fabric"],
                  slots={k: [tuple(s) for s in v]
                         for k, v in raw["slots"].items()})
    return p.verify(fabric)


# ----------------------------------------------------------------- generators
def sequential_fill(fabric) -> Placement:
    """Row-major fill at every level (the nested floorplan)."""
    return Placement(
        fabric_name=fabric.name,
        slots={lv.name: fabric.slots(lv.name)
               for lv in fabric.levels if lv.mesh is not None},
    ).verify(fabric)