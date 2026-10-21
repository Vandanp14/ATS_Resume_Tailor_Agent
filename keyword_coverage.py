"""Deterministic JD requirement matching and keyword coverage.

ATS keyword matching is literal, and a model grading its own coverage is not a
measurement. This module owns the literal side: which JD requirements the
master already states (``direct``), which it lacks (``missing``), which of the
missing ones have validated adjacent evidence (``proxy``), and how many of them
the finished resume actually carries. It contains no provider, prompt, or I/O
code.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache

from models import JDProfile, KeywordWeight, RequirementProxyPlan


TECH_CATEGORIES = frozenset({"language", "framework", "tool", "platform"})
_TYPE_RANK = {"must_have": 0, "weighted_keyword": 1, "nice_to_have": 2}
_TYPE_DEFAULT_WEIGHT = {"must_have": 5, "nice_to_have": 2, "weighted_keyword": 3}

# Equivalent spellings an ATS or recruiter treats as the same requirement. Each
# group is matched as a unit: a requirement naming any member is satisfied by
# text naming any other member. Only true synonyms belong here; related-but-
# different tools (Docker/containers, Git/version control) would hide real gaps.
ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("PostgreSQL", "Postgres", "Postgres SQL"),
    ("Kubernetes", "K8s"),
    ("JavaScript", "JS", "ECMAScript"),
    ("TypeScript", "TS"),
    ("Node.js", "NodeJS", "Node"),
    ("React", "React.js", "ReactJS"),
    ("Vue", "Vue.js", "VueJS"),
    ("Next.js", "NextJS"),
    ("Go", "Golang"),
    ("C#", "C Sharp"),
    ("AWS", "Amazon Web Services"),
    ("GCP", "Google Cloud Platform", "Google Cloud"),
    ("Azure", "Microsoft Azure"),
    ("CI/CD", "CI/CD pipelines", "Continuous Integration", "Continuous Deployment"),
    ("REST", "RESTful", "REST APIs", "RESTful APIs", "REST API"),
    ("Machine Learning", "ML"),
    ("Artificial Intelligence", "AI"),
    ("Large Language Models", "LLM", "LLMs"),
    ("Natural Language Processing", "NLP"),
    ("Object-Oriented Programming", "OOP", "Object-Oriented Design", "OOD"),
    ("Microservices", "Microservice architecture"),
    ("Data Structures and Algorithms", "DSA"),
    ("Infrastructure as Code", "IaC"),
    ("Unit testing", "Unit tests"),
    ("Automated testing", "Test automation"),
    ("SQL", "Structured Query Language"),
    ("MongoDB", "Mongo"),
    ("GraphQL", "Graph QL"),
    ("Scikit-learn", "sklearn"),
    ("Functional programming", "FP"),
)
# Short or common-word names that only count when written with their exact
# capitalization ("Go", not "go to market").
_CASE_SENSITIVE_WORDS = frozenset(
    {
        "go",
        "r",
        "c",
        "d",
        "swift",
        "rust",
        "spark",
        "chef",
        "ant",
        "make",
        "elm",
        "dart",
        "julia",
        "crystal",
        "node",
        "spring",
        "ai",
        "ml",
        "fp",
        "ts",
        "js",
        "ood",
    }
)
_ALIASES_BY_KEY = {
    member.casefold(): group for group in ALIAS_GROUPS for member in group
}
_PAREN_RE = re.compile(r"^(?P<outer>[^()]+?)\s*\((?P<inner>[^()]+)\)\s*$")
_SENIORITY_WORDS = frozenset(
    {
        "intern",
        "internship",
        "junior",
        "jr",
        "senior",
        "sr",
        "staff",
        "principal",
        "lead",
        "i",
        "ii",
        "iii",
        "iv",
        "associate",
        "entry",
        "level",
        "new",
        "grad",
        "graduate",
        "co-op",
        "coop",
        "trainee",
    }
)


def normalize_term(value: str) -> str:
    return " ".join(value.split()).casefold()


@dataclass(frozen=True)
class Requirement:
    id: str
    term: str
    requirement_type: str
    weight: int
    category: str | None = None
    variants: tuple[str, ...] = field(default_factory=tuple)

    @property
    def importance(self) -> int:
        return self.weight * (2 if self.requirement_type == "must_have" else 1)


def _expand_variants(term: str, extra: Iterable[str] = ()) -> tuple[str, ...]:
    seen: dict[str, str] = {}

    def add(value: str) -> None:
        cleaned = " ".join(value.split()).strip(" .,;:")
        if cleaned and normalize_term(cleaned) not in seen:
            seen[normalize_term(cleaned)] = cleaned

    for value in (term, *extra):
        add(value)
        if match := _PAREN_RE.match(value):
            add(match.group("outer"))
            add(match.group("inner"))
    for value in list(seen.values()):
        for member in _ALIASES_BY_KEY.get(value.casefold(), ()):
            add(member)
    return tuple(seen.values())


def build_requirements(jd: JDProfile) -> list[Requirement]:
    """Merge must-haves, nice-to-haves, and weighted keywords into one ranked list."""

    merged: dict[str, dict] = {}

    def add(
        term: str,
        requirement_type: str,
        weight: int | None,
        keyword: KeywordWeight | None = None,
    ) -> None:
        cleaned = " ".join(term.split())
        if not cleaned:
            return
        key = normalize_term(cleaned)
        entry = merged.get(key)
        if entry is None:
            entry = merged[key] = {
                "term": cleaned,
                "requirement_type": requirement_type,
                "weight": weight or _TYPE_DEFAULT_WEIGHT[requirement_type],
                "category": None,
                "aliases": [],
            }
        elif _TYPE_RANK[requirement_type] < _TYPE_RANK[entry["requirement_type"]]:
            entry["requirement_type"] = requirement_type
            entry["term"] = cleaned
        entry["weight"] = max(
            entry["weight"], weight or _TYPE_DEFAULT_WEIGHT[requirement_type]
        )
        if keyword is not None:
            entry["aliases"].extend(keyword.aliases)
            entry["category"] = entry["category"] or keyword.category

    keyword_by_term = {normalize_term(item.term): item for item in jd.keywords}
    for term in jd.must_have_skills:
        keyword = keyword_by_term.get(normalize_term(term))
        add(term, "must_have", 5, keyword)
    for item in jd.keywords:
        add(item.term, "weighted_keyword", item.weight, item)
    for term in jd.nice_to_have_skills:
        keyword = keyword_by_term.get(normalize_term(term))
        add(term, "nice_to_have", keyword.weight if keyword else None, keyword)

    ordered = sorted(
        merged.values(),
        key=lambda entry: (_TYPE_RANK[entry["requirement_type"]], -entry["weight"]),
    )
    return [
        Requirement(
            id=f"R{index}",
            term=entry["term"],
            requirement_type=entry["requirement_type"],
            weight=entry["weight"],
            category=entry["category"],
            variants=_expand_variants(entry["term"], entry["aliases"]),
        )
        for index, entry in enumerate(ordered, start=1)
    ]


@lru_cache(maxsize=2048)
def _variant_pattern(variant: str) -> re.Pattern[str]:
    words = re.split(r"[\s\-_]+", variant.strip())
    body = r"[\s\-_]+".join(re.escape(word) for word in words if word)
    plural = (
        r"(?:e?s)?"
        if variant[-1:].isalpha() and variant.casefold() not in _CASE_SENSITIVE_WORDS
        else ""
    )
    sensitive = variant.casefold() in _CASE_SENSITIVE_WORDS or len(variant) <= 2
    # Short ambiguous names also refuse a hyphen neighbor: "Go-live" is not Go.
    edge = r"A-Za-z0-9+#\-" if sensitive else r"A-Za-z0-9+#"
    return re.compile(
        rf"(?<![{edge}]){body}{plural}(?![{edge}])", 0 if sensitive else re.I
    )


def mentions(text: str | None, variants: Sequence[str]) -> bool:
    if not text:
        return False
    return any(_variant_pattern(variant).search(text) for variant in variants)


def term_mentioned(text: str | None, term: str) -> bool:
    return mentions(text, _expand_variants(term))


def requirement_map(
    jd: JDProfile, fact_index: Mapping[str, dict]
) -> list[dict]:
    """Classify every JD requirement against the complete master fact bank."""

    result: list[dict] = []
    for requirement in build_requirements(jd):
        matched = [
            source_id
            for source_id, fact in fact_index.items()
            if mentions(fact.get("text"), requirement.variants)
        ]
        result.append(
            {
                "id": requirement.id,
                "term": requirement.term,
                "requirement_type": requirement.requirement_type,
                "weight": requirement.weight,
                "importance": requirement.importance,
                "category": requirement.category,
                "variants": list(requirement.variants),
                "status": "direct" if matched else "missing",
                "matched_fact_ids": matched,
            }
        )
    return result


def restore_requirements(
    jd: JDProfile, fact_index: Mapping[str, dict], proxy_plan: RequirementProxyPlan
) -> tuple[list[dict], RequirementProxyPlan]:
    """Rebuild the map from current facts and keep proxies still needed.

    Direct matches are decided in code, so a skill confirmed after the saved
    proxy plan simply becomes ``direct`` and its stale proxy is dropped.
    """
    requirements = requirement_map(jd, fact_index)
    missing = {
        normalize_term(item["term"]) for item in requirements if item["status"] == "missing"
    }
    kept = proxy_plan.model_copy(
        update={
            "proxies": [
                proxy
                for proxy in proxy_plan.proxies
                if normalize_term(proxy.requirement) in missing
            ]
        }
    )
    return attach_proxies(requirements, kept.proxies), kept


def missing_requirements(requirements: Sequence[dict]) -> list[dict]:
    return [item for item in requirements if item["status"] == "missing"]


def attach_proxies(requirements: Sequence[dict], proxies: Iterable[object]) -> list[dict]:
    """Return a copy of the map with validated proxies folded in."""

    by_term = {normalize_term(proxy.requirement): proxy for proxy in proxies}
    result: list[dict] = []
    for item in requirements:
        proxy = by_term.get(normalize_term(item["term"]))
        updated = dict(item)
        if proxy is not None and item["status"] == "missing":
            updated.update(
                {
                    "status": "proxy",
                    "category": item.get("category") or proxy.category,
                    "proxy_terms": list(proxy.proxy_terms),
                    "proxy_fact_ids": list(proxy.source_fact_ids),
                    "proximity": proxy.proximity,
                    "transfer_basis": proxy.transfer_basis,
                    "proxy_relevance": proxy.relevance,
                }
            )
        result.append(updated)
    return result


def priority_proxies(
    requirements: Sequence[dict],
    fact_index: Mapping[str, dict] | None = None,
    limit: int = 3,
) -> list[dict]:
    """Proxied requirements important enough that their evidence must reach the page.

    With a fact index, proxies backed only by bare skill keywords are skipped
    before the limit applies: a keyword cannot carry a bullet, and the skills
    section already lists it.
    """

    candidates = [
        item
        for item in requirements
        if item["status"] == "proxy"
        and (item["requirement_type"] == "must_have" or item["weight"] >= 4)
        and (
            fact_index is None
            or any(
                fact_index.get(fact_id, {}).get("kind") != "skill"
                for fact_id in item.get("proxy_fact_ids", [])
            )
        )
    ]
    candidates.sort(
        key=lambda item: (
            _TYPE_RANK[item["requirement_type"]],
            -item["weight"],
            -item.get("proxy_relevance", 0),
        )
    )
    return candidates[:limit]


def forbidden_claim_terms(requirements: Sequence[dict]) -> tuple[str, ...]:
    """Technologies the candidate never used; bullets must not claim them.

    Only technology-shaped requirements are enforced, so a missing soft skill
    such as "communication" never blocks an otherwise truthful bullet.
    """

    terms: list[str] = []
    for item in requirements:
        if item["status"] not in {"missing", "proxy"}:
            continue
        if item.get("category") not in TECH_CATEGORIES:
            continue
        if len(item["term"]) <= 1:
            continue
        terms.append(item["term"])
    return tuple(terms)


def supported_tech_requirements(
    requirements: Sequence[dict],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """(term, spellings) for JD technologies the master states somewhere."""

    return tuple(
        (item["term"], tuple(item.get("variants") or [item["term"]]))
        for item in requirements
        if item["status"] == "direct" and item.get("category") in TECH_CATEGORIES
    )


def find_terms(text: str | None, terms: Iterable[str]) -> list[str]:
    """Return each term mentioned by its exact spelling (aliases excluded).

    Alias expansion is deliberately off: a forbidden "Node.js" must not reject
    a bullet that legitimately says "node" in another sense.
    """

    return [term for term in terms if mentions(text, (term,))]


def assignment_entry_ids(
    fact_ids: Iterable[str], fact_index: Mapping[str, dict]
) -> set[str]:
    return {
        fact_index[source_id]["entry_id"]
        for source_id in fact_ids
        if source_id in fact_index
    }


def candidate_requirement_cover(
    requirements: Sequence[dict], fact_index: Mapping[str, dict]
) -> dict[str, set[str]]:
    """Map entry IDs (work[0], projects[3], ...) to requirement IDs they evidence."""

    cover: dict[str, set[str]] = {}
    for item in requirements:
        fact_ids = [*item.get("matched_fact_ids", []), *item.get("proxy_fact_ids", [])]
        for entry_id in assignment_entry_ids(fact_ids, fact_index):
            cover.setdefault(entry_id, set()).add(item["id"])
    return cover


def _title_tokens(value: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9+#]+", value.casefold())
    return {token[:6] for token in tokens if token not in _SENIORITY_WORDS}


def title_matches(position: str | None, jd: JDProfile) -> bool:
    """True when a role title names the target job (seniority words ignored)."""

    if not position:
        return False
    position_tokens = _title_tokens(position)
    for alias in (jd.role, *jd.title_aliases):
        alias_tokens = _title_tokens(alias or "")
        if alias_tokens and alias_tokens <= position_tokens:
            return True
    return False


def _bullet_texts(entries: object) -> list[str]:
    texts: list[str] = []
    for entry in entries or []:
        for bullet in entry.get("highlights") or []:
            texts.append(bullet["text"] if isinstance(bullet, Mapping) else bullet)
    return texts


def resume_coverage(resume: Mapping, requirements: Sequence[dict]) -> dict:
    """Measure which requirements the finished resume carries, and where."""

    skills_text = "\n".join(
        keyword
        for group in resume.get("skills") or []
        for keyword in group.get("keywords") or []
    )
    work = resume.get("work") or []
    projects = resume.get("projects") or []
    experience_text = "\n".join(
        [
            *_bullet_texts(work),
            *(entry.get("summary") or "" for entry in work),
            *(entry.get("position") or "" for entry in work),
            *_bullet_texts(projects),
            *(entry.get("description") or "" for entry in projects),
            *(
                technology
                for entry in projects
                for technology in (entry.get("technologies") or [])
            ),
        ]
    )
    page_text = "\n".join([skills_text, experience_text])
    rows: list[dict] = []
    total = covered_weight = supported_total = supported_covered = 0
    for item in requirements:
        variants = item.get("variants") or [item["term"]]
        in_skills = mentions(skills_text, variants)
        in_experience = mentions(experience_text, variants)
        proxy_on_page = bool(item.get("proxy_terms")) and mentions(
            page_text, item["proxy_terms"]
        )
        covered = in_skills or in_experience
        importance = item.get("importance", item["weight"])
        total += importance
        covered_weight += importance if covered else 0
        if item["status"] == "direct":
            supported_total += importance
            supported_covered += importance if covered else 0
        rows.append(
            {
                "id": item["id"],
                "term": item["term"],
                "requirement_type": item["requirement_type"],
                "weight": item["weight"],
                "status": item["status"],
                "in_skills": in_skills,
                "in_experience": in_experience,
                "covered": covered,
                "proxy_terms": item.get("proxy_terms", []),
                "proxy_on_page": proxy_on_page,
            }
        )
    return {
        "computed_coverage_pct": round(100 * covered_weight / total, 1) if total else 100.0,
        "supported_coverage_pct": (
            round(100 * supported_covered / supported_total, 1)
            if supported_total
            else 100.0
        ),
        "missing_supported_terms": [
            row["term"] for row in rows if row["status"] == "direct" and not row["covered"]
        ],
        "proxied_terms_without_proxy_on_page": [
            row["term"]
            for row in rows
            if row["status"] == "proxy" and not row["proxy_on_page"]
        ],
        "requirements": rows,
    }


def placement_findings(
    resume: Mapping, requirements: Sequence[dict], *, coverage: Mapping | None = None
) -> list[str]:
    """Warn-only placement rules for the strongest supported must-haves."""

    findings: list[str] = []
    if coverage is None:
        coverage = resume_coverage(resume, requirements)
    by_id = {row["id"]: row for row in coverage["requirements"]}
    top = [
        item
        for item in requirements
        if item["requirement_type"] == "must_have" and item["status"] == "direct"
    ][:3]
    for item in top:
        row = by_id[item["id"]]
        if not row["in_skills"]:
            findings.append(f"must-have {item['term']!r} is missing from the skills section")
        if not row["in_experience"]:
            findings.append(
                f"must-have {item['term']!r} appears in no work or project bullet"
            )
    work = resume.get("work") or []
    if top and work:
        first_bullets = _bullet_texts(work[:1])[:1]
        if first_bullets and not mentions(first_bullets[0], top[0]["variants"]):
            findings.append(
                f"top must-have {top[0]['term']!r} is not in the first bullet of the "
                "first role"
            )
    return findings


def sanitize_jd_profile(jd: JDProfile, jd_text: str) -> tuple[JDProfile, list[str]]:
    """Drop weighted keywords the posting never states (invented keywords)."""

    kept: list[KeywordWeight] = []
    dropped: list[str] = []
    normalized_text = normalize_term(jd_text)
    for item in jd.keywords:
        grounded = mentions(jd_text, _expand_variants(item.term, item.aliases)) or (
            bool(item.evidence_span)
            and normalize_term(item.evidence_span) in normalized_text
        )
        if grounded:
            kept.append(item)
        else:
            dropped.append(item.term)
    if not dropped:
        return jd, []
    return jd.model_copy(update={"keywords": kept}), dropped


_EXAMPLE_MARKER_RE = re.compile(
    r"\b(?:such as|e\.g\.,?|including(?:,? but not limited to)?|like)\s+", re.I
)
_PAREN_LIST_RE = re.compile(r"\(([^()]+)\)")
_LIST_END_RE = re.compile(r"[;:()]|\.(?:\s|$)")
_LIST_SPLIT_RE = re.compile(r",|\s+or\s+|\s+and\s+", re.I)
_ITEM_PREFIX_RE = re.compile(r"^(?:or|and|a|an|the)\s+", re.I)
_ITEM_SUFFIX_RE = re.compile(r"[\s,]*(?:etc\.?|and more|and others)?[\s.,]*$", re.I)


def _list_items(raw: str) -> list[str]:
    items: list[str] = []
    for part in _LIST_SPLIT_RE.split(raw):
        item = _ITEM_SUFFIX_RE.sub("", _ITEM_PREFIX_RE.sub("", part.strip())).strip()
        if item and len(item.split()) <= 4:
            items.append(item)
    return items


def _example_items(term: str, span: str | None) -> list[str]:
    """Concrete examples a posting lists for a category term, in order."""

    if not span:
        return []
    found: list[str] = []
    marker = _EXAMPLE_MARKER_RE.search(span)
    if marker:
        rest = span[marker.end() :]
        end = _LIST_END_RE.search(rest)
        found = _list_items(rest[: end.start()] if end else rest)
    if not found:
        for match in _PAREN_LIST_RE.finditer(span):
            items = _list_items(match.group(1))
            # "(or equivalent)" is a qualifier, not a list of tools.
            if len(items) >= 2:
                found = items
                break
    umbrella = normalize_term(term)
    unique: dict[str, str] = {}
    for item in found:
        key = normalize_term(item)
        if key != umbrella:
            unique.setdefault(key, item)
    return list(unique.values())


def expand_example_lists(jd: JDProfile) -> tuple[JDProfile, list[str]]:
    """Split category terms into the literal tools the posting names.

    "cloud platforms such as AWS, Azure, or Google Cloud" is searched by
    recruiters and rankers as AWS / Azure / Google Cloud, never as the category.
    Each example becomes its own keyword with the category's weight and list
    membership; the category stays only as a weight-1 keyword.
    """

    existing = {normalize_term(item.term) for item in jd.keywords}
    keywords: list[KeywordWeight] = []
    replacements: dict[str, list[str]] = {}
    added: list[str] = []
    for item in jd.keywords:
        examples = _example_items(item.term, item.evidence_span)
        if not examples:
            keywords.append(item)
            continue
        keywords.append(item.model_copy(update={"weight": 1}))
        replacements[normalize_term(item.term)] = examples
        for example in examples:
            key = normalize_term(example)
            if key in existing:
                continue
            existing.add(key)
            added.append(example)
            keywords.append(
                KeywordWeight(
                    term=example,
                    weight=item.weight,
                    aliases=[],
                    category=item.category,
                    evidence_span=item.evidence_span,
                )
            )
    if not replacements:
        return jd, []

    def expand(terms: list[str]) -> list[str]:
        result: dict[str, str] = {}
        for term in terms:
            for value in replacements.get(normalize_term(term), [term]):
                result.setdefault(normalize_term(value), value)
        return list(result.values())

    return (
        jd.model_copy(
            update={
                "keywords": keywords,
                "must_have_skills": expand(jd.must_have_skills),
                "nice_to_have_skills": expand(jd.nice_to_have_skills),
            }
        ),
        added,
    )


def prompt_requirement_map(requirements: Sequence[dict]) -> list[dict]:
    """Compact map for prompts: drop long fact lists the model does not need."""

    compact: list[dict] = []
    for item in requirements:
        row = {
            "id": item["id"],
            "term": item["term"],
            "requirement_type": item["requirement_type"],
            "weight": item["weight"],
            "status": item["status"],
            "evidence_fact_ids": item.get("matched_fact_ids", [])[:6],
        }
        if item["status"] == "proxy":
            row.update(
                {
                    "proxy_terms": item.get("proxy_terms", []),
                    "proxy_fact_ids": item.get("proxy_fact_ids", []),
                    "transfer_basis": item.get("transfer_basis"),
                }
            )
        compact.append(row)
    return compact
