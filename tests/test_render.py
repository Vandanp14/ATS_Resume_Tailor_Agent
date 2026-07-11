"""Tests for the renderer (render.py) and its one-page fit loop.

Coverage:
  * ``latex_escape`` per special character (& % $ # _ { } ~ ^ \\) + None/blank.
  * Null-omission on a nulls-heavy fixture: no placeholder text, no dangling
    ``$|$`` separators, no empty itemize environments.
  * ``.tex`` content assertions on a fully-populated resume.
  * Trim-priority order (a -> b -> c -> d -> e) asserted step-by-step with a
    hand-built oversized fixture, plus the recency tie-break.
  * ``fit_to_one_page`` loop control with an INJECTED fake page counter (no
    tectonic needed) -- stop-at-one-page, exact drops, cap raise, exhaustion raise.
  * A real tectonic compile + page-count test marked ``integration`` (skipped
    when tectonic is not installed).
"""

import shutil

import pytest

import render
from render import (
    RenderError,
    ScoredResume,
    _next_trim,
    build_context,
    count_pages,
    fit_to_one_page,
    latex_escape,
    render_tex,
    scored_to_plain,
)
from models import (
    Basics,
    Education,
    JSONResume,
    Profile,
    Project,
    ScoredBullet,
    ScoredProject,
    ScoredSkill,
    ScoredWork,
    Skill,
    Work,
)


# ---------------------------------------------------------------------------
# LaTeX escaping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("a & b", r"a \& b"),
        ("100%", r"100\%"),
        ("$5", r"\$5"),
        ("C#", r"C\#"),
        ("snake_case", r"snake\_case"),
        ("f(x){y}", r"f(x)\{y\}"),
        ("a~b", r"a\textasciitilde{}b"),
        ("x^2", r"x\textasciicircum{}2"),
        ("a\\b", r"a\textbackslash{}b"),
    ],
)
def test_latex_escape_each_special_char(raw, expected):
    assert latex_escape(raw) == expected


def test_latex_escape_backslash_does_not_double_escape_braces():
    # A single pass: the braces introduced by \textbackslash{} must NOT then be
    # re-escaped into \textbackslash\{\}.
    assert latex_escape("\\") == r"\textbackslash{}"
    assert latex_escape("~") == r"\textasciitilde{}"
    assert latex_escape("^") == r"\textasciicircum{}"


def test_latex_escape_all_specials_together():
    raw = r"& % $ # _ { } ~ ^ \ "
    out = latex_escape(raw)
    # No unescaped special survives except inside the replacement macros.
    for macro in (r"\&", r"\%", r"\$", r"\#", r"\_", r"\{", r"\}",
                  r"\textasciitilde{}", r"\textasciicircum{}", r"\textbackslash{}"):
        assert macro in out


def test_latex_escape_none_and_blank():
    assert latex_escape(None) is None
    assert latex_escape("") == ""


def test_latex_escape_normalizes_unicode_punctuation():
    # Curly quotes, en/em dashes, bullets, ellipsis, and NBSP have no glyph in
    # the template's T1 setup; they must be normalized to ASCII, not passed
    # through (which XeTeX would silently drop).
    assert latex_escape("team’s") == "team's"
    assert latex_escape("“vision”") == '"vision"'
    assert latex_escape("a–b") == "a--b"  # en dash
    assert latex_escape("a—b") == "a---b"  # em dash
    assert latex_escape("a•b") == "a-b"  # bullet
    assert latex_escape("done…") == "done..."  # ellipsis
    assert latex_escape("a b") == "a b"  # non-breaking space
    # Normalization runs BEFORE the specials pass, so specials still escape.
    assert latex_escape("5+ yrs — 100% ‘x’") == r"5+ yrs --- 100\% 'x'"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _full_resume():
    return JSONResume(
        basics=Basics(
            name="Ada Lovelace",
            email="ada@example.com",
            phone="+1 555 0100",
            url="https://ada.dev",
            summary="Backend engineer fluent in C_sharp & scaling to 100% uptime.",
            profiles=[
                Profile(network="GitHub", url="github.com/ada"),
                Profile(network="LinkedIn", url="linkedin.com/in/ada"),
            ],
        ),
        education=[
            Education(
                institution="MIT",
                area="Computer Science",
                studyType="B.Sc.",
                startDate="2016",
                endDate="2020",
                score="GPA 3.9",
            )
        ],
        work=[
            Work(
                name="Acme & Co",
                position="Senior Engineer",
                startDate="2021-01",
                endDate="Present",
                highlights=[
                    "Built payments serving 1M+ users (50% faster)",
                    "Cut infra costs by $2M",
                ],
            )
        ],
        projects=[
            Project(
                name="opensrc_cli",
                technologies=["Python", "Click"],
                url="github.com/ada/cli",
                highlights=["1k GitHub stars"],
            )
        ],
        skills=[Skill(name="Languages", keywords=["Python", "C++", "Go"])],
    )


