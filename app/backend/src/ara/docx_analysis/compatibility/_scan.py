"""Streaming syntax and branch decisions over unchanged physical element positions."""

from dataclasses import dataclass, replace

from ara.docx_analysis.sections._xml import parse
from ara.docx_package.projection import SourceAnchor

from ._models import CompatibilityAction, CompatibilityPart, budget, require
from ._names import CORE, MC, PREFIX, UNDERSTOOD, XML, split, words
from ._scope import Scope


@dataclass(slots=True)
class Frame:
    tag: str
    anchor: SourceAnchor
    active: bool
    saved: tuple
    children: int = 0
    choices: int = 0
    fallback: bool = False
    chosen: bool = False
    action_index: int | None = None


class Scanner:
    def __init__(self, source_sha256, part, limits, tally):
        self.source_sha256, self.part = source_sha256, part
        self.limits, self.tally = limits, tally
        self.scope = Scope()
        self.frames, self.actions = [], []

    def start_ns(self, prefix, uri):
        self.scope.start_ns(prefix, uri)

    def add(self, kind, anchor, *, selected=None, attributes=()):
        self.tally[0] += 1
        budget(self.tally[0], self.limits.max_actions)
        self.actions.append(CompatibilityAction(kind, anchor, selected, attributes))
        return len(self.actions) - 1

    def select(self, parent, anchor):
        parent.chosen = True
        if parent.action_index is not None:
            index = parent.action_index
            self.actions[index] = replace(self.actions[index], selected_anchor=anchor)

    def start(self, tag, attrs):
        parent = self.frames[-1] if self.frames else None
        path = () if parent is None else parent.anchor.path + (parent.children,)
        if parent is not None:
            parent.children += 1
        anchor = SourceAnchor(self.source_sha256, self.part, path)
        saved = self.scope.enter(attrs, anchor)
        active = parent.active if parent is not None else True
        frame = Frame(tag, anchor, active, saved)
        uri, local = split(tag)
        if uri == MC:
            self.mc_start(frame, parent, attrs, local)
        else:
            self.ordinary_start(frame, parent, attrs, uri, local)
        if frame.active:
            require(
                all(uri in UNDERSTOOD for uri in saved[3]),
                anchor,
                "unsupported_compatibility_requirement",
            )
        self.frames.append(frame)

    def mc_start(self, frame, parent, attrs, local):
        anchor = frame.anchor
        require(
            local in ("AlternateContent", "Choice", "Fallback"),
            anchor,
            "unsupported_compatibility_markup",
        )
        self.scope.compatibility_attrs(attrs, anchor, choice=local == "Choice")
        if local == "AlternateContent":
            require(parent is None or parent.tag != PREFIX + "AlternateContent", anchor)
            if frame.active:
                frame.action_index = self.add("alternate_content", anchor)
            return
        require(parent is not None and parent.tag == PREFIX + "AlternateContent", anchor)
        if local == "Choice":
            require(not parent.fallback and "Requires" in attrs, anchor)
            needs = self.scope.prefixes(attrs["Requires"], anchor)
            require(bool(needs), anchor)
            parent.choices += 1
            selected = not parent.chosen and all(uri in UNDERSTOOD for uri in needs)
        else:
            require(parent.choices > 0 and not parent.fallback, anchor)
            parent.fallback = True
            selected = not parent.chosen
        if selected:
            self.select(parent, anchor)
        frame.active = frame.active and selected

    def ordinary_start(self, frame, parent, attrs, uri, local):
        ignorable = uri not in UNDERSTOOD and self.scope.ignorable[uri] > 0
        unwrap = ignorable and self.scope.unwrap(uri, local)
        if parent is not None and parent.tag == PREFIX + "AlternateContent":
            require(bool(uri) and self.scope.ignorable[uri] > 0, frame.anchor)
            require(not frame.active or (ignorable and not unwrap), frame.anchor)
        if not frame.active:
            return
        if ignorable:
            if unwrap:
                require(
                    not any("{" + XML + "}" + n in attrs for n in ("base", "lang", "space")),
                    frame.anchor,
                )
                self.add("unwrap_element", frame.anchor)
            else:
                self.add("ignore_element", frame.anchor)
                frame.active = False
            return
        removed = tuple(
            sorted(
                name
                for name in attrs
                if name in CORE
                or (split(name)[0] not in UNDERSTOOD and self.scope.ignorable[split(name)[0]] > 0)
            )
        )
        if removed:
            self.add("strip_attributes", frame.anchor, attributes=removed)

    def data(self, value):
        if self.frames and self.frames[-1].tag == PREFIX + "AlternateContent":
            require(next(words(value), None) is None, self.frames[-1].anchor)

    def end(self, tag):
        frame = self.frames.pop()
        if tag == PREFIX + "AlternateContent":
            require(frame.choices > 0, frame.anchor)
        self.scope.leave(frame.saved)

    def close(self):
        return CompatibilityPart(
            self.part,
            SourceAnchor(self.source_sha256, self.part, ()),
            tuple(sorted(self.actions, key=lambda a: (a.anchor.path, a.kind))),
        )


def scan_part(data, part, source_sha256, bounds, limits, tally):
    return parse(data, part, bounds, Scanner(source_sha256, part, limits, tally))
