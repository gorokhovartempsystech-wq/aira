"""Expose prototype cards through the native Word review extension."""

from .aira_review import review

_LABELS = {
    "acceptance": "Критерии приёмки",
    "unverifiable": "Что нужно уточнить",
    "contradiction": "Возможное противоречие",
}


def propose(fragments):
    texts = {fragment["id"]: fragment["text"] for fragment in fragments}
    return [
        {
            "text": _LABELS[card["kind"]],
            "reason": card["reason"],
            "references": [
                {"fragment_id": key, "start": 0, "end": min(len(texts[key]), 500)}
                for key in card["fragment_ids"]
            ],
        }
        for card in review(texts)[:6]
    ]
