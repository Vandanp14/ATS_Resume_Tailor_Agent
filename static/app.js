/* ATS Resume Tailor web client.
   One EventSource, explicit async states, and text-only rendering for untrusted data. */

"use strict";

const STAGE_NAMES = [
  "Preflight",
  "Parse job description",
  "Research company tech stack",
  "Research company hiring signals",
  "Map requirement coverage",
  "Select work",
  "Select projects",
  "Plan evidence",
  "Tailor skills",
  "Rewrite work",
  "Rewrite projects",
  "Assemble draft",
  "Holistic review",
  "Validate review edits",
  "Write summary",
  "Render and fit one page",
  "Write artifacts",
];
const RESEARCH_STACK_INDEX = 2;
const RESEARCH_SIGNALS_INDEX = 3;
const TAB_NAMES = ["progress", "review", "files"];

const $ = (id) => document.getElementById(id);
const state = {
  meta: null,
  providers: null,
  queue: null,
  tracker: null,
  jobs: new Map(),
  events: new Map(),
  selectedId: null,
  currentDetail: null,
  detailAbort: null,
  seenEvents: new Set(),
  logFilter: "all",
  bulletReview: null,
  logRendered: { jobId: null, filter: "all", count: 0 },
  queueStatus: "loading",
  queueError: "",
  detailStatus: "empty",
  detailError: "",
  activeTab: "progress",
  submitting: false,
  selecting: false,
  selected: new Set(),
  selectLegacy: false,
  inventory: null,
  deleting: null,
  submission: null,
  review: null,
  reviewJobId: null,
  reviewLoadingId: null,
  recoveryCache: new Map(),
  recoveryLoads: new Map(),
  recovery: {
    jobId: null,
    data: null,
    loading: false,
    error: "",
    submitting: false,
    awaitingResult: false,
    requestSignature: "",
    idempotencyKey: "",
  },
};

/* DOM helpers: untrusted provider, JD, and job values never become HTML. */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function parseTime(value) {
  if (!value) return Number.NaN;
  return Date.parse(String(value).replace("Z", "+00:00"));
}

function formatElapsed(started, finished) {
  const start = parseTime(started);
  const end = finished ? parseTime(finished) : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end)) return "—";
  const seconds = Math.max(0, Math.floor((end - start) / 1000));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function formatWhen(value) {
  const time = parseTime(value);
  if (Number.isNaN(time)) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(time);
}

