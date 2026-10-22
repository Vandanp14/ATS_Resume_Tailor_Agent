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
    TRANSFERABLE_SKILL_GROUP,
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
    for macro in (
        r"\&",
        r"\%",
        r"\$",
        r"\#",
        r"\_",
        r"\{",
        r"\}",
        r"\textasciitilde{}",
        r"\textasciicircum{}",
        r"\textbackslash{}",
    ):
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
    # The renderer prints a summary only when one is set; assembly strips the
    # master's own summary, so only a college-mode summary ever reaches it.
    assert r"\section{Summary}" in body and r"C\_sharp" in body

    # Contact line: phone plain, email as a mailto \href, joined with Jake's
    # " $|$ " separator (spaces, no trailing one).
    assert (
        r"+1 555 0100 $|$ \href{mailto:ada@example.com}{\underline{ada@example.com}}"
        in body
    )
    # Profile links show the network label; the raw URL stays in the target.
    assert r"\href{github.com/ada}{\underline{GitHub}}" in body
    assert r"\href{linkedin.com/in/ada}{\underline{LinkedIn}}" in body
    # Personal site (basics.url) shows the "Portfolio" label.
    assert r"\href{https://ada.dev}{\underline{Portfolio}}" in body

    # Sections present.
    for section in (
        r"\section{Education}",
        r"\section{Experience}",
        r"\section{Projects}",
        r"\section{Technical Skills}",
    ):
        assert section in body

    # Education degree combines studyType + area; dates form a range.
    assert "{B.Sc., Computer Science}" in body
    assert "2016 -- 2020" in body
    assert "Jan 2021 -- Present" in body

    # Work bullets, escaped.
    assert r"Built payments serving 1M+ users (50\% faster)" in body
    assert r"Cut infra costs by \$2M" in body

    # Project heading: identity/date and metadata/link render on separate rows.
    assert r"\resumeProjectHeading" in body
    assert "{opensrc\\_cli}{}\n      {Python, Click}" in body
    assert r"\href{github.com/ada/cli}{\underline{GitHub}}" in body
    project_section = body.split(r"\section{Projects}", 1)[1].split(
        r"\section{Technical Skills}", 1
    )[0]
    assert "$|$" not in project_section

    # Skills line.
    assert r"\textbf{Languages}{: Python, C++, Go}" in body


def test_future_education_end_date_is_expected_but_completed_date_is_not():
    future = JSONResume(
        basics=Basics(name="Future Student"),
        education=[Education(institution="State U", endDate="2026-12")],
    )
    completed = JSONResume(
        basics=Basics(name="Graduate"),
        education=[Education(institution="State U", endDate="2020-05")],
    )
    assert "Expected Dec 2026" in _document_body(render_tex(future))
    completed_body = _document_body(render_tex(completed))
    assert "May 2020" in completed_body
    assert "Expected May 2020" not in completed_body


def test_context_omits_missing_contact_pieces():
    r = _full_resume()
    r.basics.phone = None
    r.basics.profiles = None
    ctx = build_context(r)
    # Only email + portfolio url remain, joined once, no dangling separator.
    # Email shows the address (mailto link); basics.url shows the "Portfolio"
    # label with the raw URL as the target, joined with Jake's " $|$ ".
    assert ctx["contact_line"] == (
        r"\href{mailto:ada@example.com}{\underline{ada@example.com}}"
        r" $|$ "
        r"\href{https://ada.dev}{\underline{Portfolio}}"
    )


def test_contact_line_href_raw_target_escaped_display():
    # Pins Jake's clickable-link contract: the \href *target* is the RAW url /
    # mailto (specials like '_' survive so the link works), while the *display*
    # text is a short escaped label -- the profile's network name, falling back
    # to the scheme/www-stripped URL when network is missing/blank.
    r = _full_resume()
    r.basics.phone = None
    r.basics.email = "a_b@x.com"
    r.basics.url = None
    r.basics.profiles = [
        Profile(network="Git_Hub", url="https://www.git.io/ada_x"),
        Profile(network=None, url="https://www.git.io/no_net"),
    ]
    ctx = build_context(r)
    line = ctx["contact_line"]
    # Email: mailto target keeps the raw underscore; display escapes it.
    assert r"\href{mailto:a_b@x.com}{\underline{a\_b@x.com}}" in line
    # Profile with a network: target keeps scheme + www + raw underscore; the
    # display is the network label, latex-escaped.
    assert r"\href{https://www.git.io/ada_x}{\underline{Git\_Hub}}" in line
    # Profile without a network: display falls back to the URL, scheme and
    # www. stripped, then escaped -- target still raw.
    assert r"\href{https://www.git.io/no_net}{\underline{git.io/no\_net}}" in line
    # Three pieces, two separators, no dangling one.
    assert line.count("$|$") == 2


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
    # A metadata-only project uses the compact single-row fallback.
    r = JSONResume(
        projects=[Project(name=None, technologies=["Python"], url="https://g.h/x")]
    )
    body = _document_body(render_tex(r))
    assert r"\resumeProjectSingleHeading" in body
    assert r"\emph{Python}" in body
    assert r"\href{https://g.h/x}{\underline{Live Demo}}" in body
    assert r"\textbf{}" not in body
    assert "$|$" not in body


