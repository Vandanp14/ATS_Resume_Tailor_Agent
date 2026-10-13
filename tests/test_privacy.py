"""Personal data never reaches a model; code restores it in the final resume."""

import copy
import json
from unittest.mock import MagicMock

import pytest

import resume_tailor.pipeline as pipeline_module
import tailor
from llm_utils import call_llm_with_retry
from models import JSONResume
from resume_tailor.privacy import (
    PrivacyGuard,
    strip_personal_fields,
    strip_prompt_context,
)
from tests.test_holistic_review import Stub
from tests.test_tailor import MASTER_DATA

PRIVATE_VALUES = (
    "Jordan Doe",
    "Jordan",
    "jordan@example.com",
    "jordan.backup@mail.test",
    "(315) 555-0142",
    "555-0142",
    "jordan.dev",
    "github.com/jordan",
    "linkedin.com/in/jdoe-eng",
    "jdoe-eng",
    "12 Lake Street",
    "13126",
    "Remote, NY",
    "acme.example",
)


def private_master() -> JSONResume:
    data = copy.deepcopy(MASTER_DATA)
    data["basics"].update(
        {
            "phone": "(315) 555-0142",
            "location": {
                "address": "12 Lake Street",
                "postalCode": "13126",
                "city": "Oswego",
            },
        }
    )
    data["basics"]["profiles"].append(
        {
            "network": "LinkedIn",
            "username": "jdoe-eng",
            "url": "https://linkedin.com/in/jdoe-eng",
        }
    )
    data["work"][0]["location"] = "Remote, NY"
    # Personal values hidden in free text the models do see.
    data["work"][1]["highlights"][0] = (
        "Built a JavaScript reporting interface; Jordan Doe was on-call owner "
        "(jordan.backup@mail.test)."
    )
    data["projects"][0][
        "description"
    ] = "Automated a grading workflow, demo at https://jordan.dev/grader."
    data["references"] = [{"name": "Pat Mentor", "reference": "Great engineer."}]
    return JSONResume.model_validate(data)


class Recorder:
    """Inner provider: records exactly what would leave the machine."""

    def __init__(self):
        self.sent: list[str] = []
        self.answer = "{}"

    def chat(self, model, messages, options=None, **kwargs):
        self.sent.extend(message["content"] for message in messages)
        return {"message": {"role": "assistant", "content": self.answer}}


def run_private(monkeypatch, tmp_path):
    recorder = Recorder()
    pipeline = tailor.TailorPipeline(
        model="gemini-3.1-flash-lite", call_interval=0, provider=recorder
    )
    stub = Stub()

    def call_once(template, response_model, **context):
        recorder.answer = stub(template, response_model, **context).model_dump_json()
        return call_llm_with_retry(
            pipeline.provider,
            "gemini-3.1-flash-lite",
            pipeline._messages(template, **context),
            response_model,
            max_retries=0,
        )

    monkeypatch.setattr(pipeline, "_call_once", call_once)
    monkeypatch.setattr(pipeline_module, "render", MagicMock())
    result = pipeline.run(
        private_master(), "Hiring Python engineer", tmp_path, no_pdf=True
    )
    return result, recorder, stub


def test_no_personal_value_reaches_any_model_call(monkeypatch, tmp_path):
    result, recorder, stub = run_private(monkeypatch, tmp_path)
    assert result == 0
    templates = {template for template, _, _ in stub.calls}
    assert "holistic_review" in templates
    outbound = "\n".join(recorder.sent).lower()
    assert outbound
    for value in (*PRIVATE_VALUES, "Pat Mentor"):
        assert value.lower() not in outbound, value
    assert "[person_1]" in outbound  # the planted name was replaced, not dropped

    # Code, not the model, puts identity back on the resume.
    tailored = json.loads((tmp_path / "tailored.json").read_text())
    assert tailored["basics"]["name"] == "Jordan Doe"
    assert tailored["basics"]["email"] == "jordan@example.com"
    assert tailored["basics"]["phone"] == "(315) 555-0142"
    assert tailored["work"][0]["location"] == "Remote, NY"
    report = json.loads((tmp_path / "match_report.json").read_text())
    counts = report["privacy"]["values_kept_out_of_model_calls"]
    assert counts["person"] >= 1 and counts["email"] >= 1


def test_prompt_context_drops_identity_fields_but_keeps_jd():
    master_json = private_master().model_dump_json()
    context = strip_prompt_context(
        {
            "master_json": master_json,
            "jd_profile_json": json.dumps({"location": "Austin, TX"}),
            "feedback": "plain text stays",
        }
    )
    stripped = json.loads(context["master_json"])
    assert "basics" not in stripped and "references" not in stripped
    assert all(
        "url" not in item and "location" not in item for item in stripped["work"]
    )
    assert stripped["work"][0]["name"] == "Acme"
    assert json.loads(context["jd_profile_json"]) == {"location": "Austin, TX"}
    assert context["feedback"] == "plain text stays"
    assert strip_personal_fields([{"email": "x", "keep": 1}]) == [{"keep": 1}]


def test_guard_redacts_and_restores_round_trip():
    guard = PrivacyGuard(MagicMock(), private_terms=["Project Falcon"])
    guard.protect(private_master())
    text = (
        "Jordan Doe (jordan@example.com, +1 315-555-0142) built Project Falcon; "
        "see github.com/jordan/automation and https://jordan.dev/grader. "
        "api_key=sk-abc123def456ghi789jkl and SSN 123-45-6789."
    )
    redacted = guard.redact(text)
    for value in (
        "Jordan",
        "jordan@example.com",
        "315-555-0142",
        "Project Falcon",
        "github.com",
        "sk-abc123",
        "123-45-6789",
    ):
        assert value not in redacted, value
    assert guard.restore(redacted) == text


@pytest.mark.parametrize(
    "text",
    [
        "Served 12,500 users across 2021-2023 with 35% lower latency.",
        "Built ASP.NET and Node.js services on AWS us-east-1.",
        "Cut p99 from 1200 ms to 450 ms; 3 releases per week.",
    ],
)
def test_guard_leaves_ordinary_resume_text_alone(text):
    guard = PrivacyGuard(MagicMock(), private_terms=[])
    guard.protect(JSONResume.model_validate({"basics": {"name": "Jordan Doe"}}))
    assert guard.redact(text) == text


def test_guard_restores_placeholders_in_model_answers():
    inner = MagicMock()
    guard = PrivacyGuard(inner, private_terms=[])
    guard.protect(private_master())

    def chat(model, messages, options=None, **kwargs):
        assert "jordan.dev" not in messages[0]["content"]
        return {"message": {"content": messages[0]["content"].upper().lower()}}

    inner.chat.side_effect = lambda **kw: chat(**kw)
    sent = "Demo at https://jordan.dev/grader"
    answer = guard.chat(model="m", messages=[{"role": "user", "content": sent}])
    # Placeholders survive even a case-mangling model and come back exactly.
    assert "https://jordan.dev/grader" in answer["message"]["content"]


def test_guard_catches_handles_and_domains_built_from_the_name():
    guard = PrivacyGuard(MagicMock(), private_terms=[])
    guard.protect(private_master())
    text = "Deployed the portfolio at jordandoe.me and pushed as doejordan42."
    redacted = guard.redact(text)
    assert "jordan" not in redacted.lower()
    assert redacted.endswith(".")  # sentence punctuation is not swallowed
    assert guard.restore(redacted) == text
