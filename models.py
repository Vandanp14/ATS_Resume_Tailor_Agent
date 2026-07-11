from typing import (
    List,
    Optional,
    Dict,
    Tuple,
    Any,
    Protocol,
    runtime_checkable,
    Type,
    Union,
)
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class ModelProvider(Enum):
    """Enum for supported model providers."""

    OLLAMA = "ollama"
    GEMINI = "gemini"


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers."""

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        options: Dict[str, Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Send a chat request to the LLM provider."""
        ...


# ---------------------------------------------------------------------------
# JSON Resume data models (copied verbatim from hiring-agent)
# ---------------------------------------------------------------------------


class Location(BaseModel):
    """Location information for JSON Resume format."""

    address: Optional[str] = None
    postalCode: Optional[str] = None
    city: Optional[str] = None
    countryCode: Optional[str] = None
    region: Optional[str] = None


class Profile(BaseModel):
    """Social profile information for JSON Resume format."""

    network: Optional[str] = None
    username: Optional[str] = None
    url: str


class Basics(BaseModel):
    """Basic information for JSON Resume format."""

    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    url: Optional[str] = None
    summary: Optional[str] = None
    location: Optional[Location] = None
    profiles: Optional[List[Profile]] = None


class Work(BaseModel):
    """Work experience for JSON Resume format."""

    name: Optional[str] = None
    position: Optional[str] = None
    url: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    summary: Optional[str] = None
    highlights: Optional[List[str]] = None


class Volunteer(BaseModel):
    """Volunteer experience for JSON Resume format."""

    organization: Optional[str] = None
    position: Optional[str] = None
    url: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    summary: Optional[str] = None
    highlights: Optional[List[str]] = None


class Education(BaseModel):
    """Education information for JSON Resume format."""

    institution: Optional[str] = None
    url: Optional[str] = None
    area: Optional[str] = None
    studyType: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    score: Optional[str] = None
    courses: Optional[List[str]] = None


class Award(BaseModel):
    """Award information for JSON Resume format."""

    title: Optional[str] = None
    date: Optional[str] = None
    awarder: Optional[str] = None
    summary: Optional[str] = None


class Certificate(BaseModel):
    """Certificate information for JSON Resume format."""

    name: Optional[str] = None
    date: Optional[str] = None
    issuer: Optional[str] = None
    url: Optional[str] = None


class Publication(BaseModel):
    """Publication information for JSON Resume format."""

    name: Optional[str] = None
    publisher: Optional[str] = None
    releaseDate: Optional[str] = None
    url: Optional[str] = None
    summary: Optional[str] = None


class Skill(BaseModel):
    """Skill information for JSON Resume format."""

    name: Optional[str] = None
    level: Optional[str] = None
    keywords: Optional[List[str]] = None


class Language(BaseModel):
    """Language information for JSON Resume format."""

    language: Optional[str] = None
    fluency: Optional[str] = None


class Interest(BaseModel):
    """Interest information for JSON Resume format."""

    name: Optional[str] = None
    keywords: Optional[List[str]] = None


class Reference(BaseModel):
    """Reference information for JSON Resume format."""

    name: Optional[str] = None
    reference: Optional[str] = None


class Project(BaseModel):
    """Project information for JSON Resume format."""

    name: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    description: Optional[str] = None
    highlights: Optional[List[str]] = None
    url: Optional[str] = None
    technologies: Optional[List[str]] = None
    skills: Optional[List[str]] = None


class JSONResume(BaseModel):
    """Complete JSON Resume format model."""

    basics: Optional[Basics] = None
    work: Optional[List[Work]] = None
    volunteer: Optional[List[Volunteer]] = None
    education: Optional[List[Education]] = None
    awards: Optional[List[Award]] = None
    certificates: Optional[List[Certificate]] = None
    publications: Optional[List[Publication]] = None
    skills: Optional[List[Skill]] = None
    languages: Optional[List[Language]] = None
    interests: Optional[List[Interest]] = None
    references: Optional[List[Reference]] = None
    projects: Optional[List[Project]] = None


