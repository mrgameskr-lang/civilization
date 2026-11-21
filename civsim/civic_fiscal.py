"""5.0D fiscal responses and tax settlement from lagged, realized civic participation."""
from types import SimpleNamespace

from .fiscal_policy import _posting, audit_collection
from .model import GOODS
from .political_rules import GROUPS


ACTIVE = ("petition", "protest", "strike", "refusal")


def _check(ok, message):
    if not ok:
        raise ValueError("civic finance: " + message)


def withheld_labor(regions, context):
    rows = {r["id"]:r for r in context["regions"]}
    _check(len(rows)==len(context["regions"]) and set(rows)=={r.id for r in regions}, "region coverage")
    held = {}
    for r in regions:
        row = rows[r.id]
        groups = row["groups"]
        _check(row["owner"]==r.owner and set(groups)==set(GROUPS), "group identity")
        for g in groups.values():
            m,p,w = (g[k] for k in ("members","participants","withheld_workers"))
            _check(all(type(q) is int for q in (m,p,w)) and 0 <= w <= p <= m
                   and (g["action"] in ("protest","strike") or w==0), "invalid or duplicated worker withdrawal")
        held[r.id] = sum(g["withheld_workers"] for g in groups.values())
        _check(sum(g["members"] for g in groups.values())<=r.population and held[r.id]<=r.population//2,
               "participants exceed residents or available workers")
    return held


def _summary(plan):
    edge = plan["target_edge"]
    return {"action":plan["action"], "target_region":plan["target_region"],
            "target_edge":list(edge) if edge is not None else None, "quantity":plan["quantity"],
            "budget":plan["budget"].copy(), "economic_score":plan["selected_score"]}


def _select(plan, option):
    edge, action, region = option["target_edge"], option["action"], option["target_region"]
    return {**plan, "action":action, "target_region":region, "target_edge":edge,
            "target":edge if action=="road" else region, "quantity":option["quantity"],
            "budget":option["budget"].copy(), "admin_units":option["budget"]["admin_units"],
            "selected_score":option["score"], "relief_limit":option["quantity"] if action=="relief" else 0}


