"""Linear paragraph segmentation at generated markers, with exact source slices."""

from ara.docx_analysis.visible_main._canonical import digest
from ara.docx_analysis.visible_main._models import POLICY, VisibleFragment, VisiblePiece, budget
from ara.docx_analysis.visible_stories._assemble import Output as StoryOutput

from ._models import PROFILE, NoteReference
from ._reader import LABEL, REFERENCE


class Output(StoryOutput):
    marker_codes = {LABEL: "note_number_marker"}

    def __init__(self, source_sha256, limits, lookup, *, profile=PROFILE):
        super().__init__(source_sha256, limits)
        self.lookup, self.references = lookup, []
        self.profile = profile

    def segment(self, reader, paragraph, visible, preceding):
        if not any(text.strip() for _, _, _, text in visible):
            return None
        length = sum(len(text) for _, _, _, text in visible)
        start = self.position + (2 if self.fragments else 0)
        budget(start + length, self.limits.max_text_characters)
        budget(len(self.fragments) + 1, self.limits.max_paragraphs)
        self.pieces += len(visible)
        budget(self.pieces, self.limits.max_pieces)
        pieces, texts, offset = [], [], 0
        for kind, node, run, text in visible:
            pieces.append(
                VisiblePiece(
                    kind,
                    reader.anchors[node],
                    reader.anchors[run],
                    paragraph,
                    offset,
                    offset + len(text),
                    0,
                    len(text),
                )
            )
            texts.append(text)
            offset += len(text)
        story, flow = reader.anchors[reader.body], reader.flow_anchor(paragraph)
        fid = "vf-" + digest(
            dict(
                domain="docx-note-fragment/1",
                profile=self.profile,
                policy_version=POLICY,
                source_sha256=self.sha,
                story_anchor=story,
                flow_anchor=flow,
                paragraph_anchor=paragraph,
                preceding_marker=preceding,
            ),
            self.limits.max_manifest_bytes,
        )
        self.fragments.append(
            VisibleFragment(
                fid, story, flow, paragraph, "".join(texts), tuple(pieces), start, start + length
            )
        )
        self.cover("included", "paragraph_segment", paragraph, fid)
        self.position = start + length
        return fid

    def paragraph(self, reader, paragraph, visible):
        segments, boundaries = [[]], []
        preceding = [None]
        for atom in visible:
            kind, node, _, _ = atom
            if kind == REFERENCE or kind in self.marker_codes:
                anchor = reader.anchors[node]
                if kind == REFERENCE:
                    note_kind, target = self.lookup.resolve(reader, node)
                    boundaries.append((len(segments) - 1, anchor, note_kind, target))
                    self.cover("metadata", "note_reference", anchor)
                else:
                    self.cover("metadata", self.marker_codes[kind], anchor)
                segments.append([])
                preceding.append(anchor)
            else:
                segments[-1].append(atom)
        ids = [
            self.segment(reader, paragraph, atoms, marker)
            for atoms, marker in zip(segments, preceding, strict=True)
        ]
        if not any(ids):
            self.cover("empty", "empty_paragraph", paragraph)
        # Nearest nonblank segment on either side, computed once, also for consecutive markers.
        left, right, last = [], [None] * len(ids), None
        for fid in ids:
            last = fid or last
            left.append(last)
        last = None
        for i in range(len(ids) - 1, -1, -1):
            last = ids[i] or last
            right[i] = last
        for i, anchor, kind, target in boundaries:
            budget(len(self.references) + 1, self.limits.max_pieces)
            self.references.append(
                NoteReference(kind, anchor, paragraph, target, left[i], right[i + 1])
            )

    def add(self, reader, paragraphs, runs, atoms):
        budget(len(self.paragraphs) + len(paragraphs), self.limits.max_paragraphs)
        budget(len(self.runs) + len(runs), self.limits.max_runs)
        self.paragraphs.extend(paragraphs)
        self.runs.extend(runs)
        self.cover("metadata", "story_flow_read", reader.anchors[reader.body])
        for status, code, anchor in reader.events:
            self.cover(status, code, anchor)
        for paragraph, visible in zip(paragraphs, atoms, strict=True):
            self.paragraph(reader, paragraph.paragraph_anchor, visible)
