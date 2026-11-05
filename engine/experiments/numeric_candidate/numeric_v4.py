"""Experimental numeric sets + narrow proof for suppressing NLI. No label access."""
import re
from dataclasses import asdict
from decimal import Decimal
from . import numeric_atoms as atoms
from . import numeric_v3 as prior

NEG_END=re.compile(r'(?:не\s+(?:должен|должна|должно|должны|может|могут)\s+(?:составлять|быть|равняться|храниться)\s*|не\s+|запрещено\s+(?:хранить|иметь|составлять|быть)\s*)$',re.I)

def region(lo=None,hi=None,lop=False,hip=False):return dict(lo=lo,hi=hi,lo_open=lop,hi_open=hip)
def invert(op):return {'eq':'ne','ne':'eq','lt':'ge','ge':'lt','gt':'le','le':'gt'}[op]
def regions(op,n):
    return {'eq':[region(n,n)],'ne':[region(None,n,False,True),region(n,None,True,False)],'lt':[region(None,n,False,True)],'le':[region(None,n)],'gt':[region(n,None,True,False)],'ge':[region(n)]}[op]
def extract(text):
    bounds,rejected=atoms.extract(text);out=[]
    for b in bounds:
        op=atoms.RX.fullmatch(b.quote)['op'].lower()
        kind='eq' if op=='ровно' else 'lt' if op=='менее' else 'gt' if op=='более' else 'ge' if op in ('не менее','не ранее чем через','≥') else 'le'
        n=b.lower if b.lower is not None else b.upper
        prefix=text[:b.start];prefix=re.split(r'[;\n.!?]',prefix)[-1]
        neg=NEG_END.search(prefix)
        # Unknown/double negation must not silently turn into a positive bound.
        if re.search(r'не запрещено|не обязательно|рекомендуется|желательно',text,re.I) or (re.search(r'\bне\b|запрещ',prefix,re.I) and not neg):
            rejected.append(dict(quote=b.quote,reason='unresolved_negation_or_modality'));continue
        if neg:
            if kind in ('ge','le') and op.startswith('не '):
                rejected.append(dict(quote=b.quote,reason='nested_negation'));continue
            kind=invert(kind)
        x=asdict(b);x.update(operator=kind,allowed=regions(kind,n),negation_evidence=dict(start=b.start-len(prefix)+neg.start(),end=b.start,quote=neg[0]) if neg else None)
        out.append(x)
    return out,rejected

def overlap_region(a,b):
    lowers=[(Decimal(x['lo']),x['lo_open']) for x in (a,b) if x['lo'] is not None]
    uppers=[(Decimal(x['hi']),x['hi_open']) for x in (a,b) if x['hi'] is not None]
    if not lowers or not uppers:return True
    lo=max(v for v,o in lowers);hi=min(v for v,o in uppers)
    return lo<hi or (lo==hi and not any(o for v,o in lowers if v==lo) and not any(o for v,o in uppers if v==hi))
def disjoint(a,b):return not any(overlap_region(x,y) for x in a['allowed'] for y in b['allowed'])

SUBJECT=re.compile(r'(?:срок хранения (?:того же )?(?:заказа|акта)|audit log(?: сервиса [а-яё-]+)?|(?:все )?(?:(?:тестовые|производственные|временные) )?логи в hot storage|ttfb(?: страницы «[^»]+»)?|покрытие unit-тестами(?: продукта [а-яё-]+)?)',re.I)
COPULA=re.compile(r'\s*(?:должен составлять|должна составлять|должно составлять|должны составлять|должен храниться|должна храниться|должны храниться|хранится|хранятся|составляет|не должен составлять|не должно составлять|не должен быть|должен быть)?\s*',re.I)
def pure_numeric(text,items):
    # Whitelist of fully consumed single-claim templates, not a bag of keywords.
    if len(items)!=1:return False
    x=items[0];m=SUBJECT.match(text.strip())
    if not m:return False
    leading=len(text)-len(text.lstrip());subject_end=leading+m.end()
    return bool(COPULA.fullmatch(text[subject_end:x['start']]) and re.fullmatch(r'[.\s]*',text[x['end']:]))

def compare(a,b):
    rel,sa,sb=prior.scope_relation(a,b)
    aa,ra=extract(sa['clean']);bb,rb=extract(sb['clean']);matches=[]
    if rel=='overlap_supported':
        for x in aa:
            for y in bb:
                if x['unit']!=y['unit'] or x['binding'][:3]!=y['binding'][:3]:continue
                if x['unit']=='days' and x['binding'][-1]!=y['binding'][-1]:continue
                matches.append(dict(a=x,b=y,disjoint=disjoint(x,y)))
    verdict='conflict' if any(m['disjoint'] for m in matches) else 'compatible_bounds' if matches else 'different_scope' if rel=='different' else 'not_applicable' if rel=='excluded' else 'unknown'
    # Compatibility of one number cannot refute a separate semantic conflict.
    veto=verdict=='compatible_bounds' and len(matches)==1 and pure_numeric(sa['clean'],aa) and pure_numeric(sb['clean'],bb) and not ra and not rb
    return dict(verdict=verdict,matches=matches,scope_relation=rel,scope_a=sa,scope_b=sb,extracted_a=aa,extracted_b=bb,rejected_a=ra,rejected_b=rb,suppress_nli_compatible=veto)

def filter_policy(a,b):
    v=compare(a,b);conflict=v['verdict']=='conflict'
    uncertain_exception=v['verdict']=='unknown' and bool(re.search(r'кроме|исключен',a+' '+b,re.I))
    different=v['verdict'] in ('different_scope','not_applicable') or uncertain_exception
    return dict(numeric_conflict=conflict,block_pair=different or v['suppress_nli_compatible'],bypass_siblings=conflict,suppress_duplicate=conflict or different)