# ---------------------------------------------------------------------------
# Tailoring pipeline models (new — not present in hiring-agent)
#
# These carry JD-driven `relevance` scores emitted at generation time so the
# renderer's one-page fit loop can trim the least-relevant items. The
# `strip_relevance_*` helpers below convert them back to the plain JSON Resume
# models above for rendering and JSON output.
# ---------------------------------------------------------------------------


class KeywordWeight(BaseModel):
    """A JD keyword paired with an importance weight (1 = minor, 5 = critical)."""

    term: str
    weight: int = Field(
        ge=1, le=5, description="Importance weight, 1 (minor) to 5 (critical)"
    )


class JDProfile(BaseModel):
    """Structured profile extracted from a job description (pipeline stage [1])."""

    role: str
    seniority: Optional[str] = None
    domain: Optional[str] = None
    must_have_skills: List[str]
    nice_to_have_skills: List[str]
    keywords: List[KeywordWeight]


class TailoredSummary(BaseModel):
    """Output of the summary tailor stage."""

    summary: str


class ScoredSkill(Skill):
    """A JSON Resume skill group carrying a JD-driven relevance score (0-100)."""

    relevance: int = Field(
        ge=0, le=100, description="JD relevance, 0 (irrelevant) to 100 (critical)"
    )


class ScoredBullet(BaseModel):
    """A single work highlight bullet carrying a JD-driven relevance score."""

    text: str
    relevance: int = Field(ge=0, le=100, description="JD relevance, 0 to 100")


class ScoredWork(Work):
    """A JSON Resume work entry with a relevance score and per-bullet scores.

    Overrides ``Work.highlights`` (``List[str]``) with per-bullet
    ``ScoredBullet`` objects so the one-page fit loop can trim the
    least-relevant bullets within a position independently.
    """

    relevance: int = Field(ge=0, le=100, description="JD relevance, 0 to 100")
    highlights: Optional[List[ScoredBullet]] = None


class ScoredProject(Project):
    """A JSON Resume project carrying a JD-driven relevance score (0-100)."""

    relevance: int = Field(ge=0, le=100, description="JD relevance, 0 to 100")


class TailoredSkills(BaseModel):
    """Output of the skills tailor stage."""

    skills: List[ScoredSkill]


class TailoredWork(BaseModel):
    """Output of the work tailor stage."""

    work: List[ScoredWork]


class TailoredProjects(BaseModel):
    """Output of the projects tailor stage."""

    projects: List[ScoredProject]


class TruthViolation(BaseModel):
    """A single content-policy (truth floor) violation flagged by the scorer."""

    section: str
    claim: str
    reason: str


class MatchReport(BaseModel):
    """Output of the match scorer (pipeline stage [4])."""

    coverage_pct: float = Field(
        ge=0, le=100, description="JD keyword/skill coverage, 0-100"
    )
    missing_must_haves: List[str]
    weak_sections: List[str]
    truth_violations: List[TruthViolation]
    notes: Optional[str] = None


def strip_relevance_skill(scored: ScoredSkill) -> Skill:
    """Convert a ScoredSkill back to a plain JSON Resume Skill (drops relevance)."""
    return Skill(name=scored.name, level=scored.level, keywords=scored.keywords)


def strip_relevance_work(scored: ScoredWork) -> Work:
    """Convert a ScoredWork back to a plain JSON Resume Work.

    Per-bullet ScoredBullet highlights collapse back to their plain text in
    order; all relevance scores are discarded.
    """
    highlights = (
        [bullet.text for bullet in scored.highlights]
        if scored.highlights is not None
        else None
    )
    return Work(
        name=scored.name,
        position=scored.position,
        url=scored.url,
        startDate=scored.startDate,
        endDate=scored.endDate,
        summary=scored.summary,
        highlights=highlights,
    )


def strip_relevance_project(scored: ScoredProject) -> Project:
    """Convert a ScoredProject back to a plain JSON Resume Project (drops relevance)."""
    return Project(
        name=scored.name,
        startDate=scored.startDate,
        endDate=scored.endDate,
        description=scored.description,
        highlights=scored.highlights,
        url=scored.url,
        technologies=scored.technologies,
        skills=scored.skills,
    )


def strip_relevance_skills(tailored: TailoredSkills) -> List[Skill]:
    """Strip relevance from every skill group in a TailoredSkills wrapper."""
    return [strip_relevance_skill(skill) for skill in tailored.skills]


