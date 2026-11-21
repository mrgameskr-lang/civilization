"""Matched fixed and responsive peacetime public-service paths on the B1 warehouse economy."""
import json
from pathlib import Path

from experiments.phase6b import KEY, parser, run_stage


TRACE=("eligible_workers","target","enrolled","released","serving","stationed","available","unavailable",
       "ration_food","tools_used","travel_food","reassignment_out","reassignment_in","rationed_at_station")
REG_METRICS=tuple("service_"+k for k in TRACE)+("service_deaths","service_emigrants","closing_service_roster",
                                               "service_roster_open_years","service_road_load")
SERVICE_METRICS=(*REG_METRICS,"service_opportunity_food_estimate","service_undersupplied_country_years",
                 "service_zero_available_country_years","service_eligible_country_years","service_rate_permille_sum")
EXTRA_ENDPOINTS=("closing_service_roster",)
OBSERVATIONS=("population","max_opening_tension","prior_breached_directions","tension_weighted_import_dependence",
              "public_food","public_food_buffer","public_gap_permille","shortage_permille","industry_road_signal",
              "farm_relief_signal","consumer_relief_signal","adaptive_rate_permille","target_rate_permille","prior_crop",
              "prior_food_need","reference_roster","reference_foregone_food","food_cost_denominator","foregone_share_permille",
              "incumbent","platform_road","platform_relief","weighted_support","mean_opening_relation","opportunity_food_estimate","readiness_permille")
EXTRA_PANELS={
    "service-policy":(*KEY,"owner","mode",*OBSERVATIONS,"adjustments_json","target","serving","available","unavailable"),
    "service-moves":(*KEY,"owner","home","station","people","distance","road_load","travel_food","tile_path")}


def observe_service(record,key,writers):
    trace=record["service"]
    costs,places,extra={},{},{}
    for r in trace["regions"]:
        i=r["id"]
        cost={"home_food":r["ration_food"],"travel_food":r["travel_food"],"public_tools":r["tools_used"],"work_loss":r["serving"]}
        if r["used"]!={"food":cost["home_food"]+cost["travel_food"],"ore":0,"tools":cost["public_tools"]}:
            raise ValueError("public service supplies differ from physical debits")
        if r["opening_roster"]+r["enrolled"]-r["released"]!=r["serving"]:
            raise ValueError("enrollment and releases do not reconcile")
        if r["serving"]-r["service_deaths"]-r["service_emigrants"]!=r["closing_roster"]:
            raise ValueError("service register fails to close")
        costs[i]=cost
        places[i]={**{"service_"+k:r[k] for k in TRACE},"service_deaths":r["service_deaths"],
                   "service_emigrants":r["service_emigrants"],"closing_service_roster":r["closing_roster"],
                   "service_roster_open_years":r["opening_roster"],"service_road_load":0}
    load=0
    for m in trace["moves"]:
        load+=m["road_load"]
        places[m["home"]]["service_road_load"]+=m["road_load"]
        writers["service-moves"].writerow({**key,**{k:m[k] for k in ("owner","home","station","people","distance","road_load","travel_food")},
                                         "tile_path":" ".join(map(str,m["path"]))})
    if load!=sum(e["duty_use"] for e in record["government"]["roads"]): raise ValueError("public duty road postings diverged")
    for c in trace["countries"]:
        i=c["id"]
        subtotal=[r for r in trace["regions"] if r["owner"]==i]
        if any(sum(r[k] for r in subtotal)!=c[k] for k in (*TRACE,"closing_roster","service_deaths","service_emigrants")):
            raise ValueError("service national accounts differ from regional postings")
        extra[i]={"service_opportunity_food_estimate":c["opportunity_food_estimate"],
                  "service_undersupplied_country_years":int(c["serving"]>c["available"]),
                  "service_zero_available_country_years":int(c["serving"]>0 and not c["available"]),
                  "service_eligible_country_years":int(c["eligible_workers"]>0),
                  "service_rate_permille_sum":c["target_rate_permille"]}
        writers["service-policy"].writerow({**key,"owner":i,"mode":trace["mode"],**{k:c[k] for k in OBSERVATIONS},
                   "adjustments_json":json.dumps(c["rate_adjustments"],sort_keys=True,separators=(",",":")),
                   **{k:c[k] for k in ("target","serving","available","unavailable")}})
    return costs,extra,places


def run_study(output,*,sample,reference,seeds=20,horizons=(50,100,200),workers=5,verify=None):
    return run_stage(output,sample=sample,seeds=seeds,horizons=horizons,workers=workers,verify=verify,
                     arms=("C","D"),engine_name="civsim.peace62",extension_name="experiments.phase6b2",reference=reference)


if __name__=="__main__":
    p=parser()
    p.add_argument("--reference",type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(run_study(a.out,sample=a.sample,seeds=a.seeds,horizons=tuple(map(int,a.horizons.split(","))),
                               workers=a.workers,reference=a.reference,verify=a.verify_against)))