function compactNumber(value) {
  const number = Number(value || 0);
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}m`;
  if (number >= 1000) return `${Math.round(number / 1000)}k`;
  return String(number);
}

function jobLabel(job) {
  return [job.company, job.role].filter(Boolean).join(" · ") || job.job_id;
}

function stateLabel(value) {
  if (value === "action_required") return "Action needed";
  return String(value || "").replaceAll("_", " ");
}

function stageStatus(stageName, job) {
  const index = STAGE_NAMES.indexOf(stageName);
  if (
    (index === RESEARCH_STACK_INDEX || index === RESEARCH_SIGNALS_INDEX) &&
    job.options &&
    !job.options.research_company
  )
    return "skipped";
  if (stageName === "Write summary" && job.options && !job.options.college_mode) return "skipped";
  if (job.current_stage === stageName && job.state === "running") return "active";
  const events = state.events.get(job.job_id) || [];
  for (const event of [...events].reverse()) {
    if (event.stage !== stageName) continue;
    if (event.kind === "stage_completed") return "done";
    if (event.kind === "stage_started") return "active";
  }
  return "pending";
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, { ...options, signal: options.signal || AbortSignal.timeout(15000) });
  if (response.status === 401) {
    location.assign("/login");
    throw new Error("Your session ended. Sign in to continue.");
  }
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : `Request failed (${response.status}).`;
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return body;
}

/* Meta and Gemini quota */

async function fetchMeta() {
  state.meta = await fetchJson("/api/meta");
  if (state.meta.tracker) state.tracker = state.meta.tracker;
  renderMeta();
  renderTracker();
}

function renderMeta() {
  if (!state.meta) return;
  const meta = state.meta;
  $("logout-btn").hidden = !meta.auth_required;
  $("server-status").textContent = meta.ready
    ? `Ready · PDF ${meta.pdf_available === false ? "unavailable" : "available"}`
    : "Starting…";
  if (meta.pdf_available === false) lockSkipPdf();
}

function lockSkipPdf() {
  const field = $("no-pdf");
  field.checked = true;
  field.disabled = true;
  const label = field.closest("label");
  if (label) label.classList.add("disabled");
}

function trackerValues(snapshot) {
  return {
    rpm: Number(snapshot.requests_in_minute ?? 0),
    rpmLimit: Number(snapshot.requests_per_minute_limit ?? 15),
    tpm: Number(snapshot.input_tokens_in_minute ?? 0),
    tpmLimit: Number(snapshot.tokens_per_minute_limit ?? 250000),
    rpd: Number(snapshot.requests_today ?? 0),
    rpdLimit: Number(snapshot.requests_per_day_limit ?? 500),
  };
}

function setProgress(id, value, limit) {
  const progress = $(id);
  progress.max = Math.max(limit, 1);
  progress.value = Math.min(Math.max(value, 0), progress.max);
}

function renderTracker() {
  const snapshot = state.tracker;
  if (!snapshot) return;
  const trigger = $("tracker");
  const dot = $("tracker-dot");
  dot.className = "status-dot";

  if (snapshot.active === false) {
    trigger.classList.add("inactive");
    dot.classList.add("inactive");
    $("tracker-copy").textContent = "Inactive";
    $("tracker-state").textContent = "Inactive";
    $("tracker-note").textContent = "Gemini tracking is inactive for the selected provider.";
    return;
  }

  trigger.classList.remove("inactive");
  const values = trackerValues(snapshot);
  const waitReason = snapshot.wait_reason || "";
  let label = "Ready";
  if (snapshot.state === "paused") label = "Paused";
  else if (snapshot.state === "waiting") label = "Waiting";
  if (snapshot.state === "paused") dot.classList.add("paused");
  if (snapshot.state === "waiting") dot.classList.add("waiting");

  $("tracker-copy").textContent = `${values.rpm}/${values.rpmLimit}`;
  $("tracker-state").textContent = waitReason ? `${label} · ${waitReason.toUpperCase()}` : label;
  $("tracker-state").className = `status-pill ${snapshot.state || "neutral"}`;
  $("rpm-copy").textContent = `${values.rpm} / ${values.rpmLimit}`;
  $("tpm-copy").textContent = `${compactNumber(values.tpm)} / ${compactNumber(values.tpmLimit)}`;
  $("rpd-copy").textContent = `${values.rpd} / ${values.rpdLimit}`;
  setProgress("rpm-progress", values.rpm, values.rpmLimit);
  setProgress("tpm-progress", values.tpm, values.tpmLimit);
  setProgress("rpd-progress", values.rpd, values.rpdLimit);

  let note = "Usage recorded by this web app. Daily quota resets at midnight Pacific.";
  if (snapshot.next_allowed_at) {
    const remaining = Math.max(0, Math.ceil((parseTime(snapshot.next_allowed_at) - Date.now()) / 1000));
    if (remaining > 0) note = `Next request available in ${remaining}s. ${note}`;
  }
  if (snapshot.token_usage_complete === false) {
    note += " Input-token usage excludes responses without provider usage metadata.";
  }
  $("tracker-note").textContent = note;
}

/* Queue and history */

async function fetchQueue() {
  const snapshot = await fetchJson("/api/queue");
  state.queue = snapshot;
  if (snapshot.tracker && (snapshot.tracker.active !== false || !state.tracker)) {
    state.tracker = snapshot.tracker;
  }
  renderTracker();
  renderJobLists();
}

async function fetchJobs() {
  const jobs = await fetchJson("/api/jobs");
  const previous = state.selectedId;
  state.jobs = new Map(jobs.map((job) => [job.job_id, job]));
  if (previous && !state.jobs.has(previous)) state.selectedId = null;
  renderJobLists();
}

const DELETABLE_STATES = ["completed", "failed", "action_required"];

function selectRow(job) {
  const item = el("li", "job-item");
  const label = el("label", "job-select select-row");
  const box = el("input");
  box.type = "checkbox";
  const deletable = DELETABLE_STATES.includes(job.state);
  box.disabled = !deletable;
  box.checked = state.selected.has(job.job_id);
  box.addEventListener("change", () => {
    if (box.checked) state.selected.add(job.job_id);
    else state.selected.delete(job.job_id);
    renderSelection();
  });
  label.appendChild(box);
  const copy = el("span", "job-copy");
  copy.appendChild(el("strong", null, job.company || "Untitled company"));
  copy.appendChild(el("span", null, deletable ? [job.role, formatWhen(job.finished_at || job.created_at)].filter(Boolean).join(" · ") : (job.state === "queued" ? "Queued, can't delete" : "Running, can't delete")));
  label.appendChild(copy);
  const tag = ViewModel.historyTag(job.state);
  label.appendChild(el("span", `status-pill ${tag.tone}`, tag.text));
  if (!deletable) label.classList.add("disabled");
  item.appendChild(label);
  return item;
}

function jobRow(job, position = null) {
  if (state.selecting) return selectRow(job);
  const item = el("li", "job-item");
  item.dataset.jobId = job.job_id;

  const select = el("button", "job-select");
  select.type = "button";
  select.setAttribute("aria-label", `Open ${jobLabel(job)}`);
  select.setAttribute("aria-current", String(job.job_id === state.selectedId));
  const copy = el("span", "job-copy");
  copy.appendChild(el("strong", null, job.company || "Untitled company"));
  const when = job.state === "queued" && position ? `#${position} in queue` : formatWhen(job.finished_at || job.created_at);
  copy.appendChild(el("span", null, [job.role, when].filter(Boolean).join(" · ")));
  select.appendChild(copy);
  const tag = ViewModel.historyTag(job.state);
  select.appendChild(el("span", `status-pill ${tag.tone}`, tag.text));
  select.addEventListener("click", () => go(`#job/${encodeURIComponent(job.job_id)}`));
  item.appendChild(select);

  if (job.state === "queued" && !job.active) {
    const remove = el("button", "remove-job", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${jobLabel(job)} from the queue`);
    remove.addEventListener("click", () => removeJob(job.job_id));
    item.appendChild(remove);
  }
  return item;
}

function renderQueueBanner() {
  if (!state.queue) return;
  const snapshot = state.queue;
  const paused = snapshot.state === "paused";
  const action = $("pause-btn");
  action.textContent = paused ? "Resume queue" : "Pause queue";
  action.hidden = !paused && !snapshot.active_job_id && snapshot.queue_count === 0;
}

const HISTORY_ORDER = { running: 0, queued: 1, action_required: 2 };

function historyJobs() {
  const positions = new Map((state.queue ? state.queue.waiting : []).map((entry) => [entry.job_id, entry.queue_position]));
  const jobs = new Map(state.jobs);
  for (const entry of state.queue ? state.queue.waiting : []) {
    if (!jobs.has(entry.job_id)) jobs.set(entry.job_id, { ...entry, state: "queued", active: false, options: {} });
  }
  const search = $("job-search").value.trim().toLowerCase();
  const statusFilter = $("job-status-filter").value;
  const rows = [...jobs.values()]
    .filter((job) => jobLabel(job).toLowerCase().includes(search))
    .filter((job) => statusFilter === "all" || job.state === statusFilter)
    .sort((a, b) => {
      const rank = (HISTORY_ORDER[a.state] ?? 3) - (HISTORY_ORDER[b.state] ?? 3);
      if (rank) return rank;
      if (a.state === "queued") return (positions.get(a.job_id) || 0) - (positions.get(b.job_id) || 0);
      return String(b.finished_at || b.created_at).localeCompare(String(a.finished_at || a.created_at));
    });
  return { rows, positions, filtered: Boolean(search) || statusFilter !== "all", total: jobs.size };
}

function renderJobLists() {
  const list = $("history-list");
  clear(list);
  const loading = state.queueStatus === "loading";
  const failed = state.queueStatus === "error";
  $("queue-loading").hidden = !loading;
  $("queue-error").hidden = !failed;
  $("queue-error-copy").textContent = state.queueError;
  if (loading || failed || !state.queue) {
    $("history-empty").hidden = true;
    return;
  }

  const { rows, positions, filtered, total } = historyJobs();
  state.visibleDeletable = rows.filter((job) => DELETABLE_STATES.includes(job.state)).map((job) => job.job_id);
  for (const job of rows) list.appendChild(jobRow(job, positions.get(job.job_id)));
  const empty = $("history-empty");
  empty.hidden = rows.length > 0;
  empty.querySelector("strong").textContent = filtered ? "No matching resumes" : "No resumes yet";
  empty.querySelector("span").textContent = filtered ? "Try another search or status." : "Paste a job description on New resume to make one.";

  const activeId = state.queue.active_job_id;
  const active = activeId ? state.jobs.get(activeId) : null;
  $("history-count").textContent = String(total);
  renderTopbarRunning(active);
  renderQueueBanner();
  renderSelection();
}

async function loadJobData() {
  state.queueStatus = "loading";
  state.queueError = "";
  renderJobLists();
  const results = await Promise.allSettled([fetchQueue(), fetchJobs()]);
  const rejected = results.find((result) => result.status === "rejected");
  if (rejected) {
    state.queueStatus = "error";
    state.queueError = String(rejected.reason && rejected.reason.message ? rejected.reason.message : rejected.reason);
  } else {
    state.queueStatus = "success";
  }
  renderJobLists();
}

/* Selected job */

async function fetchDetail(jobId) {
  if (state.detailAbort) state.detailAbort.abort();
  const controller = new AbortController();
  state.detailAbort = controller;
  state.detailStatus = "loading";
  renderDetailState();
  try {
    const detail = await fetchJson(`/api/jobs/${jobId}`, { signal: controller.signal });
    if (controller.signal.aborted || state.selectedId !== jobId) return;
    state.events.set(jobId, detail.events || []);
    state.currentDetail = detail.job;
    state.jobs.set(jobId, detail.job);
    state.detailStatus = "success";
    renderDetail(detail.job);
    renderJobLists();
  } catch (error) {
    if (error.name === "AbortError") return;
    if (error.status === 404 && state.view === "job") {
      state.selectedId = null;
      state.detailStatus = "empty";
      $("history-note").textContent = "That resume no longer exists.";
      go("#history");
      return;
    }
    state.detailStatus = "error";
    state.detailError = String(error.message || error);
    renderDetailState();
  }
}

function renderDetailState() {
  $("detail-empty").hidden = state.detailStatus !== "empty";
  $("detail-loading").hidden = state.detailStatus !== "loading";
  $("detail-error").hidden = state.detailStatus !== "error";
  $("detail-body").hidden = state.detailStatus !== "success";
  $("detail-error-copy").textContent = state.detailError;
}

function selectJob(jobId) {
  if (!jobId) {
    state.selectedId = null;
    state.currentDetail = null;
    state.detailStatus = "empty";
    renderDetailState();
    renderJobLists();
    return;
  }
  const changed = state.selectedId !== jobId;
  state.selectedId = jobId;
  if (changed) state.activeTab = "progress";
  renderJobLists();
  fetchDetail(jobId);
}

function renderDetail(job) {
  state.currentDetail = job;
  state.detailStatus = "success";
  renderDetailState();
  $("detail-company").textContent = job.company || "Untitled company";
  $("detail-body").dataset.state = job.state;
  const resumable = job.state === "failed" && job.source !== "cli";
  $("resume-job").hidden = !resumable;
  $("resume-job").textContent = job.current_stage ? `Resume from ${job.current_stage.toLowerCase()}` : "Resume run";
  $("resume-job").title = "Reuse every finished stage and continue where the run stopped";
  $("duplicate-job").hidden = job.source === "cli" || ["queued", "running"].includes(job.state);
  $("duplicate-job").textContent = job.state === "failed" ? "Start over" : "Tailor again";
  $("detail-role").textContent = job.role || "Role not provided";
  const badge = $("detail-state");
  const tag = ViewModel.historyTag(job.state);
  badge.className = `status-pill ${tag.tone}`;
  badge.textContent = tag.text;

  const stage = job.current_stage || (job.state === "queued" ? "Waiting to start" : job.state === "completed" ? "Tailoring complete" : job.state === "failed" ? "Run stopped" : job.state === "action_required" ? (job.action_kind === "bullet_review" ? "Action needed: review bullets" : "Action needed: one-page fit") : "Preparing");
  $("detail-stage-text").textContent = stage;
  $("detail-body").dataset.live = String(job.state === "running");
  $("detail-elapsed").textContent = job.started_at ? formatElapsed(job.started_at, job.finished_at) : "—";
  $("detail-provider").textContent = providerSummary(job.options);
  $("detail-position").textContent = job.queue_position ? `#${job.queue_position}` : job.active ? "Active" : "—";
  $("detail-output").textContent = job.artifacts && job.artifacts.length ? `${job.artifacts.length} ${job.artifacts.length === 1 ? "file" : "files"}` : ["failed", "cancelled"].includes(job.state) ? "None" : "Pending";
  $("detail-message").hidden = !job.message || job.state === "action_required";
  clear($("detail-message"));
  if (job.message) $("detail-message").appendChild(el("span", "run-alert-text", job.message));
  $("detail-message").title = job.message ? "Full message in the Activity log" : "";
  $("detail-export-warning").hidden = !job.export_warning;
  $("detail-export-warning").textContent = job.export_warning || "";
  renderRecoveryCard(job);
  renderJobView(job);
  renderStages(job);
  renderLog(job);
  renderPreview(job);
  renderFiles(job);
  if (state.reviewJobId !== job.job_id) {
    state.review = null;
    state.reviewJobId = job.job_id;
    clear($("review-content"));
  }
  activateTab(state.activeTab, false);
  if (job.state === "completed" && !state.review && state.reviewLoadingId !== job.job_id) loadReview();
  else if (state.review) renderSummary(state.review);
}

function recoveryPageLabel(value) {
  const count = Number(value);
  if (!Number.isFinite(count) || count < 1) return "—";
  return `${count} ${count === 1 ? "page" : "pages"}`;
}

function recoveryAttemptLabel(value) {
  const count = Number(value);
  if (!Number.isFinite(count) || count < 0) return "—";
  return `${count} ${count === 1 ? "attempt" : "attempts"}`;
}

function recoveryPayload(body) {
  return body && body.recovery ? body.recovery : body;
}

function renderRecoveryCard(job) {
  const card = $("fit-recovery-card");
  const reviewing = job.state === "action_required" && job.action_kind === "bullet_review";
  $("bullet-review-card").hidden = !reviewing;
  if (reviewing) $("bullet-review-card-summary").textContent = job.message || "Choose what to use for each flagged bullet.";
  const visible = job.state === "action_required" && !reviewing;
  card.hidden = !visible;
  if (!visible) return;

  const data = state.recoveryCache.get(job.job_id);
  if (data) {
    $("fit-recovery-card-summary").textContent = `This version spans ${recoveryPageLabel(data.page_count)} after ${recoveryAttemptLabel(data.concision_attempts)} of shortening.`;
  } else {
    $("fit-recovery-card-summary").textContent = "The resume still spans two pages after automatic shortening.";
    ensureRecoverySummary(job.job_id).catch(() => {});
  }
}

async function ensureRecoverySummary(jobId, { force = false } = {}) {
  if (!force && state.recoveryCache.has(jobId)) return state.recoveryCache.get(jobId);
  if (!force && state.recoveryLoads.has(jobId)) return state.recoveryLoads.get(jobId);

  const request = fetchJson(`/api/jobs/${jobId}/fit-recovery`)
    .then((body) => {
      const data = recoveryPayload(body);
      state.recoveryCache.set(jobId, data);
      if (state.currentDetail && state.currentDetail.job_id === jobId) renderRecoveryCard(state.currentDetail);
      return data;
    })
    .finally(() => state.recoveryLoads.delete(jobId));
  state.recoveryLoads.set(jobId, request);
  return request;
}

function recoveryBucket(kind) {
  if (kind === "work_bullet" || String(kind).startsWith("work")) return "Work";
  if (kind === "project_bullet" || String(kind).startsWith("project")) return "Projects";
  return "Skills";
}

function recommendationLabel(value) {
  if (value === "recommended") return "Suggested removal";
  if (value === "keep_if_possible") return "Keep if possible";
  return "Consider removing";
}

function candidateRow(candidate, index) {
  const row = el("label", "recovery-candidate");
  const input = document.createElement("input");
  input.type = "checkbox";
  input.name = "candidate_ids";
  input.value = String(candidate.candidate_id || "");
  input.id = `recovery-candidate-${index}`;
  input.dataset.recommended = String(candidate.recommendation === "recommended");
  row.appendChild(input);

  const body = el("span", "recovery-candidate-body");
  const heading = el("span", "recovery-candidate-heading");
  heading.appendChild(el("strong", null, candidate.label || "Resume content"));
  const badge = el("span", `recommendation-badge ${candidate.recommendation || "consider"}`, recommendationLabel(candidate.recommendation));
  heading.appendChild(badge);
  body.appendChild(heading);
  body.appendChild(el("span", "recovery-candidate-text", candidate.text || candidate.label || "Untitled content"));

  const relevance = Number(candidate.relevance);
  const estimatedLines = Number(candidate.estimated_lines);
  const meta = el("span", "recovery-candidate-meta");
  meta.appendChild(el("span", "tabnum", Number.isFinite(relevance) ? `Relevance ${relevance}` : "Relevance unavailable"));
  meta.appendChild(el("span", "tabnum", Number.isFinite(estimatedLines) ? `Est. ${estimatedLines} ${estimatedLines === 1 ? "line" : "lines"} saved` : "Space estimate unavailable"));
  body.appendChild(meta);
  if (candidate.reason) body.appendChild(el("span", "recovery-candidate-reason", candidate.reason));
  row.appendChild(body);
  return row;
}

function renderRecoveryOptions(data) {
  const host = $("recovery-options");
  clear(host);
  const candidates = Array.isArray(data.candidates) ? data.candidates : [];
  let rowIndex = 0;

  for (const bucket of ["Work", "Projects", "Skills"]) {
    const bucketCandidates = candidates.filter((candidate) => recoveryBucket(candidate.kind) === bucket);
    if (!bucketCandidates.length) continue;

    const fieldset = el("fieldset", "recovery-fieldset");
    fieldset.appendChild(el("legend", null, bucket));
    let previousGroup = null;
    for (const candidate of bucketCandidates) {
      const group = candidate.group || "";
      if (group && group !== previousGroup) {
        fieldset.appendChild(el("h3", "recovery-group-label", group));
        previousGroup = group;
      }
      fieldset.appendChild(candidateRow(candidate, rowIndex));
      rowIndex += 1;
    }
    host.appendChild(fieldset);
  }

  if (!candidates.length) {
    const empty = el("div", "recovery-empty");
    empty.appendChild(el("strong", null, "No removable content is available"));
    empty.appendChild(el("span", null, "This resume cannot be shortened further without changing protected content."));
    host.appendChild(empty);
  }
}

function setRecoveryControlsDisabled(disabled) {
  $("select-recommendations-btn").disabled = disabled;
  $("clear-recovery-selection-btn").disabled = disabled;
  $("apply-removals-btn").disabled = disabled;
  for (const input of document.querySelectorAll('#recovery-options input[type="checkbox"]')) input.disabled = disabled;
}

function renderRecoveryDialogData(data, { resetSelection = true } = {}) {
  state.recovery.data = data;
  $("recovery-page-count").textContent = recoveryPageLabel(data.page_count);
  $("recovery-concision-count").textContent = recoveryAttemptLabel(data.concision_attempts);
  renderRecoveryOptions(data);
  if (resetSelection) clearRecoverySelection();
  $("recovery-loading").hidden = true;
  $("recovery-load-error").hidden = true;
  $("recovery-content").hidden = false;
  setRecoveryControlsDisabled(state.recovery.awaitingResult);
}

function renderRecoveryLoading() {
  $("recovery-loading").hidden = false;
  $("recovery-load-error").hidden = true;
  $("recovery-content").hidden = true;
  $("recovery-page-count").textContent = "—";
  $("recovery-concision-count").textContent = "—";
  $("apply-removals-btn").disabled = true;
}

function renderRecoveryLoadError(error) {
  $("recovery-loading").hidden = true;
  $("recovery-content").hidden = true;
  $("recovery-load-error").hidden = false;
  $("recovery-load-error-copy").textContent = `Check your connection and try again. ${String(error.message || error)}`;
  $("apply-removals-btn").disabled = true;
}

async function loadRecoveryDialog({ resetSelection = true } = {}) {
  const jobId = state.recovery.jobId;
  if (!jobId) return;
  state.recovery.loading = true;
  state.recovery.error = "";
  renderRecoveryLoading();
  try {
    const data = await ensureRecoverySummary(jobId, { force: true });
    if (state.recovery.jobId !== jobId) return;
    state.recovery.loading = false;
    renderRecoveryDialogData(data, { resetSelection });
  } catch (error) {
    if (state.recovery.jobId !== jobId) return;
    state.recovery.loading = false;
    state.recovery.error = String(error.message || error);
    renderRecoveryLoadError(error);
  }
}

function openRecoveryDialog() {
  const job = state.currentDetail;
  if (!job || job.state !== "action_required") return;
  state.recovery.jobId = job.job_id;
  state.recovery.data = null;
  state.recovery.error = "";
  state.recovery.submitting = false;
  state.recovery.awaitingResult = false;
  state.recovery.requestSignature = "";
  state.recovery.idempotencyKey = "";
  $("recovery-selection-error").textContent = "";
  $("recovery-submit-status").textContent = "";
  $("recovery-submit-status").classList.remove("error");
  const dialog = $("fit-recovery-dialog");
  if (!dialog.open) dialog.showModal();
  loadRecoveryDialog();
}

function closeRecoveryDialog() {
  const dialog = $("fit-recovery-dialog");
  if (dialog.open) dialog.close();
}

function clearRecoveryError() {
  $("recovery-selection-error").textContent = "";
  $("recovery-options").setAttribute("aria-invalid", "false");
}

function clearRecoverySelection() {
  for (const input of document.querySelectorAll('#recovery-options input[type="checkbox"]')) input.checked = false;
  clearRecoveryError();
  state.recovery.requestSignature = "";
  state.recovery.idempotencyKey = "";
}

function selectRecommendedCandidates() {
  const recommendedIds = new Set((state.recovery.data && state.recovery.data.recommended_candidate_ids || []).map(String));
  for (const input of document.querySelectorAll('#recovery-options input[type="checkbox"]')) {
    input.checked = recommendedIds.size ? recommendedIds.has(input.value) : input.dataset.recommended === "true";
  }
  clearRecoveryError();
  state.recovery.requestSignature = "";
  state.recovery.idempotencyKey = "";
}

function selectedRecoveryIds() {
  return [...document.querySelectorAll('#recovery-options input[type="checkbox"]:checked')].map((input) => input.value);
}

async function submitRecovery(event) {
  event.preventDefault();
  if (state.recovery.submitting || state.recovery.awaitingResult || !state.recovery.data) return;
  const candidateIds = selectedRecoveryIds();
  if (!candidateIds.length) {
    $("recovery-selection-error").textContent = "Select at least one item to remove, or cancel to keep this version unchanged.";
    $("recovery-options").setAttribute("aria-invalid", "true");
    $("recovery-options").focus();
    return;
  }

  clearRecoveryError();
  const revision = state.recovery.data.revision;
  const signature = JSON.stringify([revision, [...candidateIds].sort()]);
  if (state.recovery.requestSignature !== signature) {
    state.recovery.requestSignature = signature;
    state.recovery.idempotencyKey = crypto.randomUUID();
  }

  state.recovery.submitting = true;
  const status = $("recovery-submit-status");
  status.classList.remove("error");
  status.textContent = "Removing the selected content and rendering a new PDF…";
  $("apply-removals-btn").textContent = "Removing and rendering…";
  setRecoveryControlsDisabled(true);
  try {
    await fetchJson(`/api/jobs/${state.recovery.jobId}/fit-recovery`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": state.recovery.idempotencyKey,
      },
      body: JSON.stringify({ revision, candidate_ids: candidateIds }),
    });
    state.recovery.awaitingResult = true;
    status.textContent = "Selections saved. Rendering the updated resume…";
    state.recoveryCache.delete(state.recovery.jobId);
    loadJobData().catch(() => {});
    if (state.selectedId === state.recovery.jobId) fetchDetail(state.recovery.jobId);
  } catch (error) {
    status.classList.add("error");
    status.textContent = `The updated resume was not queued. Check your connection and try again. ${String(error.message || error)}`;
    setRecoveryControlsDisabled(false);
  } finally {
    state.recovery.submitting = false;
    $("apply-removals-btn").textContent = "Remove selected and render";
  }
}

