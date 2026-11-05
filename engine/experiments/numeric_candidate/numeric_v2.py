"""Research-only v2. No expected labels, IDs, model writes or external calls."""
import re
from dataclasses import asdict
from . import numeric_v1 as old

# Record instance qualifiers, separately from metric/category. No family/ID lookup.
PATTERNS={
 'route':r'маршрут[а-я]*\s+(/[a-z0-9_/-]+)',
 'tenant':r'арендатор[а-я]*\s+([а-яa-z0-9_-]+)',
 'service':r'сервис[а-я]*\s+([а-яa-z0-9_-]+)',
 'product':r'продукт[а-я]*\s+([а-яa-z0-9_-]+)',
 'tariff':r'тариф[а-я]*\s+([а-яa-z0-9_-]+)',
 'region':r'регион[а-я]*\s+([а-яa-z0-9_-]+)',
 'role':r'для роли\s+([а-яa-z0-9_-]+)',
 'page':r'страниц[а-я]*\s+[«"]([^»"]+)[»"]',
}

def scope(text):
    t=text.lower().replace('ё','е')
    fields={}
    for name,rx in PATTERNS.items():
        vs={v for v in re.findall(rx,t) if v not in {'не','должен','должна','должно','должны','того','той','в','для','и','системы','система'}}
        if len(vs)>1:return {'fields':fields,'unresolved':True,'reason':'multiple_instances'}
        if vs:fields[name]=next(iter(vs))
    if 'веб-приложен' in t:fields['platform']='web'
    if 'мобильном приложен' in t or 'мобильного приложен' in t:fields['platform']='mobile'
    modes=[]
    for key,rx in [('normal',r'штатн'),('peak',r'пиков'),('emergency',r'аварийн'),('recovery',r'восстановлен')]:
        if re.search(rx,t):modes.append(key)
    if len(modes)>1:return {'fields':fields,'unresolved':True,'reason':'multiple_modes'}
    if modes:fields['mode']=modes[0]
    if re.search(r'в рабочие дни|по будням',t):fields['day_class']='work'
    if re.search(r'в выходные|по выходным|по субботам|праздник',t):
        if 'day_class' in fields:return {'fields':fields,'unresolved':True,'reason':'multiple_day_classes'}
        fields['day_class']='weekend'
    if re.search(r'оформленн\w* заказ',t):fields['lifecycle']='placed'
    if re.search(r'черновик\w* заказ',t):fields['lifecycle']='draft'
    # Unhandled conditions remain unresolved instead of being dropped.
    unknown=bool(re.search(r'если|кроме|исключен|согласован|согласованию|после|со дня|с даты|с момента|при условии|при нагрузке|при числе|при количестве|при температуре',t))
    return {'fields':fields,'unresolved':unknown,'reason':'unresolved_condition_or_exception' if unknown else None}

def scope_relation(a,b):
    sa,sb=scope(a),scope(b)
    if sa['unresolved'] or sb['unresolved']:return 'unknown',sa,sb
    shared=sa['fields'].keys() & sb['fields'].keys()
    if any(sa['fields'][k]!=sb['fields'][k] for k in shared):return 'different',sa,sb
    # A bare counterpart may be an anaphora, but we do not resolve it by guessing.
    if sa['fields'].keys()!=sb['fields'].keys():return 'unknown',sa,sb
    return 'same_supported_scope',sa,sb

def compare(a,b):
    relation,sa,sb=scope_relation(a,b)
    v=old.compare(a,b)
    # Compare only after instance/condition equality; canonical metric keys still
    # come from v1. No lifting general rules into exceptions in this version.
    if relation!='same_supported_scope':
        v['matches']=[];v['verdict']='different_scope' if relation=='different' else 'unknown'
    v.update(scope_relation=relation,scope_a=sa,scope_b=sb)
    return v

def filter_policy(a,b):
    v=compare(a,b)
    # Change only demonstrably numeric cases; do not globally remove siblings.
    numeric_conflict=v['verdict']=='conflict'
    # Exception handling requires a scoped rule; not a contradictory pair verdict.
    exception=bool(re.search(r'кроме|исключен',a+' '+b,re.I))
    return dict(numeric_conflict=numeric_conflict,
                block_pair=v['verdict']=='different_scope' or exception,
                bypass_siblings=numeric_conflict,
                suppress_duplicate=v['verdict'] in ('conflict','different_scope') or exception)
