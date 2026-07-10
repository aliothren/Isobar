"""Per-crossbar weight-placement and inter-crossbar data-movement logging.

Timeloop's raw `.map.txt` and `.stats.txt` mapper outputs already contain everything
needed to reconstruct, per physical crossbar (one CiM macro/tile instance):
  - which slice of a layer's weight matrix it holds, and where within its own
    row/column array each weight element sits
  - how much input/output data it moves per inference
  - how much data is exchanged between groups of crossbars over the row/column NoCs

`.map.txt` gives, per architecture level, the per-instance dataspace tile size and the
ordered (outer->inner) list of spatial/temporal loop factors. `.stats.txt` gives, per
level, per-instance access counts, and a "Networks" section with explicit per-dataspace
fanout/multicast/spatial-reduction stats between every pair of adjacent levels. Neither
file is currently parsed anywhere in this repo (`tl_output_parsing.py` only extracts
aggregate cycles/energy/area); this module fills that gap without needing any change to
Timeloop/Accelergy or to how the mapper is invoked.

Crossbar = one macro/tile instance (the `tile` container in `cim_tile_array.yaml`).
Weight placement *inside* a crossbar is tracked via the `column`/`row` array containers
(see `basic_analog/arch.yaml`). These component names are architecture-specific; pass
different ones via `crossbar_levels`/`array_levels` if used with a different chip yaml.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

# Levels (architecture container/component names) that identify one physical crossbar,
# and levels that identify a position *within* one crossbar's array. Order doesn't matter
# here; nesting order is recovered from the .map.txt parse.
DEFAULT_CROSSBAR_LEVELS = ("tile_col_group", "tile")
DEFAULT_ARRAY_LEVELS = ("column", "row")

# Component -> (kind, role) used to identify the crossbar's I/O boundary and the NoC
# components that move data between crossbars.
DEFAULT_INPUT_BOUNDARY_COMPONENT = "row_drivers"
DEFAULT_OUTPUT_BOUNDARY_COMPONENT = "adc"
DEFAULT_WEIGHT_COMPONENT = "cim_unit"
DEFAULT_NOC_COMPONENTS = ("row_noc", "col_noc")


# --------------------------------------------------------------------------- #
# .map.txt parsing
# --------------------------------------------------------------------------- #


@dataclass
class LoopFactor:
    dim: str
    extent: int
    kind: str  # "spatial-x", "spatial-y", or "temporal"


@dataclass
class LevelMapping:
    """One block of .map.txt: the component(s) at a level, their per-instance tile
    sizes, and the loop factors that appear directly below them in the nest."""

    components: List[str]
    tile_sizes: Dict[str, Dict[str, int]]  # component -> {dataspace: per-instance size}
    loops: List[LoopFactor]

    @property
    def primary_component(self) -> Optional[str]:
        return self.components[-1] if self.components else None


_COMPONENT_LINE_RE = re.compile(r"^(\w+)\s*\[(.*)\]\s*$")
_TILE_SIZE_RE = re.compile(r"(\w+):(\d+)\s*\((\d+)\)")
_LOOP_LINE_RE = re.compile(
    r"^\|+\s*for\s+(\w+)\s+in\s+\[0:(\d+)\)(?:\s*\((Spatial-[XY])\))?\s*$"
)


def parse_map_txt(text: str) -> List[LevelMapping]:
    """Parse a timeloop-mapper `.map.txt` file into ordered (outer->inner) levels."""
    blocks = re.split(r"\n\s*\n", text.strip())
    levels: List[LevelMapping] = []

    for block in blocks:
        lines = [l for l in block.splitlines() if l.strip()]
        components: List[str] = []
        tile_sizes: Dict[str, Dict[str, int]] = {}
        loops: List[LoopFactor] = []

        for line in lines:
            m = _COMPONENT_LINE_RE.match(line)
            if m:
                name, body = m.group(1), m.group(2)
                components.append(name)
                sizes = {ds: int(n) for ds, n, _ in _TILE_SIZE_RE.findall(body)}
                if sizes:
                    tile_sizes[name] = sizes
                continue
            if set(line.strip()) == {"-"}:
                continue  # separator line
            lm = _LOOP_LINE_RE.match(line)
            if lm:
                dim, extent, spatial_kind = lm.groups()
                kind = (
                    "spatial-x"
                    if spatial_kind == "Spatial-X"
                    else "spatial-y" if spatial_kind == "Spatial-Y" else "temporal"
                )
                loops.append(LoopFactor(dim=dim, extent=int(extent), kind=kind))
                continue
            if line.strip() == "<< Compute >>":
                continue
            # Unrecognized line (e.g. stray separator); ignore rather than fail hard.

        if components or loops:
            levels.append(LevelMapping(components=components, tile_sizes=tile_sizes, loops=loops))

    return levels


# --------------------------------------------------------------------------- #
# .stats.txt parsing
# --------------------------------------------------------------------------- #


@dataclass
class DataspaceAccess:
    partition_size: Optional[int] = None
    utilized_capacity: Optional[int] = None
    reads_per_instance: Optional[int] = None
    fills_per_instance: Optional[int] = None
    updates_per_instance: Optional[int] = None


@dataclass
class LevelStats:
    name: str
    instances_total: int
    instances_factors: Tuple[int, ...]  # e.g. (1024, 32) for "32768 (1024*32)"
    dataspaces: Dict[str, DataspaceAccess] = field(default_factory=dict)


@dataclass
class NetworkEdgeStats:
    parent: str
    child: str
    dataspaces: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # per dataspace: fanout, multicast_factor, ingresses, spatial_reductions


_LEVEL_HEADER_RE = re.compile(r"=== (\w+) ===")
_INSTANCES_RE = re.compile(r"Instances\s*:\s*(\d+)\s*\(([\d*]+)\)")
_DATASPACE_HEADER_RE = re.compile(r"^\s{4}(Inputs|Outputs|Weights):\s*$", re.MULTILINE)
_FIELD_RE = lambda label: re.compile(rf"{re.escape(label)}\s*:\s*([0-9.eE+\-]+)")

_NETWORK_HEADER_RE = re.compile(r"^(\S+)\s*<==>\s*(\S+)\s*$")


def parse_stats_txt(text: str) -> Tuple[Dict[str, LevelStats], List[NetworkEdgeStats]]:
    """Parse a timeloop-mapper `.stats.txt` file.

    Returns (level_stats keyed by component name, list of inter-level network edges).
    """
    networks_split = re.split(r"\nNetworks\n-+\n", text, maxsplit=1)
    levels_text = networks_split[0]
    rest_text = networks_split[1] if len(networks_split) > 1 else ""
    # Networks section ends where the per-component "Operational Intensity" summary
    # starts (or end of file).
    networks_text = re.split(r"\nOperational Intensity Stats\n", rest_text, maxsplit=1)[0]

    level_stats: Dict[str, LevelStats] = {}
    for block in re.split(r"\nLevel \d+\n-+\n", levels_text)[1:]:
        header = _LEVEL_HEADER_RE.search(block)
        if not header:
            continue
        name = header.group(1)

        inst_m = _INSTANCES_RE.search(block)
        if inst_m:
            total = int(inst_m.group(1))
            factors = tuple(int(x) for x in inst_m.group(2).split("*"))
        else:
            total, factors = 1, (1,)

        dataspaces: Dict[str, DataspaceAccess] = {}
        # Split the STATS section into per-dataspace chunks.
        stats_section = block.split("STATS\n    -----\n", 1)
        if len(stats_section) > 1:
            stats_body = stats_section[1]
            headers = list(_DATASPACE_HEADER_RE.finditer(stats_body))
            for i, hm in enumerate(headers):
                ds_name = hm.group(1)
                start = hm.end()
                end = headers[i + 1].start() if i + 1 < len(headers) else len(stats_body)
                chunk = stats_body[start:end]
                dataspaces[ds_name] = DataspaceAccess(
                    partition_size=_extract_int(chunk, "Partition size"),
                    utilized_capacity=_extract_int(chunk, "Utilized capacity"),
                    reads_per_instance=_extract_int(chunk, "Scalar reads (per-instance)"),
                    fills_per_instance=_extract_int(chunk, "Scalar fills (per-instance)"),
                    updates_per_instance=_extract_int(chunk, "Scalar updates (per-instance)"),
                )

        level_stats[name] = LevelStats(
            name=name, instances_total=total, instances_factors=factors, dataspaces=dataspaces
        )

    edges: List[NetworkEdgeStats] = []
    for block in re.split(r"\nNetwork \d+\n-+\n", networks_text)[1:]:
        lines = [l for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        hm = _NETWORK_HEADER_RE.match(lines[0].strip())
        if not hm:
            continue
        parent, child = hm.groups()

        dataspaces: Dict[str, Dict[str, float]] = {}
        stats_section = block.split("STATS\n    -----\n", 1)
        if len(stats_section) > 1:
            stats_body = stats_section[1]
            headers = list(_DATASPACE_HEADER_RE.finditer(stats_body))
            for i, dm in enumerate(headers):
                ds_name = dm.group(1)
                start = dm.end()
                end = headers[i + 1].start() if i + 1 < len(headers) else len(stats_body)
                chunk = stats_body[start:end]
                dataspaces[ds_name] = {
                    "fanout": _extract_float(chunk, "Fanout") or 0.0,
                    "multicast_factor": _extract_float(chunk, "Multicast factor") or 0.0,
                    "ingresses": _extract_float(chunk, "Ingresses") or 0.0,
                    "spatial_reductions": _extract_float(chunk, "Spatial reductions") or 0.0,
                }

        edges.append(NetworkEdgeStats(parent=parent, child=child, dataspaces=dataspaces))

    return level_stats, edges


def _extract_int(text: str, label: str) -> Optional[int]:
    v = _extract_float(text, label)
    return int(v) if v is not None else None


def _extract_float(text: str, label: str) -> Optional[float]:
    m = _FIELD_RE(label).search(text)
    return float(m.group(1)) if m else None


# --------------------------------------------------------------------------- #
# Per-dimension spatial-split composition (weight placement)
# --------------------------------------------------------------------------- #


# Dimensions that index into the Weights dataspace (problem_base.yaml's Weights
# projection is C, M, R, S, Y, G; Y is weight-bits-per-slice, not a tensor index).
WEIGHT_DIMS = ("C", "M", "R", "S", "G")


@dataclass
class _LoopAxis:
    level_name: str
    dim: str
    extent: int
    stride: int  # global stride for this dim's index composition
    kind: str  # "spatial-x", "spatial-y", or "temporal"


def _dim_chains(
    level_mappings: List[LevelMapping],
) -> Dict[str, List[Tuple[str, int, str]]]:
    """dim -> ordered (outer->inner) list of (level_name, extent, kind) for ALL its
    loops (spatial and temporal). Composing strides over this full chain (not just the
    spatial portion) is required for dims that don't fit the array spatially and are
    therefore also tiled temporally above the crossbar (e.g. a weight matrix bigger
    than the available tile-array capacity, reloaded in sequential chunks)."""
    chains: Dict[str, List[Tuple[str, int, str]]] = defaultdict(list)
    for lvl in level_mappings:
        level_name = lvl.primary_component
        for loop in lvl.loops:
            if level_name is not None:
                chains[loop.dim].append((level_name, loop.extent, loop.kind))
    return chains


def _axes_with_strides(chain: List[Tuple[str, int, str]], dim: str) -> List[_LoopAxis]:
    strides = [1] * len(chain)
    acc = 1
    for i in range(len(chain) - 1, -1, -1):
        strides[i] = acc
        acc *= chain[i][1]
    return [
        _LoopAxis(level_name=name, dim=dim, extent=extent, stride=stride, kind=kind)
        for (name, extent, kind), stride in zip(chain, strides)
    ]


def _canonicalize_level_name(name: str, base_names: Tuple[str, ...]) -> Optional[str]:
    """Map a parsed level name back to one of `base_names`.

    Timeloop hosts each container's spatial for-loop under an auto-generated
    "inter_<container_name>_spatial" pseudo-component rather than the container's own
    name, so both forms need to resolve to the same base name.
    """
    for base in base_names:
        if name == base or name == f"inter_{base}_spatial":
            return base
    return None


# --------------------------------------------------------------------------- #
# Per-crossbar table
# --------------------------------------------------------------------------- #


def build_crossbar_table(
    level_mappings: List[LevelMapping],
    level_stats: Dict[str, LevelStats],
    variables: Dict[str, float],
    crossbar_levels: Tuple[str, ...] = DEFAULT_CROSSBAR_LEVELS,
    array_levels: Tuple[str, ...] = DEFAULT_ARRAY_LEVELS,
    input_boundary_component: str = DEFAULT_INPUT_BOUNDARY_COMPONENT,
    output_boundary_component: str = DEFAULT_OUTPUT_BOUNDARY_COMPONENT,
    weight_component: str = DEFAULT_WEIGHT_COMPONENT,
) -> pd.DataFrame:
    """One row per (physical crossbar, weight time-step).

    If a layer's weight matrix is bigger than the tile array's spatial capacity, the
    mapper reloads each crossbar with a new weight block one or more times over the
    course of one inference (captured by temporal loops on weight dims *above* the
    crossbar level, e.g. at `main_memory`/`l2_shared_buf`) — so a single crossbar
    coordinate can have multiple rows, one per distinct block it holds over time. Group
    by the crossbar id columns to get the full sequence of blocks one physical crossbar
    visits; group by everything *except* the time-step columns to get the resident
    snapshot for a single point in time.

    Columns: tile coordinate per crossbar-identifying level, a time-step index per
    weight-reload level (if any), the (dim_lo, dim_hi) weight block resident at that
    time, the physical array shape, weight reuse factor (cross-check: should equal the
    product of the time-step extents), and per-access input/output data volume in
    bytes (each access moves this many bytes; multiply by the number of time-steps for
    a per-crossbar full-inference total).
    """
    chains = _dim_chains(level_mappings)

    crossbar_axes: List[_LoopAxis] = []
    array_axes: List[_LoopAxis] = []
    time_axes: List[_LoopAxis] = []
    for dim, chain in chains.items():
        for axis in _axes_with_strides(chain, dim):
            is_spatial = axis.kind in ("spatial-x", "spatial-y")
            if is_spatial:
                base = _canonicalize_level_name(axis.level_name, crossbar_levels)
                if base is not None:
                    axis.level_name = base
                    crossbar_axes.append(axis)
                    continue
                base = _canonicalize_level_name(axis.level_name, array_levels)
                if base is not None:
                    axis.level_name = base
                    array_axes.append(axis)
            elif dim in WEIGHT_DIMS:
                # A temporal loop over a weight dimension, outside the array entirely:
                # this crossbar gets reloaded with a different block at each step.
                time_axes.append(axis)

    # Per-instance tile sizes (already account for everything nested below that level).
    def tile_size(component: str, dataspace: str) -> int:
        for lvl in level_mappings:
            if component in lvl.tile_sizes and dataspace in lvl.tile_sizes[component]:
                return lvl.tile_sizes[component][dataspace]
        return 0

    encoded_input_bits = variables.get("ENCODED_INPUT_BITS", 1) or 1
    encoded_output_bits = variables.get("ENCODED_OUTPUT_BITS", 1) or 1
    input_bits = variables.get("INPUT_BITS", encoded_input_bits)
    output_bits = variables.get("OUTPUT_BITS", encoded_output_bits)

    in_elems = tile_size(input_boundary_component, "Inputs")
    out_elems = tile_size(output_boundary_component, "Outputs")
    data_in_bytes_per_access = in_elems / encoded_input_bits * input_bits / 8
    data_out_bytes_per_access = out_elems / encoded_output_bits * output_bits / 8

    weight_access = level_stats.get(weight_component)
    weight_ds = weight_access.dataspaces.get("Weights") if weight_access else None
    weight_reuse_factor = 1.0
    if weight_ds and weight_ds.partition_size and weight_ds.utilized_capacity:
        weight_reuse_factor = weight_ds.partition_size / weight_ds.utilized_capacity

    array_rows = 1
    array_cols = 1
    for axis in array_axes:
        if axis.level_name == "row":
            array_rows = axis.extent
        elif axis.level_name == "column":
            array_cols = axis.extent

    # Enumerate the combined crossbar-coordinate + weight-reload-time-step space: one
    # combination per (level_name, dim) axis, spatial or temporal.
    id_axes = crossbar_axes + time_axes
    coord_levels = sorted({(a.level_name, a.dim) for a in id_axes})
    extents_by_level_dim = {(a.level_name, a.dim): a.extent for a in id_axes}

    rows = []
    import itertools

    ranges = [range(extents_by_level_dim[k]) for k in coord_levels]
    for combo in itertools.product(*ranges) if ranges else [()]:
        coord = dict(zip(coord_levels, combo))
        # Disambiguate with the dim when one level hosts more than one axis (e.g. a
        # weight matrix that doesn't fit the array gets reloaded along both M and C
        # above the crossbar boundary, both at the same "main_memory" level) -- a bare
        # "{level}_idx" column would silently collide and drop one of the two indices.
        names_seen = defaultdict(int)
        for name, _dim in coord:
            names_seen[name] += 1
        row = {
            (f"{name}_idx" if names_seen[name] == 1 else f"{name}_{dim}_idx"): idx
            for (name, dim), idx in coord.items()
        }

        dim_bases: Dict[str, int] = defaultdict(int)
        for axis in id_axes:
            idx = coord[(axis.level_name, axis.dim)]
            dim_bases[axis.dim] += idx * axis.stride

        dim_block_sizes: Dict[str, int] = defaultdict(lambda: 1)
        for axis in array_axes:
            dim_block_sizes[axis.dim] *= axis.extent

        for dim in set(list(dim_bases.keys()) + list(dim_block_sizes.keys())):
            lo = dim_bases.get(dim, 0)
            hi = lo + dim_block_sizes.get(dim, 1)
            row[f"{dim}_lo"] = lo
            row[f"{dim}_hi"] = hi

        row["array_rows"] = array_rows
        row["array_cols"] = array_cols
        row["weight_reuse_factor"] = weight_reuse_factor
        row["data_in_bytes_per_access"] = data_in_bytes_per_access
        row["data_out_bytes_per_access"] = data_out_bytes_per_access
        rows.append(row)

    return pd.DataFrame(rows)


def build_within_crossbar_map(
    level_mappings: List[LevelMapping],
    array_levels: Tuple[str, ...] = DEFAULT_ARRAY_LEVELS,
) -> pd.DataFrame:
    """Per-cell (row_idx, col_idx) -> weight-dim offsets within ONE crossbar's array.

    Offsets are relative to that crossbar's own weight block (add the block's `*_lo`
    from `build_crossbar_table` to get global indices). Call once per layer shape; the
    same per-cell layout applies to every crossbar of that layer (Timeloop's analytical
    model guarantees uniform per-instance behavior within a spatial group).
    """
    chains = _dim_chains(level_mappings)
    array_axes: List[_LoopAxis] = []
    for dim, chain in chains.items():
        for axis in _axes_with_strides(chain, dim):
            if axis.kind not in ("spatial-x", "spatial-y"):
                continue
            base = _canonicalize_level_name(axis.level_name, array_levels)
            if base is not None:
                axis.level_name = base
                array_axes.append(axis)

    import itertools

    axes_by_level = {a.level_name: a for a in array_axes}
    levels = [l for l in array_levels if l in axes_by_level]
    ranges = [range(axes_by_level[l].extent) for l in levels]

    rows = []
    for combo in itertools.product(*ranges) if ranges else [()]:
        row = {}
        offsets: Dict[str, int] = defaultdict(int)
        for level, idx in zip(levels, combo):
            row[f"{level}_idx"] = idx
            axis = axes_by_level[level]
            offsets[axis.dim] += idx * axis.stride
        for dim, off in offsets.items():
            row[f"{dim}_offset"] = off
        rows.append(row)

    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Inter-crossbar (NoC) data movement
# --------------------------------------------------------------------------- #


def build_noc_edge_table(
    level_mappings: List[LevelMapping],
    level_stats: Dict[str, LevelStats],
    network_edges: List[NetworkEdgeStats],
    variables: Dict[str, float],
    noc_components: Tuple[str, ...] = DEFAULT_NOC_COMPONENTS,
) -> pd.DataFrame:
    """One row per (NoC component, dataspace) group: one NoC-component instance and the
    crossbars nested below it (e.g. one `col_noc` instance and the tiles in its column).

    Topology-agnostic: describes how much data a NoC component moves and whether it's
    broadcasting (fanout > 1, `spatial_reductions == 0`) or reducing
    (`spatial_reductions > 0`) — read directly off Timeloop's own per-edge network
    stats rather than assumed from the architecture description, so it reflects what a
    given mapping actually does, not just what the NoC was designed for.

    Each NoC component appears in two network edges (one to its parent, one to its
    child); only the child-facing edge is used, since that is the one Timeloop reports
    in per-NoC-instance units (the parent-facing edge reports totals already summed
    across every instance of this NoC component).
    """
    level_order = {
        comp: i for i, lvl in enumerate(level_mappings) for comp in lvl.components
    }

    bits_by_dataspace = {
        "Inputs": variables.get("INPUT_BITS", 1),
        "Outputs": variables.get("OUTPUT_BITS", 1),
        "Weights": variables.get("WEIGHT_BITS", 1),
    }
    encoded_bits_by_dataspace = {
        "Inputs": variables.get("ENCODED_INPUT_BITS", 1) or 1,
        "Outputs": variables.get("ENCODED_OUTPUT_BITS", 1) or 1,
        "Weights": variables.get("ENCODED_WEIGHT_BITS", 1) or 1,
    }

    rows = []
    for edge in network_edges:
        component = edge.parent if edge.parent in noc_components else (
            edge.child if edge.child in noc_components else None
        )
        if component is None:
            continue
        peer = edge.child if component == edge.parent else edge.parent
        # Keep only the edge where `component` is the parent (nests earlier in the
        # mapping) i.e. the child-facing edge reported in per-instance units.
        if level_order.get(component, 0) > level_order.get(peer, 0):
            continue

        n_instances = level_stats[component].instances_total if component in level_stats else 1

        for ds_name, stats in edge.dataspaces.items():
            if stats["ingresses"] == 0:
                continue
            kind = "reduce" if stats["spatial_reductions"] > 0 else "broadcast"
            bits = bits_by_dataspace.get(ds_name, 1)
            encoded_bits = encoded_bits_by_dataspace.get(ds_name, 1)
            volume_per_group_bytes = stats["ingresses"] / encoded_bits * bits / 8
            rows.append(
                {
                    "component": component,
                    "peer": peer,
                    "dataspace": ds_name,
                    "kind": kind,
                    "n_groups": n_instances,
                    "fanout": stats["fanout"],
                    "volume_per_group_bytes": volume_per_group_bytes,
                    "total_volume_bytes": volume_per_group_bytes * n_instances,
                }
            )

    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Convenience wrapper
# --------------------------------------------------------------------------- #


def log_crossbar_stats(
    spec,
    output_dir: str,
    map_filename: str = "timeloop-mapper.map.txt",
    stats_filename: str = "timeloop-mapper.stats.txt",
    **kwargs,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Read `{output_dir}/{map,stats}_filename`, return (crossbar_df, edges_df)."""
    import os

    with open(os.path.join(output_dir, map_filename)) as f:
        level_mappings = parse_map_txt(f.read())
    with open(os.path.join(output_dir, stats_filename)) as f:
        level_stats, network_edges = parse_stats_txt(f.read())

    variables = dict(spec.variables)
    crossbar_df = build_crossbar_table(level_mappings, level_stats, variables, **kwargs)
    edges_df = build_noc_edge_table(level_mappings, level_stats, network_edges, variables)
    return crossbar_df, edges_df