def _document_body(tex: str) -> str:
    """Return the tex after \\begin{document}, stripped of LaTeX comment lines.

    Command *definitions* in the preamble mention tokens like ``resumeItemListStart``,
    so section-body assertions must look only past ``\\begin{document}``.
    """
    doc = tex.split(r"\begin{document}", 1)[1]
    return "\n".join(l for l in doc.splitlines() if not l.lstrip().startswith("%"))


# ---------------------------------------------------------------------------
# .tex content assertions (fully-populated resume)
# ---------------------------------------------------------------------------


def test_render_tex_full_resume_content():
    tex = render_tex(_full_resume())
    body = _document_body(tex)

    # Header + escaped inline content.
    assert r"\scshape Ada Lovelace" in body
    assert "ada@example.com" in body
    assert r"C\_sharp" in body  # underscore escaped in summary
    assert r"100\% uptime" in body  # percent escaped in summary

    # Contact line joins present pieces with a $|$ separator (no trailing one).
    assert "+1 555 0100~$|$~ada@example.com" in body
    assert "github.com/ada" in body

    # Sections present.
    for section in (r"\section{Education}", r"\section{Experience}",
                    r"\section{Projects}", r"\section{Technical Skills}"):
        assert section in body

    # Education degree combines studyType + area; dates form a range.
    assert "{B.Sc., Computer Science}" in body
    assert "2016 -- 2020" in body
    assert "2021-01 -- Present" in body

    # Work bullets, escaped.
    assert r"Built payments serving 1M+ users (50\% faster)" in body
    assert r"Cut infra costs by \$2M" in body

    # Project heading: name (escaped) + tech + link.
    assert r"\textbf{opensrc\_cli}" in body
    assert r"\emph{Python, Click}" in body
    assert "github.com/ada/cli" in body

    # Skills line.
    assert r"\textbf{Languages}{: Python, C++, Go}" in body


def test_context_omits_missing_contact_pieces():
    r = _full_resume()
    r.basics.phone = None
    r.basics.profiles = None
    ctx = build_context(r)
    # Only email + portfolio url remain, joined once, no dangling separator.
    assert ctx["contact_line"] == r"ada@example.com~$|$~https://ada.dev"


# ---------------------------------------------------------------------------
# Null-omission on a nulls-heavy fixture
# ---------------------------------------------------------------------------


def test_null_heavy_resume_omits_everything_cleanly():
    r = JSONResume(
        basics=Basics(name="Nyla Nulls"),  # no phone/email/url/profiles/summary
        work=[Work(position="Engineer")],  # no company, no dates, no highlights
        projects=[Project(name="solo")],  # no tech, no url, no highlights
        skills=[Skill(name="Backend"), Skill(keywords=["Rust"])],
    )
    body = _document_body(render_tex(r))

    assert "None" not in body  # no literal placeholder
    assert "$|$" not in body  # no dangling contact separator (no contacts at all)
    # No empty itemize: work/project without highlights must not open an item list.
    assert r"\resumeItemListStart" not in body
    # Name still renders; sections with content still appear.
    assert "Nyla Nulls" in body
    assert r"\section{Experience}" in body
    # A skill group with only keywords renders the keywords; only-name renders bold.
    assert r"\textbf{Backend}" in body
    assert "Rust" in body


def test_project_heading_no_dangling_separator_when_name_missing():
    # A project with no name but with tech/url must not emit a leading "$|$"
    # (the renderer's no-dangling-separator contract).
    r = JSONResume(
        projects=[Project(name=None, technologies=["Python"], url="https://g.h/x")]
    )
    body = _document_body(render_tex(r))
    # The two present pieces are still separated ...
    assert r"\emph{Python} $|$ https://g.h/x" in body
    # ... but there is no empty \textbf{} and no leading separator.
    assert r"\textbf{}" not in body
    assert "{ $|$" not in body


def test_no_education_section_when_absent():
    r = JSONResume(basics=Basics(name="X"), work=[Work(name="Co", position="Eng")])
    body = _document_body(render_tex(r))
    assert r"\section{Education}" not in body
    assert r"\section{Projects}" not in body
    assert r"\section{Technical Skills}" not in body


# ---------------------------------------------------------------------------
# render() file behaviour
# ---------------------------------------------------------------------------


def test_render_writes_tex_and_skips_pdf(tmp_path):
    result = render.render(_full_resume(), tmp_path, compile_pdf=False)
    assert result.tex == tmp_path / "resume.tex"
    assert result.tex.exists()
    assert result.pdf is None
    assert r"\begin{document}" in result.tex.read_text(encoding="utf-8")


