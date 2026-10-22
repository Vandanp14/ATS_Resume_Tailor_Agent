/* Pure display logic for the dashboard. Classic script: browser global
   `ViewModel`, and `module.exports` under Node (used by tests/js). */
(function () {
  const STEP_GROUPS = [
    {
      label: "Read the posting",
      stages: [
        "Preflight",
        "Parse job description",
        "Research company tech stack",
        "Research company hiring signals",
        "Map requirement coverage",
      ],
    },
    { label: "Match your experience", stages: ["Select work", "Select projects", "Plan evidence"] },
    {
      label: "Write your resume",
      stages: ["Tailor skills", "Rewrite work", "Rewrite projects", "Assemble draft"],
    },
    {
      label: "Review",
      stages: ["Holistic review", "Validate review edits", "Write summary", "Apply bullet review"],
    },
    {
      label: "Fit and save",
      stages: [
        "Render and fit one page",
        "Emergency bullet concision",
        "Audit emergency concision",
        "Write artifacts",
      ],
    },
  ];

  function progressSteps(stageStatusFor) {
    return STEP_GROUPS.map((group) => {
      const statuses = group.stages.map((name) => stageStatusFor(name));
      let status = "pending";
      if (statuses.every((s) => s === "done" || s === "skipped")) status = "done";
      else if (statuses.includes("active")) status = "active";
      return { label: group.label, status };
    });
  }

  function friendlyNote(message) {
    const text = String(message || "");
    if (/unavailable[\s\S]*falling back/i.test(text)) return "Gemini is busy, so it's using a backup model.";
    if (/every model is busy/i.test(text)) return "Gemini is busy; waiting to retry.";
    return null;
  }

  function namedTerms(row) {
    const reason = String(row.reason || "");
    const marker = "not in your resume:";
    const at = reason.toLowerCase().indexOf(marker);
    if (at >= 0) {
      const terms = reason.slice(at + marker.length).replace(/\s*\([^)]*\)\s*$/, "").trim();
      if (terms) return terms;
    }
    return row.text || "";
  }

  function summary(review) {
    const r = review || {};
    const hasKeyword = typeof r.keyword_match_pct === "number";
    const pct = hasKeyword ? r.keyword_match_pct : typeof r.coverage_pct === "number" ? r.coverage_pct : null;
    const notes = [];
    for (const row of r.qualification_coverage || []) {
      if (row.status === "unsupported") {
        notes.push({
          tone: "amber",
          text: `Not on your resume: ${namedTerms(row)}. Tick it in the skill check if you've done this work.`,
        });
      } else if (row.status === "supported_not_on_page") {
        notes.push({ tone: "amber", text: `True, but not shown on the page: ${row.text}` });
      } else if (row.status === "covered_with_substitution") {
        notes.push({ tone: "grey", text: `Met through your completed credits: ${row.text}` });
      }
    }
    for (const violation of r.truth_violations || []) {
      notes.push({ tone: "red", text: `Check this claim: ${violation.claim}` });
    }
    return { pct, estimated: !hasKeyword && pct !== null, allIncluded: r.all_stated_included === true, notes };
  }

  const HISTORY_TAGS = {
    completed: { text: "Ready", tone: "green" },
    running: { text: "Running", tone: "ink" },
    failed: { text: "Failed", tone: "red" },
    queued: { text: "Queued", tone: "grey" },
    action_required: { text: "Needs you", tone: "amber" },
  };

  function historyTag(state) {
    const tag = HISTORY_TAGS[state] || { text: String(state || ""), tone: "grey" };
    return { text: tag.text, tone: tag.tone };
  }

  const ViewModel = { STEP_GROUPS, progressSteps, friendlyNote, summary, historyTag };
  globalThis.ViewModel = ViewModel;
  if (typeof module !== "undefined" && module.exports) module.exports = ViewModel;
})();
