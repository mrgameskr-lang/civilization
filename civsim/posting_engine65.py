"""Optional year-end office affiliations attached to the unchanged fixed civilian economy."""
from copy import deepcopy

from . import civic_followup64, peace62
from .model import GOODS, generate_world
from .regions import regionalize


def _require(condition,message):
    if not condition:
        raise ValueError(message)


def _by_id(rows,key):
    result={r[key]:r for r in rows}
    _require(len(rows)==len(result),"duplicate economic account")
    return result


def audit_households(record,previous=None):
    """Validate actual resident meals and public/private custody using both levels of accounts."""
    regions=_by_id(record["regions"],"id")
    countries=_by_id(record["countries"],"id")
    depots=_by_id(record["government"]["depots"],"region")
    accounts=_by_id(record["government"]["accounts"],"id")
    _require(set(regions)==set(depots) and set(accounts)==set(countries) and
             set(countries)=={r["owner"] for r in regions.values()},"regional or national coverage")
    if previous is not None:
        old=_by_id(previous["regions"],"id")
        old_depots=_by_id(previous["government"]["depots"],"region")
        _require(previous["year"]+1==record["year"] and old.keys()==regions.keys() and old_depots.keys()==depots.keys(),
                 "prior household register or year differs")
        _require(all(old[i]["closing"]==r["opening"] and old_depots[i]["closing"]==depots[i]["opening"]
                     for i,r in regions.items()),"household or public custody discontinuity")
    for i,r in regions.items():
        p=r["opening"]["population"]
        meal=r["consumption"]
        vital=r["demography"]
        _require(min(p,meal["food_eaten"],meal["food_unmet"],meal["food_spoiled"])>=0 and
                 p==meal["food_need"]==meal["food_eaten"]+meal["food_unmet"] and
                 meal["used"]["food"]==meal["food_eaten"]+meal["food_spoiled"],"resident meals")
        _require(vital["opening_population"]==p and
                 r["closing"]["population"]==vital["closing_population"]==
                 p+vital["births"]-vital["deaths"]+vital["immigrants"]-vital["emigrants"],"resident census")
        _require(depots[i]["owner"]==r["owner"] and all(min(r[side]["stock"][g],depots[i][side][g])>=0
                 for side in ("opening","closing") for g in GOODS),"negative or misassigned regional stocks")
    for owner,n in countries.items():
        local=[r for r in regions.values() if r["owner"]==owner]
        for side,when in (("opening","open"),("closing","close")):
            _require(all(sum(r[side][k] for r in local)==n[side][k] for k in ("population","cash")),
                     "national household cash or population")
            for g in GOODS:
                private=sum(r[side]["stock"][g] for r in local)
                public=sum(depots[r["id"]][side][g] for r in local)
                _require(private==n[side]["stock"][g]==accounts[owner]["private_"+when][g] and
                         public==accounts[owner]["public_"+when][g] and
                         private+public==accounts[owner]["combined_"+when][g],"national goods balance")


def _fixed_service(economy):
    policy=economy["public_policy"]
    service=economy["service"]
    _require(policy["arm"]=="C" and policy["model_version"]=="6.0B2" and
             policy["diagnostic"] is None and service["mode"]=="fixed" and service["stage"]=="closed",
             "expected ordinary closed fixed-policy economy")
    return service


def fork_affiliation(opening,economy,*,hold):
    """Compare two year-end registers on the same *settled* economic receipts.

    The intervention holds one otherwise posted office affiliation. Both registers
    consume their own copies of those receipts and of the same opening book.
    """
    from .postings65 import advance_postings, audit_postings
    _require(hold is not None,"select an issued administrative change to hold")
    service=_fixed_service(economy)
    year=economy["year"]
    normal,_=advance_postings(opening.copy(),deepcopy(service),year=year)
    variant,_=advance_postings(opening.copy(),deepcopy(service),year=year,hold=hold)
    audit_postings(normal,service)
    audit_postings(variant,service)
    return normal,variant


def run(seed,years,policy="A",*,consult=True,pledges=False):
    """Yield one tuple per year, preserving the original PR18 triple for A.

    A_fixed yields (ordinary 6.0B2/C economy, None, None). B yields the same
    economy, None, and a separate year-end register. Consult/pledge records
    are provided only by PR18. Office affiliations have no economic input.
    """
    _require(type(years) is int and years>=0 and type(consult) is bool and type(pledges) is bool,
             "invalid horizon or historical flags")
    if policy=="A":
        yield from civic_followup64.run(seed,years,consult=consult,pledges=pledges)
        return
    _require(policy in ("A_fixed","B") and not pledges,"fixed economic controls do not run the pledge register")
    world=regionalize(generate_world(seed))
    simulation=peace62.start62(world)
    if policy=="B":
        from .postings65 import advance_postings, audit_postings, start_postings
        book=start_postings(world.regions)
    previous_economy=previous_register=None
    for year in range(1,years+1):
        economy=peace62.step62(simulation,year,"C")
        register=None
        if policy=="B":
            audit_households(economy,previous=previous_economy)
            service=_fixed_service(economy)
            register,book=advance_postings(book,deepcopy(service),year=year)
            audit_postings(register,service,previous=previous_register)
            previous_economy={
                "year":year,
                "regions":[{"id":r["id"],"closing":deepcopy(r["closing"])} for r in economy["regions"]],
                "government":{"depots":[{"region":r["region"],"closing":r["closing"].copy()}
                                       for r in economy["government"]["depots"]]},
            }
            previous_register=deepcopy(register)
        yield economy,None,register
