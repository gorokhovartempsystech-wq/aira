"""One pinned source, one section/style context and unique original section stories."""

from dataclasses import replace
from hashlib import sha256

from ara.docx_analysis import sections
from ara.docx_analysis.visibility import StyleContextError
from ara.docx_analysis.visibility._read import read_style_context
from ara.docx_analysis.visible_main._build import contexts, valid_identity
from ara.docx_analysis.visible_main._canonical import coverage_key, digest
from ara.docx_analysis.visible_main._models import (
    POLICY,
    VisibleSnapshot,
    VisibleViewError,
    budget,
    checked_limits,
)
from ara.docx_analysis.visible_main._reader import Refusal
from ara.docx_analysis.visible_styled_tables._reader import prepare_styles, translated
from ara.docx_package import DocxError, DocxLimits, open_docx
from ara.docx_package.projection import SourceAnchor

from . import _parse
from ._assemble import PROFILE, Output
from ._coverage import package_coverage
from ._proofs import prove
from ._reader import StoryReader


def build(data, *, document_id, storage_revision, source_sha256, limits):
    limits = checked_limits(limits)
    if type(data) is not bytes or not valid_identity(document_id, storage_revision, source_sha256):
        raise VisibleViewError("invalid_input")
    bounds = DocxLimits()
    if len(data) > bounds.max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise VisibleViewError("source_mismatch")
    source = open_docx(data)
    _parse.preflight(data, source, bounds, limits)
    style_factory = prepare_styles(data, source, limits)
    try:
        section_catalog = sections.read_section_catalog(
            data, source_sha256=source_sha256, limits=sections.SectionLimits(**_parse.caps(limits))
        )
    except sections.SectionCatalogError as exc:
        code = "view_limit_exceeded" if exc.code == "section_limit_exceeded" else exc.code
        raise VisibleViewError(code) from None
    try:
        style_context = read_style_context(data, source_sha256=source_sha256, limits=limits.styles)
    except StyleContextError as exc:
        raise translated(exc) from None
    cached = None

    def proof_factory(context):
        nonlocal cached
        if context is not style_context:
            raise Refusal("style_context_blocked")
        if cached is None:
            cached = style_factory(context)
        return cached

    failures, output = [], Output(source_sha256, limits)
    if section_catalog.status == "blocked":
        failures.append((source.main_part, "section_catalog_blocked", None))
    if style_context.status == "blocked":
        failures.append((source.main_part, "style_context_blocked", None))
    if not failures:
        sequence = [(source.main_part, "main")] + [
            (s.part_name, s.kind) for s in section_catalog.stories
        ]
        main_namespace = None
        for part, kind in sequence:
            root = _parse.build_tree(data, part, bounds)
            if kind == "main":
                main_namespace = root.tag.rpartition("}")[0] + "}"
            table_proof, move_proof = prove(
                root, source, part, kind == "main", section_catalog, limits
            )
            reader = StoryReader(
                root,
                source,
                limits,
                part=part,
                kind=kind,
                main_namespace=main_namespace,
                section_catalog=section_catalog,
                table_catalog=table_proof,
                catalog=move_proof,
                proof_factory=proof_factory,
            )
            try:
                reader.validate_style_context(style_context)
                plans = reader.plans()
                paragraphs, runs, atoms = contexts(reader, plans, style_context, limits)
                output.add(reader, paragraphs, runs, atoms)
            except Refusal as exc:
                failures.append((part, exc.code, SourceAnchor(source_sha256, part, ())))
                break
    complete, coverage = package_coverage(source, section_catalog, style_context, failures, limits)
    if complete:
        budget(len(coverage) + len(output.coverage), limits.max_coverage_items)
        coverage.extend(output.coverage)
        paragraphs, runs, fragments = (
            tuple(output.paragraphs),
            tuple(output.runs),
            tuple(output.fragments),
        )
    else:
        paragraphs = runs = fragments = ()
    text = "\n\n".join(f.text for f in fragments)
    result = VisibleSnapshot(
        document_id,
        storage_revision,
        source_sha256,
        PROFILE,
        POLICY,
        source.main_part,
        style_context,
        paragraphs,
        runs,
        fragments,
        text,
        tuple(sorted(coverage, key=coverage_key)),
        complete,
        sha256(text.encode()).hexdigest(),
        "",
    )
    return replace(
        result, snapshot_sha256=digest(result, limits.max_manifest_bytes, omit_hash=True)
    )
