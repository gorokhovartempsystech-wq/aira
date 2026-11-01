"""Narrow guards for standalone, single-variable requirements. Unknown => NLI."""
import re
from decimal import Decimal


def normalized(text):
    # Preserve case and punctuation: IDs and quoted values can be case-sensitive.
    return " ".join(text.split())


_PATTERN = re.compile(
    r"(?P<subject>[^.;!?]+?) "
    r"(?P<operator>должн[ао]? составлять (?:не более|не менее|ровно)|"
    r"не должн[ао]? превышать|должн[ао]? быть не меньше) "
    r"(?P<number>\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?) "
    r"(?P<unit>рублей|рубля|рубль|секунд|секунды|секунда|символов|символа|символ)\.?$"
)


def parse(text):
    t=normalized(text)
    # Clauses, quotations, multiple quantities and hidden contexts are out of scope.
    if re.search(r'[«»"`]|\b(?:если|кроме|при|после|до|максимальн\w*|минимальн\w*)\b',t,re.I):
        return None
    m=_PATTERN.fullmatch(t)
    if not m:return None
    subject=m['subject']
    if re.search(r'\d|\b(?:и|или|не|только)\b',subject,re.I):return None
    op=m['operator']
    relation='eq' if 'ровно' in op else ('ge' if 'не менее' in op or 'не меньше' in op else 'le')
    unit=next(x for x in ['руб','секунд','символ'] if m['unit'].startswith(x))
    value=Decimal(m['number'].replace(' ','').replace('\u00a0','').replace(',','.'))
    return subject,unit,relation,value


def verdict(a,b):
    """Return False for provable compatibility, True for disjoint bounds, else None.

    Assumes the caller verified active status/no explicit exception. This parser is
    intentionally not a general numeric-label corrector or domain reasoner.
    """
    x,y=parse(a),parse(b)
    if x is None or y is None or x[:2]!=y[:2]:return None
    def interval(c):
        op,v=c[2:]
        return {'eq':(v,v),'ge':(v,Decimal('Infinity')),'le':(Decimal('-Infinity'),v)}[op]
    lo,hi=interval(x);otherlo,otherhi=interval(y)
    return max(lo,otherlo)>min(hi,otherhi)


def equivalent(a,b):
    x,y=parse(a),parse(b)
    return x is not None and x==y


def explicit_identity(text):
    x=parse(text)
    return bool(x and (re.search(r'\b[A-Z][A-Z0-9_]+\b',x[0]) or re.search(r'\bпол[ея] [a-z]+_[a-z_]+\b',x[0])))
