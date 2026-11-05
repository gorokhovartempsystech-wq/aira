"""Ordinary-run formatting algebra over one freshly read pinned style context."""

from ._read import read_style_context
from ._rules_models import (
    RunVisibility,
    RunVisibilityBatch,
    RunVisibilityError,
    RunVisibilityLimits,
    RunVisibilityQuery,
)

__all__ = [
    "resolve_run_visibility",
    "RunVisibilityQuery",
    "RunVisibilityLimits",
    "RunVisibilityError",
    "RunVisibility",
    "RunVisibilityBatch",
]


def _blocked(code):
    return RunVisibility("blocked", code, None, None, None)


def _select(index, identity, kind):
    if identity is None:
        return None, None
    record = index.get(identity)
    if record is None:
        return None, f"missing_{kind}_style"
    if record.style_type != kind:
        return None, f"{kind}_style_type_mismatch"
    if record.status != "resolved":
        return None, f"unresolved_{kind}_style"
    return record.properties, None


def _effective(context, index, q):
    if context.status == "blocked":
        return _blocked("style_context_blocked")
    p_id = q.paragraph_style_id
    if p_id is None:
        p_id = context.default_paragraph_style
    paragraph, code = _select(index, p_id, "paragraph")
    if code:
        return _blocked(code)
    character, code = _select(index, q.character_style_id, "character")
    if code:
        return _blocked(code)
    if q.character_style_id is None and context.default_character_style is not None:
        implicit, code = _select(index, context.default_character_style, "character")
        if code or any(
            getattr(implicit, n).value is True for n in ("vanish", "spec_vanish", "web_hidden")
        ):
            return _blocked("implicit_character_style")
    d = context.defaults.vanish.value is True
    p = paragraph.vanish.value if paragraph else None
    c = character.vanish.value if character else None
    hidden = q.direct_vanish
    if hidden is None:
        hidden = d ^ (d if p is None else p) ^ (d if c is None else c)
    ordinary = []
    for name in ("spec_vanish", "web_hidden"):
        value = getattr(context.defaults, name).value is True
        for level in (paragraph, character):
            if level is not None and getattr(level, name).value is not None:
                value = getattr(level, name).value
        direct = getattr(q, "direct_" + name)
        if direct is not None:
            value = direct
        ordinary.append(value)
    return RunVisibility("hidden" if hidden else "visible", None, hidden, *ordinary)


def resolve_run_visibility(
    data: bytes,
    *,
    source_sha256: str,
    queries: tuple[RunVisibilityQuery, ...],
    limits: RunVisibilityLimits | None = None,
) -> RunVisibilityBatch:
    if limits is None:
        limits = RunVisibilityLimits()
    if type(limits) is not RunVisibilityLimits or type(queries) is not tuple:
        raise RunVisibilityError("invalid_input")
    limits.__post_init__()
    if len(queries) > limits.max_queries:
        raise RunVisibilityError("resolution_limit_exceeded")
    for query in queries:
        if type(query) is not RunVisibilityQuery:
            raise RunVisibilityError("invalid_input")
        query.__post_init__()
    context = read_style_context(data, source_sha256=source_sha256, limits=limits.styles)
    index = {s.style_id: s for s in context.styles}
    return RunVisibilityBatch(
        context.source_sha256,
        "docx-visibility/run-rules-v1",
        "docx-analysis-policy/final-visible-no-comments-v2",
        context.context_sha256,
        tuple(_effective(context, index, q) for q in queries),
    )
