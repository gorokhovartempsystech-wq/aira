"""Experimental numeric checker. No engine imports, label/oracle access or model writes.
Finite lexical binding rules; unsupported scope deliberately abstains.
"""
import re
from decimal import Decimal
from dataclasses import dataclass, asdict

OP = r'не должен превышать|не должна превышать|не должно превышать|не должны превышать|не превышает|не более|не менее|не ранее чем через|в течение|более|до|≥|≤'
UNIT = r'миллисекунд\w*|мс|секунд\w*|минут\w*|мин|месяц\w*|год\w*|лет|дн\w*|сут\w*|актив\w*|клик\w*|%'
RX = re.compile(r'(?P<op>'+OP+r')\s*(?P<n>\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?)\s*(?P<u>'+UNIT+r')(?![а-яё])', re.I)
UNSAFE = re.compile(r'если|при условии|кроме|исключен|согласован|согласованию|после|со дня|с даты|с момента|старше|дополнительно|доля|не ранее.*не позднее', re.I)
@dataclass
class Bound:
    start: int
    end: int
    quote: str
    lower: str | None
    upper: str | None
    lower_open: bool
    unit: str
    binding: tuple
    context: str

def base_binding(t, unit):
    t=t.lower().replace('ё','е')
    if UNSAFE.search(t): return None
    if 'ttfb' in t: return ('latency','ttfb','default')
    if 'unit' in t and ('покрыти' in t or '%' in t): return ('coverage','unit','default')
    if 'integration' in t and ('покрыти' in t or '%' in t): return ('coverage','integration','default')
    if re.search(r'хран|храни', t):
        if re.search(r'быстр|доступ|производительност', t): return None
        if 'hot storage' in t: obj='logs:hot'
        elif re.search(r'архив',t): obj='logs:archive'
        elif re.search(r'audit log|админк',t): obj='journal:admin-actions'
        elif re.search(r'журнал.*действ',t): obj='journal:user-actions'
        elif re.search(r'заказ',t): obj='orders'
        elif re.search(r'акт[а-я]*\b',t): obj='acts'
        elif re.search(r'оценк',t): obj='grades'
        else: return None
        return ('retention',obj,'default')
    if unit=='assets' and re.search(r'актив',t): return ('capacity','licensed-assets','default')
    if unit=='clicks' and re.search(r'бронирован',t):
        if re.search(r'отмен',t): return ('path-length','cancellation','default')
        if re.search(r'поиск',t): return ('path-length','search-booking','default')
    if unit=='seconds' and re.search(r'алерт|предупрежден',t):
        p=re.search(r'\bp([12])\b',t)
        if p: return ('delivery-latency','alert','p'+p[1])
    # SLA branch intentionally unsupported: local/inherited condition scope unresolved.
    return None

def binding(t, unit):
    base=base_binding(t,unit)
    if base is None: return None
    t=t.lower().replace('ё','е')
    # Positive conditions do not cancel each other: unbound default versus a
    # specific day class is unknown. Multiple classes also remain unsupported.
    work=bool(re.search(r'в рабочие дни|по будням',t))
    weekend=bool(re.search(r'в выходные|по выходным|по субботам|праздник',t))
    if work and weekend: return None
    condition='workdays' if work else 'weekends' if weekend else 'unspecified'
    # Distinguish explicitly named pages; same-page deictics retain default.
    page=re.search(r'страниц(?:ы|а|е|у)\s+(?:«([^»]+)»|"([^"]+)")',t)
    entity=next((v for v in page.groups() if v),'unspecified') if page else 'unspecified'
    # Unknown condition syntax is not silently projected away.
    if re.search(r'при (?:нагрузке|числе|количестве|температуре)|для роли|для пользователя с ролью',t): return None
    return (*base,condition,entity)

def extract(text):
    out=[]; rejected=[]
    ms=list(RX.finditer(text))
    for m in ms:
        # A number in a clause must not inherit a sibling clause's object/condition.
        left=max(text.rfind(';',0,m.start()),text.rfind(',',0,m.start()),text.rfind('\n',0,m.start()))+1
        ends=[x for x in (text.find(';',m.end()),text.find(',',m.end()),text.find('\n',m.end())) if x>=0]
        right=min(ends) if ends else len(text)
        context=text if len(ms)==1 else text[left:right]
        u=m['u'].lower(); n=Decimal(m['n'].replace(' ','').replace('\u00a0','').replace(',','.'))
        if u=='мс' or u.startswith('миллисекунд'): unit='seconds'; n/=1000
        elif u.startswith('секунд'): unit='seconds'
        elif u.startswith('мин'): unit='seconds'; n*=60
        elif u.startswith(('год','лет')): unit='months'; n*=12
        elif u.startswith('месяц'): unit='months'
        elif u.startswith(('дн','сут')): unit='days'
        elif u.startswith('актив'): unit='assets'
        elif u.startswith('клик'): unit='clicks'
        else: unit='percent'
        key=binding(context,unit)
        if not key:
            rejected.append({'quote':m[0],'reason':'object_metric_or_condition_unresolved','context':context}); continue
        # Explicit calendar distinctions must agree. Generic days are not silently work days.
        calendar='work' if re.search(r'рабоч\w* д',context,re.I) else 'calendar' if re.search(r'календар',context,re.I) else 'unspecified'
        if unit=='days': key=(*key,calendar)
        op=m['op'].lower()
        lower=op in ('не менее','не ранее чем через','≥','более')
        out.append(Bound(m.start(),m.end(),m[0],str(n) if lower else None,None if lower else str(n),op=='более',unit,key,context))
    return out,rejected

def disjoint(a,b):
    for lo,hi in ((a,b),(b,a)):
        if lo.lower is not None and hi.upper is not None:
            x,y=Decimal(lo.lower),Decimal(hi.upper)
            if x>y or (x==y and lo.lower_open): return True
    return False

def compare(a,b):
    aa,ra=extract(a); bb,rb=extract(b)
    matched=[]
    for x in aa:
        for y in bb:
            if x.unit==y.unit and x.binding==y.binding:
                matched.append({'a':asdict(x),'b':asdict(y),'disjoint':disjoint(x,y)})
    verdict='conflict' if any(x['disjoint'] for x in matched) else 'compatible_bounds' if matched else 'unknown'
    return {'verdict':verdict,'matches':matched,'rejected_a':ra,'rejected_b':rb,'extracted_a':[asdict(x) for x in aa],'extracted_b':[asdict(x) for x in bb]}