def strip_relevance_work_list(tailored: TailoredWork) -> List[Work]:
    """Strip relevance from every work entry in a TailoredWork wrapper."""
    return [strip_relevance_work(work) for work in tailored.work]


def strip_relevance_projects(tailored: TailoredProjects) -> List[Project]:
    """Strip relevance from every project in a TailoredProjects wrapper."""
    return [strip_relevance_project(project) for project in tailored.projects]


# ---------------------------------------------------------------------------
# Provider layer + Gemini schema converter (copied verbatim from hiring-agent,
# post-hardening state — retry helper, dict/class schema dispatch, output cap)
# ---------------------------------------------------------------------------


class OllamaProvider:
    """Ollama LLM provider implementation."""

    def __init__(self):
        import ollama

        self.client = ollama

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        options: Dict[str, Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Send a chat request to Ollama."""

        ollama_options = options.copy() if options else {}

        # remove steam from ollama options
        ollama_options.pop("stream", None)

        # Add num_ctx 32K context window to options
        ollama_options["num_ctx"] = 32768

        # convert to chat params
        chat_params = {
            "model": model,
            "messages": messages,
            "options": ollama_options,
        }

        # add it to top level
        if "stream" in kwargs:
            chat_params["stream"] = kwargs["stream"]

        if "format" in kwargs:
            chat_params["format"] = kwargs["format"]

        return self.client.chat(**chat_params)


_GEMINI_SCHEMA_ALLOWED_KEYS = {
    "type", "format", "description", "nullable", "enum",
    "items", "max_items", "min_items", "properties", "required",
}
_GEMINI_SCHEMA_KEY_RENAMES = {"minItems": "min_items", "maxItems": "max_items"}


def _resolve_schema_refs(node: Any, defs: Dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            ref_name = node["$ref"].split("/")[-1]
            resolved = _resolve_schema_refs(defs[ref_name], defs)
            overrides = {k: v for k, v in node.items() if k != "$ref"}
            merged = dict(resolved)
            merged.update(overrides)
            return merged
        return {k: _resolve_schema_refs(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_schema_refs(v, defs) for v in node]
    return node


def _collapse_optional_unions(node: Any) -> Any:
    if isinstance(node, dict):
        node = {k: _collapse_optional_unions(v) for k, v in node.items()}
        any_of = node.pop("anyOf", None)
        if any_of is not None:
            non_null = [option for option in any_of if option.get("type") != "null"]
            if len(any_of) != 2 or len(non_null) != 1:
                raise ValueError(
                    f"Gemini structured output only supports Optional, not general unions: {any_of}"
                )
            node.update(non_null[0])
            node["nullable"] = True
        return node
    if isinstance(node, list):
        return [_collapse_optional_unions(v) for v in node]
    return node


def _strip_unsupported_schema_keys(node: Any) -> Any:
    if isinstance(node, dict):
        cleaned = {}
        for key, value in node.items():
            renamed_key = _GEMINI_SCHEMA_KEY_RENAMES.get(key, key)
            if renamed_key not in _GEMINI_SCHEMA_ALLOWED_KEYS:
                continue
            if renamed_key == "properties" and isinstance(value, dict):
                # `properties` maps arbitrary field names -> sub-schemas.
                # The field names themselves are not schema keys and must
                # not be run through the allow-list, or every property
                # would be silently dropped (found while implementing
                # this task — every model's schema came out as
                # `{"type": "object", "properties": {}}`).
                cleaned[renamed_key] = {
                    prop_name: _strip_unsupported_schema_keys(prop_schema)
                    for prop_name, prop_schema in value.items()
                }
            elif renamed_key == "type" and isinstance(value, str):
                # protos.Schema.type is a proto enum with members like
                # OBJECT/STRING/ARRAY, but Pydantic's JSON Schema emits
                # lowercase JSON Schema type names ("object"/"string"/...),
                # which fail enum lookup (KeyError) unless upper-cased.
                cleaned[renamed_key] = value.upper()
            else:
                cleaned[renamed_key] = _strip_unsupported_schema_keys(value)
        return cleaned
    if isinstance(node, list):
        return [_strip_unsupported_schema_keys(v) for v in node]
    return node


def _pydantic_to_gemini_schema(
    model_or_schema: Union[Type[BaseModel], Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Convert a Pydantic model (or an already-built `model_json_schema()` dict)
    to a schema dict Gemini's `response_schema` accepts.

    Accepts either form because not every call site has migrated to passing
    the raw Pydantic class yet: `pdf.py` and `evaluator.py` still build the
    schema dict themselves (`return_model.model_json_schema()` /
    `EvaluationData.model_json_schema()`) before calling `provider.chat()`,
    while `call_llm_with_retry` (llm_utils.py) passes the class directly for
    non-Ollama providers. Both must work until those call sites are migrated.

    google-generativeai's own type->schema conversion (content_types._schema_for_class)
    is broken for models with Optional[List[SubModel]] fields (leaves a dangling
    $ref) and never strips Pydantic-only keys (default/title/minLength/etc.) that
    protos.Schema rejects. This does both correctly — verified against every
    resume-section model and EvaluationData.
    """
    raw_schema = (
        model_or_schema.model_json_schema()
        if isinstance(model_or_schema, type)
        else dict(model_or_schema)
    )
    defs = raw_schema.pop("$defs", {})
    resolved = _resolve_schema_refs(raw_schema, defs)
    collapsed = _collapse_optional_unions(resolved)
    return _strip_unsupported_schema_keys(collapsed)


class GeminiProvider:
    """Google Gemini API provider implementation."""

    def __init__(self, api_key: str):
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        self.client = genai

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        options: Dict[str, Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Send a chat request to Google Gemini API."""
        import re
        import time
        import random
        from google.api_core.exceptions import ResourceExhausted

        MAX_RETRIES = 5
        BASE_DELAY = 10.0  # seconds — base for exponential backoff
        MAX_DELAY = 120.0  # cap so we never wait more than 2 minutes

        # Map options to Gemini parameters
        generation_config = {}
        if options:
            if "temperature" in options:
                generation_config["temperature"] = options["temperature"]
            if "top_p" in options:
                generation_config["top_p"] = options["top_p"]

        # Runaway-generation safety net: bound the output size so degenerate
        # token-repetition loops get cut off instead of running until the
        # model's context is exhausted. 8192 tokens is generous for the
        # largest legitimate response (a full evaluation JSON) while still
        # terminating pathological output. Overridable per call via options.
        generation_config["max_output_tokens"] = (options or {}).get(
            "max_output_tokens", 8192
        )

        if "format" in kwargs and kwargs["format"] is not None:
            generation_config["response_mime_type"] = "application/json"
            generation_config["response_schema"] = _pydantic_to_gemini_schema(kwargs["format"])

        # Create a Gemini model
        gemini_model = self.client.GenerativeModel(
            model_name=model, generation_config=generation_config
        )

        # Convert messages to Gemini format
        gemini_messages = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            gemini_messages.append({"role": role, "parts": [msg["content"]]})

        for attempt in range(MAX_RETRIES):
            try:
                # Send the chat request
                response = gemini_model.generate_content(gemini_messages)

                # Convert Gemini response to Ollama-like format for compatibility
                return {"message": {"role": "assistant", "content": response.text}}

            except ResourceExhausted as e:
                if attempt == MAX_RETRIES - 1:
                    # All retries exhausted — re-raise the original exception.
                    # This surfaces unrecoverable quota errors (RPD, TPM, etc.)
                    # instead of silently failing or returning bad data.
                    raise

                # Parse the API-suggested retry delay from the error message
                match = re.search(r"retry[_ ]in\s+([\d.]+)s", str(e), re.IGNORECASE)
                api_hint = float(match.group(1)) if match else None

                # Exponential backoff: BASE_DELAY * 2^attempt, capped at MAX_DELAY
                exp_delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)

                # Prefer the API hint when it is shorter than our computed delay
                delay = api_hint if (api_hint and api_hint < exp_delay) else exp_delay

                # Add ±20% randomized jitter to avoid thundering herd
                sleep_time = round(delay * random.uniform(0.8, 1.2), 2)

                print(
                    f"[GeminiProvider] Rate limit hit "
                    f"(attempt {attempt + 1}/{MAX_RETRIES}). "
                    f"Retrying in {sleep_time}s..."
                )
                time.sleep(sleep_time)
