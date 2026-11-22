"""Regional food custody, crop inputs, household meals, and public receipts.

All amounts are integer food units unless a field describes people, land, or a
permille input. Sending a ration to households transfers custody; the actual
meal is counted only by food_eaten.
"""
from collections import defaultdict

from . import priority_evidence as fiscal


_FISCAL = ("levied_food","levy_deposited_food","levy_handling_food","relief_sent_food","relief_received_food",
           "relief_freight_food","works_used_food","works_freight_food","aid_sent_food","aid_received_food",
           "aid_freight_food","aid_handling_food","depot_spoiled_food","depot_transfer_sent_food",
           "depot_transfer_received_food","depot_transfer_freight_food")
_PROD = {"sector_workers":"workers", "farm_workers_planned":"labor_before.farm", "mine_workers":"labor.mine",
         "factory_workers":"labor.factory", "farm_workers_total":"active_farmers", "land_capacity":"land_capacity",
         "farmland":"farmland", "productivity":"productivity", "technology":"technology", "fertility":"fertility",
         "climate":"climate", "soil_before":"soil_before", "soil_after":"soil_after", "equipment":"equipment",
         "farm_share":"farm_share", "farm_multiplier":"investment.farm_multiplier", "tools_needed":"tool_need",
         "farm_tools_used":"investment.sector_used.tools", "harvest_total":"produced.food",
         "private_production_food_used":"used.food"}
_INTENSIVE = ("productivity","technology","fertility","climate","soil_before","soil_after","equipment",
              "farm_share","farm_multiplier")
PROVENANCE = {
    "year":"record.year", "region":"regions[].id", "owner":"regions[].owner",
    "population":"regions[].opening.population; one household ration per opening resident",
    "closing_population":"regions[].closing.population", "territory_tiles":"regions[].opening.land",
    **{k:"regions[].production."+v for k,v in _PROD.items()},
    "private_farm_workers":"public_harvest.regions[].workers_private or all active farmers",
    "public_farm_workers":"public_harvest.regions[].workers_public or zero",
    "private_farm_slots":"public_harvest.regions[].slots_private or all occupied farm labor slots",
    "public_farm_slots":"public_harvest.regions[].slots_public or zero; one occupied slot per farmer",
    "harvest_private":"public_harvest.regions[].food_private or all produced food",
    "harvest_public":"public_harvest.regions[].food_public or zero",
    "private_open":"regions[].opening.stock.food", "private_close":"regions[].closing.stock.food",
    "public_open":"government.depots[].opening.food", "public_close":"government.depots[].closing.food",
    "private_after_harvest":"production.closing_stock.food minus verified public harvest deposit",
    "tax_private_before":"government.levies[].private_open.food (after international trade)",
    "tax_private_after":"government.levies[].private_close.food",
    "tax_public_before":"government.levies[].depot_open.food (after foreign aid)",
    "tax_protected_food":"government.levies[].protected.food",
    "taxable_surplus_food":"max(0,tax_private_before-tax_protected_food)",
    "tax_warehouse_space":"max(0,government.levies[].reserve_cap.food-tax_public_before)",
    "tax_assessed_food":"government.levies[].baseline_levy.food",
    "tax_concession_food":"government.levies[].foregone_concession.food", "tax_refused_food":"government.levies[].refused.food",
    "tax_standing_food":"government.levies[].standing_levy.food", "tax_extra_food":"government.levies[].extra_levy.food",
    **{k:fiscal.PROVENANCE[k] for k in _FISCAL},
    "private_domestic_food_in":"domestic.shipments[target].quantity for food; credited to private households",
    "private_domestic_food_out":"domestic.shipments[source].quantity for food",
    "private_foreign_food_in":"border_market.trades[buyer].quantity for food",
    "private_foreign_food_out":"border_market.trades[seller].quantity for food",
    "private_domestic_freight_food":"domestic.shipments[source].cost_food for all goods",
    "private_foreign_freight_food":"border_market.trades[seller].cost_food for all goods",
    "private_domestic_loss_food":"zero in this rule: identical dispatched and credited private cargo quantity",
    "private_foreign_loss_food":"zero in this rule: one bilateral quantity debited and credited, verified at tax opening",
    "private_freight_food":"private domestic plus foreign freight paid in food, on all cargo",
    "public_freight_food":"works + inter-depot + relief + international aid freight paid in food",
    "household_public_issue_food":"service.regions[].ration_food; accounted in the same home private inventory before meals",
    "public_travel_food":"service.regions[].travel_food; paid public expense",
    "public_movement_expense_food":"unit_game.receipt.food_spent charged to receipt.source, if present",
    "other_public_expense_food":"unit_upkeep.groups[].food debited at paying depot; financial amount only",
    "private_before_domestic":"domestic.nodes[].opening.food", "private_after_domestic":"domestic.nodes[].closing.food",
    "private_before_meals":"regions[].consumption.opening_food", "food_need":"regions[].consumption.food_need",
    "food_eaten":"regions[].consumption.food_eaten", "food_unmet":"regions[].consumption.food_unmet",
    "private_spoiled_food":"regions[].consumption.food_spoiled",
}
COLUMNS = tuple(PROVENANCE)
_FI = {k:fiscal.COLUMNS.index(k) for k in (*_FISCAL,"region","depot_open_food","depot_close_food")}


