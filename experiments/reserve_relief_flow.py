"""Account for public food at successive relief stages and private resident meals.

Amounts are additive except incident road capacities (halved in country/world
totals). Shortage exposure by depot location describes observed stocks. It does
not assume unused stocks could be transported or would have been eaten.
"""
from collections import Counter, defaultdict

from experiments import food_flow


BASE = ('year','region','owner','population','closing_population','food_need','food_eaten','food_unmet',
        'private_open','private_close','public_open','public_close','harvest_total','harvest_private','harvest_public',
        'private_farm_workers','public_farm_workers','mine_workers','factory_workers','levied_food','levy_deposited_food',
        'taxable_surplus_food','levy_handling_food','aid_sent_food','aid_received_food','aid_freight_food',
        'private_domestic_food_in','private_domestic_food_out','private_foreign_food_in','private_foreign_food_out',
        'private_domestic_freight_food','private_foreign_freight_food','private_before_meals',
        'household_public_issue_food','private_spoiled_food','depot_spoiled_food',
        'public_movement_expense_food','other_public_expense_food','public_freight_food')
PROVENANCE = {k:food_flow.PROVENANCE[k] for k in BASE}
PROVENANCE.update({
    'opening_cash':'regions[].opening.cash', 'closing_cash':'regions[].closing.cash',
    'deaths':'regions[].demography.deaths, all realized deaths',
    'after_harvest_public':'public harvest depot_after.food, or levy opening reversed by net foreign aid receipts',
    'pre_ordinary_public':'government.relief.nodes[].depot_open.food',
    'post_ordinary_public':'government.relief.nodes[].depot_close.food',
    'pre_extra_public':'emergency_relief.nodes[].depot_open.food; otherwise the observed ordinary relief close',
    'pre_extra_private':'emergency_relief.nodes[].private_food_open; otherwise the ordinary relief private close',
    'pre_extra_gap_after_reserved':'max(0, opening residents minus pre-extra private food minus already debited household rations)',
    'ordinary_prior_request':'min(previous unmet, opening private shortage, throughput) from the regional fiscal relief candidate; forecast need',
    'ordinary_forecast_quantity':'candidate.quantity, the isolated opening forecast before final authorization',
    'ordinary_forecast_freight':'candidate.inputs.estimated_freight_food, a forecast, not a payment',
    'ordinary_approved_regions':'final government decision selects relief at this site',
    'ordinary_approved_food':'final government decision.quantity for the selected target',
    'ordinary_budget_food':'final government decision.budget.food for the selected target, covering cargo and freight',
    'ordinary_admin_limit':'ordinary relief admin.limit assigned once to its selected target',
    'ordinary_open_gap':'max(0,population - ordinary relief node.private_food_open); before later household rations and private transfers',
    'ordinary_gap_not_authorized':'part of ordinary_open_gap above the approved cargo ceiling; includes unselected regions',
    'ordinary_gap_admin':'additional gap above authorized administration/throughput at the selected target',
    'ordinary_gap_budget':'remaining gap above authorized food budget, ignoring freight',
    'ordinary_gap_not_dispatched':'remaining approved gap after those ceilings with no delivery. Supply, competition, route and freight causes are not isolated by this residual.',
    'emergency_active_regions':'1 if the supplementary relief ledger exists, otherwise 0',
    'emergency_requested':'emergency_relief.applications[].requested; actual applications only',
    'emergency_approved':'emergency_relief.applications[].approved',
    'emergency_dispatched_for_target':'emergency_relief.applications[].dispatched; destination basis',
    'unmet_with_local_stock':'final unmet in regions with positive pre_extra_public, regardless of accessibility later',
    'unmet_with_other_domestic_stock_only':'final unmet where local pre-extra depot was empty but another same-country depot held food; route availability unmeasured',
    'unmet_without_domestic_stock':'final unmet where every same-country depot was empty at pre-extra time',
    'unmet_with_closing_local_stock':'final unmet in regions whose year-end local public depot was positive, a separate timing',
    'unmet_without_ordinary_approval':'final unmet where this region was not the final ordinary relief target; observational overlap',
    'unmet_after_ordinary_approval':'final unmet at the selected ordinary relief target',
    'unmet_with_reserved_household_food':'final unmet where food had already been debited and reserved for household meals; it enters private meals later',
    'unmet_after_observed_remote_delivery':'final unmet where either relief stage actually received cargo from another domestic region',
    'private_domestic_cargo_in':'all goods on private domestic invoices credited at the destination, once per cargo',
    'private_foreign_cargo_in':'all goods on private foreign invoices credited at the buying region, once per cargo',
})
REASONS = ('handling','admin','stock','road','freight')
for reason in REASONS:
    PROVENANCE['emergency_unfilled_'+reason] = f'emergency_relief.applications[].unfilled.{reason}; receiver, actual stage'