def test_render_compile_without_tectonic_raises_actionable_error(tmp_path, monkeypatch):
    # Force "tectonic missing" regardless of the host so the message is asserted.
    monkeypatch.setattr(render.shutil, "which", lambda name: None)
    with pytest.raises(RenderError) as exc:
        render.render(_full_resume(), tmp_path, compile_pdf=True)
    msg = str(exc.value)
    assert "tectonic" in msg
    assert "brew install tectonic" in msg
    # .tex is still written before compilation is attempted.
    assert (tmp_path / "resume.tex").exists()


# ---------------------------------------------------------------------------
# Trim priority order (step-by-step, no tectonic)
# ---------------------------------------------------------------------------


def _oversized_scored_resume():
    def bl(text, rel):
        return ScoredBullet(text=text, relevance=rel)

    return ScoredResume(
        basics=Basics(name="Trimmy"),
        education=[Education(institution="Never Trimmed U")],
        work=[
            ScoredWork(
                name="A",
                position="Eng",
                startDate="2021",
                endDate="2023",
                relevance=90,  # more recent, higher relevance
                highlights=[bl("a95", 95), bl("a80", 80), bl("a30", 30), bl("a20", 20)],
            ),
            ScoredWork(
                name="B",
                position="Eng",
                startDate="2018",
                endDate="2020",
                relevance=40,  # older, lower relevance
                highlights=[bl("b70", 70), bl("b50", 50), bl("b10", 10)],
            ),
        ],
        projects=[
            ScoredProject(name="P1", relevance=90),
            ScoredProject(name="P2", relevance=55),
            ScoredProject(name="P3", relevance=25),
        ],
        skills=[ScoredSkill(name="Sk1", relevance=80), ScoredSkill(name="Sk2", relevance=20)],
    )


def test_trim_order_exact_sequence():
    sr = _oversized_scored_resume()
    steps = []
    while True:
        action = _next_trim(sr)
        steps.append(action)
        if action is None:
            break

    # Exact, fully-deterministic drop order across all five tiers.
    assert steps == [
        "tier-a: pos#1 bullet 'b10' (rel=10)",  # lowest bullet, from any >2-bullet position
        "tier-a: pos#0 bullet 'a20' (rel=20)",  # B now has 2 bullets; only A eligible
        "tier-a: pos#0 bullet 'a30' (rel=30)",  # A down to 2 bullets -> tier-a exhausted
        "tier-b: project 'P3' (rel=25)",        # projects >2 -> drop lowest
        "tier-c: skill group 'Sk2' (rel=20)",   # projects now 2 -> drop weakest skill group
        # tier-c floors at ONE group: Sk1 (rel=80) is kept, so the Technical
        # Skills section is never zeroed out -> the loop moves on to tier-d.
        "tier-d: pos#1 bullet 'b50' (rel=50)",  # oldest low-rel position (B) -> bullets to 1
        "tier-d: pos#0 bullet 'a80' (rel=80)",  # then A -> bullets to 1
        "tier-e: position 'B' (rel=40)",        # whole lowest-relevance position first
        "tier-e: position 'A' (rel=90)",        # then the last position
        None,                                    # education/header/last skill group never trimmed
    ]


def test_trim_tier_c_keeps_last_skill_group():
    # A resume whose only trimmable content is skill groups keeps the last group:
    # skills are the densest keyword carrier, never zeroed out by tier (c).
    sr = ScoredResume(
        basics=Basics(name="Keep"),
        skills=[
            ScoredSkill(name="Hi", relevance=90),
            ScoredSkill(name="Lo", relevance=10),
        ],
    )
    assert _next_trim(sr) == "tier-c: skill group 'Lo' (rel=10)"
    # One group left -> tier (c) refuses to drain it; nothing else applies.
    assert _next_trim(sr) is None
    assert [s.name for s in sr.skills] == ["Hi"]


def test_trim_never_touches_education_or_header():
    sr = _oversized_scored_resume()
    while _next_trim(sr) is not None:
        pass
    assert sr.education is not None and len(sr.education) == 1
    assert sr.education[0].institution == "Never Trimmed U"
    assert sr.basics is not None and sr.basics.name == "Trimmy"


def test_trim_recency_tiebreak_older_position_first():
    # Two positions, equal relevance, single bullet each -> only tier-e applies.
    # The OLDER position must be dropped first.
    sr = ScoredResume(
        work=[
            ScoredWork(name="Newer", startDate="2022", endDate="2024", relevance=50,
                       highlights=[ScoredBullet(text="x", relevance=10)]),
            ScoredWork(name="Older", startDate="2016", endDate="2018", relevance=50,
                       highlights=[ScoredBullet(text="y", relevance=10)]),
        ]
    )
    first = _next_trim(sr)
    assert "position 'Older'" in first
    assert [w.name for w in sr.work] == ["Newer"]


