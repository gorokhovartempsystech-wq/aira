"""Frozen ordinary-run rules: literal truth tables and blocker precedence."""

import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from hashlib import sha256
from importlib import import_module
from pathlib import Path

import pytest
from docx_projection_fixtures import package
from test_docx_visibility_styles import PRIVATE, fixture, read, style


def api():
    return import_module("ara.docx_analysis.visibility.rules")


def query(**kwargs):
    return api().RunVisibilityQuery(**kwargs)


def resolve(raw, queries, **kwargs):
    return api().resolve_run_visibility(
        raw, source_sha256=sha256(raw).hexdigest(), queries=queries, **kwargs
    )


def prop(value, name="vanish"):
    return "" if value is None else f'<w:{name} w:val="{int(value)}"/>'


def source(d=None, p=None, c=None, *, default_character=False, default_paragraph=False):
    content = (
        f"<w:docDefaults><w:rPrDefault><w:rPr>{prop(d)}</w:rPr></w:rPrDefault></w:docDefaults>"
    )
    content += style(
        "P", f"<w:rPr>{prop(p)}</w:rPr>", attrs='w:default="1"' if default_paragraph else ""
    )
    content += style(
        "C",
        f"<w:rPr>{prop(c)}</w:rPr>",
        kind="character",
        attrs='w:default="1"' if default_character else "",
    )
    return fixture(content)[0]


@pytest.mark.parametrize(
    "d,p,c,hidden",
    [
        (False, False, False, False),
        (False, False, True, True),
        (False, True, False, True),
        (False, True, True, False),
        (True, False, False, True),
        (True, False, True, False),
        (True, True, False, False),
        (True, True, True, True),
    ],
)
def test_literal_three_level_toggle_table_and_direct_overrides(d, p, c, hidden):
    raw = source(d, p, c)
    selectors = dict(paragraph_style_id="P", character_style_id="C")
    result = resolve(
        raw,
        (
            query(**selectors),
            query(**selectors, direct_vanish=False),
            query(**selectors, direct_vanish=True),
        ),
    )
    assert [r.hidden for r in result.results] == [hidden, False, True]
    assert [r.status for r in result.results] == [
        "hidden" if hidden else "visible",
        "visible",
        "hidden",
    ]
    assert all(r.code is None for r in result.results)
    assert result.profile == "docx-visibility/run-rules-v1"
    assert result.policy_version == "docx-analysis-policy/final-visible-no-comments-v2"
    assert result.context_sha256 == read(raw).context_sha256


@pytest.mark.parametrize("d,hidden", [(None, False), (False, False), (True, True)])
def test_absent_levels_inherit_defaults_and_do_not_use_named_normal(d, hidden):
    raw = source(d)
    result = resolve(raw, (query(), query(paragraph_style_id="P", character_style_id="C")))
    assert [r.hidden for r in result.results] == [hidden, hidden]
    absent = resolve(package("<w:p/>")[0], (query(),))
    assert absent.results[0].status == "visible"


def test_nearest_based_on_and_default_paragraph_selection():
    raw = fixture(
        style("Base", "<w:rPr><w:vanish/></w:rPr>")
        + style(
            "P",
            '<w:basedOn w:val="Base"/><w:rPr><w:vanish w:val="0"/></w:rPr>',
            attrs='w:default="1"',
        )
        + style("same", '<w:basedOn w:val="Base"/><w:rPr><w:vanish/></w:rPr>')
    )[0]
    result = resolve(raw, (query(), query(paragraph_style_id="same")))
    assert [r.hidden for r in result.results] == [False, True]


def test_spec_and_web_are_overrides_and_do_not_hide_ordinary_run():
    content = "<w:docDefaults><w:rPrDefault><w:rPr><w:specVanish/><w:webHidden/>"
    content += "</w:rPr></w:rPrDefault></w:docDefaults>"
    content += style("P", '<w:rPr><w:specVanish w:val="0"/></w:rPr>')
    content += style("C", '<w:rPr><w:webHidden w:val="0"/></w:rPr>', kind="character")
    raw = fixture(content)[0]
    result = resolve(
        raw,
        (
            query(),
            query(paragraph_style_id="P", character_style_id="C"),
            query(
                paragraph_style_id="P",
                character_style_id="C",
                direct_spec_vanish=True,
                direct_web_hidden=True,
            ),
        ),
    )
    assert [(r.hidden, r.spec_vanish, r.web_hidden) for r in result.results] == [
        (False, True, True),
        (False, False, False),
        (False, True, True),
    ]
    assert all(r.status == "visible" for r in result.results)


