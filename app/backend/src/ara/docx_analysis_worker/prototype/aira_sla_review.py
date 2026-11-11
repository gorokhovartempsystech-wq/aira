"""Report missing out-of-hours reaction deadlines on stable source fragments."""
import argparse
from collections import defaultdict
from decimal import Decimal
import json
from pathlib import Path
import re

from .aira_scope_gate import CLAUSE, DURATION, OBJECTS, STAGES, labels, modes, verify


UPPER_LIMIT = re.compile(
    r"\b(?:не\s+(?:(?:долж\w*|может)\s+)?превыша\w*|не\s+более|не\s+позднее\s+чем\s+через|в\s+течение)\s+"
    r"\d+\s*(?:\([^()]+\)\s*)?(?:(?:рабоч\w*|календарн\w*)\s+)?(?:мин\w*|час\w*|сут\w*|дн\w*|день)\b", re.I,
)
START_EVENT = re.compile(r"\b(?:с\s+(?:момента|даты)|после)\s+(?:получен\w*|поступлен\w*|уведомлен\w*|выявлен\w*|регистраци\w*)", re.I)
EXCEPTION = re.compile(r"\bза\s+исключением\b|\bв\s+случае\b", re.I)
AGREED_LIMIT = re.compile(r"\bсрок\w*\s+(?:устран\w*\s+)?согласовыва\w*\b|\bсогласован\w*\s+срок\w*\b", re.I)
AGREEMENT_ACTION = re.compile(r"\bсоглас(?:ова|у)\w*\b[^.!?]{0,80}\bсрок\w*\s+устран\w*\b|\bсрок\w*\s+устран\w*\b[^.!?]{0,80}\bсоглас(?:ова|у)\w*\b", re.I)
SEPARATE_CONTRACT = re.compile(r"\bпо\s+отдельн\w*\s+договор\w*\b", re.I)
CONTRACT_DECISION = re.compile(r"\b(?:решени\w*|реша\w*|решит\w*)\b[^.!?]{0,120}\bотдельн\w*\s+договор\w*\b", re.I)
SPECIAL_CASES = {
    "utilities": re.compile(r"\bкоммунальн\w*\s+служб\w*\b", re.I),
    "special_work": re.compile(r"\bспециальн\w*\s+работ\w*\b", re.I),
    "complex": re.compile(r"\bособо\s+сложн\w*\s+неисправност\w*\b", re.I),
    "missing_parts": re.compile(r"\bотсутств\w*\s+запасн\w*\s+част\w*\b", re.I),
}
TEMPORARY_ACTION = re.compile(r"\b(?:временн\w*\s+схем\w*|резервн\w*\s+(?:лини\w*|канал\w*|оборудован\w*))\b", re.I)
PENDING_AGREEMENT = re.compile(r"\b(?:до\s+согласован\w*|на\s+период\s+согласован\w*)\b", re.I)
CLASSIFICATION = re.compile(r"\b(?:признак\w*|критери\w*|считается|призна[её]тся)\b", re.I)


def exception_deadline_cards(documents):
    """Inspect explicit repair exceptions against their own scope and stage."""
    fragments = [(key, text) for document in documents for key, text in document.items()]
    candidates = []
    for key, text in fragments:
        marker = EXCEPTION.search(text)
        if not marker:
            continue
        ordinary = CLAUSE.split(text[:marker.start()].strip())[-1]
        exception = text[marker.start():]
        if not (STAGES["resolution"].search(ordinary) and UPPER_LIMIT.search(ordinary) and START_EVENT.search(ordinary)):
            continue
        conditions = labels(exception, SPECIAL_CASES)
        if not conditions:
            continue
        if AGREED_LIMIT.search(exception):
            candidates.append((key, conditions, "agreement"))
        elif SEPARATE_CONTRACT.search(exception):
            candidates.append((key, conditions, "contract"))
    if not candidates:
        return

    clauses = [(key, clause, tags) for key, text in fragments for clause in CLAUSE.split(text)
               if (tags := labels(clause, SPECIAL_CASES))]
    for key, conditions, stage in candidates:
        applicable = [(clause, tags) for source, clause, tags in clauses
                      if source != key or not EXCEPTION.search(clause)]
        action = AGREEMENT_ACTION if stage == "agreement" else CONTRACT_DECISION
        missing = []
        timed = set().union(*(tags for clause, tags in applicable
                              if action.search(clause) and UPPER_LIMIT.search(clause) and START_EVENT.search(clause)))
        if not conditions <= timed:
            missing.append("предельный срок согласования и событие его отсчёта" if stage == "agreement"
                           else "срок решения о ремонте по отдельному договору и событие его отсчёта")
        temporary = set().union(*(tags for clause, tags in applicable
                                   if TEMPORARY_ACTION.search(clause) and PENDING_AGREEMENT.search(clause)))
        if stage == "agreement" and not conditions <= temporary:
            missing.append("временный режим до согласования")
        if stage == "contract" and "complex" in conditions and not any(
                "complex" in tags and CLASSIFICATION.search(clause) for clause, tags in applicable):
            missing.append("признаки особо сложной неисправности")
        if missing:
            setup = ("Для исключения срок устранения согласовывают отдельно." if stage == "agreement"
                     else "Для исключения ремонт переводится на отдельный договор.")
            yield {"kind": "unverifiable", "fragment_ids": [key],
                   "reason": f"{setup} Сверьте {', '.join(missing)}."}


