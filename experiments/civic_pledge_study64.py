"""Replay optional two-party civilian pledges on the unmodified PR 17 economic archive."""
import argparse
from collections import Counter
from contextlib import ExitStack
import csv
import gzip
import hashlib
from itertools import combinations
import json
from pathlib import Path
import platform
from tempfile import TemporaryDirectory
import time

from civsim.storage import canonical_line
from experiments.civic_disputes63 import ECONOMIC, HORIZONS, MODES, verify_tables, write_json, write_table
from experiments.phase6a import compressed, digest_file, emit


PRIOR = Path(__file__).resolve().parents[1]/"examples/phase6c1"
PAIRS = tuple(combinations(range(8), 2))
PAIR_METRICS = ("pair_years", "observed_years", "source_accepted", "source_declined", "source_defer", "source_none",
                "signed", "no_agreement", "defer", "none", "assessed", "joint_kept", "joint_broken", "joint_unknown",
                "party_kept", "party_broken", "party_unknown", "different_party_verdicts")
COUNTRY_METRICS = ("signature_decisions", "signed_individually", "declined_individually",
                   "jointly_committed", "assessed", "kept", "broken", "unknown")
FORK_METRICS = ("pair_years", "decision_changed", "joint_signature_changed", "individual_signature_changed",
                "scored_signature_changed", "joint_gained", "joint_lost")
ACTION_FIELDS = ("seed", "year", "mode", "a", "b", "country", "partner", "phase", "kind", "signed_year",
                 "economic_year", "due_year", "source_decision", "joint", "status", "reason", "source",
                 "target", "baseline", "actual", "opportunities", "base_score", "history_score", "score",
                 "partner_last_known", "partner_known_year", "history_hidden_sign")


def check_source_pair(a, b):
    identity = ("seed", "year", "a", "b", "evidence_year", "observed", "evidence", "signal", "event")
    if any(a[k] != b[k] for k in identity) or any(a["closing"][k] != b["closing"][k] for k in ("active","quiet_years")):
        raise ValueError("consultation paths have different settled economics or dispute evidence")


def summarize_settlement(*, signed, assessed, kept, broken, unknown):
    if (not 0 <= assessed <= signed or min(kept, broken, unknown) < 0
            or 2*assessed != kept+broken+unknown):
        raise ValueError("signed pledges and mature party judgments do not close")
    return {"pending": signed-assessed, "pending_party_judgments": 2*(signed-assessed)}


def csv_rows(path):
    with path.open(encoding="utf8", newline="") as f:
        return list(csv.DictReader(f))


def checked_inputs(prior, sample, seeds):
    directory = prior/"diplomacy"/sample
    old = json.loads((directory/"execution.json").read_bytes())
    repeat = json.loads((directory.parent/f"final-replay-{sample}.json").read_bytes())
    if (old["sample"] != sample or repeat["sample"] != sample or old["table_sha256"] != repeat["table_sha256"]
            or repeat["replayed_civic_checkpoints"] != len(seeds)*2*len(HORIZONS)):
        raise ValueError("prior consultation study and its independent repeat disagree")
    for name, sha in old["table_sha256"].items():
        if digest_file(directory/name) != sha:
            raise ValueError("unverified historical civic input: "+name)
    fiscal = prior/"baseline"/"checkpoints.csv"
    fiscal_sha = digest_file(fiscal)
    if fiscal_sha != json.loads((fiscal.parent/"receipt.json").read_bytes())["table_sha256"]["checkpoints.csv"]:
        raise ValueError("historical economic replay changed")
    checkpoints = {(int(r["seed"]), int(r["year"])): r for r in csv_rows(fiscal)}
    civic = csv_rows(directory/"runs.csv")
    grid = {(int(r["seed"]),r["mode"],int(r["year"])): r for r in civic}
    if set(grid) != {(s, m, y) for s in seeds for m in MODES for y in HORIZONS} or len(grid) != len(civic):
        raise ValueError("incomplete historical grid")
    for (s,m,y), r in grid.items():
        historic = checkpoints[s,y]
        other = grid[s, "observe", y]
        if (r["initial_sha256"] != historic["initial_sha256"] or r["economic_years_sha256"] != historic["years_sha256"]
                or any(r[k] != other[k] for k in ECONOMIC)):
            raise ValueError("archived civic and economic paths diverge")
    return grid, {"pr17": old["table_sha256"], "economic_checkpoints_sha256": fiscal_sha}


