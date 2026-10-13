"""Die-capacity variants of the multi-die fabric (next-round item 3 and the
attention-die assumption of item 2.2): the same macro, core and crossbar,
a different number of macros per die. The mapper sizes its die hierarchy
from the fabric's per-parent counts (mlx_system.mlx_die_callfunc), and the
tiler's die capacity (llm_workload.DIE_WEIGHT_CELLS) follows the same
fabric, so a process started with CIMSIM_FABRIC = <variant> measures and
tiles on that die consistently. The glb (8 MB), the digital unit and every
link parameter are left as declared in the base file.

    python3 scripts/v4_fabric_variants.py   -> models/fabric/variants/mlx300_multidie_m{N}.yaml
"""
import os
import re

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(WS, "models", "fabric", "mlx300_multidie.yaml")
OUT = os.path.join(WS, "models", "fabric", "variants")
MACROS = {2: (1, 2), 4: (2, 2), 6: (2, 3), 8: (2, 4), 12: (3, 4), 16: (4, 4), 24: (4, 6), 32: (4, 8)}   # macros per die -> [X, Y] mesh
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
        hdr = (f"# CAPACITY VARIANT (next-round item 3): {n} macros per die ({n / BASE_MACROS:g} x the base die's\n"
               f"# {BASE_MACROS}), macro mesh [{mx}, {my}]; everything else as in mlx300_multidie.yaml. The die's\n"
               f"# weight capacity scales with the macro count ({n} x 32 crossbars x 256 x 256 cells).\n")
        open(variant_path(n), "w").write(hdr + t)
        print("->", variant_path(n))


if __name__ == "__main__":
    main()
