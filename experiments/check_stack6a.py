"""Preview each pinned integration tree and independently test all eight snapshots."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from experiments.check_stack5d import PULL_REQUESTS, check, git

STACK = (*PULL_REQUESTS, (11, "c220dc526d88b4e08396cdbd7a7717d7a0c59cf7", "a4721bd26a685dba1a8f46bddc14e4a2c560e6f9"))


def preview(entry):
    number, base, head = entry
    tree = git("merge-tree", "--write-tree", base, head)
    if tree != git("rev-parse", head+"^{tree}"):
        raise ValueError(f"PR {number} integration tree differs from tested head")
    return {**check(entry), "integration_tree": tree}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--workers", type=int, default=3)
    args = p.parse_args()
    if args.out.exists():
        p.error("output already exists")
    if any(lower[2] != upper[1] for lower, upper in zip(STACK, STACK[1:])):
        p.error("the pinned snapshots do not form a contiguous chain")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(preview, STACK))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(results, f, indent=2)
        f.write("\n")
    print([(r["pr"], r["tests_passed"], r["previous_examples"]) for r in results])