for stage in ('ordinary','emergency'):
    for field, description in {
            'sent_food':'gross food dispatched by source, excluding freight',
            'received_food':'household cargo credited to destination, not a meal',
            'local_received':'received food on invoices with the same origin and destination',
            'remote_received':'received food on realized invoices from another region',
            'freight_food':'actual food freight paid by source',
            'road_open':'incident domestic residual capacity upon entry',
            'road_left':'incident domestic residual capacity after dispatch'}.items():
        PROVENANCE[stage+'_'+field] = f'{stage} relief receipts: {description}'
COLUMNS = tuple(PROVENANCE)
ROAD_FIELDS = {stage+'_'+k for stage in ('ordinary','emergency') for k in ('road_open','road_left')}


def _check(condition, message):
    if not condition:
        raise ValueError('relief evidence: '+message)


def _index(rows, key):
    result = {row[key]:row for row in rows}
    _check(len(result)==len(rows),'duplicate '+key)
    return result


def _base(record, extra):
    # The existing independent food balance accepts one list of public food-to-household invoices.
    # Present both observed invoice lists in a temporary view solely for that balance check.
    # Each physical stage is subsequently measured and reconciled against its own original ledger.
    view = record
    if extra is not None:
        gov = record['government']
        ordinary = gov['relief']
        combined = {**ordinary, 'shipments': [*ordinary['shipments'], *extra['shipments']]}
        view = {**record, 'government': {**gov,'relief':combined}}
    output = {}
    for row in food_flow.region_rows(view):
        base = dict(zip(food_flow.COLUMNS,row,strict=True))
        out = dict.fromkeys(COLUMNS,0)
        out.update({k:base[k] for k in BASE})
        out['after_harvest_public'] = (base['tax_public_before']-base['aid_received_food']
                                     +base['aid_sent_food']+base['aid_freight_food'])
        output[out['region']] = out
    return output


