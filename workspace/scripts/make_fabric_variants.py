"""Die-capacity variants of the multi-die fabric: the same macro, core and
crossbar, a different number of macros per die. The mapper sizes its die hierarchy
from the fabric's per-parent counts (mlx_system.mlx_die_callfunc), and the
tiler's die capacity (llm_workload.DIE_WEIGHT_CELLS) follows the same
fabric, so a process started with CIMSIM_FABRIC = <variant> measures and
tiles on that die consistently. The glb (8 MB), the digital unit and every
link parameter are left as declared in the base file.

    python3 scripts/make_fabric_variants.py   -> models/fabric/variants/mlx300_multidie_m{N}.yaml
"""
import os
import re

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(WS, "models", "fabric", "mlx300_multidie.yaml")
OUT = os.path.join(WS, "models", "fabric", "variants")
MACROS = {4: (2, 2), 16: (4, 4), 32: (4, 8)}   # macros per die -> [X, Y] mesh; 8 is the base file itself
BASE_MACROS = 8


def variant_path(n):
    return os.path.join(OUT, f"mlx300_multidie_m{n}.yaml")


def main():
    os.makedirs(OUT, exist_ok=True)
    text = open(BASE).read()
    for n, (mx, my) in MACROS.items():
        t = text
        t = re.sub(r"(- name: macro\n(?:.*\n)*?\s+per_parent: )8", rf"\g<1>{n}", t, count=1)
        t = re.sub(r"(- name: macro\n(?:.*\n)*?\s+mesh: )\[2, 4\]", rf"\g<1>[{mx}, {my}]", t, count=1)
        assert f"per_parent: {n}" in t and f"mesh: [{mx}, {my}]" in t, n
        t = t.replace("fabric:\n  name: mlx300-multidie", f"fabric:\n  name: mlx300-multidie-m{n}")
        # the mapper's per-operator run checks the operator's span against the fabric's die count (24 in the base file);
        # a small die makes an operator span more than 24 dies, so the variants carry a 144-die package (the die count
        # plays no part in the per-operator account; the deployments use their own die grids)
        t = re.sub(r"(- name: die\n(?:.*\n)*?\s+per_parent: )24", r"\g<1>144", t, count=1)
        t = re.sub(r"(- name: die\n(?:.*\n)*?\s+mesh: )\[6, 4\]", r"\g<1>[12, 12]", t, count=1)
        assert "per_parent: 144" in t and "mesh: [12, 12]" in t, n
        # comments of the base file that describe its own 2x4 macro mesh
        t = t.replace("# 2x4 fills the eight macro slots exactly", f"# {mx}x{my} fills the {n} macro slots exactly")
        t = t.replace("# fills exactly; with the [2, 4] macro mesh the die is square (16x16 crossbars)", "# fills exactly")
        t = t.replace("# die slots of the package; a CiMLoop run models one die,", "# die slots for the per-operator runs; a CiMLoop run models one die,")
        hdr = (f"# CAPACITY VARIANT: {n} macros per die ({n / BASE_MACROS:g} x the base die's\n"
               f"# {BASE_MACROS}), macro mesh [{mx}, {my}]; everything else as in mlx300_multidie.yaml. The die's\n"
               f"# weight capacity scales with the macro count ({n} x 32 crossbars x 256 x 256 cells).\n")
        open(variant_path(n), "w").write(hdr + t)
        print("->", variant_path(n))


if __name__ == "__main__":
    main()
