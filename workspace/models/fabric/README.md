# models/fabric: the physical fabric

A fabric file declares the physical structure the placement-aware overlay
prices: the levels (package, die, macro, core, crossbar), how many children
each level has and in what grid, the link of each level with its topology,
routing and calibration tag, the port model, and the device's row time.
`scripts/fabric.py` loads and validates them; `CIMSIM_FABRIC=<file>`
selects one for a mapper-side run, and `--fabric <file>` selects one on
the command line (`scripts/cimsim_cli.py`). A level may declare its port
ratio as `ports: {ratio: kappa}`; the main configuration declares 2 on
the die level, which the command line takes as its default `--kappa`.

| file | system |
|---|---|
| `mlx300_multidie576.yaml` | the main configuration: 576 die slots on a 24x24 mesh, XY routing; the 2.7B-class model occupies 544 |
| `mlx300_multidie48.yaml` | the 48-die package of the GPT-2-medium class studies |
| `mlx300_multidie.yaml` | the earlier 24-die package, retired from the results |
| `mlx300.yaml` | one die: the fill-exact 2x4 macro and 4x2 crossbar grids, the default since C27 |
| `mlx300_3x3.yaml` | one die with the earlier 3x3 grids, kept for comparison |
| `mlx300_mesh.yaml` | one die with its macro NoC modelled as a 2-D mesh with XY routing instead of the default star; the other levels stay star |
| `simba.yaml` | the Simba package as reproduced for the silicon comparison |

The device block of a fabric is checked against the macro model on every
run, so a fabric cannot silently declare a row time its macro does not have.
