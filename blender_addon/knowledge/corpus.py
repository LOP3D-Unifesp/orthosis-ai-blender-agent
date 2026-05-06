"""Knowledge corpus loader for Phase 6 of REFATOR_PLAN.md.

Scans knowledge/domain/, knowledge/skills/, and knowledge/recipes/ for
Markdown files with front-matter and returns a typed list of KnowledgeItems.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class KnowledgeItem:
    title: str
    content: str               # body text with front-matter stripped
    applies_when: list[str]    # turn-class strings from front-matter
    topics: list[str]          # scoring keywords
    priority: str              # "high" | "medium" | "low"
    lang: str                  # "en" | "pt"
    path: Path
    category: str              # "skills" | "recipes" | "domain"


# ---------------------------------------------------------------------------
# Front-matter parser
# ---------------------------------------------------------------------------

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Return (fields_dict, body_text) for a Markdown file with front-matter.

    If no front-matter block is found the fields dict is empty and body_text
    is the original text.  A leading UTF-8 BOM is stripped transparently.
    """
    # Strip BOM if present (file read without utf-8-sig encoding).
    text = text.lstrip("\ufeff")
    m = _FM_RE.match(text)
    if not m:
        return {}, text

    raw_fm = m.group(1)
    body = text[m.end():]
    fields: dict[str, str] = {}
    for line in raw_fm.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip()] = val.strip()
    return fields, body


def _csv(value: str) -> list[str]:
    """Split a comma-separated string into a stripped list, filtering blanks."""
    return [v.strip() for v in value.split(",") if v.strip()]


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

_SUBDIRS = ("skills", "recipes", "domain")


class KnowledgeCorpus:
    """Loads and caches all knowledge items found under *corpus_dir*."""

    def __init__(self, corpus_dir: Path) -> None:
        self._corpus_dir = corpus_dir
        self._cache: list[KnowledgeItem] | None = None

    def items(self) -> list[KnowledgeItem]:
        if self._cache is not None:
            return self._cache
        self._cache = list(self._load())
        return self._cache

    def _load(self):
        for subdir in _SUBDIRS:
            sub = self._corpus_dir / subdir
            if not sub.is_dir():
                continue
            for md in sorted(sub.glob("*.md")):
                item = self._parse_file(md, category=subdir)
                if item is not None:
                    yield item

    def _parse_file(self, path: Path, category: str) -> KnowledgeItem | None:
        try:
            # Use utf-8-sig so BOM-prefixed files are handled transparently.
            text = path.read_text(encoding="utf-8-sig")
        except Exception:
            return None

        fields, body = parse_front_matter(text)
        title = fields.get("title", path.stem)
        applies_when = _csv(fields.get("applies_when", ""))
        topics = _csv(fields.get("topics", ""))
        priority = fields.get("priority", "medium")
        lang = fields.get("lang", "")

        return KnowledgeItem(
            title=title,
            content=body.strip(),
            applies_when=applies_when,
            topics=topics,
            priority=priority,
            lang=lang,
            path=path,
            category=category,
        )
