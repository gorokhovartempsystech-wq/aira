"""Контракт ML ↔ backend и формат пакетов данных.

Поля выведены из макета Анны (04.10): у каждого замечания есть тип, важность,
фрагмент в тексте, второе требование с его статусом и объяснение.
Подробно — docs/contract.md.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["active", "deprecated", "exception", "discussion"]
Check = Literal["lint", "duplicates", "contradictions"]
IssueType = Literal["contradiction", "duplicate", "lint", "wording"]
Severity = Literal["critical", "warning", "info"]
Relation = Literal["contradiction", "duplicate", "independent", "version_update"]


class Requirement(BaseModel):
    id: str
    version: int = 1
    title: str = ""
    section: str = ""
    document: str = ""
    text: str
    # без статуса нельзя отличить противоречие от замены старой версии —
    # на этом построена гипотеза, поэтому поле обязательно в контракте
    status: Status = "active"
    links: list[str] = Field(default_factory=list)


class Change(BaseModel):
    requirement_id: str
    old_text: str | None = None
    new_text: str


class Target(BaseModel):
    requirement_id: str
    version: int | None = None


class AnalyzeRequest(BaseModel):
    project_id: str = ""
    checks: list[Check] = Field(default_factory=lambda: ["lint", "duplicates", "contradictions"])
    target: Target | None = None
    change: Change | None = None
    requirements: list[Requirement]


class Span(BaseModel):
    start: int
    end: int
    quote: str


class Related(BaseModel):
    requirement_id: str
    version: int
    status: Status
    quote: str


class Suggestion(BaseModel):
    before: str
    after: str


class Issue(BaseModel):
    id: str
    type: IssueType
    severity: Severity
    requirement_id: str
    span: Span | None = None
    related: Related | None = None
    explanation: str
    rule: str | None = None
    suggestion: Suggestion | None = None
    score: float | None = None


class Skipped(BaseModel):
    check: Check
    reason: str


class AnalyzeResponse(BaseModel):
    model_version: str
    issues: list[Issue]
    skipped: list[Skipped] = Field(default_factory=list)


# --- пакеты данных для экспериментов ---------------------------------------

class GoldContradiction(BaseModel):
    requirement_id: str
    # фрагмент второго требования, который противоречит изменению
    quote: str


class PacketChange(BaseModel):
    id: str
    requirement_id: str
    old_text: str | None = None
    new_text: str
    # correct — корректное изменение (в т.ч. замена старой версии): на нём меряем ложные тревоги
    kind: Literal["contradicting", "correct"]
    contradicts: list[GoldContradiction] = Field(default_factory=list)
    # требования, которые эксперт считает нужным увидеть, чтобы принять решение
    evidence: list[str] = Field(default_factory=list)
    note: str = ""


class Packet(BaseModel):
    id: str
    family: str          # семейство документов: разбиение dev/test только по нему
    domain: str
    source: Literal["synthetic", "open", "pilot"] = "synthetic"
    split: Literal["dev", "test"] = "dev"
    requirements: list[Requirement]
    changes: list[PacketChange]
