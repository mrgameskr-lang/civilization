"""Replay untouched 6.0A A/B. The six-arm experiment separately replays C/D."""
import argparse
import csv
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path

from civsim.diplomacy import diplomacy_snapshot, start_diplomacy, step_diplomacy
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.publication import publish_file
from tempfile import TemporaryDirectory

ARCHIVE = Path(__file__).resolve().parents[1]/"examples"/"phase6a"/"study"


def replay(task):
    seed,arm,expected = task
    sim = start_diplomacy(regionalize(generate_world(seed)))
    initial = hashlib.sha256(canonical_line(diplomacy_snapshot(sim))).hexdigest()
    digest = hashlib.sha256()
    results = []
    for y in range(1,201):
        digest.update(canonical_line(step_diplomacy(sim,y,arm)))
        if y in expected:
            if (initial,digest.hexdigest()) != expected[y]:
                raise ValueError(f"6.0A archive mismatch: {seed}/{arm}/{y}")
            results.append({"seed":seed,"arm":arm,"year":y,"sha256":digest.hexdigest()})
    return results


def verify(directory,workers):
    tasks = {}
    for sample in ("dev","holdout"):
        with (ARCHIVE/sample/"runs.csv").open(encoding="utf8",newline="") as src:
            for r in csv.DictReader(src):
                if r["arm"] in ("A","B"):
                    key = (int(r["seed"]),r["arm"])
                    tasks.setdefault(key,{})[int(r["year"])] = (r["initial_sha256"],r["years_sha256"])
    if set(tasks) != {(s,a) for s in range(40) for a in ("A","B")} or any(set(v)!={50,100,200} for v in tasks.values()):
        raise ValueError("historical reference grid incomplete")
    if directory.exists() or directory.is_symlink():
        raise FileExistsError(directory)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        checks = [row for chunk in pool.map(replay,[(s,a,v) for (s,a),v in tasks.items()]) for row in chunk]
    directory.parent.mkdir(exist_ok=True,parents=True)
    with TemporaryDirectory(dir=directory.parent) as work:
        output = Path(work)/"checked.json"
        output.write_text(json.dumps({"annual_transitions":16000,"verified":checks},indent=2)+"\n",encoding="utf8",newline="\n")
        publish_file(output,directory)
    print(f"{len(checks)} historical checkpoints matched")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--workers",default=8,type=int)
    args = parser.parse_args()
    verify(args.out,args.workers)