def test_trim_project_floor_keeps_two():
    sr = ScoredResume(
        projects=[
            ScoredProject(name="P1", relevance=10),
            ScoredProject(name="P2", relevance=20),
        ]
    )
    # Only 2 projects: tier-b must not fire (floor is 2) and nothing else applies.
    assert _next_trim(sr) is None
    assert len(sr.projects) == 2


def test_trim_bullets_floor_keeps_two_per_position_in_tier_a():
    sr = ScoredResume(
        work=[
            ScoredWork(name="A", relevance=50, highlights=[
                ScoredBullet(text="hi", relevance=90),
                ScoredBullet(text="lo", relevance=10),
            ])
        ]
    )
    # A position with exactly 2 bullets is not eligible for tier-a; tier-d would
    # reduce it to 1 only after (b)/(c) are exhausted -- which they are here.
    action = _next_trim(sr)
    assert action.startswith("tier-d")
    assert len(sr.work[0].highlights) == 1
    assert sr.work[0].highlights[0].text == "hi"  # weaker bullet dropped


# ---------------------------------------------------------------------------
# fit_to_one_page with an injected fake page counter (no tectonic)
# ---------------------------------------------------------------------------


def test_fit_returns_immediately_when_already_one_page(tmp_path):
    sr = _oversized_scored_resume()
    calls = {"n": 0}

    def counter(_plain):
        calls["n"] += 1
        return 1  # already fits

    result = fit_to_one_page(sr, tmp_path, page_counter=counter)
    assert isinstance(result, JSONResume)
    assert calls["n"] == 1  # counted once, no trims
    # Nothing was dropped: both positions and all bullets survive.
    assert [w.name for w in result.work] == ["A", "B"]
    assert len(result.work[0].highlights) == 4
    assert len(result.projects) == 3
    assert len(result.skills) == 2


def _total_bullets(plain: JSONResume) -> int:
    return sum(len(w.highlights or []) for w in (plain.work or []))


def test_fit_drops_exactly_until_one_page(tmp_path):
    sr = _oversized_scored_resume()  # starts with 7 work bullets total

    # Overflow while >5 bullets remain; two tier-a drops bring 7 -> 5.
    def counter(plain):
        return 2 if _total_bullets(plain) > 5 else 1

    result = fit_to_one_page(sr, tmp_path, page_counter=counter)
    assert _total_bullets(result) == 5
    # The two weakest bullets (b10, a20) are gone; everything else untouched.
    a_bullets = result.work[0].highlights
    b_bullets = result.work[1].highlights
    assert "a20" not in a_bullets and "a30" in a_bullets
    assert "b10" not in b_bullets and "b50" in b_bullets
    # We stopped inside tier-a, so projects and skills are still intact.
    assert len(result.projects) == 3
    assert len(result.skills) == 2


def test_fit_raises_when_content_exhausted(tmp_path):
    sr = _oversized_scored_resume()

    def counter(_plain):
        return 2  # never fits, but content runs out before the 25-iter cap

    with pytest.raises(RenderError) as exc:
        fit_to_one_page(sr, tmp_path, page_counter=counter)
    assert "every trimmable item has been removed" in str(exc.value)


def test_fit_raises_on_iteration_cap(tmp_path):
    # 30 skill groups + always-overflow counter: hits the 25-iteration hard cap
    # before content is exhausted.
    sr = ScoredResume(
        basics=Basics(name="Cap"),
        skills=[ScoredSkill(name=f"S{i}", relevance=i) for i in range(30)],
    )

    def counter(_plain):
        return 2

    with pytest.raises(RenderError) as exc:
        fit_to_one_page(sr, tmp_path, page_counter=counter, max_iterations=25)
    assert "Exceeded the one-page fit cap of 25" in str(exc.value)


def test_scored_to_plain_strips_relevance(tmp_path):
    sr = _oversized_scored_resume()
    plain = scored_to_plain(sr)
    assert isinstance(plain, JSONResume)
    assert type(plain.work[0]) is Work
    assert type(plain.projects[0]) is Project
    assert type(plain.skills[0]) is Skill
    # Bullets collapse back to plain strings.
    assert plain.work[0].highlights == ["a95", "a80", "a30", "a20"]
    assert not any(hasattr(w, "relevance") for w in plain.work)


# ---------------------------------------------------------------------------
# Integration: real tectonic compile + page count
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("tectonic") is None, reason="tectonic not installed")
def test_real_tectonic_compile_and_page_count(tmp_path):
    result = render.render(_full_resume(), tmp_path, compile_pdf=True)
    assert result.pdf is not None and result.pdf.exists()
    assert count_pages(result.pdf) == 1
