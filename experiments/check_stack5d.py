"""Read-only validation of the pinned PR #4–#10 stack via independent Git archives."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

PULL_REQUESTS = (
    (4, "102dd33cb2e9f56cbf4461a18f048d657a6de582", "64fcfeb1a83c046ed523949583c251abc329dfbf"),
    (5, "64fcfeb1a83c046ed523949583c251abc329dfbf", "881469a70083db50fd38525cc2335cdf5748f2f1"),
    (6, "881469a70083db50fd38525cc2335cdf5748f2f1", "a8172b9c92662872d5fb4d8acd1c015ad8c13e30"),
    (7, "a8172b9c92662872d5fb4d8acd1c015ad8c13e30", "37935d78954b5c11de697257a8d38a4cb7a1d3c9"),
    (8, "37935d78954b5c11de697257a8d38a4cb7a1d3c9", "739a1685c249d04854e67d6334ab83feacde8fb9"),
    (9, "739a1685c249d04854e67d6334ab83feacde8fb9", "b7c2aaacbb6d95f6788b398b4152056bf8b7325f"),
    (10, "b7c2aaacbb6d95f6788b398b4152056bf8b7325f", "c220dc526d88b4e08396cdbd7a7717d7a0c59cf7"),
)


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def examples(commit):
    rows = git("ls-tree", "-r", commit, "--", "examples").splitlines()
    return {path: info.split()[2] for info, path in (r.split("\t", 1) for r in rows)}


def check(entry):
    number, base, head = entry
    if git("merge-base", base, head) != base:
        raise ValueError(f"PR {number} base is not an ancestor")
    before, after = examples(base), examples(head)
    changed = [p for p in before if before[p] != after.get(p)]
    with TemporaryDirectory() as folder:
        snapshot = Path(folder, "source")
        archive = Path(folder, "source.zip")
        subprocess.run(["git", "archive", "--format=zip", "-o", str(archive), head], check=True)
        with ZipFile(archive) as f:
            f.extractall(snapshot)
        run = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-q"], cwd=snapshot,
                             capture_output=True, text=True, errors="replace")
        trace = run.stderr + run.stdout
        if run.returncode or not re.search(r"^OK$", trace, re.M):
            raise RuntimeError(f"PR {number} tests failed\n{trace[-5000:]}")
        match = re.search(r"Ran (\d+) tests in ([\d.]+)s", trace)
        if not match:
            raise ValueError("test count missing")
    return {"pr": number, "base": base, "head": head, "ancestor": True, "previous_examples": len(before),
            "changed_or_removed_examples": changed, "new_examples": len(after.keys() - before.keys()),
            "tests_passed": int(match[1]), "seconds": float(match[2])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output already exists")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(check, PULL_REQUESTS))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print([(r["pr"], r["tests_passed"]) for r in results])
