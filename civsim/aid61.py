"""Standalone run/replay entry point for 6.0A.1; historical archive readers keep their original schema."""
import argparse
import json
import os
from pathlib import Path

from .diplomacy61 import ARMS, snapshot61, start61, step61
from .model import generate_world
from .regional_storage import _publish, _verify_stream
from .regions import regionalize


def _inputs(meta):
    fields = {"schema","model_version","arm","seed","years","nations","width","height","per_nation"}
    if (set(meta)!=fields or type(meta["schema"]) is not int or meta["schema"]!=1 or meta["model_version"]!="6.0A.1"
            or meta["arm"] not in ARMS or type(meta["years"]) is not int or meta["years"]<1):
        raise ValueError("invalid 6.0A.1 manifest")
    world = generate_world(meta["seed"],meta["width"],meta["height"],meta["nations"])
    sim = start61(regionalize(world,meta["per_nation"]))
    return snapshot61(sim), lambda year:step61(sim,year,meta["arm"])


def write_run61(directory, *, seed=0, years=50, arm="F", width=48, height=32, nations=8, per_nation=4):
    directory = Path(directory)
    if os.path.lexists(directory):
        raise FileExistsError(directory)
    meta = {"schema":1,"model_version":"6.0A.1","arm":arm,"seed":seed,"years":years,"nations":nations,
            "width":width,"height":height,"per_nation":per_nation}
    _publish(directory,meta,*_inputs(meta))


def verify_run61(directory):
    directory = Path(directory)
    meta = json.loads((directory/"manifest.json").read_bytes())
    return _verify_stream(directory,meta,*_inputs(meta))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command",required=True)
    run = commands.add_parser("run")
    run.add_argument("--arm",choices=ARMS,default="F")
    run.add_argument("--seed",type=int,default=0)
    run.add_argument("--years",type=int,default=50)
    run.add_argument("--out",type=Path,required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("directory",type=Path)
    args = cli.parse_args()
    if args.command=="run":
        write_run61(args.out,arm=args.arm,seed=args.seed,years=args.years)
        print(args.out)
    else:
        print(verify_run61(args.directory))


if __name__ == "__main__":
    main()