/* Bullet review: per-bullet keep / safe / regenerate choices. */

const REVIEW_CHOICES = [
  { value: "safe", title: "Use safe version", note: (item) => (item.safe_kind === "edited" ? "Flagged wording removed." : "Written from your master resume.") },
  { value: "keep", title: "Keep as written", note: () => "Only if this is true for you." },
  { value: "regenerate", title: "Regenerate this bullet", note: () => "One model call, rebuilt only from its source facts." },
];

function reviewItem(item, index) {
  const fieldset = el("fieldset", "review-item");
  const legend = el("legend");
  legend.append(el("span", "review-item-index tabnum", String(index + 1)), document.createTextNode(item.label));
  fieldset.appendChild(legend);
  const issues = el("ul", "review-issues");
  for (const issue of item.issues) issues.appendChild(el("li", null, issue));
  fieldset.appendChild(issues);
  for (const choice of REVIEW_CHOICES) {
    const disabled = choice.value === "keep" && (!item.can_keep || !item.original_text);
    const label = el("label", `review-choice${disabled ? " disabled" : ""}`);
    const input = el("input");
    input.type = "radio";
    input.name = `review-${item.flag_id}`;
    input.value = choice.value;
    input.checked = choice.value === "safe";
    input.disabled = disabled;
    label.appendChild(input);
    const body = el("span", "review-choice-body");
    body.appendChild(el("strong", null, choice.title));
    body.appendChild(el("small", null, disabled ? (item.original_text ? "Not available: this draft has a structural problem." : "Not available: the model wrote no bullet.") : choice.note(item)));
    const quote = choice.value === "safe" ? item.safe_text : choice.value === "keep" ? item.original_text : "";
    if (quote) body.appendChild(el("q", "review-quote", quote));
    label.appendChild(body);
    fieldset.appendChild(label);
  }
  if (item.source_facts && item.source_facts.length) {
    const facts = el("details", "review-facts");
    facts.appendChild(el("summary", null, "Source facts"));
    const list = el("ul");
    for (const fact of item.source_facts) list.appendChild(el("li", null, fact));
    facts.appendChild(list);
    fieldset.appendChild(facts);
  }
  return fieldset;
}

