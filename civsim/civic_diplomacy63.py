"""Lagged observation of bilateral civilian disputes and separately consented consultations."""
from itertools import combinations


COUNTERS=('breach','trade_food','trade_ore','trade_tools','trade_value','trade_denied','migrants',
          'exit_denied','entry_denied','closing_tension','closing_trust')


def _require(ok, why):
    if not ok:
        raise ValueError('civic diplomacy: '+why)


def _integer(x):
    if type(x) is int:
        return x
    if isinstance(x,str) and x.removeprefix('-').isascii() and x.removeprefix('-').isdigit():
        return int(x)
    raise ValueError('civic diplomacy: expected a whole number')


def _observation(raw,seed,year,nations):
    try:
        result={k:_integer(raw[k]) for k in ('seed','year','source','target',*COUNTERS)}
        result['arm']=raw['arm']
    except (KeyError,TypeError) as exc:
        raise ValueError('civic diplomacy: incomplete observation') from exc
    _require(result['seed']==seed and result['year']==year-1 and year>1 and result['arm']=='D',
             'expected the previous completed year of the same seed and D trajectory')
    a,b=result['source'],result['target']
    _require(a!=b and a in nations and b in nations,'invalid direction')
    _require(all(result[k]>=0 for k in COUNTERS) and result['breach']<=1
             and max(result['closing_tension'],result['closing_trust'])<=1000,'invalid counters or scale')
    cargo=sum(result['trade_'+g] for g in ('food','ore','tools'))
    _require(bool(cargo)==bool(result['trade_value']),'trade value conflicts with delivered quantities')
    _require(result['breach']==0 or result['trade_denied']>0,'access breach lacks an observed denial')
    return result


def _initial():
    return dict(active=False,quiet_years=0,consulting=False)


def _signal(observations):
    directions=[]
    for f in observations:
        cargo=f['trade_food']+f['trade_ore']+f['trade_tools']
        blocked_people=f['exit_denied']+f['entry_denied']
        trade_total=cargo+f['trade_denied']
        people_total=f['migrants']+blocked_people
        directions.append(dict(source=f['source'],target=f['target'],trade_attempted=trade_total,
            trade_denied=f['trade_denied'],people_attempted=people_total,people_denied=blocked_people,
            material_trade=f['trade_denied']>0 and 4*f['trade_denied']>=trade_total,
            material_movement=blocked_people>0 and 4*blocked_people>=people_total))
    return dict(directions=directions,breach=any(f['breach'] for f in observations),
                actual_denial=any(d['trade_denied'] or d['people_denied'] for d in directions),
                substantial=any(d['material_trade'] or d['material_movement'] for d in directions),
                tension=observations[0]['closing_tension'],trust=observations[0]['closing_trust'])


def _position(outbound,inbound):
    # Which other country's actions affected this country's purchases, residents or incoming arrivals?
    grievances=dict(partner_breach=2*inbound['breach'],blocked_import=int(inbound['trade_denied']>0),
                    partner_exit=int(inbound['exit_denied']>0),partner_entry=int(outbound['entry_denied']>0))
    # Consent is an independent decision using the addressed country's own observed exchange.
    stake=bool(outbound['trade_value'] or outbound['migrants'])
    reasons=[]
    if not stake: reasons.append('no_observed_outbound_exchange')
    if outbound['closing_trust']<400: reasons.append('low_trust')
    if outbound['closing_tension']>=500: reasons.append('high_tension')
    return dict(country=outbound['source'],grievances=grievances,request_score=sum(grievances.values()),
                exchange_stake=stake,consents=not reasons,consent_constraints=reasons)


