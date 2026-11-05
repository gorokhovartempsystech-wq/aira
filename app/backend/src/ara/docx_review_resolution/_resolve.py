"""Pure full-origin validation and aggregation of active correspondence aliases."""

import json
from collections import defaultdict
from uuid import UUID

from ara.documents.storage import DocumentError
from ara.docx_analysis.presentation import finding_keys
from ara.docx_analysis.presentation._view import _keys
from ara.docx_analysis.remapping import match_findings
from ara.docx_analysis.visible_lists._models import PROFILE as STRUCTURED_PROFILE
from ara.docx_analysis.visible_outline._models import PROFILE as OUTLINE_PROFILE
from ara.docx_analysis.visible_style_lists._models import PROFILE as STYLE_LIST_PROFILE
from ara.docx_analysis.visible_word._models import PROFILE as WORD_PROFILE
from ara.docx_review_preferences import _codec
from ara.docx_review_preferences._models import MAX_HIDDEN, PreferencesState, fail, require

from ._models import (
    DismissalRef,
    FindingAlias,
    Resolution,
    ResolutionInput,
    bounded,
    checked_limits,
    weight,
)


def bundle(origin):
    return origin.source, origin.attempt, origin.result


def text_size(origin):
    # Bounded metadata is an admission estimate only. Its canonical bytes and
    # exact text are independently rederived by B2 before any keys are returned.
    snapshot = json.loads(origin.source.snapshot_data)
    text = snapshot["analysis_text"]
    require(type(text) is str, "storage_error")
    cost = len(text)
    if origin.source.profile in (
        STRUCTURED_PROFILE,
        OUTLINE_PROFILE,
        STYLE_LIST_PROFILE,
        WORD_PROFILE,
    ):
        items = snapshot["lists"]
        require(type(items) is list and len(items) <= 10000, "storage_error")
        for item in items:
            require(
                type(item) is dict
                and type(item.get("label")) is str
                and len(item["label"]) <= 4096
                and type(item.get("suffix")) is str
                and item["suffix"] in ("tab", "space", "nothing"),
                "storage_error",
            )
            cost += len(item["label"]) + (item["suffix"] != "nothing")
    return cost


def validate(inputs):
    require(
        type(inputs) is ResolutionInput and type(inputs.state) is PreferencesState, "storage_error"
    )
    limits = checked_limits(inputs.limits)
    state = inputs.state
    require(type(state.document_id) is UUID and _codec.counter(state.revision), "storage_error")
    require(
        _codec.preferences(state.disabled_types, state.show_questions, state.show_hidden)[
            "disabled_types"
        ]
        == state.disabled_types,
        "storage_error",
    )
    require(type(inputs.origins) is tuple and type(inputs.decisions) is tuple, "storage_error")
    bounded(len(inputs.origins) + 1 <= limits.max_origins)
    origins = (inputs.target, *inputs.origins)
    bounded(sum(weight(origin) for origin in origins) <= limits.max_record_bytes)
    require(
        all(
            type(origin.run_id) is UUID and origin.source.document_id == state.document_id
            for origin in origins
        ),
        "storage_error",
    )
    require(len({origin.run_id for origin in origins}) == len(origins), "storage_error")
    require(
        len(inputs.decisions) <= MAX_HIDDEN
        and all(type(d) is DismissalRef for d in inputs.decisions),
        "storage_error",
    )
    require(
        tuple(sorted({d.key for d in inputs.decisions})) == state.hidden_keys
        and len(inputs.decisions) == len(state.hidden_keys),
        "storage_error",
    )
    index = {origin.run_id: origin for origin in origins}
    for d in inputs.decisions:
        require(
            _codec.digest(d.key, "dh-")
            and _codec.digest(d.finding_id, "df-")
            and type(d.run_id) is UUID
            and d.run_id in index
            and d.result_sha256 == index[d.run_id].result.result_sha256
            and _codec.counter(d.hidden_at_revision)
            and 1 <= d.hidden_at_revision <= state.revision,
            "storage_error",
        )
    require(
        set(index) == {inputs.target.run_id} | {d.run_id for d in inputs.decisions}, "storage_error"
    )
    return index


def resolve(inputs):
    try:
        return _resolve(inputs)
    except DocumentError:
        raise
    except Exception:
        fail("storage_error")


def _resolve(inputs):
    index = validate(inputs)
    target_size = text_size(inputs.target)
    work = target_size
    bounded(work <= inputs.limits.max_text_characters)
    current_keys = finding_keys(*bundle(inputs.target))
    # Verified keys exist before stored references can select any target finding.
    current = {entry.finding_id: entry.key for entry in current_keys}
    decisions = defaultdict(list)
    for item in inputs.decisions:
        decisions[item.run_id].append(item)
    aliases = defaultdict(set)
    for run_id, active in sorted(decisions.items()):
        origin = index[run_id]
        work += target_size + text_size(origin)
        bounded(work <= inputs.limits.max_text_characters)
        transfers = match_findings(bundle(origin), bundle(inputs.target))
        # E4A has revalidated this complete B2 body even if no transfer exists.
        origin_keys = {
            entry.finding_id: entry.key for entry in _keys(json.loads(origin.result.result_data))
        }
        matched = {entry.previous_finding_id: entry for entry in transfers}
        for item in active:
            require(origin_keys.get(item.finding_id) == item.key, "storage_error")
            transfer = matched.get(item.finding_id)
            if transfer is not None:
                require(
                    transfer.previous_key == item.key
                    and current.get(transfer.current_finding_id) == transfer.current_key,
                    "storage_error",
                )
                aliases[transfer.current_finding_id].add(item.key)
    found = tuple(
        FindingAlias(fid, current[fid], tuple(sorted(keys)))
        for fid, keys in sorted(aliases.items())
    )
    return Resolution(
        inputs.state,
        inputs.target,
        inputs.origins,
        inputs.decisions,
        inputs.limits,
        current_keys,
        tuple(sorted({entry.key for entry in found})),
        found,
    )
