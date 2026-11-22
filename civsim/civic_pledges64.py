"""Register and verify voluntary bilateral commitments on actual civilian border refusals."""
from copy import deepcopy
from itertools import combinations
from collections.abc import Mapping

from .civic_diplomacy63 import audit_civic_pair


KINDS=('trade','exit','entry')
OUTCOMES=('kept','broken','unknown')


def _check(ok,reason):
    if not ok: raise ValueError('civic pledges: '+reason)


def _empty():
    return {'pending':None,'history':[]}


def _channel(country,other,kind):
    # Entry decisions are made by the destination. Trade and exit decisions are made by the origin.
    return (other,country) if kind=='entry' else (country,other)


def _measure(flow,kind):
    if flow is None: return None
    if kind=='trade':
        passed=flow['trade_food']+flow['trade_ore']+flow['trade_tools']
        denied=flow['trade_denied']
    elif kind=='exit':
        passed=flow['migrants']+flow['entry_denied']
        denied=flow['exit_denied']
    else:
        passed=flow['migrants']
        denied=flow['entry_denied']
    return dict(denied=denied,passed=passed,opportunities=passed+denied)


def _subject(flows,respondent,requester):
    best_kind,highest,denominator=None,0,1
    for kind in KINDS:
        observed=_measure(flows[_channel(respondent,requester,kind)],kind)
        q,n=observed['denied'],observed['opportunities']
        if q*denominator>highest*n:
            best_kind,highest,denominator=kind,q,n
    return best_kind


def _settle(pending,flows,year):
    if pending is None: return None
    _check(pending['due_year']==year and pending['economic_year']==year-1,'missed or premature assessment')
    kind=pending['kind']
    results=[]
    for p in pending['parties']:
        seen=_measure(flows.get((p['source'],p['target'])),kind)
        if seen is None:
            status,reason='unknown','missing_direction'
        elif not seen['opportunities']:
            status,reason='unknown','no_opportunity'
        elif seen['denied']>p['baseline']:
            status,reason='broken','above_ceiling'
        else:
            status,reason='kept','within_ceiling'
        results.append(dict(country=p['country'],source=p['source'],target=p['target'],baseline=p['baseline'],
                            actual=None if seen is None else seen['denied'],
                            actual_opportunities=None if seen is None else seen['opportunities'],
                            status=status,reason=reason))
    statuses={p['status'] for p in results}
    status='broken' if 'broken' in statuses else 'unknown' if 'unknown' in statuses else 'kept'
    return dict(kind=kind,signed_year=pending['signed_year'],economic_year=pending['economic_year'],
                due_year=year,status=status,parties=results)


def _history(old,settlement,year):
    memory={(r['country'],r['kind']):r.copy() for r in old}
    if settlement:
        kind=settlement['kind']
        for p in settlement['parties']:
            n=p['country']
            h=memory.setdefault((n,kind),dict(country=n,kind=kind,kept=0,broken=0,unknown=0,
                                              last_known=None,known_year=None))
            s=p['status']
            h[s]+=1
            if s!='unknown':
                h['last_known'],h['known_year']=s,year
    return memory


def _sign(country,other,kind,flows,memory,year,feedback):
    own=_measure(flows[_channel(country,other,kind)],kind)
    partner=_measure(flows[_channel(other,country,kind)],kind)
    score=int(own['passed']>0)+int(partner['denied']>0)-int(own['denied']>own['passed'])
    history=memory.get((other,kind),{})
    known_year=history.get('known_year')
    outcome=history.get('last_known')
    adjustment=0
    if feedback and known_year is not None and 0<=year-known_year<2:
        adjustment={'kept':1,'broken':-1}[outcome]
    return dict(country=country,counterparty=other,own=own,partner=partner,base_score=score,
                partner_last_known=outcome,partner_known_year=known_year,history_score=adjustment,
                score=score+adjustment,sign=score+adjustment>0)


def _terms(kind,year,signatures):
    terms=[]
    for s in signatures:
        a,b=_channel(s['country'],s['counterparty'],kind)
        terms.append(dict(country=s['country'],source=a,target=b,baseline=s['own']['denied'],
                          baseline_opportunities=s['own']['opportunities']))
    return dict(kind=kind,signed_year=year,baseline_year=year-1,economic_year=year,due_year=year+1,parties=terms)


def _row(civic,old,enabled,feedback):
    seed,year,a,b=(civic[k] for k in ('seed','year','a','b'))
    flows={(f['source'],f['target']):f for f in civic['evidence']}
    settlement=_settle(old['pending'],flows,year)
    memory=_history(old['history'],settlement,year)
    proposal=civic['proposal']
    agreement=dict(decision='none',kind=None,signatures=[],terms=None)
    if enabled and proposal['decision']=='accepted':
        kind=_subject(flows,proposal['responder'],proposal['requester'])
        _check(kind is not None,'accepted civic grievance has no attributable refusal')
        sig=[_sign(i,j,kind,flows,memory,year,feedback) for i,j in ((a,b),(b,a))]
        agreement.update(kind=kind,signatures=sig)
        if all(s['sign'] for s in sig):
            agreement.update(decision='signed',terms=_terms(kind,year,sig))
        elif all(s['base_score']>0 for s in sig):
            agreement['decision']='defer'
        else:
            agreement['decision']='no_agreement'
    closing=dict(pending=deepcopy(agreement['terms']),history=[memory[k] for k in sorted(memory)])
    return dict(seed=seed,year=year,a=a,b=b,enabled=enabled,feedback=feedback,
                source_decision=proposal['decision'],source_requester=proposal['requester'],
                source_responder=proposal['responder'],evidence_year=civic['evidence_year'],
                opening=deepcopy(old),closing=closing,agreement=agreement,settlement=settlement)