def test_project_links_use_compact_deterministic_labels_and_raw_targets():
    r = JSONResume(
        projects=[
            Project(name="Repo", url="https://github.com/a/repo"),
            Project(name="Site", url="https://example.com/demo"),
            Project(name="Custom", url="project://artifact/42"),
        ]
    )
    projects = build_context(r)["projects"]
    assert projects[0]["link"] == (
        r"\href{https://github.com/a/repo}{\underline{GitHub}}"
    )
    assert projects[1]["link"] == (
        r"\href{https://example.com/demo}{\underline{Live Demo}}"
    )
    assert projects[2]["link"] == (
        r"\href{project://artifact/42}{\underline{Project Link}}"
    )


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
                relevance=90,
                highlights=[bl("a95", 95), bl("a80", 80), bl("a30", 30), bl("a20", 20)],
            ),
            ScoredWork(
                name="B",
                position="Eng",
                relevance=70,
                highlights=[bl("b70", 70), bl("b50", 50), bl("b10", 10)],
            ),
            ScoredWork(
                name="C",
                position="Eng",
                relevance=60,
                highlights=[bl("c70", 70), bl("c50", 50), bl("c10", 10)],
            ),
        ],
        projects=[
            ScoredProject(name="P1", relevance=90, highlights=["p1a", "p1b", "p1x"]),
            ScoredProject(name="P2", relevance=55, highlights=["p2a", "p2b", "p2x"]),
        ],
        skills=[
            ScoredSkill(name="Sk1", keywords=["One"], relevance=80),
            ScoredSkill(name="Sk2", keywords=["Two"], relevance=20),
            ScoredSkill(name="Sk3", keywords=["Three"], relevance=60),
            ScoredSkill(name="Sk4", keywords=["Four"], relevance=40),
            ScoredSkill(name="Sk5", keywords=["Five"], relevance=10),
        ],
    )


def test_trim_order_exact_sequence():
    sr = _oversized_scored_resume()
    steps = []
    while True:
        action = _next_trim(sr)
        steps.append(action)
        if action is None:
            break

    # Excess project content goes first, then skills only down to three.
    assert steps == [
        "tier-a: excess project bullet 'p2x' from 'P2'",
        "tier-a: excess project bullet 'p1x' from 'P1'",
        "tier-b: skill group 'Sk5' (rel=10)",
        "tier-b: skill group 'Sk2' (rel=20)",
        None,
    ]
    assert [len(item.highlights) for item in sr.work] == [4, 3, 3]
    assert [len(item.highlights) for item in sr.projects] == [2, 2]


def test_trim_keeps_three_skill_groups():
    sr = ScoredResume(
        basics=Basics(name="Keep"),
        skills=[
            ScoredSkill(name="Hi", keywords=["High"], relevance=90),
            ScoredSkill(name="Mid", keywords=["Mid"], relevance=50),
            ScoredSkill(name="Lo", keywords=["Low"], relevance=10),
        ],
    )
    assert _next_trim(sr) is None
    assert [s.name for s in sr.skills] == ["Hi", "Mid", "Lo"]


def test_trim_protects_transferable_skill_group_even_at_low_relevance():
    sr = ScoredResume(
        skills=[
            ScoredSkill(name="A", keywords=["A"], relevance=90),
            ScoredSkill(name="B", keywords=["B"], relevance=80),
            ScoredSkill(name="C", keywords=["C"], relevance=70),
            ScoredSkill(
                name=TRANSFERABLE_SKILL_GROUP,
                keywords=["Figma"],
                relevance=1,
            ),
        ]
    )
    action = _next_trim(sr)
    assert action == "tier-b: skill group 'C' (rel=70)"
    assert TRANSFERABLE_SKILL_GROUP in [skill.name for skill in sr.skills]


def test_trim_never_touches_education_or_header():
    sr = _oversized_scored_resume()
    while _next_trim(sr) is not None:
        pass
    assert sr.education is not None and len(sr.education) == 1
    assert sr.education[0].institution == "Never Trimmed U"
    assert sr.basics is not None and sr.basics.name == "Trimmy"


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


def test_trim_never_touches_required_work_or_project_bullets():
    sr = _oversized_scored_resume()
    while _next_trim(sr) is not None:
        pass
    assert [len(item.highlights) for item in sr.work] == [4, 3, 3]
    assert [len(item.highlights) for item in sr.projects] == [2, 2]


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
    assert [w.name for w in result.work] == ["A", "B", "C"]
    assert [len(w.highlights) for w in result.work] == [4, 3, 3]
    assert len(result.projects) == 2
    assert len(result.skills) == 5