@pytest.mark.parametrize(
    "content,options,code",
    [
        ("<w:unknown/>", {}, "style_context_blocked"),
        (style(), {"paragraph_style_id": "missing"}, "missing_paragraph_style"),
        (
            style("C", kind="character"),
            {"paragraph_style_id": "C"},
            "paragraph_style_type_mismatch",
        ),
        (
            style("P", '<w:basedOn w:val="missing"/>'),
            {"paragraph_style_id": "P"},
            "unresolved_paragraph_style",
        ),
        (style(), {"character_style_id": "missing"}, "missing_character_style"),
        (style(), {"character_style_id": "A"}, "character_style_type_mismatch"),
        (
            style("C", "<w:unknown/>", kind="character"),
            {"character_style_id": "C"},
            "unresolved_character_style",
        ),
        (
            style("C", "<w:rPr><w:vanish/></w:rPr>", kind="character", attrs='w:default="1"'),
            {},
            "implicit_character_style",
        ),
        (
            style("C", "<w:unknown/>", kind="character", attrs='w:default="1"'),
            {},
            "implicit_character_style",
        ),
    ],
)
def test_blockers_are_not_overridden_by_direct_false(content, options, code):
    result = resolve(fixture(content)[0], (query(**options, direct_vanish=False),)).results[0]
    assert result.status == "blocked" and result.code == code
    assert result.hidden is result.spec_vanish is result.web_hidden is None


def test_neutral_default_character_is_not_implicitly_applied_and_explicit_bypasses_guard():
    raw = source(True, None, False, default_character=True)
    assert resolve(raw, (query(),)).results[0].hidden is True
    raw = source(False, None, True, default_character=True)
    result = resolve(raw, (query(), query(character_style_id="C")))
    assert result.results[0].code == "implicit_character_style"
    assert result.results[1].status == "hidden"


def test_batch_order_duplicates_limits_and_source_identity():
    raw = source()
    q = query(direct_vanish=True)
    result = resolve(raw, (q, query(), q), limits=api().RunVisibilityLimits(max_queries=3))
    assert [r.status for r in result.results] == ["hidden", "visible", "hidden"]
    assert (
        result.source_sha256 == sha256(raw).hexdigest() and resolve(raw, (q, query(), q)) == result
    )
    assert resolve(raw, ()).results == ()
    assert not hasattr(result, "complete") and not hasattr(result, "analysis_text")
    with pytest.raises(FrozenInstanceError):
        result.profile = "wrong"
    with pytest.raises(api().RunVisibilityError) as caught:
        resolve(raw, (q,) * 3, limits=api().RunVisibilityLimits(max_queries=2))
    assert caught.value.code == "resolution_limit_exceeded"
    large = resolve(raw, (q,) * 10000)
    assert len(large.results) == 10000 and all(r.hidden for r in large.results)
    assert PRIVATE not in repr(query(paragraph_style_id=PRIVATE))


@pytest.mark.parametrize(
    "options",
    [
        {"paragraph_style_id": ""},
        {"paragraph_style_id": "x" * 254},
        {"character_style_id": 1},
        {"direct_vanish": 0},
        {"direct_vanish": 1},
        {"direct_spec_vanish": "false"},
        {"direct_web_hidden": []},
    ],
)
def test_strict_queries(options):
    with pytest.raises(api().RunVisibilityError) as caught:
        query(**options)
    assert caught.value.code == "invalid_input"


def test_api_revalidates_queries_limits_and_always_validates_source():
    raw = source()
    for qs in ([query()], (None,), iter(())):
        with pytest.raises(api().RunVisibilityError):
            resolve(raw, qs)
    broken = query()
    object.__setattr__(broken, "direct_vanish", 0)
    with pytest.raises(api().RunVisibilityError):
        resolve(raw, (broken,))
    for maximum in (True, 0, 10001, 1.5):
        with pytest.raises(api().RunVisibilityError):
            api().RunVisibilityLimits(max_queries=maximum)
    with pytest.raises(api().RunVisibilityError):
        api().RunVisibilityLimits(styles={})
    from ara.docx_analysis.visibility import StyleContextError

    with pytest.raises(StyleContextError):
        api().resolve_run_visibility(raw, source_sha256="0" * 64, queries=())
    from ara.docx_package import DocxError

    with pytest.raises(DocxError):
        resolve(b"bad zip", ())


def test_fresh_process_is_inert():
    raw = source(False, True)
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from hashlib import sha256
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError("Unexpected application I/O")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=forbidden
from ara.docx_analysis.visibility.rules import resolve_run_visibility,RunVisibilityQuery
b=resolve_run_visibility(data,source_sha256=sha256(data).hexdigest(),
    queries=(RunVisibilityQuery(paragraph_style_id="P"),))
assert b.results[0].status=="hidden"
blocked={"psycopg","sqlalchemy","onnxruntime","numpy","aira_ml","fastapi"}
assert not any(m.split(".")[0] in blocked for m in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=raw,
        capture_output=True,
        env={"PATH": os.defpath, "PYTHONPATH": str(Path.cwd() / "src")},
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b""
