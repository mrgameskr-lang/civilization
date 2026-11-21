"""Write and verify immutable public-depot archives from the Python command line."""
import argparse
import json
import os
from pathlib import Path

from . import supply62
from .model import generate_world
from .regional_storage import _publish, _verify_stream
from .regions import regionalize


def archive(directory, *, meta=None, model="6.0B1", arms=("A","B"), engine=supply62):
    directory = Path(directory)
    writing = meta is not None
    if writing and os.path.lexists(directory):
        raise FileExistsError(directory)
    if not writing:
        meta = json.loads((directory/"manifest.json").read_bytes())
    if (set(meta) != {"schema","model_version","seed","years","arm"} or type(meta["schema"]) is not int
            or meta["schema"]!=1 or meta["model_version"]!=model or meta["arm"] not in arms
            or type(meta["seed"]) is not int or type(meta["years"]) is not int or meta["years"]<1):
        raise ValueError("invalid public-economy manifest")
    sim = engine.start62(regionalize(generate_world(meta["seed"])))
    initial = engine.snapshot62(sim)
    def annual(year):
        return engine.step62(sim,year,meta["arm"])
    if writing:
        _publish(directory,meta,initial,annual)
        return directory
    return _verify_stream(directory,meta,initial,annual)


def main(model="6.0B1", arms=("A","B"), engine=supply62):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation",required=True)
    run = commands.add_parser("run")
    run.add_argument("--seed",type=int,default=0)
    run.add_argument("--years",type=int,default=50)
    run.add_argument("--arm",choices=arms,default=arms[-1])
    run.add_argument("--out",type=Path,required=True)
    commands.add_parser("verify").add_argument("directory",type=Path)
    args = parser.parse_args()
    if args.operation=="run":
        meta=dict(schema=1,model_version=model,seed=args.seed,years=args.years,arm=args.arm)
        print(archive(args.out,meta=meta,model=model,arms=arms,engine=engine))
    else:
        print(archive(args.directory,model=model,arms=arms,engine=engine))


if __name__=="__main__":
    main()