def test_fit_drops_exactly_until_one_page(tmp_path):
    sr = _oversized_scored_resume()

    def counter(plain):
        project_bullets = sum(
            len(item.highlights or []) for item in plain.projects or []
        )
        return 2 if project_bullets > 4 or len(plain.skills or []) > 3 else 1

    result = fit_to_one_page(sr, tmp_path, page_counter=counter)
    assert [len(item.highlights) for item in result.work] == [4, 3, 3]
    assert [len(item.highlights) for item in result.projects] == [2, 2]
    assert len(result.skills) == 3


def test_fit_reports_iterations_and_trim_decisions(tmp_path):
    sr = _oversized_scored_resume()
    messages = []

    def counter(plain):
        project_bullets = sum(
            len(item.highlights or []) for item in plain.projects or []
        )
        return 2 if project_bullets > 4 else 1

    fit_to_one_page(
        sr,
        tmp_path,
        page_counter=counter,
        progress_callback=messages.append,
    )
    assert messages[0] == "One-page fit iteration 1: rendered 2 page(s)"
    assert any(message.startswith("One-page fit trim: tier-a") for message in messages)
    assert messages[-1].endswith("rendered 1 page(s)")


def test_fit_raises_when_content_exhausted(tmp_path):
    sr = _oversized_scored_resume()

    def counter(_plain):
        return 2  # never fits, but content runs out before the 25-iter cap

    with pytest.raises(RenderError) as exc:
        fit_to_one_page(sr, tmp_path, page_counter=counter)
    assert "every trimmable item has been removed" in str(exc.value)


def test_fit_calls_exhaustion_handler_only_after_ordinary_trims(tmp_path):
    sr = _oversized_scored_resume()
    calls = []

    def counter(plain):
        return 1 if plain.work[0].highlights[0] == "short" else 2

    def recover(working, pages, trim_log):
        calls.append((pages, trim_log))
        working.work[0].highlights[0].text = "short"
        return "emergency concision work:0:0"

    result = fit_to_one_page(
        sr, tmp_path, page_counter=counter, exhaustion_handler=recover
    )

    assert result.work[0].highlights[0] == "short"
    assert len(calls) == 1
    assert calls[0][0] == 2
    assert calls[0][1] == (
        "tier-a: excess project bullet 'p2x' from 'P2'",
        "tier-a: excess project bullet 'p1x' from 'P1'",
        "tier-b: skill group 'Sk5' (rel=10)",
        "tier-b: skill group 'Sk2' (rel=20)",
    )


def test_fit_raises_on_iteration_cap(tmp_path):
    sr = ScoredResume(
        basics=Basics(name="Cap"),
        projects=[
            ScoredProject(
                name="Long",
                relevance=50,
                highlights=[f"bullet-{i}" for i in range(30)],
            )
        ],
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


def _role(name: str, start: str, end: str) -> render.Work:
    return render.Work(name=name, position="Engineer", startDate=start, endDate=end)


def test_overlapping_roles_keep_clean_date_ranges():
    ctx = render._work_ctx(
        [
            _role("Acme", "2024-01", "2025-06"),
            _role("Beta", "2024-06", "2024-12"),
            _role("Gamma", "2023-01", "2023-06"),
        ]
    )
    assert ctx[0]["dates"] == "Jan 2024 -- Jun 2025"
    assert ctx[1]["dates"] == "Jun 2024 -- Dec 2024"
    assert ctx[2]["dates"] == "Jan 2023 -- Jun 2023"


def test_sequential_and_touching_roles_are_left_alone():
    ctx = render._work_ctx(
        [
            _role("Acme", "2024-06", "2025-06"),
            _role("Beta", "2023-01", "2024-06"),
        ]
    )
    assert [item["dates"] for item in ctx] == ["Jun 2024 -- Jun 2025", "Jan 2023 -- Jun 2024"]


def test_unparseable_dates_are_never_annotated():
    ctx = render._work_ctx(
        [
            render.Work(name="Acme", position="Engineer"),
            _role("Beta", "2024-01", "Present"),
        ]
    )
    assert ctx[0]["dates"] is None
    assert ctx[1]["dates"] == "Jan 2024 -- Present"


def test_work_location_renders_beside_company():
    work = [
        render.Work(name="Acme", location="New York, NY", position="Engineer"),
        render.Work(name="Beta", position="Engineer"),
    ]
    ctx = render._work_ctx(work)
    assert ctx[0]["location"] == "New York, NY"
    assert ctx[1]["location"] is None
    tex = render_tex(JSONResume(basics=Basics(name="A"), work=work))
    assert "{Acme}{New York, NY}" in tex
