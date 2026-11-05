"""Detached global fragments, with local source slices and bounded global offsets."""

from ara.docx_analysis.visible_main._canonical import fragment_id
from ara.docx_analysis.visible_main._models import (
    VisibleCoverage,
    VisibleFragment,
    VisiblePiece,
    budget,
)

PROFILE = "docx-analysis/final-visible-section-stories-v1"


class Output:
    def __init__(self, source_sha256, limits):
        self.sha, self.limits = source_sha256, limits
        self.paragraphs, self.runs, self.fragments, self.coverage = [], [], [], []
        self.position = self.pieces = 0

    def cover(self, status, code, anchor, fid=None):
        budget(len(self.coverage) + 1, self.limits.max_coverage_items)
        self.coverage.append(VisibleCoverage(status, code, anchor.part_name, anchor, fid))

    def add(self, reader, paragraphs, runs, atoms):
        budget(len(self.paragraphs) + len(paragraphs), self.limits.max_paragraphs)
        budget(len(self.runs) + len(runs), self.limits.max_runs)
        self.paragraphs.extend(paragraphs)
        self.runs.extend(runs)
        story = reader.anchors[reader.body]
        self.cover("metadata", "story_flow_read", story)
        for status, code, anchor in reader.events:
            self.cover(status, code, anchor)
        for p, visible in zip(paragraphs, atoms, strict=True):
            if not any(text.strip() for _, _, _, text in visible):
                self.cover("empty", "empty_paragraph", p.paragraph_anchor)
                continue
            length = sum(len(text) for _, _, _, text in visible)
            start = self.position + (2 if self.fragments else 0)
            budget(start + length, self.limits.max_text_characters)
            self.pieces += len(visible)
            budget(self.pieces, self.limits.max_pieces)
            pieces, texts, offset = [], [], 0
            for kind, atom, run, text in visible:
                pieces.append(
                    VisiblePiece(
                        kind,
                        reader.anchors[atom],
                        reader.anchors[run],
                        p.paragraph_anchor,
                        offset,
                        offset + len(text),
                        0,
                        len(text),
                    )
                )
                texts.append(text)
                offset += len(text)
            flow = reader.flow_anchor(p.paragraph_anchor)
            fid = fragment_id(
                story,
                p.paragraph_anchor,
                self.sha,
                self.limits.max_manifest_bytes,
                profile=PROFILE,
                flow=flow,
            )
            self.fragments.append(
                VisibleFragment(
                    fid,
                    story,
                    flow,
                    p.paragraph_anchor,
                    "".join(texts),
                    tuple(pieces),
                    start,
                    start + length,
                )
            )
            self.cover("included", "paragraph", p.paragraph_anchor, fid)
            self.position = start + length
