"""Same-opening peacetime enrollment interventions. Both branches retain existing personnel."""
from civsim import peace62
from experiments.depot_forks62 import run_cli


if __name__=="__main__":
    run_cli(peace62,peace62.fork_recruit62,[(0,1),(0,3)],"D")