async function openBulletReview() {
  const job = state.currentDetail;
  if (!job) return;
  const dialog = $("bullet-review-dialog");
  state.bulletReview = { jobId: job.job_id, data: null, key: crypto.randomUUID(), submitting: false };
  clear($("bullet-review-items"));
  $("bullet-review-status").textContent = "";
  $("bullet-review-status").classList.remove("error");
  $("bullet-review-error").hidden = true;
  $("bullet-review-loading").hidden = false;
  $("apply-bullet-review").disabled = true;
  if (!dialog.open) dialog.showModal();
  try {
    const data = await fetchJson(`/api/jobs/${job.job_id}/bullet-review`);
    if (state.bulletReview.jobId !== job.job_id) return;
    state.bulletReview.data = data;
    data.items.forEach((item, index) => $("bullet-review-items").appendChild(reviewItem(item, index)));
    $("apply-bullet-review").disabled = false;
  } catch (error) {
    $("bullet-review-error-copy").textContent = String(error.message || error);
    $("bullet-review-error").hidden = false;
  } finally {
    $("bullet-review-loading").hidden = true;
  }
}

async function submitBulletReview(event) {
  event.preventDefault();
  const review = state.bulletReview;
  if (!review || !review.data || review.submitting) return;
  const decisions = {};
  for (const item of review.data.items) {
    const checked = document.querySelector(`input[name="review-${CSS.escape(item.flag_id)}"]:checked`);
    decisions[item.flag_id] = checked ? checked.value : "safe";
  }
  review.submitting = true;
  const button = $("apply-bullet-review");
  const status = $("bullet-review-status");
  button.disabled = true;
  button.textContent = "Continuing…";
  status.classList.remove("error");
  status.textContent = Object.values(decisions).includes("regenerate") ? "Regenerating the chosen bullets, then rendering…" : "Applying your choices and rendering…";
  try {
    await fetchJson(`/api/jobs/${review.jobId}/bullet-review`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": review.key },
      body: JSON.stringify({ revision: review.data.revision, decisions }),
    });
    $("bullet-review-dialog").close();
    loadJobData().catch(() => {});
    if (state.selectedId === review.jobId) fetchDetail(review.jobId);
  } catch (error) {
    status.classList.add("error");
    status.textContent = `Your choices were not saved. ${String(error.message || error)}`;
    button.disabled = false;
  } finally {
    review.submitting = false;
    button.textContent = "Continue tailoring";
  }
}

function stageTimeline(job) {
  /* Per-stage start/end times and issue counts, derived from the event stream. */
  const timeline = new Map();
  for (const event of state.events.get(job.job_id) || []) {
    if (!event.stage) continue;
    const entry = timeline.get(event.stage) || { started: null, finished: null, issues: 0 };
    if (event.kind === "stage_started") entry.started = event.created_at;
    if (event.kind === "stage_completed") entry.finished = event.created_at;
    if (event.kind === "stage_retry" || event.kind === "stage_warning") entry.issues += 1;
    timeline.set(event.stage, entry);
  }
  return timeline;
}

function renderStages(job) {
  const list = $("stage-list");
  clear(list);
  const timeline = stageTimeline(job);
  let completed = 0;
  let applicable = 0;
  for (const name of STAGE_NAMES) {
    const status = stageStatus(name, job);
    const failed = job.state === "failed" && status === "active";
    if (status !== "skipped") applicable += 1;
    if (status === "done") completed += 1;
    const item = el("li", `stage-item ${failed ? "failed" : status}`);
    item.appendChild(el("span", "stage-marker", failed ? "!" : "✓"));
    item.appendChild(el("span", "stage-name", name));
    const entry = timeline.get(name);
    if (entry && entry.issues) {
      const issues = el("span", "stage-issues tabnum", String(entry.issues));
      issues.title = `${entry.issues} retr${entry.issues === 1 ? "y or warning" : "ies or warnings"}`;
      item.appendChild(issues);
    }
    let meta = status === "skipped" ? "Not used" : "";
    if (entry && entry.started && (status === "done" || status === "active")) {
      meta = formatElapsed(entry.started, status === "done" ? entry.finished : failed ? job.finished_at : null);
    }
    item.appendChild(el("span", "stage-meta tabnum", meta));
    list.appendChild(item);
  }
  $("progress-summary").textContent = `${completed} of ${applicable}`;
  const done = job.state === "completed" ? applicable : completed;
  $("progress-bar").style.inlineSize = `${applicable ? Math.round((done / applicable) * 100) : 0}%`;
  $("progress-bar").dataset.state = job.state;
}

const LOG_LEVELS = {
  stage_completed: "success",
  stage_detail: "muted",
  stage_retry: "retry",
  stage_warning: "warning",
};

function logEntries(job) {
  /* Stage starts live in the pipeline pane; the log keeps outcomes and detail. */
  const entries = [];
  const started = new Map();
  for (const event of state.events.get(job.job_id) || []) {
    if (event.kind === "stage_started" && event.stage) started.set(event.stage, event.created_at);
    const level = LOG_LEVELS[event.kind];
    if (!level) continue;
    let text = event.message || "";
    if (event.kind === "stage_completed") {
      text = started.has(event.stage) ? `Completed · ${formatElapsed(started.get(event.stage), event.created_at)}` : "Completed";
    }
    if (event.kind === "stage_retry") {
      const attempt = event.attempt && event.max_attempts ? `Attempt ${event.attempt}/${event.max_attempts}` : "Retrying";
      text = text ? `${attempt} · ${text}` : attempt;
    }
    entries.push({ level, time: event.created_at, stage: event.stage || "", text });
  }
  if (job.state === "failed" && job.message) {
    entries.push({ level: "error", time: job.finished_at, stage: job.current_stage || "", text: job.message });
  }
  return entries;
}

