"""Skill-check answers stored in the master resume.

Confirmed skills live in an ordinary skill group (``CONFIRMED_SKILL_GROUP``),
so the fact index, requirement map, and skills validation treat them as facts
with no special path. Declined skills live in ``skill_check.declined`` and are
only used to avoid asking again.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from pathlib import Path

from keyword_coverage import normalize_term, supported_tech_requirements
from models import CONFIRMED_SKILL_GROUP, JSONResume, Skill, SkillCheckAnswers


def _unique(terms: Iterable[str]) -> list[str]:
    result: dict[str, str] = {}
    for term in terms:
        cleaned = " ".join(term.split())
        if cleaned:
            result.setdefault(normalize_term(cleaned), cleaned)
    return list(result.values())


def confirmed_terms(master: JSONResume) -> list[str]:
    for group in master.skills or []:
        if group.name == CONFIRMED_SKILL_GROUP:
            return list(group.keywords or [])
    return []


def declined_terms(master: JSONResume) -> list[str]:
    return list(master.skill_check.declined) if master.skill_check else []


def answered_keys(master: JSONResume) -> set[str]:
    """Normalized terms the user already has or already answered."""
    keys = {
        normalize_term(keyword)
        for group in master.skills or []
        for keyword in group.keywords or []
    }
    keys.update(normalize_term(term) for term in declined_terms(master))
    return keys


def replace_answers(
    master: JSONResume, confirmed: Sequence[str], declined: Sequence[str]
) -> JSONResume:
    """Copy of ``master`` whose confirmed and declined lists are exactly these."""
    confirmed_list = _unique(confirmed)
    confirmed_keys = {normalize_term(term) for term in confirmed_list}
    declined_list = [
        term for term in _unique(declined) if normalize_term(term) not in confirmed_keys
    ]
    skills = [
        group for group in master.skills or [] if group.name != CONFIRMED_SKILL_GROUP
    ]
    if confirmed_list:
        skills.append(Skill(name=CONFIRMED_SKILL_GROUP, keywords=confirmed_list))
    return master.model_copy(
        update={
            "skills": skills or None,
            "skill_check": SkillCheckAnswers(declined=declined_list),
        }
    )


def apply_answers(
    master: JSONResume, confirmed: Sequence[str], declined: Sequence[str]
) -> JSONResume:
    """Add new answers; a term answered again moves to its new list."""
    new_confirmed = {normalize_term(term) for term in confirmed}
    new_declined = {normalize_term(term) for term in declined}
    kept_confirmed = [
        term for term in confirmed_terms(master) if normalize_term(term) not in new_declined
    ]
    kept_declined = [
        term for term in declined_terms(master) if normalize_term(term) not in new_confirmed
    ]
    return replace_answers(
        master, [*kept_confirmed, *confirmed], [*kept_declined, *declined]
    )


def bullet_tech_requirements(
    requirements: Sequence[dict], master: JSONResume
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Technologies a bullet may name only when its own facts name them.

    Confirmed skills are exempt: the user vouched for them, so a bullet may
    use one wherever the work fits.
    """
    confirmed = {normalize_term(term) for term in confirmed_terms(master)}
    return tuple(
        item
        for item in supported_tech_requirements(requirements)
        if normalize_term(item[0]) not in confirmed
    )


def save_master(master: JSONResume, path: Path) -> None:
    """Write the master atomically so a running job never reads half a file."""
    path = Path(path)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        master.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)