def _pair(seed,year,a,b,opening,observations,consult):
    observed=len(observations)==2
    closing=opening.copy()
    proposal=dict(decision='none',requester=None,responder=None,positions=[])
    event='unobserved'
    signal=None
    if observed:
        left,right=observations
        _require(all(left[k]==right[k] for k in ('closing_tension','closing_trust')),
                 'inconsistent bilateral closing observations')
        signal=_signal(observations)
        starts=signal['breach'] or signal['substantial'] or (signal['actual_denial'] and signal['tension']>=125)
        if opening['active']:
            quiet=0 if signal['actual_denial'] else opening['quiet_years']+1
            event='ease' if quiet==2 else 'continue'
            closing.update(active=quiet<2,quiet_years=quiet if quiet<2 else 0)
        else:
            event='start' if starts else 'none'
            closing.update(active=starts,quiet_years=0)
        closing['consulting']=False
        p,q=_position(left,right),_position(right,left)
        proposal['positions']=[p,q]
        if closing['active']:
            proposal['decision']='defer'
            proposer,responder=sorted((p,q),key=lambda d:(-d['request_score'],d['country']))
            if consult and proposer['request_score']>0:
                closes=responder['consents']
                proposal.update(decision='accepted' if closes else 'declined',requester=proposer['country'],
                                responder=responder['country'])
                closing['consulting']=closes
    return dict(seed=seed,year=year,a=a,b=b,consult=consult,observed=observed,
                evidence_year=year-1 if observations else None,evidence=observations,opening=opening.copy(),
                closing=closing,event=event,signal=signal,proposal=proposal)


def audit_civic_pair(row, previous_row=None):
    """Check one recorded decision. Supply its predecessor to also check historical continuity."""
    seed,year,a,b=row['seed'],row['year'],row['a'],row['b']
    _require(all(type(i) is int for i in (seed,year,a,b)) and year>0 and 0<=a<b and type(row['consult']) is bool,
             'invalid decision identity')
    opening=row['opening']
    _require(set(opening)=={'active','quiet_years','consulting'} and type(opening['active']) is bool
             and type(opening['consulting']) is bool and type(opening['quiet_years']) is int
             and opening['quiet_years'] in (0,1) and (opening['active'] or opening==_initial()),
             'invalid opening civic state')
    if year==1: _require(opening==_initial() and previous_row is None,'invalid first-year opening')
    if previous_row is not None:
        _require((previous_row['seed'],previous_row['year'],previous_row['a'],previous_row['b'])
                 ==(seed,year-1,a,b) and previous_row['closing']==opening,'discontinuous pair memory')
    raw=[_observation(f,seed,year,{a,b}) for f in row['evidence']]
    keys=[f['source'] for f in raw]
    _require(keys==sorted(set(keys)),'duplicate or unordered directional evidence')
    expected=_pair(seed,year,a,b,opening,raw,row['consult'])
    _require(row==expected,'evidence, decision, or closing state differs from the rules')


class CivicDiplomacy:
    """One seed, bounded pair memory. Keys in each returned year are canonical (a,b), a<b."""
    def __init__(self,seed,nations=8,*,consult=False):
        _require(type(seed) is int and type(nations) is int and nations>0 and type(consult) is bool,
                 'invalid seed, country count, or consultation switch')
        self.seed=seed
        self._nations=range(nations)
        self._consult=consult
        self.year=0
        self._memory={k:_initial() for k in combinations(self._nations,2)}

    def fork(self,*,consult):
        other=CivicDiplomacy(self.seed,len(self._nations),consult=consult)
        other.year=self.year
        other._memory={k:s.copy() for k,s in self._memory.items()}
        return other

    def advance(self,year,previous_rows=()):
        _require(type(year) is int and year==self.year+1,'expected next consecutive year')
        directions={}
        for raw in previous_rows:
            obs=_observation(raw,self.seed,year,self._nations)
            key=obs['source'],obs['target']
            _require(key not in directions,'duplicate directional observation')
            directions[key]=obs
        result={}
        for (a,b),old in self._memory.items():
            evidence=[directions[k] for k in ((a,b),(b,a)) if k in directions]
            result[a,b]=_pair(self.seed,year,a,b,old,evidence,self._consult)
        # Only publish state after every input and pair has been validated.
        self._memory={k:r['closing'].copy() for k,r in result.items()}
        self.year=year
        return result