def review_documents(documents, classify_stage=None):
    cards = []
    for subject in OBJECTS:
        target = {"stage": "reaction", "object": subject, "mode": "work"}
        working = next((result for document in documents if (result := verify(target, document))), None)
        if not working or any(verify({**target, "mode": "off"}, document, classify_stage)
                              for document in documents):
            continue
        cards.append({"kind": "unverifiable", "fragment_ids": [working[0]],
                      "reason": "Для указанной категории инцидентов задан срок реакции в рабочее время. "
                                "Сверьте применимый предел реакции вне рабочего времени."})
    return [*cards, *exception_deadline_cards(documents)]


def review(fragments, classify_stage=None):
    return review_documents([fragments], classify_stage)


def cross_document_conflicts(documents):
    """Compare repeated literal SLA clauses in documents of one declared scope."""
    claims = defaultdict(dict)
    for source, fragments in documents:
        for identity, text in fragments.items():
            for clause in CLAUSE.split(text):
                subjects = labels(clause, OBJECTS)
                if labels(clause, STAGES) != {"reaction"} or len(subjects) != 1:
                    continue
                mode = modes(clause)
                if not mode or not verify({"stage": "reaction", "object": next(iter(subjects)),
                                           "mode": min(mode)}, {identity: clause}):
                    continue
                match, = DURATION.finditer(clause)
                value, unit = match.groups()
                signature = " ".join((clause[:match.start()] + " <срок> " + clause[match.end():]).casefold().split())
                unit_class = next(prefix for prefix in ("мин", "час", "сут", "д") if unit.casefold().startswith(prefix))
                normalized_value = Decimal(value.replace(",", "."))
                claims[(signature, unit_class)].setdefault(source, {}).setdefault(normalized_value, identity)
    cards = []
    for (_, unit), sources in claims.items():
        if len(sources) < 2 or any(len(values) != 1 for values in sources.values()):
            continue
        values = {next(iter(items)) for items in sources.values()}
        if len(values) > 1:
            units = {"мин": "мин", "час": "ч", "сут": "сут.", "д": "дн."}
            durations = " и ".join(f"{value.normalize():f} {units[unit]}" for value in sorted(values))
            cards.append({
                "kind": "contradiction", "fragment_ids": [next(iter(items.values())) for items in sources.values()],
                "reason": f"Для одной нормы реакции указаны разные сроки: {durations}. "
                          "Сверьте применимый срок для этой категории инцидентов и режима.",
            })
    return cards


def learned_classifier(threshold=0.70):
    # The experiment's trained stage tagger is reused unchanged in this candidate.
    from probe_scope_pairs import train

    model = train()
    cache = {}

    def classify(text):
        if text not in cache:
            values = model.predict_proba([text])[0]
            best = int(values.argmax())
            cache[text] = str(model.classes_[best]) if values[best] >= threshold else "other"
        return cache[text]

    return classify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON mapping stable fragment IDs to source text")
    parser.add_argument("--learned-stage", action="store_true")
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or any(not k.strip() or not isinstance(v, str) or not v.strip()
                                         for k, v in data.items()):
        parser.error("expected a mapping from nonempty IDs to nonempty text")
    model = learned_classifier() if args.learned_stage else None
    print(json.dumps(review(data, model), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