def respond(plan, local):
    """Use one existing appropriation. A tax compromise also costs foregone standing revenue."""
    voices = [(row["id"], name, row["groups"][name]) for row in local for name in GROUPS
              if row["groups"][name]["action"] in ACTIVE and row["groups"][name]["participants"]]
    voices.sort(key=lambda v:(-v[2]["participants"],-v[2]["duration"],v[0],GROUPS.index(v[1])))
    slots = plan["relief_throughput"]
    petitions = sum((g["participants"]+31)//32 for _,_,g in voices if g["action"]=="petition")
    receipt = {"id":plan["owner"],"kind":"maintain","target_region":None,"target_group":None,
               "concession_region":None,"concession_group":None,"legal_concession_permille":0,
               "petition_admin_used":min(slots,petitions),"admin_before":slots,"admin_remaining":max(0,slots-petitions),
               "score_allowance":0,"before":_summary(plan),"after":_summary(plan)}
    if not voices:
        return plan,receipt
    target,name,primary = voices[0]
    allowance = min(512, primary["participants"]*8//32)
    receipt.update(target_region=target,target_group=name,score_allowance=allowance)
    candidates = [c for c in plan["candidates"] if c["action"]==primary["demand"] and c["permitted"]
                  and not c["constraints"] and (c["action"]=="defer" or (c["score"]>0 and c["quantity"]>0))
                  and (c["action"]=="defer" or c["target_region"]==target or target in (c["target_edge"] or ()))
                  and c["score"]+allowance>=plan["selected_score"]]
    approved = plan
    if candidates:
        approved = _select(plan,max(candidates,key=lambda c:(c["score"],c["population_loss"])))
        if _summary(approved) != receipt["before"]:
            receipt["kind"] = "defer" if approved["action"]=="defer" else "reprioritize"
    refusing = next(((i,k) for i,k,g in voices if g["action"]=="refusal"),None)
    if refusing is not None:
        # A standing tax cut needs no extra project/labor claim; it reduces a legal receivable.
        has_project = (receipt["kind"]=="reprioritize" and approved["action"]!="defer")
        receipt.update(kind="compromise" if has_project else "tax_adjust",
                       concession_region=refusing[0],concession_group=refusing[1],
                       legal_concession_permille=125 if has_project else 250)
    receipt["after"] = _summary(approved)
    return approved,receipt


def _settlement(base, groups, answer):
    zeros = dict.fromkeys(GOODS,0)
    by_group = {name:{k:zeros.copy() for k in ("assessed","concession","refused","paid")} for name in GROUPS}
    standing, extra, concession, refused = (zeros.copy() for _ in range(4))
    for good in GOODS:
        producer = "farm" if good=="food" else "industry"
        name = producer if groups[producer]["members"] else "consumer"
        g = groups[name]
        target = (answer["concession_region"],answer["concession_group"]) == (base["region"],name)
        cut = base["standing_levy"][good]*answer["legal_concession_permille"]//1000 if target else 0
        due = base["standing_levy"][good]-cut
        supplement = base["extra_levy"][good]
        n = g["members"]
        payers = g["participants"] if g["action"]=="refusal" else 0
        _check(type(n) is int and type(payers) is int and 0<=payers<=n,"invalid nonpayment share")
        rejected = due*payers//max(1,n)
        extra_rejected = supplement*payers//max(1,n)
        standing[good],extra[good] = due-rejected,supplement-extra_rejected
        concession[good],refused[good] = cut,rejected+extra_rejected
        for field,value in (("assessed",base["levied"][good]),("concession",cut),("refused",refused[good]),
                            ("paid",standing[good]+extra[good])):
            by_group[name][field][good]=value
    paid = {g:standing[g]+extra[g] for g in GOODS}
    handling = {**zeros,"food":(extra["food"]+31)//32}
    received = {g:paid[g]-handling[g] for g in GOODS}
    return {**base,"standing_levy":standing,"extra_levy":extra,"levied":paid,"deposited":received,
            "handling_used":handling,"baseline_levy":base["levied"],"foregone_concession":concession,"refused":refused,
            "private_close":{g:base["private_open"][g]-paid[g] for g in GOODS},
            "depot_close":{g:base["depot_open"][g]+received[g] for g in GOODS},
            "civic_tax":{"baseline_standing":base["standing_levy"],"baseline_extra":base["extra_levy"],
                         "assessed":base["levied"],"concession":concession,"refused":refused,"paid":paid,
                         "by_group":by_group}}


def collect_civic(regions, depots, plans, context):
    civic = {r["id"]:r["groups"] for r in context["regions"]}
    answers = {r["id"]:r for r in context["responses"]}
    rows = [_settlement(_posting(r,depots[r.id],plans[r.owner],"integrated"),civic[r.id],answers[r.owner])
            for r in sorted(regions,key=lambda r:r.id)]
    audit_civic_collection(regions,plans,context,rows)
    for r,entry in zip(sorted(regions,key=lambda r:r.id),rows,strict=True):
        r.stock = entry["private_close"].copy()
        depots[r.id] = entry["depot_close"].copy()
    return rows


def audit_civic_collection(regions, plans, context, postings):
    """Reassess the standard levy against opening custody; reconcile each group and both inventories."""
    local = {r.id:r for r in regions}
    civic = {r["id"]:r["groups"] for r in context["regions"]}
    answers = {r["id"]:r for r in context["responses"]}
    _check(len(postings)==len(local) and {r["region"] for r in postings}==local.keys(), "levy region coverage")
    baseline = []
    for t in postings:
        r = local[t["region"]]
        taxpayer = SimpleNamespace(id=r.id,owner=r.owner,population=r.population,stock=t["private_open"])
        base = _posting(taxpayer,t["depot_open"],plans[r.owner],"integrated")
        baseline.append(base)
        _check(t==_settlement(base,civic[r.id],answers[r.owner]),"incorrect tax relief, nonpayment or group incidence")
        for good in GOODS:
            losses = t["refused"][good]+t["foregone_concession"][good]
            _check(base["levied"][good]-losses==t["levied"][good]==t["private_open"][good]-t["private_close"][good]
                   and t["levied"][good]-t["handling_used"][good]==t["depot_close"][good]-t["depot_open"][good],
                   "assessments or custody failed to reconcile")
    audit_collection(local.values(),plans,"integrated",baseline)