function formatClock(value) {
  const time = parseTime(value);
  if (!time) return "";
  return new Date(time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function renderLog(job) {
  const scroller = $("log-scroll");
  const list = $("log-list");
  const atBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 24;
  const entries = logEntries(job);
  const issues = entries.filter((entry) => ["retry", "warning", "error"].includes(entry.level));
  $("log-issue-count").textContent = String(issues.length);
  const visible = state.logFilter === "issues" ? issues : entries;
  const previous = state.logRendered.jobId === job.job_id ? state.logRendered.count : 0;
  const sameView = state.logRendered.jobId === job.job_id && state.logRendered.filter === state.logFilter;
  if (!sameView || visible.length < previous) clear(list);
  const startIndex = sameView && visible.length >= previous ? previous : 0;
  for (const [index, entry] of visible.entries()) {
    if (index < startIndex) continue;
    const row = el("li", `log-line ${entry.level}`);
    if (sameView && previous) row.classList.add("is-new");
    row.appendChild(el("time", "log-time tabnum", formatClock(entry.time)));
    row.appendChild(el("span", "log-level", entry.level === "muted" ? "info" : entry.level));
    const body = el("span", "log-text");
    if (entry.stage) body.appendChild(el("b", null, entry.stage));
    body.appendChild(document.createTextNode(entry.text));
    row.appendChild(body);
    list.appendChild(row);
  }
  state.logRendered = { jobId: job.job_id, filter: state.logFilter, count: visible.length };
  $("log-empty").hidden = visible.length > 0;
  $("log-empty").textContent = state.logFilter === "issues" ? "No retries, warnings, or errors." : "Activity appears here once the run starts.";
  if (atBottom || !sameView) {
    scroller.scrollTop = scroller.scrollHeight;
    $("log-jump").hidden = true;
  } else if (visible.length > previous) {
    $("log-jump").hidden = false;
  }
}

function setLogFilter(filter) {
  state.logFilter = filter;
  for (const button of document.querySelectorAll("[data-log-filter]")) {
    button.setAttribute("aria-pressed", String(button.dataset.logFilter === filter));
  }
  if (state.currentDetail) renderLog(state.currentDetail);
}

async function copyLog() {
  if (!state.currentDetail) return;
  const text = logEntries(state.currentDetail)
    .map((entry) => `${formatClock(entry.time)} ${entry.level.toUpperCase()} ${entry.stage ? `[${entry.stage}] ` : ""}${entry.text}`)
    .join("\n");
  const button = $("log-copy");
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "Copied";
  } catch {
    button.textContent = "Copy failed";
  }
  setTimeout(() => { button.textContent = "Copy"; }, 1600);
}

function renderPreview(job) {
  const frame = $("preview");
  const pending = $("preview-pending");
  const jsonView = $("preview-json");
  const hasPdf = job.artifacts.includes("resume.pdf");
  const hasJson = job.artifacts.includes("tailored.json");
  // While running, the blank page on the right "inks in"; when done it is
  // replaced by the real PDF, or by the structured summary when PDF was skipped.
  frame.hidden = true;
  jsonView.hidden = true;
  pending.hidden = true;
  const finished = job.state === "completed";
  if (finished && hasPdf) {
    const src = `/api/jobs/${job.job_id}/files/resume.pdf?download=0#navpanes=0&view=FitH`;
    if (!frame.src.endsWith(src)) frame.src = src;
    frame.hidden = false;
  } else if (finished && hasJson) {
    renderTailoredJson(job.job_id);
  }
  $("job-paper").hidden = finished && (hasPdf || hasJson);
}

async function renderTailoredJson(jobId) {
  const host = $("preview-json");
  clear(host);
  try {
    const documentData = await fetchJson(`/api/jobs/${jobId}/files/tailored.json?download=0`);
    if (state.selectedId !== jobId) return;
    const basics = documentData.basics || {};
    const rows = [
      ["Name", basics.name],
      ["Email", basics.email],
      ["Phone", basics.phone],
      ["Summary", documentData.summary || documentData.professional_summary],
    ];
    for (const [key, value] of rows) {
      if (!value) continue;
      const row = el("div", "kv");
      row.appendChild(el("b", null, `${key}: `));
      row.appendChild(document.createTextNode(String(value)));
      host.appendChild(row);
    }
    host.hidden = false;
  } catch {
    host.textContent = "The structured preview could not be loaded. Download the JSON from Files instead.";
    host.hidden = false;
  }
}

function renderFiles(job) {
  const artifacts = job.artifacts || [];
  const mappings = [
    ["dl-pdf", "resume.pdf"],
    ["dl-tex", "resume.tex"],
    ["dl-json", "tailored.json"],
    ["dl-match", "match_report.json"],
    ["dl-diagnostic", "diagnostic_report.json"],
  ];
  let count = 0;
  for (const [id, filename] of mappings) {
    const link = $(id);
    const exists = artifacts.includes(filename);
    link.hidden = !exists;
    if (exists) {
      link.href = `/api/jobs/${job.job_id}/files/${filename}`;
      count += 1;
    }
  }
  $("files-empty").hidden = count > 0;
  const location = $("pdf-library-location");
  location.hidden = !job.pdf_library_name;
  if (job.pdf_library_name) {
    location.textContent = `Saved as ${job.pdf_library_name}`;
  }
}

function activateTab(name, focus = true) {
  if (!TAB_NAMES.includes(name)) return;
  state.activeTab = name;
  $("detail-body").dataset.activeTab = name;
  for (const tabName of TAB_NAMES) {
    const tab = $(`tab-${tabName}`);
    const panel = $(`panel-${tabName}`);
    const active = tabName === name;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    panel.hidden = !active;
  }
  if (focus) $(`tab-${name}`).focus();
  if (name === "review" && state.currentDetail && !state.review && state.reviewLoadingId !== state.selectedId) loadReview();
}

function onTabKeydown(event) {
  const current = TAB_NAMES.indexOf(state.activeTab);
  let next = current;
  if (event.key === "ArrowRight") next = (current + 1) % TAB_NAMES.length;
  else if (event.key === "ArrowLeft") next = (current - 1 + TAB_NAMES.length) % TAB_NAMES.length;
  else if (event.key === "Home") next = 0;
  else if (event.key === "End") next = TAB_NAMES.length - 1;
  else return;
  event.preventDefault();
  activateTab(TAB_NAMES[next], true);
}

/* Job screen: plain progress while running, a short summary when done. */

// Stages that only run in some jobs count as skipped until they report activity.
const CONDITIONAL_STAGES = ["Apply bullet review", "Emergency bullet concision", "Audit emergency concision"];

function stageStatusFor(stageName, job) {
  if (job.state === "completed") return "done";
  const status = stageStatus(stageName, job);
  if (status !== "pending") return status;
  if (CONDITIONAL_STAGES.includes(stageName)) return "skipped";
  return status;
}

function currentStepLabel(job) {
  const group = ViewModel.STEP_GROUPS.find((step) => step.stages.includes(job.current_stage));
  return group ? group.label : job.state === "queued" ? "Waiting to start" : "Starting";
}

function latestNote(job) {
  const events = state.events.get(job.job_id) || [];
  for (const event of [...events].reverse()) {
    if (event.kind === "stage_completed") return "";
    const note = event.message ? ViewModel.friendlyNote(event.message) : null;
    if (note) return note;
  }
  return "";
}

function renderJobView(job) {
  const steps = ViewModel.progressSteps((name) => stageStatusFor(name, job));
  const list = $("job-steps");
  clear(list);
  for (const step of steps) {
    const failed = job.state === "failed" && step.status === "active";
    const item = el("li", `step ${failed ? "failed" : step.status}`);
    item.appendChild(el("span", "step-mark", step.status === "done" ? "✓" : failed ? "!" : ""));
    item.appendChild(el("span", "step-label", step.label));
    list.appendChild(item);
  }
  const done = steps.filter((step) => step.status === "done").length;
  const segments = $("job-track").children;
  steps.forEach((step, index) => {
    segments[index].className = step.status === "done" ? "on" : step.status === "active" ? "cur" : "";
  });
  const lines = $("job-paper").querySelectorAll(".paper-name, .paper-line");
  const inked = Math.round((lines.length * done) / steps.length);
  lines.forEach((line, index) => line.classList.toggle("ink", index < inked));

  const running = ["queued", "running"].includes(job.state);
  const finished = job.state === "completed";
  $("job-running").hidden = finished;
  $("job-summary").hidden = !finished;
  $("job-elapsed").textContent = job.started_at ? formatElapsed(job.started_at, job.finished_at) : "—";
  $("job-note").textContent = running ? latestNote(job) : "";
  const hasPdf = (job.artifacts || []).includes("resume.pdf");
  $("download-pdf").hidden = !(finished && hasPdf);
  $("delete-job").hidden = !DELETABLE_STATES.includes(job.state);
  if (hasPdf) $("download-pdf").href = `/api/jobs/${encodeURIComponent(job.job_id)}/files/resume.pdf`;
}

function renderSummary(review) {
  const view = ViewModel.summary(review || {});
  const missing = view.pct === null || view.pct === undefined;
  $("summary-pct").hidden = missing;
  $("summary-pct").textContent = missing ? "" : `${Math.round(view.pct)}%`;
  $("summary-label").textContent = missing
    ? "No summary for this resume. The PDF is ready to download."
    : view.estimated ? "estimated keyword match" : "keyword match with the posting";
  $("summary-all").hidden = !view.allIncluded;
  const notes = $("summary-notes");
  clear(notes);
  for (const note of view.notes) notes.appendChild(el("li", `note ${note.tone}`, note.text));
}

function renderTopbarRunning(active) {
  const link = $("topbar-running");
  link.hidden = !active;
  if (!active) return;
  link.textContent = `${active.company || "Resume"}: ${currentStepLabel(active)}`;
  link.href = `#job/${encodeURIComponent(active.job_id)}`;
}

/* Cleanup: select finished resumes (and old command-line folders), confirm, delete. */

function formatBytes(bytes) {
  if (!bytes) return "0 KB";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function enterSelect() {
  try {
    state.inventory = await fetchJson("/api/cleanup");
  } catch (error) {
    $("history-note").textContent = `Couldn't load what can be deleted. ${error.message}`;
    return;
  }
  state.selecting = true;
  state.selected.clear();
  state.selectLegacy = false;
  renderJobLists();
}

function exitSelect() {
  state.selecting = false;
  state.selected.clear();
  state.selectLegacy = false;
  renderJobLists();
}

function renderSelection() {
  const selecting = state.selecting;
  $("select-btn").hidden = selecting;
  $("select-cancel").hidden = !selecting;
  $("delete-bar").hidden = !selecting;
  $("select-all-row").hidden = !selecting;
  const legacy = (state.inventory && state.inventory.legacy) || [];
  $("select-legacy-row").hidden = !selecting || legacy.length === 0;
  const count = state.selected.size + (state.selectLegacy ? legacy.length : 0);
  $("history-title").textContent = selecting ? `${count} selected` : "History";
  if (!selecting) return;
  const finished = state.visibleDeletable || [];
  $("select-all-label").textContent = `Select all finished (${finished.length})`;
  $("select-all").checked = finished.length > 0 && finished.every((id) => state.selected.has(id));
  $("select-legacy-label").textContent = `Old command-line folders (${legacy.length})`;
  $("select-legacy-names").textContent = legacy.slice(0, 4).map((item) => item.id).join(", ") + (legacy.length > 4 ? ", …" : "");
  $("select-legacy").checked = state.selectLegacy;
  const button = $("delete-selected");
  button.disabled = count === 0;
  button.textContent = count === 1 ? "Delete 1 resume" : `Delete ${count} resumes`;
}

function openDeleteDialog(jobIds, includeLegacy, source) {
  const inventory = state.inventory || { jobs: [], legacy: [] };
  const byId = new Map(inventory.jobs.map((item) => [item.id, item]));
  const items = jobIds.map((id) => byId.get(id) || { id, label: jobLabel(state.jobs.get(id) || { company: id }), bytes: 0 });
  const legacy = includeLegacy ? inventory.legacy : [];
  const total = items.length + legacy.length;
  state.deleting = { jobIds, includeLegacy, source };
  $("delete-title").textContent = total === 1 ? "Delete 1 resume?" : `Delete ${total} resumes?`;
  $("delete-copy").textContent = total === 1
    ? "Removes its PDF, its copy in your PDF library, its report, and its saved job description. This can't be undone."
    : "Removes each one's PDF, its copy in your PDF library, its report, and its saved job description. This can't be undone.";
  const list = $("delete-list");
  clear(list);
  for (const item of items.slice(0, 8)) list.appendChild(el("li", null, item.label));
  if (items.length > 8) list.appendChild(el("li", null, `and ${items.length - 8} more`));
  if (legacy.length) list.appendChild(el("li", null, `Old command-line folders (${legacy.length})`));
  const bytes = [...items, ...legacy].reduce((sum, item) => sum + (item.bytes || 0), 0);
  $("delete-size").textContent = `Frees about ${formatBytes(bytes)}.`;
  $("delete-error").textContent = "";
  $("delete-confirm").disabled = false;
  $("delete-dialog").showModal();
}

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(state.toastTimer);
  state.toastTimer = window.setTimeout(() => { toast.hidden = true; }, 6000);
}

async function confirmDelete() {
  const pending = state.deleting;
  if (!pending) return;
  $("delete-confirm").disabled = true;
  try {
    const result = await fetchJson("/api/cleanup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_ids: pending.jobIds, include_legacy: pending.includeLegacy }),
    });
    $("delete-dialog").close();
    state.deleting = null;
    const removed = result.deleted_jobs.length + result.deleted_legacy.length;
    let message = `Deleted ${removed} ${removed === 1 ? "resume" : "resumes"}. ${formatBytes(result.freed_bytes)} freed.`;
    if (result.skipped.length) message += ` Skipped: ${result.skipped.map((item) => `${item.id} (${item.label})`).join("; ")}.`;
    for (const id of result.deleted_jobs) state.jobs.delete(id);
    if (result.deleted_jobs.includes(state.selectedId)) {
      state.selectedId = null;
      state.currentDetail = null;
      state.detailStatus = "empty";
    }
    state.selecting = false;
    state.selected.clear();
    state.selectLegacy = false;
    state.inventory = null;
    showToast(message);
    if (pending.source === "job") go("#history");
    await loadJobData();
  } catch (error) {
    $("delete-error").textContent = `Couldn't delete. ${error.message}`;
    $("delete-confirm").disabled = false;
  }
}

