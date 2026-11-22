"""Paired readout and replay check for the published reserve/emergency scenario."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from civsim.annual_game import create
from civsim.peace62 import snapshot62
from civsim.relief_benefits import relief_benefits
from civsim.storage import canonical_line
from experiments.food_reserve_study import CHECKPOINTS, digest
from experiments.reserve_relief_study import advance


ARCHIVE = Path(__file__).resolve().parents[1] / "examples/reserve-relief-v1/study"


def check_world(seed, years, out):
    control = create(seed)
    observed = deepcopy(control)
    opening = digest(snapshot62(control.economy))
    archive = json.loads((ARCHIVE / f"seed-{seed:02}.json").read_bytes())
    frozen = archive["annual_hashes"]["E"]
    if archive["seed"] != seed or set(frozen) != {str(y) for y in CHECKPOINTS}:
        raise ValueError(f"incomplete or misidentified E checkpoint manifest for seed {seed}")
    checks, exposure, changes = {}, Counter(), Counter()
    years_file = out / f"seed-{seed:02}-years.jsonl"
    receipts_file = out / f"seed-{seed:02}-receipts.jsonl"
    with years_file.open("xb") as series, receipts_file.open("xb") as receipts:
        for year in range(1, years + 1):
            off = advance(control, year, "E")
            on = advance(observed, year, "E")
            view = relief_benefits(on)
            off_hash, on_hash = digest(off), digest(on)
            if off_hash != on_hash or control.away != observed.away:
                raise ValueError(f"observation changed annual game record at {seed}/{year}")
            if str(year) in frozen:
                if off_hash != frozen[str(year)]:
                    raise ValueError(f"archived E checkpoint mismatch at {seed}/{year}")
                checks[str(year)] = off_hash
            if year <= 16:
                receipts.write(canonical_line(view))
                for row in view["regions"]:
                    extra = row["emergency_received"]
                    exposure["region_years"] += 1
                    exposure["ordinary"] += row["ordinary_received"]
                    exposure["emergency"] += extra
                    exposure["emergency_region_years"] += int(extra > 0)
                    if row["ordinary_received"] == 0 and extra > 0:
                        exposure["only_emergency"] += extra
                        exposure["only_emergency_region_years"] += 1
            for a, b in zip(off["politics"]["regions"], on["politics"]["regions"], strict=True):
                for group, g in a["closing"]["groups"].items():
                    for metric in ("support", "discontent"):
                        changes[metric] += int(g[metric] != b["closing"]["groups"][group][metric])
            for a, b in zip(off["competition"]["countries"], on["competition"]["countries"], strict=True):
                changes["elections_observed"] += int(a["election"]["election"])
                changes["election_results"] += int(a["election"] != b["election"])
            for a, b in zip(off["government"]["accounts"], on["government"]["accounts"], strict=True):
                changes["policy_decisions"] += int(a["decision"] != b["decision"])
            # Keep separate digests for each political and fiscal ledger.
            comparisons = {}
            for key in ("politics", "competition", "government", "collective"):
                comparisons[key] = {"off": digest(off[key]), "on": digest(on[key])}
            series.write(canonical_line({
                "year": year, "off": off_hash, "on": on_hash, "comparisons": comparisons,
                "elections": sum(c["election"]["election"] for c in on["competition"]["countries"]),
                "turnovers": sum(c["election"]["turnover"] for c in on["competition"]["countries"]),
            }))
    if snapshot62(control.economy) != snapshot62(observed.economy):
        raise ValueError("closing world states differ")
    return {"seed": seed, "years": years, "common_opening": opening,
            "closing": digest(snapshot62(observed.economy)), "archived_e": checks,
            "first_16_exposure": dict(exposure),
            "equal_annual_records": years, "political_comparison_counts": dict(changes)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 20])
    parser.add_argument("--years", type=int, default=200)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if (not 1 <= args.years <= 200 or len(set(args.seeds)) != len(args.seeds)
            or not set(args.seeds) <= set(range(40))):
        parser.error("use distinct published seeds 0..39 and 1..200 years")
    args.out.mkdir(parents=True, exist_ok=False)
    rows = [check_world(seed, args.years, args.out) for seed in args.seeds]
    with (args.out / "summary.json").open("xb") as stream:
        stream.write(canonical_line({"scenario": "E", "comparison": "reading arrival benefits on/off",
                                    "worlds": rows}))
    print(json.dumps(rows, sort_keys=True))


if __name__ == "__main__":
    main()
