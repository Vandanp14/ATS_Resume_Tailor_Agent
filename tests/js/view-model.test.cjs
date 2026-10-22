const test = require("node:test");
const assert = require("node:assert/strict");
const VM = require("../../static/view-model.js");

const all = (s) => () => s;

test("progressSteps all pending", () => {
  const steps = VM.progressSteps(all("pending"));
  assert.deepEqual(steps.map((s) => s.label), [
    "Read the posting", "Match your experience", "Write your resume", "Review", "Fit and save",
  ]);
  assert.ok(steps.every((s) => s.status === "pending"));
});

test("progressSteps partial", () => {
  const done = new Set(VM.STEP_GROUPS[0].stages);
  const steps = VM.progressSteps((n) => (done.has(n) ? "done" : n === "Select work" ? "active" : "pending"));
  assert.deepEqual(steps.map((s) => s.status), ["done", "active", "pending", "pending", "pending"]);
});

test("progressSteps counts skipped as done", () => {
  const steps = VM.progressSteps((n) => (VM.STEP_GROUPS[1].stages.includes(n) ? "skipped" : "pending"));
  assert.equal(steps[1].status, "done");
  assert.equal(steps[0].status, "pending");
});

test("friendlyNote", () => {
  assert.equal(
    VM.friendlyNote("Model X unavailable (503); falling back to Y"),
    "Gemini is busy, so it's using a backup model.",
  );
  assert.equal(VM.friendlyNote("Every model is busy, waiting 30s"), "Gemini is busy; waiting to retry.");
  assert.equal(VM.friendlyNote("something else"), null);
});

test("summary with full review", () => {
  const s = VM.summary({
    keyword_match_pct: 55.6,
    coverage_pct: 90,
    all_stated_included: true,
    qualification_coverage: [
      { text: "3 years of web dev", status: "unsupported", reason: "not in your resume: React, Node (tick it in the skill check if you know it)" },
      { text: "Teamwork", status: "unsupported", reason: "" },
      { text: "Ships fast", status: "supported_not_on_page" },
      { text: "Degree", status: "covered_with_substitution" },
      { text: "Fine", status: "covered" },
    ],
    truth_violations: [{ claim: "Led 50 people" }],
  });
  assert.equal(s.pct, 55.6);
  assert.equal(s.estimated, false);
  assert.equal(s.allIncluded, true);
  assert.deepEqual(s.notes, [
    { tone: "amber", text: "Not on your resume: React, Node. Tick it in the skill check if you've done this work." },
    { tone: "amber", text: "Not on your resume: Teamwork. Tick it in the skill check if you've done this work." },
    { tone: "amber", text: "True, but not shown on the page: Ships fast" },
    { tone: "grey", text: "Met through your completed credits: Degree" },
    { tone: "red", text: "Check this claim: Led 50 people" },
  ]);
});

test("summary with old review", () => {
  const s = VM.summary({ coverage_pct: 72 });
  assert.equal(s.pct, 72);
  assert.equal(s.estimated, true);
  assert.equal(s.allIncluded, false);
  assert.deepEqual(s.notes, []);
});

test("historyTag", () => {
  assert.deepEqual(VM.historyTag("completed"), { text: "Ready", tone: "green" });
  assert.deepEqual(VM.historyTag("running"), { text: "Running", tone: "ink" });
  assert.deepEqual(VM.historyTag("failed"), { text: "Failed", tone: "red" });
  assert.deepEqual(VM.historyTag("queued"), { text: "Queued", tone: "grey" });
  assert.deepEqual(VM.historyTag("action_required"), { text: "Needs you", tone: "amber" });
});
