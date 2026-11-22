"""Optional civilian undertakings attached to the settled PR #17 consultation register."""
import argparse
import json

from .civic_observer63 import run as run_original


def run(seed, years, *, consult=True, pledges=False):
    """Yield (original economy, original civic pairs, optional bilateral undertakings).

    The additional register can see only the civic pairs, whose evidence ends in the
    preceding year. It has no reference to the economic engine or its current ledger.
    """
    if type(consult) is not bool or type(pledges) is not bool:
        raise ValueError("consult and pledges must be boolean")
    register = None
    if pledges:
        from .civic_pledges64 import CivicPledges
        register = CivicPledges(seed)
    mode = "consult" if consult else "observe"
    for economy,pairs in run_original(seed,years,mode):
        promises = register.advance(economy["year"],pairs) if register is not None else None
        yield economy,pairs,promises


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed",required=True,type=int)
    parser.add_argument("--years",required=True,type=int)
    parser.add_argument("--consult",action=argparse.BooleanOptionalAction,default=True)
    parser.add_argument("--pledges",action="store_true")
    options = parser.parse_args()
    for economy,_,promises in run(options.seed,options.years,consult=options.consult,pledges=options.pledges):
        print(json.dumps({"schema":"civil-pledges/1","seed":options.seed,"year":economy["year"],
                          "consult":options.consult,"pledges_enabled":options.pledges,
                          "pledges":None if promises is None else list(promises.values())},
                         sort_keys=True,separators=(",",":")))


if __name__=="__main__":
    main()
