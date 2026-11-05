"""Local research candidate: explicit universals/exclusions, exact intervals.
Missing context is not treated as a universal quantifier. No reference labels.
"""
import re
from dataclasses import asdict
from . import numeric_exact as intervals
from . import numeric_v2 as previous

CLASSES={'тестовых':'test','временных':'temporary','производственных':'production'}
EXCEPTION=re.compile(r'(?:за исключением|кроме)\s+(тестовых|временных|производственных)\s+логов',re.I)
UNIVERSALS={
    'mode':r'во всех режимах',
    'service':r'для всех сервисов',
    'tenant':r'для всех арендаторов',
    'region':r'для всех регионов',
    'product':r'для всех продуктов',
    'tariff':r'для всех тарифов',
    'log_class':r'все логи|для всех логов',
}
def parsed_scope(text):
    clean=text; exclusions={};evidence=[]
    def blank(m):return ' '*len(m[0])
    for m in EXCEPTION.finditer(text):
        exclusions.setdefault('log_class',[]).append(CLASSES[m[1].lower()])
        evidence.append(dict(kind='exception',start=m.start(),end=m.end(),quote=m[0]))
    clean=EXCEPTION.sub(blank,clean)
    universal=[]
    for field,rx in UNIVERSALS.items():
        for m in re.finditer(rx,clean,re.I):
            universal.append(field);evidence.append(dict(kind='universal',field=field,start=m.start(),end=m.end(),quote=m[0]))
        # keep "логи" for numeric metric binding: only the scope parser sees blanks.
    scope_text=clean
    for rx in UNIVERSALS.values():scope_text=re.sub(rx,blank,scope_text,flags=re.I)
    s=previous.scope(scope_text)
    # Any unrecognized exception remains unknown. Never guess its class.
    if re.search(r'кроме|исключен',clean,re.I):s.update(unresolved=True,reason='unsupported_exception')
    t=clean.lower().replace('ё','е')
    types=[]
    for cls,stem in [('test','тестов'),('temporary','временн'),('production','производственн')]:
        if re.search(stem+r'\w*\s+лог|лог\w*\s+'+stem,t):types.append(cls)
    if len(types)>1:s.update(unresolved=True,reason='multiple_log_classes')
    elif types:s['fields']['log_class']=types[0]
    # "logs except class X" defines the complement even without the word "all".
    if exclusions:universal.append('log_class')
    # A named object plus a different class in the same sentence is unsupported.
    s.update(universal=sorted(set(universal)),excluded=exclusions,evidence=evidence,clean=clean)
    return s

def scope_relation(a,b):
    sa,sb=parsed_scope(a),parsed_scope(b)
    if sa['unresolved'] or sb['unresolved']:return 'unknown',sa,sb
    for x,y in ((sa,sb),(sb,sa)):
        for field,values in x['excluded'].items():
            if y['fields'].get(field) in values:return 'excluded',sa,sb
    keys=sa['fields'].keys()|sb['fields'].keys()
    unknown=False
    for k in keys:
        av,bv=sa['fields'].get(k),sb['fields'].get(k)
        if av is not None and bv is not None and av!=bv:return 'different',sa,sb
        if av is None and bv is not None and k not in sa['universal']:unknown=True
        if bv is None and av is not None and k not in sb['universal']:unknown=True
    if unknown:return 'unknown',sa,sb
    # Explicit universal/finite complements overlap over the remaining instances.
    return 'overlap_supported',sa,sb

def compare(a,b):
    rel,sa,sb=scope_relation(a,b)
    aa,ra=intervals.extract(sa['clean']);bb,rb=intervals.extract(sb['clean'])
    matches=[]
    if rel=='overlap_supported':
        for x in aa:
            for y in bb:
                if x.unit!=y.unit or x.binding[:3]!=y.binding[:3]:continue
                if x.unit=='days' and x.binding[-1]!=y.binding[-1]:continue
                matches.append(dict(a=asdict(x),b=asdict(y),disjoint=intervals.disjoint(x,y)))
    verdict='conflict' if any(m['disjoint'] for m in matches) else 'compatible_bounds' if matches else 'different_scope' if rel=='different' else 'not_applicable' if rel=='excluded' else 'unknown'
    return dict(verdict=verdict,matches=matches,scope_relation=rel,scope_a=sa,scope_b=sb,extracted_a=[asdict(x) for x in aa],extracted_b=[asdict(x) for x in bb],rejected_a=ra,rejected_b=rb)

def filter_policy(a,b):
    v=compare(a,b);conflict=v['verdict']=='conflict'
    uncertain_exception=v['verdict']=='unknown' and bool(re.search(r'кроме|исключен',a+' '+b,re.I))
    block=v['verdict'] in ('different_scope','not_applicable') or uncertain_exception
    return dict(numeric_conflict=conflict,block_pair=block,bypass_siblings=conflict,suppress_duplicate=conflict or block)
