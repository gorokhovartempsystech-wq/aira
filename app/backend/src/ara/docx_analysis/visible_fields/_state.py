"""Linear retained-field structure pass, independent of marker run visibility."""

from dataclasses import dataclass

from ara.docx_analysis.visible_main._models import budget
from ara.docx_analysis.visible_main._reader import Refusal


@dataclass
class Frame:
    kind: str
    node: object
    phase: str


class State:
    def __init__(self, reader):
        self.reader, self.stack = reader, []
        self.flow, self.codes = None, 0
        self.depth_limit = min(64, reader.limits.max_xml_depth)

    def push(self, kind, node, phase):
        budget(len(self.stack) + 1, self.depth_limit)
        self.stack.append(Frame(kind, node, phase))
        if phase == "code":
            self.codes += 1

    def top(self, kind, node=None):
        if not self.stack or self.stack[-1].kind != kind:
            raise Refusal("unresolved_field_structure")
        frame = self.stack[-1]
        if node is not None and frame.node is not node:
            raise Refusal("unresolved_field_structure")
        return frame

    def marker(self, kind, node):
        self.reader.event("metadata", "field_boundary", node)
        if kind == "field_begin":
            self.push("complex", node, "code")
        elif kind == "field_separate":
            frame = self.top("complex")
            if frame.phase != "code":
                raise Refusal("unresolved_field_structure")
            frame.phase = "result"
            self.codes -= 1
            self.reader.event("metadata", "cached_field_result", node)
        else:
            frame = self.top("complex")
            if frame.phase == "code":
                self.codes -= 1
                self.reader.event("metadata", "field_without_result", frame.node)
            self.stack.pop()

    def run(self, plan):
        result = []
        for kind, node, text in plan.atoms:
            if kind in ("field_begin", "field_separate", "field_end"):
                self.marker(kind, node)
            elif self.codes:
                self.reader.event("excluded", "field_code_content", node)
            elif kind == "field_instruction":
                if text:
                    result.append(("text", node, text))
            else:
                result.append((kind, node, text))
        plan.atoms = result

    def consume(self, events):
        for kind, paragraph, subject in events:
            if kind == "barrier":
                if self.stack:
                    raise Refusal("unsupported_field_flow")
                continue
            flow = self.reader.flow_anchor(self.reader.anchors[paragraph])
            if self.stack and flow != self.flow:
                raise Refusal("unsupported_field_flow")
            self.flow = flow
            if kind == "run":
                self.run(subject)
            elif kind == "simple_enter":
                self.push("simple", subject, "result")
                self.reader.event("excluded", "field_instruction", subject)
                code = "cached_field_result" if len(subject) else "field_without_result"
                self.reader.event("metadata", code, subject)
            elif kind == "simple_exit":
                self.top("simple", subject)
                self.stack.pop()
            elif kind == "paragraph_end" and paragraph in self.reader.section_boundaries:
                if self.stack:
                    raise Refusal("unsupported_field_flow")
        if self.stack:
            raise Refusal("unresolved_field_structure")
