"""Regenerate and verify the published civilian pledge summary in a fresh process."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from experiments.civic_disputes63 import verify_tables, write_json
from experiments.phase6a import digest_file


def check(study, out):
    if out.exists():
        raise FileExistsError(out)
    with TemporaryDirectory(dir=out.parent) as scratch:
        summary = Path(scratch)/"outcomes.json"
        subprocess.run([sys.executable, "-B", "-m", "experiments.civic_pledge_study64",
                        "--summarize", str(study), "--out", str(summary)], check=True)
        verify_tables(study, summary.parent, ("outcomes.json",))
        samples = json.loads(summary.read_bytes())
        checkpoints = sum(s["verified_journal_checkpoints"] for s in samples.values())
        write_json(out, {"identical": True, "sha256": digest_file(summary), "raw_checkpoints": checkpoints})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    check(args.study, args.out)