def _stage(rows, trace, name):
    nodes = _index(trace['nodes'],'id')
    _check(nodes.keys()==rows.keys(),'missing '+name+' warehouse')
    load = Counter()
    for s in trace['shipments']:
        i,j,q,fee = s['source'],s['target'],s['quantity'],s['cost_food']
        _check(type(q) is int and q>0 and type(fee) is int and fee>=0 and s['good']=='food','invalid relief cargo')
        _check(rows[i]['owner']==rows[j]['owner']==s['owner'],'relief crosses country boundary')
        path = s['path']
        _check(path and path[0]==i and path[-1]==j,'invalid relief path endpoints')
        rows[i][name+'_sent_food'] += q
        rows[i][name+'_freight_food'] += fee
        rows[j][name+'_received_food'] += q
        rows[j][name+('_local_received' if i==j else '_remote_received')] += q
        for a,b in zip(path,path[1:]):
            load[tuple(sorted((a,b)))] += q
    seen = set()
    for e in trace['roads']:
        a,b = e['a'],e['b']
        edge = tuple(sorted((a,b)))
        cap,left = e['capacity'], e['remaining']
        _check(a!=b and edge not in seen and rows[a]['owner']==rows[b]['owner'] and
               0<=left<=cap and cap-left==load[edge], 'road capacity or relief leg differs')
        seen.add(edge)
        for i in (a,b):
            rows[i][name+'_road_open'] += cap
            rows[i][name+'_road_left'] += left
    _check(load.keys()<=seen,'unrecorded relief road')
    for i,n in nodes.items():
        row = rows[i]
        _check(n['owner']==row['owner'] and n['depot_close']['food']==n['depot_open']['food']
               -row[name+'_sent_food']-row[name+'_freight_food'] and
               n['private_food_close']==n['private_food_open']+row[name+'_received_food'],'relief node custody differs')
    _check(trace['delivered']==sum(r[name+'_received_food'] for r in rows.values()) and
           trace['cost_food']==sum(r[name+'_freight_food'] for r in rows.values()),'relief stage totals differ')
    return nodes


def _ordinary(rows, record, nodes):
    accounts = _index(record['government']['accounts'],'id')
    limits = _index(record['government']['relief']['admin'],'owner')
    for owner,account in accounts.items():
        plan = account['decision']
        candidates = _index([c for c in plan['candidates'] if c['action']=='relief'], 'target_region')
        for i,candidate in candidates.items():
            row = rows[i]
            _check(row['owner']==owner,'relief candidate has a foreign target')
            inputs = candidate['inputs']
            row['ordinary_prior_request'] = min(inputs['previous_unmet'], inputs['opening_shortage'], inputs['throughput'])
            row['ordinary_forecast_quantity'] = candidate['quantity']
            row['ordinary_forecast_freight'] = inputs['estimated_freight_food']
        if plan['action']=='relief':
            target = rows[plan['target_region']]
            _check(target['owner']==owner,'invalid approved relief target')
            target['ordinary_approved_regions'] = 1
            target['ordinary_approved_food'] = plan['quantity']
            target['ordinary_budget_food'] = plan['budget']['food']
            target['ordinary_admin_limit'] = limits[owner]['limit'] if plan['budget']['admin_units'] else 0
    for i,row in rows.items():
        n = nodes[i]
        row['pre_ordinary_public'] = n['depot_open']['food']
        row['post_ordinary_public'] = n['depot_close']['food']
        gap = max(0,row['population']-n['private_food_open'])
        approved = min(gap,row['ordinary_approved_food'])
        capacity = min(approved,row['ordinary_admin_limit'])
        funded = min(capacity,row['ordinary_budget_food'])
        _check(row['ordinary_received_food']+sum(s['cost_food'] for s in record['government']['relief']['shipments']
                                                if s['target']==i)<=row['ordinary_budget_food'] and
               row['ordinary_received_food']<=funded,'ordinary relief exceeds approval, budget, need or capacity')
        row.update(ordinary_open_gap=gap,ordinary_gap_not_authorized=gap-approved,
                   ordinary_gap_admin=approved-capacity,ordinary_gap_budget=capacity-funded,
                   ordinary_gap_not_dispatched=funded-row['ordinary_received_food'])


