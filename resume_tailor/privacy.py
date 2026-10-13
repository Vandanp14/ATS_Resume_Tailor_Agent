"""Keep personal data out of every model call.

Two independent layers:

1. ``strip_personal_fields`` removes identity fields (basics, contact details,
   URLs, locations, references) from the JSON put into prompts. Code owns those
   fields: assembly copies them from the master, so models never need them.
2. ``PrivacyGuard`` wraps the chat provider (any model, any vendor) and replaces
   whatever personal value still appears in a message -- the user's name,
   email, phone, profile handles, URLs, secrets, and any term listed in a
   private-terms file -- with a stable placeholder. Model answers are restored
   (placeholder -> original) before anything parses them.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from models import JSONResume

PERSONAL_KEYS = frozenset(
    {
        "basics",
        "references",
        "url",
        "location",
        "email",
        "phone",
        "profiles",
        "username",
        "address",
        "postalCode",
    }
)
# Prompt contexts derived from the job posting, not from the user.
JD_CONTEXT_KEYS = frozenset(
    {"jd_text", "jd_profile_json", "company_stack_json", "company_signals_json"}
)

_PLACEHOLDER_RE = re.compile(
    r"\[(?:PERSON|EMAIL|PHONE|URL|ID|SECRET|PRIVATE)_\d+\]", re.IGNORECASE
)
_TLDS = r"(?:com|dev|io|org|net|app|me|ai|co|edu|us|xyz|tech|site|page|sh)"
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "SECRET",
        re.compile(
            r"(?i)\b(?:password|passwd|api[_ -]?key|secret|token)\s*[:=]\s*[^\s\"',;]+"
        ),
    ),
    (
        "SECRET",
        re.compile(
            r"\b(?:sk-(?:or-)?[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{30,}"
            r"|gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9-]{10,})"
        ),
    ),
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    (
        "URL",
        re.compile(
            r"(?i)\b(?:https?://|www\.)[^\s\"'<>]+"
            rf"|\b(?:[a-z0-9-]+\.)+{_TLDS}/[^\s\"'<>]*"
            # Personal-site domains even without a scheme or path (name.me).
            r"|\b(?:[a-z0-9-]+\.)+(?:me|dev|page|site|xyz)\b"
        ),
    ),
    ("ID", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    (
        "PHONE",
        re.compile(
            r"(?<![\w.])(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])"
            r"\d{3}[\s.-]\d{4}(?![\w.])"
        ),
    ),
)


def strip_personal_fields(value: Any) -> Any:
    """Copy of ``value`` without identity keys, at any depth."""
    if isinstance(value, dict):
        return {
            key: strip_personal_fields(item)
            for key, item in value.items()
            if key not in PERSONAL_KEYS
        }
    if isinstance(value, list):
        return [strip_personal_fields(item) for item in value]
    return value


def strip_prompt_context(context: dict[str, object]) -> dict[str, object]:
    """Strip identity keys from every resume-derived JSON prompt variable."""
    cleaned: dict[str, object] = {}
    for key, value in context.items():
        if key in JD_CONTEXT_KEYS or not isinstance(value, str):
            cleaned[key] = value
            continue
        try:
            parsed = json.loads(value)
        except ValueError:
            cleaned[key] = value
            continue
        if not isinstance(parsed, (dict, list)):
            cleaned[key] = value
            continue
        cleaned[key] = json.dumps(
            strip_personal_fields(parsed), indent=2, ensure_ascii=False
        )
    return cleaned


def load_private_terms(path: str | os.PathLike[str] | None = None) -> list[str]:
    """Lines of the private-terms file (``PRIVATE_TERMS_FILE``), if present."""
    target = Path(path or os.getenv("PRIVATE_TERMS_FILE", "private_terms.txt"))
    if not target.is_file():
        return []
    return [
        line.strip()
        for line in target.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _master_literals(master: JSONResume) -> list[tuple[str, str]]:
    basics = master.basics
    if basics is None:
        return []
    literals: list[tuple[str, str]] = []
    name = (basics.name or "").strip()
    if name:
        literals.append(("PERSON", name))
        literals.extend(
            ("PERSON", part)
            for part in re.split(r"\s+", name)
            if len(part.strip(".,")) >= 3
        )
    if basics.email:
        literals.append(("EMAIL", basics.email))
    if basics.phone:
        literals.append(("PHONE", basics.phone))
    if basics.url:
        literals.append(("URL", basics.url))
    for profile in basics.profiles or []:
        if profile.url:
            literals.append(("URL", profile.url))
        if profile.username and len(profile.username) >= 3:
            literals.append(("PERSON", profile.username))
    if basics.location:
        for value in (basics.location.address, basics.location.postalCode):
            if value and len(value) >= 3:
                literals.append(("PRIVATE", value))
    for reference in master.references or []:
        reference_name = getattr(reference, "name", None)
        if reference_name and len(reference_name) >= 3:
            literals.append(("PERSON", reference_name))
    return literals


def _handle_parts(master: JSONResume) -> list[str]:
    basics = master.basics
    if basics is None:
        return []
    parts = [part for part in re.split(r"[\s.,]+", basics.name or "") if len(part) >= 4]
    parts += [
        profile.username
        for profile in basics.profiles or []
        if profile.username and len(profile.username) >= 4
    ]
    return list(dict.fromkeys(parts))


class PrivacyGuard:
    """ChatProvider wrapper: redact outbound messages, restore inbound text."""

    def __init__(self, provider: Any, private_terms: Iterable[str] | None = None):
        self._provider = provider
        self._private_terms = list(
            load_private_terms() if private_terms is None else private_terms
        )
        self.reset()

    def reset(self) -> None:
        self._literals: list[tuple[str, re.Pattern[str]]] = []
        self._handles: list[re.Pattern[str]] = []
        self._placeholders: dict[tuple[str, str], str] = {}
        self._originals: dict[str, str] = {}
        self._counts: Counter[str] = Counter()
        self._register(("PRIVATE", term) for term in self._private_terms)

    def protect(self, master: JSONResume | None) -> None:
        """Start a run: forget old values and register this master's identifiers."""
        self.reset()
        if master is not None:
            self._register(_master_literals(master))
            self._register_handles(_handle_parts(master))

    def _register_handles(self, parts: Iterable[str]) -> None:
        """Whole tokens containing the user's name or handle: domains, usernames.

        Catches ``janedoe.me`` or ``doejane42`` that word-bounded name matching
        misses. Applied after exact literals, so ``[URL_1]`` stays intact.
        """
        for part in parts:
            pattern = re.compile(
                r"(?<![\w.@/-])[\w.+/-]*" + re.escape(part) + r"[\w.+/-]*(?<![.,])",
                re.IGNORECASE,
            )
            self._handles.append(pattern)

    def _register(self, literals: Iterable[tuple[str, str]]) -> None:
        for kind, value in literals:
            value = value.strip()
            if not value:
                continue
            pattern = re.compile(
                r"(?<![\w])" + re.escape(value) + r"(?![\w])", re.IGNORECASE
            )
            self._literals.append((kind, pattern))
        # Longest first, so a full name wins over its first name.
        self._literals.sort(key=lambda item: len(item[1].pattern), reverse=True)

    def _placeholder(self, kind: str, original: str) -> str:
        key = (kind, original.lower())
        if key not in self._placeholders:
            number = sum(1 for k, _ in self._placeholders if k == kind) + 1
            placeholder = f"[{kind}_{number}]"
            self._placeholders[key] = placeholder
            self._originals[placeholder] = original
            self._counts[kind.lower()] += 1
        return self._placeholders[key]

    def redact(self, text: str) -> str:
        def substitute(kind: str):
            return lambda match: self._placeholder(kind, match.group(0))

        for kind, pattern in self._literals:
            text = pattern.sub(substitute(kind), text)
        for pattern in self._handles:
            text = pattern.sub(
                lambda match: self._placeholder(
                    "URL" if "." in match.group(0) else "PERSON", match.group(0)
                ),
                text,
            )
        for kind, pattern in _PATTERNS:
            text = pattern.sub(substitute(kind), text)
        return text

    def restore(self, text: str) -> str:
        # A redacted URL can itself hold a redacted handle, so repeat until stable.
        for _ in range(3):
            restored = _PLACEHOLDER_RE.sub(
                lambda match: self._originals.get(
                    match.group(0).upper(), match.group(0)
                ),
                text,
            )
            if restored == text:
                break
            text = restored
        return text

    @property
    def counts(self) -> dict[str, int]:
        """Distinct values kept out of model calls, by category (never the values)."""
        return dict(self._counts)

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        safe = [
            {**message, "content": self.redact(str(message.get("content", "")))}
            for message in messages
        ]
        response = self._provider.chat(
            model=model, messages=safe, options=options, **kwargs
        )
        if isinstance(response, dict):
            message = response.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                response = {
                    **response,
                    "message": {
                        **message,
                        "content": self.restore(message["content"]),
                    },
                }
        return response


def unrestored_placeholders(text: str) -> list[str]:
    return sorted(set(_PLACEHOLDER_RE.findall(text)))
