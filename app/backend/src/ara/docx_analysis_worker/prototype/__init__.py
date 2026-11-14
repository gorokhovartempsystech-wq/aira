"""Expose prototype cards through the native Word review extension."""

from .aira_review import review

_LABELS = {
    "acceptance": "Критерии приёмки",
    "unverifiable": "Что нужно уточнить",
    "contradiction": "Возможное противоречие",
}


def propose(fragments):
    texts = {fragment["id"]: fragment["text"] for fragment in fragments}
    output = []
    for card in review(texts):
        # Exact rule spans take precedence. Otherwise cite the entire source
        # paragraph: an arbitrary prefix can omit the issue being explained.
        references = card.get("references")
        if references is None:
            references = [
                {"fragment_id": key, "start": 0, "end": len(texts[key])}
                for key in card["fragment_ids"]
            ]
        # The existing Word contract permits at most 16 references per item.
        # Retain every reference in explicitly labelled continuation cards.
        parts = (len(references) + 15) // 16
        for index in range(parts):
            suffix = f" (опоры: часть {index + 1} из {parts})" if parts > 1 else ""
            output.append(
                {
                    "text": _LABELS[card["kind"]] + suffix,
                    "reason": card["reason"],
                    "references": references[index * 16 : (index + 1) * 16],
                }
            )
    return output
