"""Сборка ответа по контракту: линтинг, дубли, противоречия."""
from __future__ import annotations

from . import __version__, select
from .classify import default_classifier
from .embed import default_embedder
from .lint import lint
from .schema import (AnalyzeRequest, AnalyzeResponse, Issue, Related, Skipped, Span)

DUP_THRESHOLD = 0.83      # из бенчмарка на 100 синтетических парах — перекалибровать на реальных


class Analyzer:
    def __init__(self, embedder=None, classifier=None, selector="structured", k=select.K):
        self.embedder = embedder or default_embedder()
        self.classifier = classifier or default_classifier()
        self.selector = select.SELECTORS[selector]
        self.selector_name = selector
        self.k = k

    @property
    def model_version(self):
        return f"aira-ml {__version__} / {self.embedder.name} / {self.classifier.name} / {self.selector_name}"

    def analyze(self, req: AnalyzeRequest) -> AnalyzeResponse:
        reqs = req.requirements
        if req.change:
            rid, text = req.change.requirement_id, req.change.new_text
        elif req.target:
            rid = req.target.requirement_id
            text = next((r.text for r in reqs if r.id == rid), "")
        else:
            raise ValueError("нужен target или change")

        issues: list[Issue] = []
        skipped: list[Skipped] = []
        n = 0

        def nid():
            nonlocal n
            n += 1
            return f"iss-{n}"

        if "lint" in req.checks:
            for rule, a, b, quote in lint(text):
                issues.append(Issue(id=nid(), type="lint", severity=rule.severity, requirement_id=rid,
                                    span=Span(start=a, end=b, quote=quote), explanation=rule.explanation,
                                    rule=f"ISO/IEC/IEEE 29148: {rule.property}"))

        others = [r for r in reqs if r.id != rid and r.status not in ("deprecated", "discussion")]
        if "duplicates" in req.checks and others:
            vecs = self.embedder.encode([text] + [r.text for r in others])
            for r, c in zip(others, vecs[1:] @ vecs[0]):
                if c >= DUP_THRESHOLD:
                    issues.append(Issue(id=nid(), type="duplicate", severity="warning", requirement_id=rid,
                                        related=Related(requirement_id=r.id, version=r.version, status=r.status,
                                                        quote=r.text),
                                        explanation=f"{r.id} описывает то же поведение другими словами. "
                                                    "Стоит объединить и оставить одно.",
                                        score=round(float(c), 3)))

        if "contradictions" in req.checks:
            if not self.classifier.uses_llm:
                skipped.append(Skipped(check="contradictions",
                                       reason="LLM не настроена: противоречия ищет эвристика по числам "
                                              "и единицам измерения, остальные типы не найдутся"))
            for c in self.selector(text, rid, reqs, self.embedder, k=self.k):
                v = self.classifier.classify(text, c.req.text, c.cos, c.status)
                if v.relation != "contradiction":
                    continue
                q = v.change_quote or text
                a = text.find(q)
                issues.append(Issue(
                    id=nid(), type="contradiction", severity="critical", requirement_id=rid,
                    span=Span(start=a, end=a + len(q), quote=q) if a >= 0 else None,
                    related=Related(requirement_id=c.req.id, version=c.req.version, status=c.req.status,
                                    quote=v.candidate_quote or c.req.text),
                    explanation=v.explanation, rule="ISO/IEC/IEEE 29148: непротиворечивость набора",
                    score=round(v.confidence, 3)))
        return AnalyzeResponse(model_version=self.model_version, issues=issues, skipped=skipped)
