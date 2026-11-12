"""Standalone review of Russian requirements with stable fragment identifiers."""

import argparse
import json
import re
from collections import defaultdict
from hashlib import sha256
from pathlib import Path

from .aira_acceptance_review import review as acceptance_review
from .aira_inspection_schedule import review as inspection_schedule_review
from .aira_numeric_review import literal_tiers
from .aira_numeric_review import review as numeric_review
from .aira_sla_review import (
    cross_document_conflicts,
    learned_classifier,
)
from .aira_sla_review import (
    review as sla_review,
)
from .aira_sla_review import (
    review_documents as sla_review_documents,
)
from .aira_warranty_review import review as warranty_review

SOURCE_HASH = re.compile(r"[0-9a-f]{64}")


def document_cards(fragments, *, classify_stage=None, include_sla=True):
    if not isinstance(fragments, dict) or any(
        not isinstance(key, str) or not key.strip() or not isinstance(text, str) or not text.strip()
        for key, text in fragments.items()
    ):
        raise ValueError(
            "Expected a JSON object mapping stable fragment IDs to nonempty source text"
        )
    return [
        *numeric_review(fragments, literal_tiers(fragments)),
        *acceptance_review(fragments),
        *(sla_review(fragments, classify_stage) if include_sla else []),
        *warranty_review(fragments),
    ]


def ordered_cards(cards, fragments):
    order = {key: index for index, key in enumerate(fragments)}
    unique = {(card["kind"], card["reason"], tuple(card["fragment_ids"])): card for card in cards}
    return sorted(unique.values(), key=lambda card: min(order[key] for key in card["fragment_ids"]))


def review(fragments, *, classify_stage=None):
    """Return cards in source order, with IDs from the input document."""
    return ordered_cards(document_cards(fragments, classify_stage=classify_stage), fragments)


def review_bundle(projections, *, classify_stage=None):
    """Review document projections and retain each card's original source locations."""
    if not isinstance(projections, list) or not projections:
        raise ValueError("Expected a nonempty array of document projections")
    locations, cards, seen_sources = {}, [], set()
    shared_scopes = defaultdict(list)
    for projection in projections:
        if not isinstance(projection, dict):
            raise ValueError("Invalid document projection")
        source, units = projection.get("source_sha256"), projection.get("units")
        if (
            not isinstance(source, str)
            or not SOURCE_HASH.fullmatch(source)
            or source in seen_sources
        ):
            raise ValueError("Expected a distinct SHA-256 for each source document")
        if not isinstance(units, list) or not units:
            raise ValueError("Expected a nonempty array of source units")
        scope = projection.get("shared_sla_scope")
        if scope is not None and (not isinstance(scope, str) or not scope.strip()):
            raise ValueError("Expected a nonempty shared SLA scope")
        seen_sources.add(source)
        fragments = {}
        for unit in units:
            if (
                not isinstance(unit, dict)
                or not isinstance(path := unit.get("xml_path"), str)
                or not path.strip()
            ):
                raise ValueError("Expected an XML path for each source unit")
            identity = "vf-" + sha256(f"{source}\n{path}".encode()).hexdigest()
            if identity != unit.get("id") or identity in locations:
                raise ValueError("Invalid or repeated stable fragment ID")
            fragments[identity] = unit.get("text")
            locations[identity] = {
                "fragment_id": identity,
                "source_sha256": source,
                "xml_path": path,
            }
            if unit.get("kind") == "image_transcription":
                asset, member = unit.get("asset_sha256"), unit.get("asset_member")
                if (
                    not isinstance(asset, str)
                    or not SOURCE_HASH.fullmatch(asset)
                    or not isinstance(member, str)
                    or not member
                ):
                    raise ValueError("Expected original image hash and archive member")
                locations[identity].update(asset_sha256=asset, asset_member=member)
            if unit.get("kind") == "spreadsheet_row":
                sheet, number, member = (
                    unit.get("sheet"),
                    unit.get("row"),
                    unit.get("source_member"),
                )
                if (
                    not isinstance(sheet, str)
                    or not sheet
                    or type(number) is not int
                    or number < 1
                    or not isinstance(member, str)
                    or not member
                    or not path.endswith(f"/row[@r={number}]")
                ):
                    raise ValueError("Expected worksheet name, row and original archive member")
                locations[identity].update(sheet=sheet, row=number, source_member=member)
            if unit.get("kind") == "pdf_page":
                page = unit.get("page")
                if type(page) is not int or page < 1 or path != f"/page[{page}]":
                    raise ValueError("Expected matching one-based PDF page number and path")
                locations[identity]["page"] = page
                if unit.get("manual_transcription") is True:
                    locations[identity]["manual_transcription"] = True
        if scope is None:
            cards.extend(review(fragments, classify_stage=classify_stage))
        else:
            cards.extend(document_cards(fragments, include_sla=False))
            shared_scopes[scope].append((source, fragments))
        cards.extend(inspection_schedule_review(units))
    for documents in shared_scopes.values():
        cards.extend(
            sla_review_documents([fragments for _, fragments in documents], classify_stage)
        )
        cards.extend(cross_document_conflicts(documents))
    cards = ordered_cards(cards, locations)
    return {
        "cards": cards,
        "locations": {
            key: locations[key]
            for key in dict.fromkeys(key for card in cards for key in card["fragment_ids"])
        },
    }


def unique_json_object(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("Repeated JSON key")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", type=Path, help="JSON object mapping stable fragment IDs to source text"
    )
    parser.add_argument(
        "--learned-stage", action="store_true", help="Enable the experimental SLA stage classifier"
    )
    parser.add_argument(
        "--bundle", action="store_true", help="Read an array of document projections"
    )
    args = parser.parse_args()
    try:
        fragments = json.loads(
            args.input.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_json_object
        )
        classifier = learned_classifier() if args.learned_stage else None
        analyze = review_bundle if args.bundle else review
        cards = analyze(fragments, classify_stage=classifier)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(cards, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
