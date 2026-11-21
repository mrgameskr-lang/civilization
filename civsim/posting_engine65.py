"""Optional year-end office affiliations attached to the unchanged fixed civilian economy."""
from copy import deepcopy
from collections import Counter
from types import SimpleNamespace

from . import civic_followup64, peace62
from .civic_fiscal import withheld_labor
from .demography import BIRTHS_PER_THOUSAND_FED, BASE_DEATHS_PER_THOUSAND, EXTRA_DEATHS_PER_THOUSAND_UNFED
from .model import GOODS, generate_world
from .regions import regionalize


def _require(condition,message):
    if not condition:
        raise ValueError(message)


def _by_id(rows,key):
    result={r[key]:r for r in rows}
    _require(len(rows)==len(result),"duplicate economic account")
    return result


ROSTER_COUNTS=("opening_roster","enrolled","released","eligible_workers","serving",
               "service_deaths","service_emigrants","closing_roster")


def _natural(q):
    return type(q) is int and q>=0


def _audit_census_and_roster(region,staff,incoming,outgoing,projects,withheld):
    p=region["opening"]["population"]
    meal=region["consumption"]
    v=region["demography"]
    births=meal["food_eaten"]*BIRTHS_PER_THOUSAND_FED//1000
    deaths=(p*BASE_DEATHS_PER_THOUSAND+meal["food_unmet"]*EXTRA_DEATHS_PER_THOUSAND_UNFED)//1000
    before_moves=p+births-deaths
    after=before_moves+incoming-outgoing
    vital_fields=("opening_population","births","deaths","population_before_migration","immigrants","emigrants","closing_population")
    _require(all(_natural(v[k]) for k in vital_fields) and
             tuple(v[k] for k in vital_fields)==(p,births,deaths,before_moves,incoming,outgoing,after) and
             outgoing<=before_moves and region["closing"]["population"]==after,"resident births, deaths or migration")
    _require(all(_natural(staff[k]) for k in (*ROSTER_COUNTS,"population","workers","withheld")) and
             staff["population"]==p and staff["owner"]==region["owner"] and
             staff["released"]<=staff["opening_roster"]<=p,"address roster inputs")
    s=staff["opening_roster"]-staff["released"]+staff["enrolled"]
    _require(s==staff["serving"],"roster entries and releases")
    # These are subsets of the independently reconciled resident events.
    lost=s*deaths//p if p else 0
    left=(s-lost)*outgoing//before_moves if before_moves else 0
    _require((staff["service_deaths"],staff["service_emigrants"],staff["closing_roster"])==(lost,left,s-lost-left)
             and staff["closing_roster"]<=after,"roster exits differ from resident census")
    prod=region["production"]
    jobs=(s,withheld,projects,prod["workers"],prod["soil_care"]["workers"],prod["investment"]["construction_labor"])
    _require(all(_natural(q) for q in jobs) and staff["workers"]==p//2==sum(jobs) and
             staff["withheld"]==prod["withheld_workers"]==withheld and
             s<=staff["eligible_workers"]==p//2-withheld,"resident workers counted more than once or missing")


def audit_households(record,previous=None):
    """Validate actual resident meals and public/private custody using both levels of accounts."""
    regions=_by_id(record["regions"],"id")
    countries=_by_id(record["countries"],"id")
    depots=_by_id(record["government"]["depots"],"region")
    accounts=_by_id(record["government"]["accounts"],"id")
    staff=_by_id(record["service"]["regions"],"id")
    national_staff=_by_id(record["service"]["countries"],"id")
    _require(set(regions)==set(depots)==set(staff) and set(accounts)==set(countries)==set(national_staff) and
             set(countries)=={r["owner"] for r in regions.values()},"regional or national coverage")
    incoming,outgoing,projects=Counter(),Counter(),Counter()
    for m in record["moves"]:
        a,b,q=m["source"],m["target"],m["people"]
        _require(a in regions and b in regions and a!=b and _natural(q) and q>0,"resident movement receipt")
        outgoing[a]+=q
        incoming[b]+=q
    for job in record["government"]["works"]["projects"]:
        _require(job["target"] in regions and _natural(job["workers"]),"project worker receipt")
        projects[job["target"]]+=job["workers"]
    people=[SimpleNamespace(id=i,owner=r["owner"],population=r["opening"]["population"]) for i,r in regions.items()]
    withheld=withheld_labor(people,record["collective"])
    if previous is not None:
        old=_by_id(previous["regions"],"id")
        old_depots=_by_id(previous["government"]["depots"],"region")
        _require(previous["year"]+1==record["year"] and old.keys()==regions.keys() and old_depots.keys()==depots.keys(),
                 "prior household register or year differs")
        _require(all(old[i]["closing"]==r["opening"] and old_depots[i]["closing"]==depots[i]["opening"]
                     for i,r in regions.items()),"household or public custody discontinuity")
        prior_staff=_by_id(previous["service"]["regions"],"id")
        _require(prior_staff.keys()==staff.keys() and all(prior_staff[i]["closing_roster"]==r["opening_roster"]
                 for i,r in staff.items()),"address roster discontinuity")
    elif record["year"]==1:
        _require(all(r["opening_roster"]==0 for r in staff.values()),"nonempty initial roster")
    for i,r in regions.items():
        p=r["opening"]["population"]
        meal=r["consumption"]
        _require(min(p,meal["food_eaten"],meal["food_unmet"],meal["food_spoiled"])>=0 and
                 p==meal["food_need"]==meal["food_eaten"]+meal["food_unmet"] and
                 meal["used"]["food"]==meal["food_eaten"]+meal["food_spoiled"],"resident meals")
        _audit_census_and_roster(r,staff[i],incoming[i],outgoing[i],projects[i],withheld[i])
        _require(depots[i]["owner"]==r["owner"] and all(min(r[side]["stock"][g],depots[i][side][g])>=0
                 for side in ("opening","closing") for g in GOODS),"negative or misassigned regional stocks")
    for owner,n in countries.items():
        local=[r for r in regions.values() if r["owner"]==owner]
        _require(all(_natural(national_staff[owner][k]) and
                     national_staff[owner][k]==sum(staff[r["id"]][k] for r in local)
                     for k in ROSTER_COUNTS),"national roster differs from homes")
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
    audit_households(economy)
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
                "service":{"regions":[{"id":r["id"],"closing_roster":r["closing_roster"]} for r in service["regions"]]},
                "regions":[{"id":r["id"],"closing":deepcopy(r["closing"])} for r in economy["regions"]],
                "government":{"depots":[{"region":r["region"],"closing":r["closing"].copy()}
                                       for r in economy["government"]["depots"]]},
            }
            previous_register=deepcopy(register)
        yield economy,None,register