def annual_sources(stream, seed, year):
    records, lines = {}, {}
    for mode in MODES:
        line = stream.readline()
        if not line:
            raise ValueError("truncated civic archive")
        row = json.loads(line)
        if row["mode"] != mode or row["year"] != year or len(row["pairs"]) != len(PAIRS):
            raise ValueError("archived path, year, or pair count differs")
        for pair, r in zip(PAIRS, row["pairs"], strict=True):
            if (r["seed"],r["year"],r["a"],r["b"]) != (seed,year,*pair):
                raise ValueError("archived pair out of order")
        records[mode], lines[mode] = row["pairs"], line
    for a,b in zip(records["observe"],records["consult"],strict=True):
        check_source_pair(a,b)
    return records, lines


def totals(counter):
    censored = summarize_settlement(signed=counter["signed"], assessed=counter["assessed"],
                                    kept=counter["party_kept"], broken=counter["party_broken"], unknown=counter["party_unknown"])
    return {**counter, **censored}


def summary_by_pair(counters):
    return totals(Counter({k: sum(c[k] for c in counters.values()) for k in PAIR_METRICS}))


class PathLedger:
    def __init__(self, seed, mode, enabled):
        from civsim.civic_pledges64 import CivicPledges
        self.seed, self.mode, self.enabled = seed, mode, enabled
        self.model = CivicPledges(seed) if enabled else None
        self.pairs = {p: Counter(dict.fromkeys(PAIR_METRICS,0)) for p in PAIRS}
        self.countries = {i: Counter(dict.fromkeys(COUNTRY_METRICS,0)) for i in range(8)}
        self.hash = hashlib.sha256()
        self.previous = {}

    def advance(self, year, source, line, stream):
        from civsim.civic_pledges64 import audit_pledge_pair
        result = self.model.advance(year,source) if self.enabled else {}
        if self.enabled and set(result) != set(PAIRS):
            raise ValueError("incomplete pledge journal")
        written = (canonical_line({"mode":self.mode+"_on","year":year,"pairs":[result[p] for p in PAIRS]})
                   if self.enabled else line)
        stream.write(written.decode("utf8"))
        self.hash.update(written)
        for pair, civic in zip(PAIRS,source,strict=True):
            t = self.pairs[pair]
            t["pair_years"] += 1
            t["observed_years"] += int(civic["observed"])
            t["source_"+civic["proposal"]["decision"]] += 1
            if self.enabled:
                r = result[pair]
                audit_pledge_pair(r,civic,self.previous.get(pair))
                self.post(pair, r)
            else:
                t["none"] += 1
        self.previous = result
        return result

    def post(self, pair, r):
        t = self.pairs[pair]
        agreement, settled = r["agreement"], r["settlement"]
        decision = agreement["decision"]
        t[decision] += 1
        for s in agreement["signatures"]:
            nation = self.countries[s["country"]]
            nation["signature_decisions"] += 1
            nation["signed_individually" if s["sign"] else "declined_individually"] += 1
        if decision == "signed":
            for i in pair:
                self.countries[i]["jointly_committed"] += 1
        if settled:
            t["assessed"] += 1
            t["joint_"+settled["status"]] += 1
            t["different_party_verdicts"] += int(len({p["status"] for p in settled["parties"]}) > 1)
            for p in settled["parties"]:
                nation = self.countries[p["country"]]
                nation["assessed"] += 1
                nation[p["status"]] += 1
                t["party_"+p["status"]] += 1


def run_study(out, sample, *, prior=PRIOR, verify=None):
    out = Path(out)
    if out.exists():
        raise FileExistsError(out)
    return perform_study(out, sample, prior, verify)


