"""Parse the small Markji subset used by the vocabulary library."""

from __future__ import annotations

import re
from dataclasses import dataclass


TITLE_PATTERN = re.compile(r"^\[P#H1#([^\]]+)\]")
REFERENCE_PATTERN = re.compile(r"\[Card#ID/([^#\]]+)#")
BASE_PREFIX = "基础词义｜"
COMPARISON_PREFIX = "近义辨析｜"
APPLICATION_PREFIX = "语境应用｜"


@dataclass(frozen=True)
class ParsedCard:
    card_id: str
    root_id: str
    grammar_version: int | None
    content: str
    title: str
    card_type: str
    term: str
    members: tuple[str, ...]
    member_set: frozenset[str]
    references: tuple[str, ...]


def parse_card(card: dict) -> ParsedCard:
    content = str(card.get("content") or "")
    match = TITLE_PATTERN.match(content)
    if not match:
        raise ValueError("missing Markji H1 title")
    title = match.group(1).strip()
    references = tuple(REFERENCE_PATTERN.findall(content))
    invalid = [reference for reference in references if not reference.startswith("mkjr_")]
    if invalid:
        raise ValueError("non-root card reference: " + "、".join(invalid))

    term = ""
    members: tuple[str, ...] = ()
    if title.startswith(BASE_PREFIX):
        card_type = "base"
        term = title.removeprefix(BASE_PREFIX).strip()
    elif title.startswith(COMPARISON_PREFIX):
        card_type = "comparison"
        members = tuple(
            part.strip()
            for part in title.removeprefix(COMPARISON_PREFIX).split("、")
            if part.strip()
        )
    elif title.startswith(APPLICATION_PREFIX):
        card_type = "application"
    else:
        card_type = "other"

    return ParsedCard(
        card_id=str(card.get("id") or ""),
        root_id=str(card.get("root_id") or ""),
        grammar_version=card.get("grammar_version"),
        content=content,
        title=title,
        card_type=card_type,
        term=term,
        members=members,
        member_set=frozenset(members),
        references=references,
    )
