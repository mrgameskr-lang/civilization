"""Explain missing sets at the observed checkout boundary in each published regional ledger."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

from civsim.storage import canonical_line
from experiments.priority_receipts import shortage

BANDS = ("1-50","51-100","101-200")


def summarize_regions(study):
    report={}
    for seed in range(40):
        sample="dev" if seed<20 else "validation"
        checkpoints=json.loads((study/f"seed-{seed:02}.json").read_bytes())
        for arm in ("move_on","relief_first"):
            bins=[Counter() for _ in BANDS]
            with gzip.open(study/f"seed-{seed:02}-{arm}.jsonl.gz","rt",encoding="utf8") as f:
                header=json.loads(next(f))
                cols=header["columns"]
                if (header["seed"],header["arm"])!=(seed,arm):
                    raise ValueError("regional file identity differs")
                npos=cols.index("marked")
                for year,line in enumerate(f,1):
                    band=0 if year<=50 else 1 if year<=100 else 2
                    counts=bins[band]
                    for raw in json.loads(line):
                        if not raw[npos]:
                            continue
                        r=dict(zip(cols,raw,strict=True))
                        n,F,T=(r[k] for k in ("marked","before_food","before_tools"))
                        paid,food,tools,both=shortage(n,F,T)
                        if (paid,food,tools,both)!=tuple(r[k] for k in
                                ("paid","missing_food_only","missing_tools_only","missing_both")):
                            raise ValueError("published shortage counts differ from observed balances")
                        counts.update(marked=n,paid=paid,food_only=food,tools_only=tools,both=both,region_years=1)
                        incoming=(r["depot_open_food"]+r["levy_deposited_food"]+r["depot_transfer_received_food"]
                                  +r["aid_received_food"])
                        if incoming < F:
                            raise ValueError("food shelf exceeds total local inflows plus opening")
                        counts["missing_food_even_before_any_debit"]+=max(0,n-incoming)
                        counts["missing_food_at_checkout"]+=max(0,n-F)
                        counts["marked_when_no_opening_or_incoming_food"]+=n if incoming==0 else 0
                        counts["marked_when_no_net_food_levy"]+=n if r["levy_deposited_food"]==0 else 0
                        counts["marked_when_checkout_food_zero"]+=n if F==0 else 0
                        counts["marked_when_checkout_tools_zero"]+=n if T==0 else 0
                        # Local receipts seen earlier, held fixed. Independent one-expense accounting
                        # bounds overlap; these are not reruns under alternative spending decisions.
                        expenses={
                            "works":(r["works_used_food"]+r["works_freight_food"],r["works_used_tools"]),
                            "aid":(r["aid_sent_food"]+r["aid_freight_food"],0),
                            "relief":((r["relief_sent_food"]+r["relief_freight_food"]) if arm=="relief_first" else 0,0),
                            "earlier_resident_issue":(r["old_public_issue_food"],0)}
                        for kind,(f_cost,t_cost) in expenses.items():
                            counts[kind+"_food_at_marked_depots"]+=f_cost
                            counts[kind+"_tools_at_marked_depots"]+=t_cost
                            counts[kind+"_fixed_receipt_extra_sets"]+=min(n,F+f_cost,T+t_cost)-paid
                        for k in ("depot_open_food","levy_deposited_food","depot_transfer_received_food",
                                  "aid_received_food","before_food","before_tools","after_food","after_tools"):
                            counts[k]+=r[k]
                if year!=200:
                    raise ValueError("incomplete regional trajectory")
            for i,(band,c) in enumerate(zip(BANDS,bins,strict=True)):
                point=checkpoints["arms"][arm]["checkpoints"][i]["cumulative"]
                for k,field in (("marked","marked_turns"),("paid","paid_turns"),("food_only","missing_food_only"),
                                ("tools_only","missing_tools_only"),("both","missing_both")):
                    if sum(b[k] for b in bins[:i+1])!=point[field]:
                        raise ValueError("regional counts disagree with seed checkpoints")
                report.setdefault(sample,{}).setdefault(arm,{}).setdefault(band,Counter()).update(c)
    return {"periods":BANDS,"samples":report,
            "attribution":"Earlier-debit sensitivities hold other postings and the opening fixed. They overlap and cannot be summed."}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    result=summarize_regions(args.study)
    with args.out.open("xb") as f:
        f.write(canonical_line(result))