def inspect_fork(actual, hidden, civic, metrics, cases):
    if any(actual[k] != hidden[k] for k in ("opening","settlement","source_decision")):
        raise ValueError("hiding compliance history changed the opening, prior evaluation or current consultation")
    a, b = actual["agreement"], hidden["agreement"]
    observed = {s["country"]:s for s in a["signatures"]}
    masked = {s["country"]:s for s in b["signatures"]}
    if set(observed) != set(masked):
        raise ValueError("different countries at signature decision")
    metrics["pair_years"] += 1
    metrics["decision_changed"] += int(a["decision"] != b["decision"])
    gained = a["decision"] == "signed" and b["decision"] != "signed"
    lost = a["decision"] != "signed" and b["decision"] == "signed"
    metrics.update(joint_signature_changed=int(gained or lost), joint_gained=int(gained), joint_lost=int(lost))
    switches = 0
    weighted = False
    for i, sig in observed.items():
        alt = masked[i]
        if sig["base_score"] != alt["base_score"] or alt["history_score"] != 0:
            raise ValueError("the fork changed the economic score or failed to mask the memory")
        switches += int(sig["sign"] != alt["sign"])
        weighted |= bool(sig["history_score"])
        metrics["scored_signature_changed"] += int(sig["score"] != alt["score"])
    metrics["individual_signature_changed"] += switches
    tags = []
    if lost: tags.append("joint_lost")
    if gained: tags.append("joint_gained")
    if switches and not (gained or lost): tags.append("individual_only")
    if weighted and not switches: tags.append("score_only")
    if a["decision"] == "no_agreement": tags.append("no_agreement")
    settled = actual["settlement"]
    if settled:
        tags.append("assessment_"+settled["status"])
        if len({p["status"] for p in settled["parties"]}) > 1:
            tags.append("different_country_assessments")
    if actual["year"] == 200 and a["decision"] == "signed": tags.append("right_censored")
    for tag in tags:
        if tag not in cases:
            cases[tag] = {"category":tag,"source":civic,"actual":actual,"history_hidden":hidden}
    return masked


def write_actions(writer, row, hidden):
    a,b = row["a"],row["b"]
    common = {"seed":row["seed"],"year":row["year"],"mode":"consult_on","a":a,"b":b,
              "source_decision":row["source_decision"]}
    agreement = row["agreement"]
    for sig in agreement["signatures"]:
        i = sig["country"]
        writer.writerow({**common, "phase":"signature","kind":agreement["kind"],"country":i,"partner":sig["counterparty"],
                         "joint":agreement["decision"],"status":"yes" if sig["sign"] else "no",
                         "history_hidden_sign":int(hidden[i]["sign"]),
                         **{k:sig[k] for k in ("base_score","history_score","score","partner_last_known","partner_known_year")}})
    settlement = row["settlement"]
    if settlement:
        for p in settlement["parties"]:
            i = p["country"]
            writer.writerow({**common, "phase":"settlement", "country":i,"partner":b if i==a else a,
                             "joint":settlement["status"],
                             **{k:settlement[k] for k in ("signed_year","economic_year","due_year","kind")},
                             **{k:p[k] for k in ("source","target","status","reason","baseline","actual")},
                             "opportunities":p["actual_opportunities"]})