async function deleteCurrentJob() {
  const job = state.currentDetail;
  if (!job) return;
  try {
    state.inventory = await fetchJson("/api/cleanup");
  } catch {
    state.inventory = null;
  }
  openDeleteDialog([job.job_id], false, "job");
}

/* Mutations and form */

async function removeJob(jobId) {
  try {
    await fetchJson(`/api/jobs/${jobId}`, { method: "DELETE" });
    if (state.selectedId === jobId) selectJob(null);
    await loadJobData();
  } catch (error) {
    state.queueStatus = "error";
    state.queueError = String(error.message || error);
    renderJobLists();
  }
}

async function pauseQueue() {
  state.queue = await fetchJson("/api/queue/pause", { method: "POST", headers: { "Content-Type": "application/json" } });
  renderJobLists();
}

async function resumeQueue() {
  state.queue = await fetchJson("/api/queue/resume", { method: "POST", headers: { "Content-Type": "application/json" } });
  renderJobLists();
}

const formFields = {
  company: $("company"),
  role: $("role"),
  jd: $("jd-text"),
};
const touchedFields = new Set();

function fieldMessage(name, value) {
  const trimmed = value.trim();
  if (name === "company") {
    if (!trimmed) return "Enter the company name.";
    if (trimmed.length > 80) return "Shorten the company name to 80 characters or fewer.";
  }
  if (name === "role") {
    if (!trimmed) return "Enter the role title.";
    if (trimmed.length > 80) return "Shorten the role title to 80 characters or fewer.";
  }
  if (name === "jd") {
    if (!trimmed) return "Paste the job description you want to tailor this resume for.";
    if (trimmed.length > 100000) return "Shorten the job description to 100,000 characters or fewer.";
  }
  return "";
}

function validateField(name) {
  const field = formFields[name];
  const message = fieldMessage(name, field.value);
  const error = $(name === "jd" ? "jd-error" : `${name}-error`);
  error.textContent = message;
  field.setAttribute("aria-invalid", String(Boolean(message)));
  return !message;
}

/* Skill check: confirm posting skills the master resume lacks, then tailor. */

const SKILL_CHECK_TIMEOUT_MS = 180000;

function resetSkillCheck() {
  state.skillCheck = null;
  state.skipSkillCheck = false;
  $("skill-check").hidden = true;
  $("skip-check-btn").hidden = true;
  $("skill-chips").replaceChildren();
  $("check-skills-btn").textContent = "Check skills";
}

function skillChip(term, pressed, onToggle) {
  const chip = document.createElement("button");
  chip.type = "button";
  chip.className = "skill-chip";
  chip.textContent = term;
  chip.setAttribute("aria-pressed", String(pressed));
  chip.addEventListener("click", () => {
    chip.setAttribute("aria-pressed", String(chip.getAttribute("aria-pressed") !== "true"));
    if (onToggle) onToggle();
  });
  return chip;
}

function chipTerms(container, pressed) {
  return [...container.querySelectorAll(".skill-chip")]
    .filter((chip) => (chip.getAttribute("aria-pressed") === "true") === pressed)
    .map((chip) => chip.textContent);
}

async function saveRememberedSkills() {
  const container = $("remembered-chips");
  const chips = [...container.querySelectorAll(".skill-chip")];
  chips.forEach((chip) => { chip.disabled = true; });
  try {
    await fetchJson("/api/skill-answers", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmed: chipTerms(container, true), declined: chipTerms(container, false) }),
    });
    $("enqueue-status").textContent = "Remembered skills saved.";
  } catch (error) {
    $("enqueue-status").textContent = `Remembered skills could not be saved. ${String(error.message || error)}`;
  } finally {
    chips.forEach((chip) => { chip.disabled = false; });
  }
}

function renderRememberedSkills(confirmed, declined) {
  const container = $("remembered-chips");
  container.replaceChildren(
    ...confirmed.map((term) => skillChip(term, true, saveRememberedSkills)),
    ...declined.map((term) => skillChip(term, false, saveRememberedSkills)),
  );
  $("remembered-skills").hidden = confirmed.length + declined.length === 0;
}

function renderSkillCheck(check) {
  const chips = $("skill-chips");
  chips.replaceChildren(...check.chips.map((chip) => skillChip(chip.term, false)));
  $("skill-check-count").textContent = `(${check.chips.length} not in your resume)`;
  $("skill-check").hidden = false;
  renderRememberedSkills(check.remembered_confirmed, check.remembered_declined);
  $("check-skills-btn").textContent = "Tailor resume";
  $("skill-check").scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}

async function runSkillCheck(draft) {
  return fetchJson("/api/skill-check", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jd_text: draft.jd_text, provider_mode: draft.provider_mode, freellm_model: draft.freellm_model ?? null, college_mode: draft.college_mode }),
    signal: AbortSignal.timeout(SKILL_CHECK_TIMEOUT_MS),
  });
}