def _state_ok(old,year,a,b):
    _check(isinstance(old,dict) and set(old)=={'history','pending'} and isinstance(old['history'],list),
           'invalid opening ledger')
    keys=[]
    for h in old['history']:
        country,kind=h['country'],h['kind']
        _check(country in (a,b) and kind in KINDS and all(type(h[s]) is int and h[s]>=0 for s in OUTCOMES)
               and 0<sum(h[s] for s in OUTCOMES)<=max(0,year-3), 'invalid outcome history')
        if h['kept']+h['broken']:
            _check(h['last_known'] in ('kept','broken') and h[h['last_known']]>0 and type(h['known_year']) is int
                   and 3<=h['known_year']<year,'unknown or future evaluation')
        else:
            _check(h['last_known'] is None and h['known_year'] is None,'unobserved promise treated as known')
        keys.append((country,kind))
    _check(keys==sorted(set(keys)),'duplicate or unordered history')
    p=old['pending']
    if p is None: return
    _check(year>=3 and p['kind'] in KINDS and p['signed_year']==p['economic_year']==year-1
           and p['baseline_year']==year-2 and p['due_year']==year
           and [r['country'] for r in p['parties']]==[a,b], 'invalid prior term or missing signature')
    for r in p['parties']:
        n=r['country']
        _check((r['source'],r['target'])==_channel(n,b if n==a else a,p['kind'])
               and type(r['baseline']) is int and type(r['baseline_opportunities']) is int
               and 0<=r['baseline']<=r['baseline_opportunities'],'unattributed or invalid ceiling')


def audit_pledge_pair(row,civic_row,previous_record=None):
    """Recompute the decision from its verified consultation and optional immediately preceding obligation."""
    audit_civic_pair(civic_row)
    year,a,b=civic_row['year'],civic_row['a'],civic_row['b']
    _check(type(row['enabled']) is bool and type(row['feedback']) is bool,'invalid policy switches')
    opening=row['opening']
    _state_ok(opening,year,a,b)
    if year==1:
        _check(previous_record is None and opening==_empty(),'not an empty first year')
    if previous_record is not None:
        _check((previous_record['year'],previous_record['a'],previous_record['b'],previous_record['seed'])==
               (year-1,a,b,civic_row['seed']) and previous_record['closing']==opening,'discontinuous promise memory')
    _check(row==_row(civic_row,opening,row['enabled'],row['feedback']),'incorrect pledge, signature or settlement')


class CivicPledges:
    def __init__(self,seed,nations=8,*,enabled=True,feedback=True):
        _check(type(seed) is int and type(nations) is int and nations>0 and type(enabled) is bool
               and type(feedback) is bool,'invalid initial settings')
        self.seed,self.nations,self.year=seed,nations,0
        self._enabled,self._feedback=enabled,feedback
        self._memory={k:_empty() for k in combinations(range(nations),2)}
        self._source_closing={}
        self._source_mode=None

    def fork(self,*,enabled=None,feedback=None):
        other=CivicPledges(self.seed,self.nations,enabled=self._enabled if enabled is None else enabled,
                          feedback=self._feedback if feedback is None else feedback)
        other.year=self.year
        other._memory=deepcopy(self._memory)
        other._source_closing=deepcopy(self._source_closing)
        other._source_mode=self._source_mode
        return other

    def advance(self,year,civic_pairs):
        _check(type(year) is int and year==self.year+1,'expected the next year')
        items=civic_pairs.items() if isinstance(civic_pairs,Mapping) else (((r['a'],r['b']),r) for r in civic_pairs)
        inputs={}
        mode=self._source_mode
        for key,c in items:
            _check(key==(c['a'],c['b']) and key in self._memory and key not in inputs and
                   (c['seed'],c['year'])==(self.seed,year),'wrong, foreign or duplicate source consultation')
            audit_civic_pair(c)
            _check(mode is None or c['consult'] is mode,'mixed source consultation paths')
            mode=c['consult']
            if self.year:
                _check(c['opening']==self._source_closing[key],'discontinuous source consultation')
            inputs[key]=c
        _check(inputs.keys()==self._memory.keys(),'missing source pairs')
        result={k:_row(inputs[k],old,self._enabled,self._feedback) for k,old in self._memory.items()}
        self._memory={k:deepcopy(r['closing']) for k,r in result.items()}
        self._source_closing={k:r['closing'].copy() for k,r in inputs.items()}
        self._source_mode=mode
        self.year=year
        return result