def seed_paths(seed, years, archive, historic, streams, tables):
    models = {(m,e):PathLedger(seed,m,e) for m in MODES for e in (False,True)}
    impact = Counter(dict.fromkeys(FORK_METRICS,0))
    cases = {}
    economic = Counter(observed_trade_value=0, observed_migrants=0)
    for year in range(1, years+1):
        source, lines = annual_sources(archive,seed,year)
        for r in source["consult"]:
            for direction in r["evidence"]:
                economic["observed_trade_value"] += direction["trade_value"]
                economic["observed_migrants"] += direction["migrants"]
        hidden = models["consult",True].model.fork(enabled=True,feedback=False)
        for (mode, enabled), path in models.items():
            path.advance(year,source[mode],lines[mode],streams["annual"])
            if enabled and canonical_line({"mode":mode,"year":year,"pairs":source[mode]}) != lines[mode]:
                raise ValueError("pledge register mutated archived civic or economic inputs")
        compared = hidden.advance(year,source["consult"])
        for idx, pair in enumerate(PAIRS):
            row = models["consult",True].previous[pair]
            alternatives = inspect_fork(row,compared[pair],source["consult"][idx],impact,cases)
            write_actions(streams["actions"],row,alternatives)
        if year in HORIZONS:
            for (mode,enabled), path in models.items():
                key={"seed":seed,"mode":mode,"pledges":"on" if enabled else "off","year":year}
                original = historic[seed,mode,year]
                if models[mode,False].hash.hexdigest() != original["civic_years_sha256"]:
                    raise ValueError("historical civic bytes differ")
                world = summary_by_pair(path.pairs)
                if enabled and mode=="observe" and world["signed"]:
                    raise ValueError("signature without any consultation")
                if world["signed"]+world["no_agreement"]+world["defer"]>world["source_accepted"]:
                    raise ValueError("registration decisions exceed accepted consultations")
                country_rows=[]
                for i,c in path.countries.items():
                    if c["assessed"]!=c["kept"]+c["broken"]+c["unknown"]:
                        raise ValueError("country evaluation ledger does not close")
                    country_rows.append({**key,"country":i,**c,"pending":c["jointly_committed"]-c["assessed"]})
                if sum(c["pending"] for c in country_rows)!=world["pending_party_judgments"]:
                    raise ValueError("country and pair pending totals disagree")
                tables["countries"].extend(country_rows)
                tables["runs"].append({**key,"register_sha256":path.hash.hexdigest(),"civic_years_sha256":original["civic_years_sha256"],
                                       "economic_years_sha256":original["economic_years_sha256"],"initial_sha256":original["initial_sha256"],
                                       **{k:int(original[k]) for k in ECONOMIC},**economic,**world})
                for (a,b), t in path.pairs.items():
                    tables["pairs"].append({**key,"a":a,"b":b,**totals(t)})
            tables["forks"].append({"seed":seed,"year":year,**impact})
    tables["cases"].extend(cases.values())


def perform_study(out, sample, prior, verify):
    started = time.perf_counter()
    seeds = {"dev":range(20),"holdout":range(20,40)}[sample]
    historic, references = checked_inputs(prior,sample,seeds)
    out.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=out.parent,prefix=".civil-pledges-") as temp:
        stage=Path(temp,"publication")
        stage.mkdir()
        tables={key:[] for key in ("runs","pairs","countries","forks","cases")}
        with ExitStack() as stack:
            source=stack.enter_context(gzip.open(prior/"diplomacy"/sample/"annual.jsonl.gz","rb"))
            annual=stack.enter_context(compressed(stage/"annual.jsonl.gz"))
            actions=stack.enter_context(compressed(stage/"party-events.csv.gz"))
            for seed in seeds:
                seed_paths(seed,200,source,historic,{"annual":annual,"actions":emit(actions,ACTION_FIELDS,header=(seed==seeds.start))},tables)
            if source.read(1):
                raise ValueError("trailing civic year after last archived seed")
        write_json(stage/"same-opening-cases.json",tables.pop("cases"))
        for name,rows in tables.items():
            write_table(stage/(name+".csv"),rows)
        write_json(stage/"source.json",{"sample":sample, "seeds":list(seeds),"archive":"phase6c1/PR17",**references})
        manifest={p.name:digest_file(p) for p in sorted(stage.iterdir())}
        if verify is not None:
            verify_tables(Path(verify),stage,manifest)
        count=len(tables["runs"])
        meta={"sample":sample,"seeds":len(seeds),"horizons":HORIZONS,"pledge_on_world_years":len(seeds)*200*2,
              "off_world_years":len(seeds)*200*2,"archived_civic_checkpoints":len(historic),
              "same_opening_pair_years":len(seeds)*200*len(PAIRS),"path_checkpoints":count,
              "verified_files":len(manifest) if verify else 0,"replayed_checkpoints":count if verify else 0,
              "table_sha256":manifest,"python":platform.python_version(),"wall_seconds":time.perf_counter()-started}
        write_json(stage/"execution.json",meta)
        if out.exists():
            raise FileExistsError(out)
        stage.rename(out)
    return meta