async function saveSkillAnswers(check) {
  const chips = $("skill-chips");
  await fetchJson(`/api/skill-check/${check.check_id}/answers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmed: chipTerms(chips, true), declined: chipTerms(chips, false) }),
  });
}

async function submitJob(event) {
  event.preventDefault();
  if (state.submitting) return;
  Object.keys(formFields).forEach((name) => touchedFields.add(name));
  const valid = Object.keys(formFields).map(validateField).every(Boolean);
  if (!valid) {
    const first = Object.keys(formFields).find((name) => !validateField(name));
    if (first) formFields[first].focus();
    return;
  }

  state.submitting = true;
  const button = $("check-skills-btn");
  const status = $("enqueue-status");
  button.disabled = true;
  try {
    const draft = currentDraft();
    let check = state.skillCheck && state.skillCheck.jd === draft.jd_text ? state.skillCheck : null;
    if (!check && !state.skipSkillCheck) {
      button.textContent = "Checking skills…";
      status.textContent = "Reading the job description for skills your resume doesn't list.";
      try {
        check = { ...(await runSkillCheck(draft)), jd: draft.jd_text };
      } catch (error) {
        status.textContent = `Skill check failed. ${String(error.message || error)}`;
        $("skip-check-btn").hidden = false;
        return;
      }
      state.skillCheck = check;
      if (check.chips.length) {
        renderSkillCheck(check);
        status.textContent = "Tap the skills you know, then tailor.";
        return;
      }
    } else if (check && check.chips.length && !state.skipSkillCheck) {
      button.textContent = "Saving answers…";
      try {
        await saveSkillAnswers(check);
      } catch (error) {
        status.textContent = `Your answers could not be saved. ${String(error.message || error)}`;
        $("skip-check-btn").hidden = false;
        return;
      }
    }
    await enqueueJob(check ? { ...draft, skill_check_id: check.check_id } : draft);
  } catch (error) {
    status.textContent = `Submission could not be confirmed. Retry to check the same request. ${String(error.message || error)}`;
  } finally {
    state.submitting = false;
    button.disabled = false;
    button.textContent = state.skillCheck?.chips.length ? "Tailor resume" : "Check skills";
  }
}

async function enqueueJob(draft) {
  const button = $("check-skills-btn");
  const status = $("enqueue-status");
  button.textContent = "Adding…";
  status.textContent = "Adding the job to the queue.";
  const body = JSON.stringify(draft);
  if (!state.submission || state.submission.body !== body) state.submission = { body, key: crypto.randomUUID() };
  saveDraft();
  const result = await fetchJson("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": state.submission.key },
    body,
  });
  state.submission = null;
  try { sessionStorage.removeItem("tailoring-draft"); } catch { /* Storage may be unavailable. */ }
  $("job-form").reset();
  resetSkillCheck();
  if (state.meta && state.meta.pdf_available === false) lockSkipPdf();
  touchedFields.clear();
  for (const name of Object.keys(formFields)) validateField(name);
  rememberProvider();
  status.textContent = "Added to the queue.";
  await loadJobData();
  go(`#job/${encodeURIComponent(result.job_id)}`);
}

/* Model provider */

const PROVIDER_MODES = ["gemini", "freellm", "freellm_gemini", "gemini_freellm"];
const PROVIDER_LABELS = { gemini: "Gemini", freellm: "FreeLLMAPI", freellm_gemini: "FreeLLMAPI → Gemini", gemini_freellm: "Gemini → FreeLLMAPI" };
const PROVIDER_STORE = "provider-choice";

function selectedMode() {
  const checked = document.querySelector('input[name="provider_mode"]:checked');
  return checked ? checked.value : "gemini";
}

function providerChoice() {
  const mode = selectedMode();
  if (mode === "gemini") return { provider_mode: "gemini" };
  return { provider_mode: mode, freellm_model: $("freellm-model").value || "auto" };
}

function ensureModelOption(model) {
  const select = $("freellm-model");
  if (model && ![...select.options].some((option) => option.value === model)) select.appendChild(new Option(model, model));
}

function setProviderChoice(mode, model) {
  const radio = document.querySelector(`input[name="provider_mode"][value="${PROVIDER_MODES.includes(mode) ? mode : "gemini"}"]`);
  if (radio && !radio.disabled) radio.checked = true;
  if (typeof model === "string" && model) { ensureModelOption(model); $("freellm-model").value = model; }
  syncProviderUi();
}

function rememberProvider() {
  try { localStorage.setItem(PROVIDER_STORE, JSON.stringify(providerChoice())); }
  catch { /* Choice still applies to this form. */ }
}

function restoreProvider() {
  try {
    const saved = JSON.parse(localStorage.getItem(PROVIDER_STORE) || "null");
    if (saved && PROVIDER_MODES.includes(saved.provider_mode)) setProviderChoice(saved.provider_mode, saved.freellm_model);
  } catch { /* Ignore a damaged saved choice. */ }
}

function syncProviderUi() {
  const mode = selectedMode();
  const usesFree = mode !== "gemini";
  const providers = state.providers;
  $("freellm-model-row").hidden = !usesFree;
  const research = $("research-company");
  research.disabled = mode === "freellm";
  if (research.disabled) research.checked = false;
  const help = $("provider-help");
  help.dataset.tone = "";
  if (!providers) {
    help.textContent = usesFree ? "Checking FreeLLMAPI…" : "Gemini uses the models configured in .env.";
    return;
  }
  const free = providers.freellm;
  if (!free.reachable) {
    help.dataset.tone = "warning";
    help.textContent = free.configured
      ? "FreeLLMAPI is offline — start the Docker container to use it. Gemini only for now."
      : "Add FREELLMAPI_API_KEY to .env to enable FreeLLMAPI. Gemini only for now.";
    return;
  }
  const geminiChain = [providers.gemini.default_model, ...providers.gemini.fallback_models].join(", ");
  const model = $("freellm-model").value || "auto";
  help.textContent = {
    gemini: `Gemini chain: ${geminiChain}.`,
    freellm: `Every stage runs on FreeLLMAPI ${model}. Company research needs Gemini.`,
    freellm_gemini: `FreeLLMAPI ${model} first; Gemini takes over if the proxy is down or busy.`,
    gemini_freellm: `Gemini first; FreeLLMAPI ${model} is the last fallback.`,
  }[mode];
}

function renderProviders() {
  const providers = state.providers;
  const free = providers?.freellm;
  const offline = providers && !free.reachable;
  for (const radio of document.querySelectorAll('input[name="provider_mode"]')) {
    radio.disabled = Boolean(offline) && radio.value !== "gemini";
    if (radio.disabled && radio.checked) document.querySelector('input[name="provider_mode"][value="gemini"]').checked = true;
  }
  if (free?.reachable) {
    const select = $("freellm-model");
    const current = select.value || free.default_model || "auto";
    clear(select);
    const ids = free.models.map((model) => model.id);
    const ordered = ["auto", ...ids.filter((id) => id !== "auto").sort((a, b) => a.localeCompare(b))];
    for (const id of new Set(ordered)) select.appendChild(new Option(id, id));
    ensureModelOption(current);
    select.value = current;
  }
  syncProviderUi();
}

async function fetchProviders() {
  try { state.providers = await fetchJson("/api/providers"); }
  catch { state.providers = null; }
  renderProviders();
}

function providerSummary(options) {
  if (!options || !options.provider_mode || options.provider_mode === "gemini") return "Gemini";
  const label = PROVIDER_LABELS[options.provider_mode] || options.provider_mode;
  return options.freellm_model ? label.replace("FreeLLMAPI", `FreeLLMAPI (${options.freellm_model})`) : label;
}

/* Live updates */

function currentDraft() {
  return {
    company: formFields.company.value.trim(), role: formFields.role.value.trim(),
    jd_text: formFields.jd.value.trim(), bridge_skills: $("bridge-skills").checked,
    research_company: $("research-company").checked, no_pdf: $("no-pdf").checked,
    college_mode: $("college-mode").checked,
    ...providerChoice(),
  };
}

function fillDraft(draft) {
  formFields.company.value = typeof draft.company === "string" ? draft.company : "";
  formFields.role.value = typeof draft.role === "string" ? draft.role : "";
  formFields.jd.value = typeof draft.jd_text === "string" ? draft.jd_text : "";
  for (const [id, key] of [["bridge-skills", "bridge_skills"], ["research-company", "research_company"], ["no-pdf", "no_pdf"], ["college-mode", "college_mode"]]) $(id).checked = draft[key] === true;
  if (PROVIDER_MODES.includes(draft.provider_mode)) setProviderChoice(draft.provider_mode, draft.freellm_model);
  if (state.meta?.pdf_available === false) lockSkipPdf();
}

function saveDraft() {
  try { sessionStorage.setItem("tailoring-draft", JSON.stringify({ draft: currentDraft(), submission: state.submission })); }
  catch { /* In-memory form remains usable when browser storage is unavailable. */ }
}

function restoreDraft() {
  try {
    const saved = JSON.parse(sessionStorage.getItem("tailoring-draft") || "null");
    if (saved?.draft) fillDraft(saved.draft);
    if (typeof saved?.submission?.key === "string" && typeof saved?.submission?.body === "string") state.submission = saved.submission;
  } catch { /* Ignore an obsolete or damaged draft. */ }
}

async function duplicateJob() {
  const jobId = state.selectedId;
  const button = $("duplicate-job");
  button.disabled = true;
  $("detail-action-status").textContent = "Loading saved job description…";
  try {
    const request = await fetchJson(`/api/jobs/${jobId}/request`);
    if (state.selectedId !== jobId) return;
    if (formFields.jd.value.trim()) {
      $("detail-action-status").textContent = "A draft is already open. Finish it or clear it before tailoring this job again.";
      go("#new");
      return;
    }
    fillDraft(request);
    state.submission = null;
    saveDraft();
    $("detail-action-status").textContent = "Review the saved description and options before adding a new run.";
    go("#new");
  } catch (error) { if (state.selectedId === jobId) $("detail-action-status").textContent = error.message; }
  finally { button.disabled = false; }
}

async function resumeJob() {
  const jobId = state.selectedId;
  const button = $("resume-job");
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "Resuming…";
  $("detail-action-status").textContent = "";
  try {
    await fetchJson(`/api/jobs/${jobId}/resume`, { method: "POST" });
    if (state.selectedId === jobId) $("detail-action-status").textContent = "Queued. Finished stages are reused; only what is left will run.";
    loadJobData().catch(() => {});
    if (state.selectedId === jobId) fetchDetail(jobId);
  } catch (error) {
    if (state.selectedId === jobId) $("detail-action-status").textContent = `Could not resume. ${error.message}`;
    button.textContent = label;
  } finally { button.disabled = false; }
}

function reviewSection(title, entries) {
  if (!Array.isArray(entries) || !entries.length) return;
  const section = el("section", "review-section");
  section.appendChild(el("h3", null, title));
  const list = el("ul", "review-list");
  for (const entry of entries) list.appendChild(el("li", null, typeof entry === "string" ? entry : [entry.claim, entry.reason].filter(Boolean).join(" — ")));
  section.appendChild(list);
  $("review-content").appendChild(section);
}

async function loadReview(force = false) {
  const job = state.currentDetail;
  if (!job) return;
  const id = job.job_id;
  if (!force && state.reviewLoadingId === id) return;
  state.reviewLoadingId = id;
  state.review = null;
  clear($("review-content"));
  $("save-review").hidden = true;
  $("review-status").textContent = "Loading analysis…";
  try {
    const report = await fetchJson(`/api/jobs/${id}/review`);
    if (state.selectedId !== id) return;
    state.review = report;
    renderSummary(report);
    $("review-status").textContent = typeof report.coverage_pct === "number" ? `${Math.round(report.coverage_pct)}% estimated requirement coverage` : "Review the analysis below.";
    const QUALIFICATION_LABELS = { covered: "Covered", covered_with_substitution: "Covered with education substitution", unsupported: "Not supported", supported_not_on_page: "True but not on the page" };
    reviewSection("Qualifications", (report.qualification_coverage || []).map((row) =>
      `${QUALIFICATION_LABELS[row.status] || row.status}${row.required ? "" : " (preferred)"}: ${row.text}${row.status === "covered" ? "" : ` — ${row.reason}`}`));
    reviewSection("Missing requirements", report.missing_must_haves);
    reviewSection("Truth concerns", report.truth_violations);
    reviewSection("Sections to improve", report.weak_sections);
    reviewSection("Recommendations", report.recommendations);
    reviewSection("Edits the validator rejected", report.rejected_section_edits);
    if (report.notes) reviewSection("Reviewer notes", [report.notes]);
    const assignments = report.evidence_assignments || [];
    if (assignments.length) {
      const details = el("details", "review-section");
      details.appendChild(el("summary", null, "Planned requirement coverage"));
      for (const item of assignments) {
        const row = el("div", "review-section");
        row.append(el("strong", null, (item.matched_requirements || []).join(", ")), el("p", null, item.intended_accomplishment));
        details.appendChild(row);
      }
      $("review-content").appendChild(details);
    }
    if (report.claims.length) {
      const section = el("section", "review-section");
      section.append(el("h3", null, "Claims to check"), el("p", "help", "Check each claim only after verifying it against your experience. Saving records your review; it does not change the resume."));
      for (const claim of report.claims) {
        const label = el("label", "claim-row");
        const checkbox = el("input", "checkbox checkbox-sm");
        checkbox.type = "checkbox";
        checkbox.value = claim.id;
        checkbox.checked = report.reviewed_ids.includes(claim.id);
        const copy = el("span", "claim-copy");
        copy.append(el("strong", null, claim.kind), el("span", null, claim.claim));
        if (claim.basis) copy.appendChild(el("small", null, `Basis: ${claim.basis}`));
        if (claim.baseline) copy.appendChild(el("small", null, `Baseline: ${claim.baseline}`));
        if (claim.destination) copy.appendChild(el("small", null, `Destination: ${claim.destination}`));
        if (claim.sources.length) copy.appendChild(el("small", null, `Evidence: ${claim.sources.join("; ")}`));
        label.append(checkbox, copy);
        section.appendChild(label);
      }
      $("review-content").appendChild(section);
      $("save-review").hidden = false;
    } else {
      reviewSection("Claims to check", ["No estimated metrics or cross-entry attributions were recorded in this report. Review the full resume before applying."]);
    }
  } catch (error) {
    if (state.selectedId !== id) return;
    $("review-status").textContent = error.message;
    // No report for this job: show the plain "no summary" state and stop asking.
    if (error.status === 404) { state.review = {}; renderSummary(state.review); }
  } finally { if (state.reviewLoadingId === id) state.reviewLoadingId = null; }
}

async function saveReview() {
  if (!state.review) return;
  const id = state.selectedId;
  const button = $("save-review");
  if (button.disabled) return;
  button.disabled = true;
  const reviewed_ids = [...$("review-content").querySelectorAll("input:checked")].map((input) => input.value);
  try {
    await fetchJson(`/api/jobs/${id}/review`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ revision: state.review.revision, reviewed_ids }) });
    if (state.selectedId === id) $("review-status").textContent = `Review saved · ${reviewed_ids.length} of ${state.review.claims.length} claims checked`;
  } catch (error) { if (state.selectedId === id) $("review-status").textContent = error.message; }
  finally { button.disabled = false; }
}