def _check(ok, message):
    if not ok:
        raise ValueError("food flow: "+message)


def _q(value):
    _check(type(value) is int and value >= 0,"expected a nonnegative integer")
    return value


def _by(rows, key):
    index = {_q(r[key]):r for r in rows}
    _check(len(index)==len(rows),"duplicate "+key)
    return index


def _crop(r, source, receipt):
    p,old,n = source["production"],source["opening"],source["closing"]
    for k,path in _PROD.items():
        value=p
        for field in path.split("."):
            value=value[field]
        r[k]=_q(value)
    r.update(population=_q(old["population"]),closing_population=_q(n["population"]),territory_tiles=_q(old["land"]),
             private_open=_q(old["stock"]["food"]),private_close=_q(n["stock"]["food"]))
    _check(all(r[k]==old[k] for k in ("productivity","technology","fertility","farmland"))
           and r["climate"]==source["climate"] and r["soil_after"]==n["soil"] and p["population"]==r["population"]
           and p["opening_stock"]["food"]==r["private_open"], "crop input differs from opening or climate")
    active = r["farm_workers_total"]
    _check(active==min(r["farm_workers_planned"],r["land_capacity"]) and
           active+r["mine_workers"]+r["factory_workers"]==r["sector_workers"],"productive workers do not reconcile")
    yield_numerator = 32
    for k in ("productivity","technology","fertility","soil_before","climate","equipment","farm_multiplier"):
        yield_numerator *= r[k]
    _check(r["harvest_total"]==active*yield_numerator//(10*1000**7),"gross crop differs from its productive inputs")
    gross_close=_q(p["closing_stock"]["food"])
    _check(gross_close==r["private_open"]+r["harvest_total"]-r["private_production_food_used"],"gross production custody")
    if receipt is None:
        r.update(private_farm_workers=active,public_farm_workers=0,private_farm_slots=active,public_farm_slots=0,
                 harvest_private=r["harvest_total"],harvest_public=0)
    else:
        _check(receipt["owner"]==r["owner"],"public crop attributed to wrong owner")
        for prefix,private,public,total in (
                ("workers","private_farm_workers","public_farm_workers",active),
                ("slots","private_farm_slots","public_farm_slots",active),
                ("food","harvest_private","harvest_public",r["harvest_total"])):
            r[private]=_q(receipt[prefix+"_private"])
            r[public]=_q(receipt[prefix+"_public"])
            _check(r[private]+r[public]==_q(receipt[prefix+"_total"])==total,"public crop allocation does not add up")
        _check(r["private_farm_slots"]==r["private_farm_workers"] and r["public_farm_slots"]==r["public_farm_workers"],
               "occupied agricultural slots differ from farmers")
        _check(r["harvest_private"]==r["private_farm_workers"]*yield_numerator//(10*1000**7),
               "crop ownership differs from marginal output of assigned farm labor")
    r["private_after_harvest"]=gross_close-r["harvest_public"]
    if receipt is not None:
        _check(_q(receipt["private_before"]["food"])==gross_close and
               _q(receipt["private_after"]["food"])==r["private_after_harvest"],"public harvest private debit")


def _cargo(rows, shipments, foreign):
    label="private_foreign" if foreign else "private_domestic"
    for s in shipments:
        a,b = (s["seller"],s["buyer"]) if foreign else (s["source"],s["target"])
        sender,buyer = rows[_q(a)],rows[_q(b)]
        _check(a!=b and (sender["owner"]!=buyer["owner"])==foreign,"invalid private trading partners")
        qty,fee = _q(s["quantity"]),_q(s["cost_food"])
        _check(s["good"] in ("food","tools","ore") and qty>0,"invalid private shipment")
        sender[label+"_freight_food"]+=fee
        if s["good"]=="food":
            sender[label+"_food_out"]+=qty
            buyer[label+"_food_in"]+=qty


def _settle(r, source, levy, node, crop):
    base = r["private_after_harvest"]+r["private_foreign_food_in"]-r["private_foreign_food_out"]-r["private_foreign_freight_food"]
    r.update(tax_private_before=_q(levy["private_open"]["food"]),tax_private_after=_q(levy["private_close"]["food"]),
             tax_public_before=_q(levy["depot_open"]["food"]),tax_protected_food=_q(levy["protected"]["food"]))
    _check(base==r["tax_private_before"] and base-r["levied_food"]==r["tax_private_after"],"pre/post-tax private custody")
    r["taxable_surplus_food"]=max(0,base-r["tax_protected_food"])
    r["tax_warehouse_space"]=max(0,_q(levy["reserve_cap"]["food"])-r["tax_public_before"])
    for k,field in (("assessed","baseline_levy"),("concession","foregone_concession"),("refused","refused"),
                    ("standing","standing_levy"),("extra","extra_levy")):
        r["tax_"+k+"_food"]=_q(levy[field]["food"])
    _check(r["tax_assessed_food"]<=min(r["taxable_surplus_food"],r["tax_warehouse_space"])
           and r["tax_assessed_food"]==r["levied_food"]+r["tax_concession_food"]+r["tax_refused_food"]
           and r["levied_food"]==r["tax_standing_food"]+r["tax_extra_food"],"tax assessment differs from receipts")
    r["private_before_domestic"]=_q(node["opening"]["food"])
    r["private_after_domestic"]=_q(node["closing"]["food"])
    _check(node["owner"]==r["owner"] and r["private_before_domestic"]==r["tax_private_after"]+r["relief_received_food"]
           and node["imports"]["food"]==r["private_domestic_food_in"] and node["exports"]["food"]==r["private_domestic_food_out"]
           and node["cost_food"]==r["private_domestic_freight_food"],"domestic trade boundary")
    _check(r["private_after_domestic"]==r["private_before_domestic"]+r["private_domestic_food_in"]
           -r["private_domestic_food_out"]-r["private_domestic_freight_food"],"domestic food not delivered")
    meal=source["consumption"]
    for k,field in (("food_eaten","food_eaten"),("food_need","food_need"),("food_unmet","food_unmet"),
                    ("private_spoiled_food","food_spoiled"),("private_before_meals","opening_food")):
        r[k]=_q(meal[field])
    _check(r["private_before_meals"]==r["private_after_domestic"]+r["household_public_issue_food"]
           and r["food_need"]==r["population"] and r["food_eaten"]==min(r["food_need"],r["private_before_meals"])
           and r["food_need"]==r["food_eaten"]+r["food_unmet"],"household ration accounting")
    leftover=r["private_before_meals"]-r["food_eaten"]
    _check(r["private_spoiled_food"]==leftover//12 and meal["used"]["food"]==r["food_eaten"]+r["private_spoiled_food"]
           and leftover-r["private_spoiled_food"]==r["private_close"]==meal["closing_food"],"private food closing")

    pre_crop=(r["public_open"]+r["depot_transfer_received_food"]-r["depot_transfer_sent_food"]
              -r["works_used_food"]-r["works_freight_food"]-r["depot_transfer_freight_food"]
              -r["household_public_issue_food"]-r["public_travel_food"])
    if crop is not None:
        _check(_q(crop["depot_before"]["food"])==pre_crop and
               _q(crop["depot_after"]["food"])==pre_crop+r["harvest_public"],"public harvest warehouse credit")
    _check(pre_crop+r["harvest_public"]+r["aid_received_food"]-r["aid_sent_food"]-r["aid_freight_food"]
           ==r["tax_public_before"],"public stocks before levy")
    after=r["tax_public_before"]+r["levy_deposited_food"]-r["relief_sent_food"]-r["relief_freight_food"]
    after-=r["public_movement_expense_food"]+r["other_public_expense_food"]
    _check(after>=0 and r["depot_spoiled_food"]==after//12 and after-r["depot_spoiled_food"]==r["public_close"],
           "public storage loss or closing balance")
    r["private_freight_food"]=r["private_domestic_freight_food"]+r["private_foreign_freight_food"]
    r["public_freight_food"]=r["works_freight_food"]+r["depot_transfer_freight_food"]+r["relief_freight_food"]+r["aid_freight_food"]


def region_rows(record):
    """Return observed regional rows; all stock and flow amounts have separate custodians."""
    try:
        return _rows(record)
    except (KeyError,TypeError) as exc:
        raise ValueError(f"missing or malformed food evidence: {exc}") from exc


def _rows(record):
    source=_by(record["regions"],"id")
    levies=_by(record["government"]["levies"],"region")
    domestic=_by(record["domestic"]["nodes"],"id")
    foods=fiscal.region_rows(record)
    _check(source.keys()==levies.keys()==domestic.keys(),"missing regional evidence")
    harvest=None
    if "public_harvest" in record:
        harvest=_by(record["public_harvest"]["regions"],"id")
        _check(harvest.keys()==source.keys(),"incomplete public harvest")
    by_region={}
    for packed in foods:
        i=packed[_FI["region"]]
        r=by_region[i]=dict.fromkeys(COLUMNS,0)
        r.update(year=_q(record["year"]),region=i,owner=_q(source[i]["owner"]),
                 public_open=packed[_FI["depot_open_food"]],public_close=packed[_FI["depot_close_food"]])
        for k in _FISCAL:
            r[k]=_q(packed[_FI[k]])
        _crop(r,source[i],harvest[i] if harvest is not None else None)
    _cargo(by_region,record["border_market"]["trades"],True)
    _cargo(by_region,record["domestic"]["shipments"],False)
    if "service" in record:
        financial=_by(record["service"]["regions"],"id")
        _check(financial.keys()==source.keys(),"missing public expense account")
        for i,s in financial.items():
            by_region[i]["household_public_issue_food"]=_q(s["ration_food"])
            by_region[i]["public_travel_food"]=_q(s["travel_food"])
    move=record.get("unit_game",{}).get("receipt")
    if move and _q(move["food_spent"]):
        by_region[_q(move["source"])]["public_movement_expense_food"]+=move["food_spent"]
    for expense in record.get("unit_upkeep",{}).get("groups",[]):
        by_region[_q(expense["location"])]["other_public_expense_food"]+=_q(expense["food"])
    for i,r in by_region.items():
        _settle(r,source[i],levies[i],domestic[i],harvest[i] if harvest is not None else None)
    accounts=_by(record["government"]["accounts"],"id")
    countries=_by(record["countries"],"id")
    _check(accounts.keys()==countries.keys()=={r["owner"] for r in by_region.values()},"national food account coverage")
    for n,a in accounts.items():
        local=[r for r in by_region.values() if r["owner"]==n]
        for side,when in (("open","opening"),("close","closing")):
            private=sum(r["private_"+side] for r in local)
            public=sum(r["public_"+side] for r in local)
            _check(private==a["private_"+side]["food"]==countries[n][when]["stock"]["food"]
                   and public==a["public_"+side]["food"] and public+private==a["combined_"+side]["food"],
                   "national private and public food custody")
        for debit,credit in (("private_domestic_food_out","private_domestic_food_in"),
                             ("depot_transfer_sent_food","depot_transfer_received_food"),
                             ("relief_sent_food","relief_received_food")):
            _check(sum(r[debit]-r[credit] for r in local)==0,"unbalanced domestic food transfers")
    _check(sum(r["aid_sent_food"]-r["aid_received_food"]-r["aid_handling_food"] for r in by_region.values())==0
           and sum(r["private_foreign_food_out"]-r["private_foreign_food_in"] for r in by_region.values())==0,
           "international food transfers")
    return [[by_region[i][k] for k in COLUMNS] for i in sorted(by_region)]


def _summary(local):
    out={k:sum(row[k] for row in local) for k in COLUMNS if k not in ("year","region","owner",*_INTENSIVE)}
    out["region_count"]=len(local)
    out["no_taxable_surplus_regions"]=sum(r["taxable_surplus_food"]==0 for r in local)
    out["private_harvest_regions"]=sum(r["harvest_private"]>0 for r in local)
    out["private_harvest_no_surplus_regions"]=sum(r["harvest_private"]>0 and r["taxable_surplus_food"]==0 for r in local)
    for k in _INTENSIVE:
        numerator=sum(row[k]*row["farm_workers_total"] for row in local)
        out[k+"_farmer_weighted_sum"]=numerator
        out[k]=numerator//out["farm_workers_total"] if out["farm_workers_total"] else None
    return out


def aggregate(rows):
    """World and country sums. Intensity means use active farmers as their weights."""
    local=[dict(zip(COLUMNS,row,strict=True)) for row in rows]
    _check(bool(local) and len({r["year"] for r in local})==1,"expected one nonempty year")
    _check(len({r["region"] for r in local})==len(local),"duplicate region in aggregation")
    owners=defaultdict(list)
    for r in local:
        owners[r["owner"]].append(r)
    return {"year":local[0]["year"],"world":_summary(local),
            "countries":[{"owner":i,**_summary(owners[i])} for i in sorted(owners)]}