def _extra(rows, ordinary_nodes, trace):
    nodes = _stage(rows,trace,'emergency') if trace is not None else None
    apps = _index(trace['applications'],'region') if trace is not None else None
    if apps is not None:
        _check(apps.keys()==rows.keys(),'incomplete emergency applications')
    for i,r in rows.items():
        if nodes is None:
            n = ordinary_nodes[i]
            public,private = n['depot_close']['food'],n['private_food_close']
            r['emergency_road_open'] = r['emergency_road_left'] = r['ordinary_road_left']
        else:
            public,private = nodes[i]['depot_open']['food'],nodes[i]['private_food_open']
            _check(private==ordinary_nodes[i]['private_food_close'] and
                   r['emergency_road_open']==r['ordinary_road_left'],'ordinary-to-emergency boundary differs')
        gap = max(0,r['population']-private-r['household_public_issue_food'])
        r.update(pre_extra_public=public,pre_extra_private=private,pre_extra_gap_after_reserved=gap)
        if apps is None:
            continue
        app = apps[i]
        r['emergency_active_regions'] = 1
        r['emergency_requested'] = app['requested']
        r['emergency_approved'] = app['approved']
        r['emergency_dispatched_for_target'] = app['dispatched']
        for reason in REASONS:
            r['emergency_unfilled_'+reason] = app['unfilled'][reason]
        _check(app['owner']==r['owner'] and app['population']==r['population'] and app['private_food']==private
               and app['household_rations']==r['household_public_issue_food'] and app['requested']==gap
               and app['ordinary_received']==r['ordinary_received_food'] and
               app['received']==app['dispatched']==r['emergency_received_food'] and
               app['requested']==app['received']+sum(app['unfilled'][k] for k in REASONS) and
               app['approved']==app['requested']-app['unfilled']['handling']-app['unfilled']['admin'],
               'emergency application, denial reasons or receipts differ')


def region_rows(record):
    """Provide a detached integer row per region in ascending ID order."""
    extra = record.get('emergency_relief')
    rows = _base(record,extra)
    ordinary = record['government']['relief']
    nodes = _stage(rows,ordinary,'ordinary')
    _ordinary(rows,record,nodes)
    _extra(rows,nodes,extra)
    reserves = Counter()
    for r in rows.values():
        reserves[r['owner']] += r['pre_extra_public']
    for src in record['regions']:
        r = rows[src['id']]
        r.update(opening_cash=src['opening']['cash'],closing_cash=src['closing']['cash'],deaths=src['demography']['deaths'])
        unmet = r['food_unmet']
        if r['pre_extra_public']:
            r['unmet_with_local_stock'] = unmet
        elif reserves[r['owner']]:
            r['unmet_with_other_domestic_stock_only'] = unmet
        else:
            r['unmet_without_domestic_stock'] = unmet
        r['unmet_with_closing_local_stock'] = unmet if r['public_close'] else 0
        r['unmet_after_ordinary_approval' if r['ordinary_approved_regions'] else 'unmet_without_ordinary_approval'] = unmet
        r['unmet_with_reserved_household_food'] = unmet if r['household_public_issue_food'] else 0
        r['unmet_after_observed_remote_delivery'] = unmet if r['ordinary_remote_received']+r['emergency_remote_received'] else 0
    for s in record['domestic']['shipments']:
        rows[s['target']]['private_domestic_cargo_in'] += s['quantity']
    for s in record['border_market']['trades']:
        rows[s['buyer']]['private_foreign_cargo_in'] += s['quantity']
    output = [[rows[i][k] for k in COLUMNS] for i in sorted(rows)]
    _check(all(type(v) is int and v>=0 for row in output for v in row),'invalid numeric field')
    return output


def aggregate(rows):
    """Sum amounts once per custodian. Each domestic road has two incident regions."""
    local = [dict(zip(COLUMNS,r,strict=True)) for r in rows]
    _check(local and len({r['year'] for r in local})==1 and len({r['region'] for r in local})==len(local),
           'duplicate region or inconsistent year')
    groups = defaultdict(list)
    for r in local:
        groups[r['owner']].append(r)

    def totals(group):
        result = {k:sum(r[k] for r in group) for k in COLUMNS if k not in ('year','region','owner')}
        for k in ROAD_FIELDS:
            _check(result[k]%2==0,'incomplete road incidence')
            result[k] //= 2
        result['region_count'] = len(group)
        return result
    return {'year':local[0]['year'],'world':totals(local),
            'countries':[{'owner':n,**totals(groups[n])} for n in sorted(groups)]}