function applyEvent(event) {
  if (event.id !== undefined) {
    if (state.seenEvents.has(event.id)) return;
    state.seenEvents.add(event.id);
  }
  const kind = event.kind || event.type || "";
  if (kind === "queue_changed") {
    state.queue = event.data;
    state.queueStatus = "success";
    if (event.data && event.data.tracker && (event.data.tracker.active !== false || !state.tracker)) state.tracker = event.data.tracker;
    renderTracker();
    renderJobLists();
    return;
  }
  if (kind === "tracker_changed") {
    state.tracker = event.data;
    renderTracker();
    return;
  }
  if (kind === "job_action_required") {
    state.recoveryCache.delete(event.job_id);
    loadJobData().catch(() => {});
    if (event.job_id === state.selectedId) fetchDetail(event.job_id);
    const dialog = $("fit-recovery-dialog");
    if (dialog.open && state.recovery.jobId === event.job_id) {
      state.recovery.awaitingResult = false;
      $("recovery-submit-status").classList.remove("error");
      $("recovery-submit-status").textContent = "More space is still needed. Review the remaining options.";
      loadRecoveryDialog();
    }
    return;
  }
  if (kind === "job_started" || kind === "job_completed" || kind === "job_failed") {
    const recoveryJob = state.recovery.jobId === event.job_id;
    if ((kind === "job_completed" || kind === "job_failed") && recoveryJob) {
      state.recovery.awaitingResult = false;
      closeRecoveryDialog();
    }
    loadJobData().catch(() => {});
    if (event.job_id === state.selectedId) {
      fetchDetail(event.job_id);
    }
    return;
  }
  if (!kind.startsWith("stage_") || !event.job_id) return;
  if (!state.events.has(event.job_id)) state.events.set(event.job_id, []);
  state.events.get(event.job_id).push(event);
  const job = state.jobs.get(event.job_id);
  if (job && kind === "stage_started") job.current_stage = event.stage;
  renderJobLists();
  if (event.job_id === state.selectedId && job) {
    state.currentDetail = job;
    renderJobView(job);
    renderStages(job);
    renderLog(job);
    $("detail-stage-text").textContent = job.current_stage || "Processing";
  }
}

function openStream() {
  const source = new EventSource("/api/events");
  source.onopen = () => { state.seenEvents.clear(); loadAll(); };
  source.onerror = () => {
    $("server-status").textContent = "Connection lost · reconnecting…";
    // The worker continues while this browser reconnects.
    fetchMeta().catch(() => {});
  };
  const kinds = ["queue_changed", "job_started", "stage_started", "stage_completed", "stage_retry", "stage_detail", "stage_warning", "job_action_required", "job_completed", "job_failed", "tracker_changed"];
  for (const kind of kinds) {
    source.addEventListener(kind, (message) => {
      try { applyEvent(JSON.parse(message.data)); } catch { /* Ignore malformed event frames. */ }
    });
  }
  return source;
}

async function loadAll() {
  await Promise.allSettled([fetchMeta(), loadJobData()]);
}

/* Views: #new (home), #job/<id>, #history. The URL hash is the source of truth,
   so reload and the browser's back button keep working. */

const VIEWS = ["new", "job", "history"];

function parseRoute() {
  const hash = location.hash.replace(/^#/, "");
  if (hash.startsWith("job/")) return { view: "job", jobId: decodeURIComponent(hash.slice(4)) };
  if (hash === "history") return { view: "history", jobId: null };
  return { view: "new", jobId: null };
}

function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

function route() {
  const { view, jobId } = parseRoute();
  state.view = view;
  if (view !== "history") {
    $("history-note").textContent = "";
    if (state.selecting) exitSelect();
  }
  for (const name of VIEWS) $(`view-${name}`).hidden = name !== view;
  $("nav-new").setAttribute("aria-pressed", String(view === "new"));
  $("nav-history").setAttribute("aria-pressed", String(view === "history"));
  if (view === "job" && jobId) {
    if (jobId !== state.selectedId || state.detailStatus === "error") selectJob(jobId);
  } else if (view === "new") {
    fetchProviders();
  }
  $("main").focus({ preventScroll: true });
}

function bindEvents() {
  for (const button of document.querySelectorAll("[data-log-filter]")) {
    button.addEventListener("click", () => setLogFilter(button.dataset.logFilter));
  }
  $("log-copy").addEventListener("click", copyLog);
  $("log-jump").addEventListener("click", () => {
    const scroller = $("log-scroll");
    scroller.scrollTo({ top: scroller.scrollHeight, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    $("log-jump").hidden = true;
  });
  $("log-scroll").addEventListener("scroll", () => {
    const scroller = $("log-scroll");
    if (scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 24) $("log-jump").hidden = true;
  }, { passive: true });
  $("suggest-details").addEventListener("click", () => {
    const text = formFields.jd.value;
    const company = text.match(/^\s*(?:company|employer)\s*:\s*(.{1,80})$/im);
    const role = text.match(/^\s*(?:role|job title|position|title)\s*:\s*(.{1,80})$/im);
    if (company && !formFields.company.value.trim()) formFields.company.value = company[1].trim();
    if (role && !formFields.role.value.trim()) formFields.role.value = role[1].trim();
    $("suggest-status").textContent = company || role ? "Labeled details copied into empty fields. Check them before submitting." : "No labeled company or role found. Enter them below.";
    saveDraft();
  });
  $("clear-draft").addEventListener("click", () => {
    if (state.submitting) return;
    if (!window.confirm("Clear this saved draft?")) return;
    $("job-form").reset(); state.submission = null; touchedFields.clear(); resetSkillCheck();
    restoreProvider(); renderProviders();
    for (const name of Object.keys(formFields)) { const error = $(name === "jd" ? "jd-error" : `${name}-error`); error.textContent = ""; formFields[name].removeAttribute("aria-invalid"); }
    $("enqueue-status").textContent = "Draft cleared.";
    $("suggest-status").textContent = "";
    if (state.meta?.pdf_available === false) lockSkipPdf();
    saveDraft();
  });
  $("job-search").addEventListener("input", renderJobLists);
  $("job-status-filter").addEventListener("change", renderJobLists);
  $("duplicate-job").addEventListener("click", duplicateJob);
  $("resume-job").addEventListener("click", resumeJob);
  $("reload-review").addEventListener("click", () => loadReview(true));
  $("save-review").addEventListener("click", saveReview);
  $("job-form").addEventListener("input", saveDraft);
  $("job-form").addEventListener("change", saveDraft);
  $("logout-btn").addEventListener("click", async () => {
    try { await fetchJson("/api/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      sessionStorage.removeItem("tailoring-draft"); location.replace("/login");
    } catch (error) { $("server-status").textContent = error.message; }
  });
  $("select-btn").addEventListener("click", enterSelect);
  $("select-cancel").addEventListener("click", exitSelect);
  $("select-all").addEventListener("change", () => {
    for (const id of state.visibleDeletable || []) {
      if ($("select-all").checked) state.selected.add(id);
      else state.selected.delete(id);
    }
    renderJobLists();
  });
  $("select-legacy").addEventListener("change", () => { state.selectLegacy = $("select-legacy").checked; renderSelection(); });
  $("delete-selected").addEventListener("click", () => openDeleteDialog([...state.selected], state.selectLegacy, "history"));
  $("delete-cancel").addEventListener("click", () => { state.deleting = null; $("delete-dialog").close(); });
  $("delete-confirm").addEventListener("click", confirmDelete);
  $("delete-job").addEventListener("click", deleteCurrentJob);
  $("nav-new").addEventListener("click", () => go("#new"));
  $("nav-history").addEventListener("click", () => go("#history"));
  window.addEventListener("hashchange", route);
  $("job-form").addEventListener("submit", submitJob);
  formFields.jd.addEventListener("input", () => { if (state.skillCheck || state.skipSkillCheck) resetSkillCheck(); });
  // College mode also offers posted standards (Section 508, ADA): check again.
  $("college-mode").addEventListener("change", () => { if (state.skillCheck || state.skipSkillCheck) resetSkillCheck(); });
  $("skip-check-btn").addEventListener("click", () => {
    state.skipSkillCheck = true;
    $("skip-check-btn").hidden = true;
    $("job-form").requestSubmit();
  });
  for (const radio of document.querySelectorAll('input[name="provider_mode"]')) radio.addEventListener("change", syncProviderUi);
  $("freellm-model").addEventListener("change", syncProviderUi);
  $("review-removals-btn").addEventListener("click", openRecoveryDialog);
  $("open-bullet-review-btn").addEventListener("click", openBulletReview);
  $("retry-bullet-review").addEventListener("click", openBulletReview);
  $("close-bullet-review").addEventListener("click", () => $("bullet-review-dialog").close());
  $("cancel-bullet-review").addEventListener("click", () => $("bullet-review-dialog").close());
  $("bullet-review-form").addEventListener("submit", submitBulletReview);
  $("close-recovery-dialog").addEventListener("click", closeRecoveryDialog);
  $("cancel-recovery-dialog").addEventListener("click", closeRecoveryDialog);
  $("fit-recovery-form").addEventListener("submit", submitRecovery);
  $("retry-recovery-btn").addEventListener("click", () => loadRecoveryDialog());
  $("select-recommendations-btn").addEventListener("click", selectRecommendedCandidates);
  $("clear-recovery-selection-btn").addEventListener("click", clearRecoverySelection);
  $("recovery-options").addEventListener("change", () => {
    clearRecoveryError();
    state.recovery.requestSignature = "";
    state.recovery.idempotencyKey = "";
  });
  $("retry-jobs-btn").addEventListener("click", loadJobData);
  $("retry-detail-btn").addEventListener("click", () => state.selectedId && fetchDetail(state.selectedId));
  $("pause-btn").addEventListener("click", () => {
    if (state.queue && state.queue.state === "paused") resumeQueue();
    else pauseQueue();
  });

  for (const name of TAB_NAMES) {
    const tab = $(`tab-${name}`);
    tab.addEventListener("click", () => activateTab(name, false));
    tab.addEventListener("keydown", onTabKeydown);
  }
  for (const [name, field] of Object.entries(formFields)) {
    field.addEventListener("blur", () => { touchedFields.add(name); validateField(name); });
    field.addEventListener("input", () => { if (touchedFields.has(name)) validateField(name); });
  }
}

function startTicker() {
  window.setInterval(() => {
    renderTracker();
    const job = state.currentDetail;
    if (job && job.state === "running") {
      $("detail-elapsed").textContent = formatElapsed(job.started_at, job.finished_at);
      $("job-elapsed").textContent = formatElapsed(job.started_at, job.finished_at);
      if (state.activeTab === "progress") renderStages(job);
    }
  }, 1000);
}

function boot() {
  restoreProvider();
  restoreDraft();
  bindEvents();
  renderDetailState();
  renderJobLists();
  route();
  loadAll();
  fetchProviders();
  openStream();
  startTicker();
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
