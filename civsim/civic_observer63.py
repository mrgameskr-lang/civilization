"""Optional civilian dispute register on the unmodified 6.0B2 D economic path."""
import argparse
import json

from . import peace62
from .civic_diplomacy63 import CivicDiplomacy
from .model import generate_world
from .regions import regionalize


def closed_directions(seed, ledger):
    """The published foreign-years export omits directions with neither adjacency nor an aid signal."""
    rows = []
    for pair in ledger["diplomacy"]["pairs"]:
        for flow,policy in zip(pair["flows"]["directions"],pair["policy"]["directions"],strict=True):
            if (flow["source"],flow["target"]) != (policy["source"],policy["target"]):
                raise ValueError("direction in the settled flow disagrees with its approval")
            if not (pair["adjacent"] or policy["aid_request"] or policy["aid_offer"]):
                continue
            rows.append(dict(seed=seed,year=ledger["year"],arm="D",source=flow["source"],target=flow["target"],
                             breach=int(flow["agreement_breach"]),trade_value=flow["trade_value"],
                             trade_food=flow["goods"]["food"],trade_ore=flow["goods"]["ore"],
                             trade_tools=flow["goods"]["tools"],trade_denied=flow["trade_denied"],
                             migrants=flow["migrants"],exit_denied=flow["migration_denied_exit"],
                             entry_denied=flow["migration_denied_entry"],closing_tension=pair["closing"]["tension"],
                             closing_trust=pair["closing"]["trust"]))
    return rows


def run(seed, years, mode="observe"):
    """Yield (original economic ledger, optional pair register); year one has no prior settlement."""
    if type(years) is not int or years<0 or mode not in ("off","observe","consult"):
        raise ValueError("invalid horizon or civilian observation mode")
    world = regionalize(generate_world(seed))
    economy = peace62.start62(world)
    observer = None if mode=="off" else CivicDiplomacy(seed,nations=len(world.nations),consult=mode=="consult")
    previous = ()
    for year in range(1,years+1):
        pairs = observer.advance(year,previous) if observer is not None else None
        ledger = peace62.step62(economy,year,"D")
        if observer is not None:
            previous = closed_directions(seed,ledger)
        yield ledger,pairs


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed",type=int,required=True)
    parser.add_argument("--years",type=int,required=True)
    parser.add_argument("--mode",choices=("off","observe","consult"),default="observe")
    args = parser.parse_args()
    for ledger, pairs in run(args.seed,args.years,args.mode):
        row = {"seed":args.seed,"year":ledger["year"],"mode":args.mode,
               "pairs":list(pairs.values()) if pairs is not None else None}
        print(json.dumps(row,sort_keys=True,separators=(",",":")))
