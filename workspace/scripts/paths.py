"""Directories of the workspace. Inputs (model files, fabrics, workloads) are
under models/; everything the pipeline produces is written under results/,
one subdirectory per stage, so a fresh checkout reproduces the paper by
running the stages in order (docs/08_reproduce_paper.md).

    results/reference/   the reference measurements: the 2.7B-class account,
                         the intra-die instance and its levers, the Simba
                         seating reference
    results/accounts/    per-operator accounts of the models (one CiMLoop
                         mapper run per operator) and the LM-head costs
    results/records/     one directory per deployment experiment
    results/booksim/     the BookSim validation libraries
    results/exports/     the tables behind every figure and table
"""
import os

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(WS, "models")
FABRICS = os.path.join(MODELS, "fabric")
RESULTS = os.environ.get("ISOBAR_RESULTS") or os.path.join(WS, "results")
REFERENCE = os.path.join(RESULTS, "reference")
ACCOUNTS = os.path.join(RESULTS, "accounts")
RECORDS = os.path.join(RESULTS, "records")
BOOKSIM = os.path.join(RESULTS, "booksim")
EXPORTS = os.path.join(RESULTS, "exports")
OUTPUTS = os.path.join(WS, "outputs")                 # CiMLoop mapper run directories

# the reference 2.7B-class account (one transformer block, S = 512)
REFERENCE_ACCOUNT = os.path.join(REFERENCE, "reference_2p7b_S512.json")
# the intra-die instance (Fig. 1(a)): per-operator records of one GPT-2-medium-class
# block on the 2x4 macro die, and the uniform-flow lever fit on that die
INTRADIE_INSTANCE = os.path.join(REFERENCE, "intradie_instance.json")
INTRADIE_LEVERS = os.path.join(REFERENCE, "intradie_levers.json")
# the Simba seating reference (Fig. 3(a))
SIMBA_SEATING = os.path.join(REFERENCE, "simba_seating.json")
# LM-head and embedding costs of the evaluated models
MODEL_END_COSTS = os.path.join(ACCOUNTS, "model_end_costs.json")


def ensure(*dirs):
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    return dirs[0] if len(dirs) == 1 else dirs