def read_outcomes(directory):
    """Analyze published artifacts independently of the pledge engine."""
    all_runs=csv_rows(directory/"runs.csv")
    index={(int(r["seed"]),r["mode"],r["pledges"],int(r["year"])):r for r in all_runs}
    seeds=sorted({int(r["seed"]) for r in all_runs})
    by_year={}
    for y in HORIZONS:
        rows=[index[s,"consult","on",y] for s in seeds]
        values={k:sum(int(r[k]) for r in rows) for k in (*PAIR_METRICS,"pending","pending_party_judgments")}
        values["worlds_without"]={k:sum(int(r[k])==0 for r in rows)
                                  for k in ("signed","no_agreement","defer","joint_kept","joint_broken","joint_unknown","pending")}
        for seed in seeds:
            comparison=index[seed,"observe","off",y]
            for mode in MODES:
                for enabled in ("off","on"):
                    r=index[seed,mode,enabled,y]
                    if any(r[k]!=comparison[k] for k in (*ECONOMIC,"initial_sha256","economic_years_sha256",
                                                          "observed_trade_value","observed_migrants")):
                        raise ValueError("economic projections differ across arms")
                    if (mode,enabled)!=("consult","on") and int(r["signed"]):
                        raise ValueError("promise without accepted consultation or registration")
        by_year[str(y)]=values
    verified=0
    with gzip.open(directory/"annual.jsonl.gz","rb") as raw:
        for seed in seeds:
            h={(m,e):hashlib.sha256() for m in MODES for e in ("off","on")}
            for year in range(1,201):
                for (m,e),digest in h.items():
                    line=raw.readline()
                    if not line:
                        raise ValueError("published follow-up journal ends prematurely")
                    digest.update(line)
                    if year in HORIZONS:
                        r=index[seed,m,e,year]
                        if (digest.hexdigest()!=r["register_sha256"] or
                                (e=="off" and digest.hexdigest()!=r["civic_years_sha256"])):
                            raise ValueError("checkpoint does not match published journal")
                        verified+=1
        if raw.read(1):
            raise ValueError("unexpected trailing journal content")
    grouped={kind:Counter() for kind in ("trade","exit","entry")}
    country=Counter()
    reasons=Counter()
    with gzip.open(directory/"party-events.csv.gz","rt",encoding="utf8",newline="") as source:
        for r in csv.DictReader(source):
            t=grouped[r["kind"]]
            if r["phase"]=="signature":
                t["signature_"+r["status"]]+=1
                t["joint_"+r["joint"]+"_signature_rows"]+=1
                sign=r["status"]=="yes"
                if sign != bool(int(r["history_hidden_sign"])):
                    t["changed_yes" if sign else "changed_no"]+=1
            else:
                t[r["status"]]+=1
                reasons[r["reason"]]+=1
                country[int(r["seed"]),int(r["country"]),r["status"]]+=1
    endpoints=[r for r in csv_rows(directory/"countries.csv")
               if (r["mode"],r["pledges"],int(r["year"]))==("consult","on",200)]
    for r in endpoints:
        if any(country[int(r["seed"]),int(r["country"]),s]!=int(r[s]) for s in ("kept","broken","unknown")):
            raise ValueError("country table differs from independent party postings")
    forks=csv_rows(directory/"forks.csv")
    changes={str(y):{k:sum(int(r[k]) for r in forks if int(r["year"])==y) for k in FORK_METRICS} for y in HORIZONS}
    n200=by_year["200"]
    if (sum(t["kept"]+t["broken"]+t["unknown"] for t in grouped.values())!=2*n200["assessed"]
            or sum(t["joint_signed_signature_rows"] for t in grouped.values())!=2*n200["signed"]
            or sum(t["changed_yes"]+t["changed_no"] for t in grouped.values())!=changes["200"]["individual_signature_changed"]):
        raise ValueError("type and party postings differ from world or fork totals")
    return {"by_year":by_year,"same_opening":changes,"by_type":grouped,"assessment_reasons":reasons,
            "verified_journal_checkpoints":verified,"verified_country_endpoints":len(endpoints)}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--sample",choices=("dev","holdout"))
    action.add_argument("--summarize",type=Path,help="read both previously published samples")
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--verify-against",type=Path)
    args=parser.parse_args()
    if args.summarize:
        write_json(args.out,{sample:read_outcomes(args.summarize/sample) for sample in ("dev","holdout")})
    else:
        print(json.dumps(run_study(args.out,args.sample,verify=args.verify_against)))
