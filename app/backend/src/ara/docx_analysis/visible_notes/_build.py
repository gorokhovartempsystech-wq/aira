"""One source and shared contexts; original note trees are cached per physical part."""

from dataclasses import replace
from hashlib import sha256

from ara.docx_analysis import notes, sections
from ara.docx_analysis.visibility import StyleContextError
from ara.docx_analysis.visibility._read import read_style_context
from ara.docx_analysis.visible_main._build import contexts, valid_identity
from ara.docx_analysis.visible_main._canonical import coverage_key, digest
from ara.docx_analysis.visible_main._models import POLICY, VisibleViewError, budget, checked_limits
from ara.docx_analysis.visible_main._reader import Refusal
from ara.docx_analysis.visible_stories._proofs import prove
from ara.docx_analysis.visible_styled_tables._reader import prepare_styles, translated
from ara.docx_package import DocxError, DocxLimits, open_docx
from ara.docx_package.projection import SourceAnchor

from . import _parse
from ._assemble import Output
from ._coverage import package_coverage
from ._models import PROFILE, NoteSnapshot
from ._proofs import part_move_identities, prove_note
from ._reader import NoteReader
from ._references import References


def metadata(data, source, limits):
    style_factory = prepare_styles(data, source, limits)
    try:
        section_catalog = sections.read_section_catalog(
            data, source_sha256=source.sha256, limits=sections.SectionLimits(**_parse.caps(limits))
        )
        note_catalog = notes.read_note_catalog(
            data, source_sha256=source.sha256, limits=notes.NoteLimits(**_parse.caps(limits))
        )
    except (sections.SectionCatalogError, notes.NoteCatalogError) as exc:
        code = "view_limit_exceeded" if exc.code.endswith("limit_exceeded") else exc.code
        raise VisibleViewError(code) from None
    try:
        style_context = read_style_context(data, source_sha256=source.sha256, limits=limits.styles)
    except StyleContextError as exc:
        raise translated(exc) from None
    return style_context, style_factory, section_catalog, note_catalog


def build(
    data,
    *,
    document_id,
    storage_revision,
    source_sha256,
    limits,
    reader_type=NoteReader,
    profile=PROFILE,
    extra_preflight=None,
    provider=None,
    output_factory=None,
    coverage_factory=None,
):
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
    if extra_preflight is not None:
        extra_preflight(data, source, bounds, limits)
    style_context, style_factory, section_catalog, note_catalog = (
        metadata(data, source, limits) if provider is None else provider.metadata()
    )
    cached = None

    def proof_factory(context):
        nonlocal cached
        if context is not style_context:
            raise Refusal("style_context_blocked")
        if cached is None:
            cached = style_factory(context)
        return cached

    failures, lookup = [], References(note_catalog)
    output = (Output if output_factory is None else output_factory)(
        source_sha256, limits, lookup, profile=profile
    )
    for catalog, code in (
        (section_catalog, "section_catalog_blocked"),
        (note_catalog, "note_catalog_blocked"),
        (style_context, "style_context_blocked"),
    ):
        if catalog.status == "blocked":
            failures.append((source.main_part, code, None))
    main_namespace = None

    def read_story(root, part, kind, path=()):
        if provider is not None:
            table, move = provider.prove(root, source, part, kind, path, section_catalog, limits)
        elif kind in ("footnote", "endnote"):
            table, move = prove_note(root, source, part, path, section_catalog, limits)
        else:
            table, move = prove(root, source, part, kind == "main", section_catalog, limits)
        reader = reader_type(
            root,
            source,
            limits,
            part=part,
            kind=kind,
            path=path,
            main_namespace=main_namespace,
            section_catalog=section_catalog,
            table_catalog=table,
            catalog=move,
            proof_factory=proof_factory,
        )
        reader.validate_style_context(style_context)
        plans = reader.plans()
        paragraphs, runs, atoms = contexts(reader, plans, style_context, limits)
        output.add(reader, paragraphs, runs, atoms)

    if not failures:
        tree_reader = _parse.build_tree if provider is None else provider.tree
        sequence = [(source.main_part, "main")] + [
            (s.part_name, s.kind) for s in section_catalog.stories
        ]
        for part, kind in sequence:
            try:
                root = tree_reader(data, part, bounds)
                if kind == "main":
                    main_namespace = root.tag.rpartition("}")[0] + "}"
                read_story(root, part, kind)
            except Refusal as exc:
                failures.append((part, exc.code, SourceAnchor(source_sha256, part, ())))
                break
    if not failures:
        trees = {}
        for target, (part, _) in lookup.used.items():
            try:
                if part.part_name not in trees:
                    tree = tree_reader(data, part.part_name, bounds)
                    guard = part_move_identities if provider is None else provider.check_note_part
                    guard(tree, source, part.part_name)
                    trees[part.part_name] = tree
                tree = trees[part.part_name]
                node = (
                    tree[target.path[0]] if provider is None else provider.note_node(tree, target)
                )
                read_story(node, part.part_name, part.kind, target.path)
            except Refusal as exc:
                failures.append((part.part_name, exc.code, target))
                break
    complete, coverage = (package_coverage if coverage_factory is None else coverage_factory)(
        source, section_catalog, note_catalog, style_context, lookup.used, failures, limits
    )
    if provider is not None:
        for item in provider.coverage():
            budget(len(coverage) + 1, limits.max_coverage_items)
            coverage.append(item)
    if complete:
        budget(len(coverage) + len(output.coverage), limits.max_coverage_items)
        coverage.extend(output.coverage)
        paragraphs, runs = tuple(output.paragraphs), tuple(output.runs)
        fragments, references = tuple(output.fragments), tuple(output.references)
    else:
        paragraphs = runs = fragments = references = ()
    text = "\n\n".join(f.text for f in fragments)
    result = NoteSnapshot(
        document_id,
        storage_revision,
        source_sha256,
        profile,
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
        references,
    )
    return replace(
        result, snapshot_sha256=digest(result, limits.max_manifest_bytes, omit_hash=True)
    )
