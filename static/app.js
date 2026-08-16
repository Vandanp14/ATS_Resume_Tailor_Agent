/* ATS Resume Tailor web client.
   One EventSource, explicit async states, and text-only rendering for untrusted data. */

"use strict";

const STAGE_NAMES = [
  "Preflight",
  "Parse job description",
  "Research company tech stack",
  "Research company hiring signals",
  "Select work",
  "Select projects",
  "Plan evidence",
  "Plan transferable skills",
  "Tailor skills",
  "Rewrite work",
  "Rewrite projects",
  "Assemble draft",
  "Holistic review",
  "Validate review edits",
  "Render and fit one page",
  "Write artifacts",
];
const RESEARCH_STACK_INDEX = 2;
const RESEARCH_SIGNALS_INDEX = 3;
const BRIDGE_INDEX = 7;
const TAB_NAMES = ["progress", "preview", "files"];

const $ = (id) => document.getElementById(id);
const state = {
  meta: null,
  queue: null,
  tracker: null,
  jobs: new Map(),
  events: new Map(),
  selectedId: null,
  currentDetail: null,
  detailAbort: null,
  seenEvents: new Set(),
  queueStatus: "loading",
  queueError: "",
  detailStatus: "empty",
  detailError: "",
  listFilter: "queue",
  activeTab: "progress",
  submitting: false,
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
  workspaceMode: "job",
  applications: {
    items: [],
    summary: { total: 0, applied: 0, not_applied: 0 },
    status: "idle",
    error: "",
    search: "",
    filter: "all",
  },
  applicationEditor: {
    jobId: null,
    revision: 0,
    submitting: false,
    returnFocus: null,
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

function appItemRow(label, value) {
  const row = el("div", "app-item-row");
  const labelEl = el("span", "app-item-label", label);
  const valueEl = el("span", "app-item-value", value === null || value === undefined ? "—" : String(value));
  row.appendChild(labelEl);
  row.appendChild(valueEl);
  return row;
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
  if (index === BRIDGE_INDEX && job.options && !job.options.bridge_skills) return "skipped";
  if (
    (index === RESEARCH_STACK_INDEX || index === RESEARCH_SIGNALS_INDEX) &&
    job.options &&
    !job.options.research_company
  )
    return "skipped";
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
  const response = await fetch(url, options);
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : `Request failed (${response.status}).`;
    const error = new Error(detail);
    error.status = response.status;
    error.body = body;
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
  $("server-status").textContent = meta.ready
    ? `Ready · PDF ${meta.pdf_available === false ? "unavailable" : "available"}`
    : "Starting…";
  $("model-provider").textContent = `Model · ${meta.model || "Unavailable"}`;
  const identity = [meta.master_name, meta.master_email].filter(Boolean).join(" · ");
  $("master-identity").textContent = `Master · ${identity || "Unavailable"}`;
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

  if (!state.selectedId) {
    const webJobs = jobs.filter((job) => job.source === "web");
    const preferred = webJobs.length ? webJobs : jobs;
    const active = preferred.find((job) => job.active);
    const newest = preferred.find((job) => ["completed", "failed", "action_required"].includes(job.state));
    const initial = active || newest;
    if (initial) selectJob(initial.job_id, { reveal: false });
  }
}

function jobRow(job, position = null) {
  const item = el("li", "job-item");
  item.dataset.jobId = job.job_id;

  const select = el("button", "job-select");
  select.type = "button";
  select.setAttribute("aria-label", `View ${jobLabel(job)}`);
  select.setAttribute("aria-current", String(job.job_id === state.selectedId));
  const mark = el("span", `job-state-mark ${job.state}`);
  mark.setAttribute("aria-hidden", "true");
  select.appendChild(mark);

  const copy = el("span", "job-copy");
  copy.appendChild(el("strong", null, job.company || "Untitled company"));
  const metadata = job.role || job.current_stage || job.state;
  copy.appendChild(el("span", null, metadata));
  select.appendChild(copy);

  let aside = "";
  if (job.state === "queued" && position) aside = `#${position}`;
  else if (job.state === "running") aside = "Live";
  else if (job.state === "action_required") aside = "Action needed";
  else aside = formatWhen(job.finished_at || job.created_at);
  select.appendChild(el("span", "job-aside", aside));
  select.addEventListener("click", () => selectJob(job.job_id, { reveal: true }));
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
  const active = snapshot.active_job_id ? state.jobs.get(snapshot.active_job_id) : null;
  const paused = snapshot.state === "paused";
  const title = $("queue-status-title");
  const copy = $("queue-status-copy");
  const dot = $("queue-status-dot");
  const action = $("pause-btn");
  dot.className = "status-dot";

  if (paused) {
    title.textContent = "Queue paused";
    copy.textContent = `${snapshot.queue_count} waiting ${snapshot.queue_count === 1 ? "job" : "jobs"} kept safely.`;
    dot.classList.add("paused");
    action.textContent = "Resume queue";
  } else if (active) {
    title.textContent = "Tailoring in progress";
    copy.textContent = active.current_stage || jobLabel(active);
    action.textContent = "Pause after current job";
  } else if (snapshot.queue_count > 0) {
    title.textContent = "Queue ready";
    copy.textContent = `${snapshot.queue_count} waiting ${snapshot.queue_count === 1 ? "job" : "jobs"}.`;
    action.textContent = "Pause queue";
  } else {
    title.textContent = "Queue ready";
    copy.textContent = "No jobs are waiting.";
  }
  action.hidden = !paused && !active && snapshot.queue_count === 0;
}

function renderJobLists() {
  const queueList = $("queue-list");
  const recentList = $("recent-list");
  clear(queueList);
  clear(recentList);

  $("filter-queue").setAttribute("aria-pressed", String(state.listFilter === "queue"));
  $("filter-recent").setAttribute("aria-pressed", String(state.listFilter === "recent"));
  queueList.hidden = state.listFilter !== "queue";
  recentList.hidden = state.listFilter !== "recent";

  const loading = state.queueStatus === "loading";
  const failed = state.queueStatus === "error";
  $("queue-loading").hidden = !loading;
  $("queue-error").hidden = !failed;
  $("queue-error-copy").textContent = state.queueError;
  if (loading || failed || !state.queue) {
    $("queue-empty").hidden = true;
    $("recent-empty").hidden = true;
    return;
  }

  const activeId = state.queue.active_job_id;
  const active = activeId ? state.jobs.get(activeId) : null;
  if (active) queueList.appendChild(jobRow(active));
  for (const entry of state.queue.waiting) {
    const known = state.jobs.get(entry.job_id);
    const job = known || { ...entry, state: "queued", active: false, options: {} };
    queueList.appendChild(jobRow(job, entry.queue_position));
  }

  const recent = [...state.jobs.values()]
    .filter((job) => ["completed", "failed", "action_required"].includes(job.state))
    .sort((a, b) => String(b.finished_at || b.created_at).localeCompare(String(a.finished_at || a.created_at)));
  for (const job of recent.slice(0, 30)) recentList.appendChild(jobRow(job));

  $("queue-count").textContent = String(state.queue.queue_count || 0);
  $("queue-empty").hidden = state.listFilter !== "queue" || Boolean(active) || state.queue.waiting.length > 0;
  $("recent-empty").hidden = state.listFilter !== "recent" || recent.length > 0;
  renderQueueBanner();
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
    state.detailStatus = "error";
    state.detailError = String(error.message || error);
    renderDetailState();
  }
}

function renderDetailState() {
  const showingApplications = state.workspaceMode === "applications";
  $("apps-dashboard").hidden = !showingApplications;
  if (showingApplications) {
    $("detail-empty").hidden = true;
    $("detail-loading").hidden = true;
    $("detail-error").hidden = true;
    $("detail-body").hidden = true;
    renderApplicationsDashboard();
    return;
  }
  $("detail-empty").hidden = state.detailStatus !== "empty";
  $("detail-loading").hidden = state.detailStatus !== "loading";
  $("detail-error").hidden = state.detailStatus !== "error";
  $("detail-body").hidden = state.detailStatus !== "success";
  $("detail-error-copy").textContent = state.detailError;
}

function selectJob(jobId, { reveal = true } = {}) {
  state.workspaceMode = "job";
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
  const job = state.jobs.get(jobId);
  if (changed) state.activeTab = job && job.state === "completed" && (job.artifacts || []).includes("resume.pdf") ? "preview" : "progress";
  renderJobLists();
  if (reveal) showMobileView("detail");
  fetchDetail(jobId);
}

function renderDetail(job) {
  state.currentDetail = job;
  state.detailStatus = "success";
  renderDetailState();
  $("detail-company").textContent = job.company || "Untitled company";
  $("detail-role").textContent = job.role || "Role not provided";
  const badge = $("detail-state");
  badge.className = `status-pill ${job.state}`;
  badge.textContent = stateLabel(job.state);

  const stage = job.current_stage || (job.state === "queued" ? "Waiting to start" : job.state === "completed" ? "Tailoring complete" : job.state === "failed" ? "Run stopped" : job.state === "action_required" ? "Action needed: one-page fit" : "Preparing");
  $("detail-stage").textContent = stage;
  $("detail-elapsed").textContent = job.started_at ? formatElapsed(job.started_at, job.finished_at) : "—";
  $("detail-position").textContent = job.queue_position ? `#${job.queue_position}` : job.active ? "Active" : "—";
  $("detail-output").textContent = job.artifacts && job.artifacts.length ? `${job.artifacts.length} ${job.artifacts.length === 1 ? "file" : "files"}` : "Pending";
  $("detail-message").hidden = !job.message;
  $("detail-message").textContent = job.message || "";
  $("detail-export-warning").hidden = !job.export_warning;
  $("detail-export-warning").textContent = job.export_warning || "";
  renderApplicationSummary(job);
  renderRecoveryCard(job);
  renderStages(job);
  renderVerbose(job);
  renderPreview(job);
  renderFiles(job);
  activateTab(state.activeTab, false);
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
  const visible = job.state === "action_required";
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

async function fetchApplications() {
  state.applications.status = "loading";
  state.applications.error = "";
  renderApplicationsDashboard();
  try {
    const body = await fetchJson("/api/applications");
    state.applications.items = Array.isArray(body.items) ? body.items : [];
    state.applications.summary = body.summary || { total: 0, applied: 0, not_applied: 0 };
    state.applications.status = "success";
  } catch (error) {
    state.applications.status = "error";
    state.applications.error = String(error.message || error);
  }
  renderApplicationsDashboard();
}

function renderApplicationsDashboard() {
  const data = state.applications;
  const filtered = filterAndSortApps();
  const hasRows = data.items.length > 0;
  const hasMatches = filtered.length > 0;
  $("apps-loading").hidden = data.status !== "loading";
  $("apps-error").hidden = data.status !== "error";
  $("apps-error-copy").textContent = data.error;
  $("apps-empty").hidden = data.status !== "success" || hasRows;
  $("apps-no-match").hidden = data.status !== "success" || !hasRows || hasMatches;
  $("apps-list").hidden = data.status !== "success" || !hasMatches;
  $("apps-total").textContent = String(data.summary.total || 0);
  $("apps-applied").textContent = String(data.summary.applied || 0);
  $("apps-not-applied").textContent = String(data.summary.not_applied || 0);
  if (data.status === "success") renderAppsList(filtered);
}

function filterAndSortApps() {
  const query = state.applications.search.trim().toLowerCase();
  return state.applications.items.filter((item) => {
    const haystack = `${item.company || ""} ${item.role || ""}`.toLowerCase();
    const statusMatches = state.applications.filter === "all" || item.application.status === state.applications.filter;
    return statusMatches && (!query || haystack.includes(query));
  });
}

function renderAppsList(apps) {
  const list = $("apps-list");
  clear(list);
  for (const app of apps) list.appendChild(appItem(app));
}

function appItem(app) {
  const item = el("li", "app-item");
  const content = el("div", "app-item-content");
  const heading = el("div", "app-item-heading");
  const title = el("div", "app-item-title");
  title.appendChild(el("strong", null, app.company || "Untitled company"));
  title.appendChild(el("span", null, app.role || "Role not provided"));
  heading.appendChild(title);
  heading.appendChild(applicationBadge(app.application.status));
  content.appendChild(heading);

  const facts = el("div", "app-item-facts");
  facts.appendChild(appItemRow("Applied date", app.application.applied_on || "—"));
  facts.appendChild(appItemRow("Tailoring", stateLabel(app.state)));
  facts.appendChild(appItemRow("Updated", formatWhen(app.application.updated_at) || "Not edited"));
  content.appendChild(facts);
  if (app.application.notes) content.appendChild(el("p", "app-item-notes", app.application.notes));

  const actions = el("div", "app-item-actions");
  const view = el("button", "button tertiary compact", "View job");
  view.type = "button";
  view.addEventListener("click", () => selectJob(app.job_id, { reveal: true }));
  const edit = el("button", "button secondary compact", "Edit tracking");
  edit.type = "button";
  edit.addEventListener("click", () => openApplicationEditor(app, edit));
  actions.appendChild(view);
  actions.appendChild(edit);
  item.appendChild(content);
  item.appendChild(actions);
  return item;
}

function applicationBadge(status) {
  return el("span", `application-badge ${status}`, status === "applied" ? "Applied" : "Not applied");
}

function upsertApplication(entry) {
  const index = state.applications.items.findIndex((item) => item.job_id === entry.job_id);
  if (index === -1) state.applications.items.unshift(entry);
  else state.applications.items[index] = entry;
  const applied = state.applications.items.filter((item) => item.application.status === "applied").length;
  state.applications.summary = {
    total: state.applications.items.length,
    applied,
    not_applied: state.applications.items.length - applied,
  };
  const known = state.jobs.get(entry.job_id);
  if (known) known.application = entry.application;
  if (state.currentDetail && state.currentDetail.job_id === entry.job_id) state.currentDetail.application = entry.application;
}

function todayLocal() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function syncAppliedDateField({ fillDefault = false } = {}) {
  const applied = $("app-status").value === "applied";
  $("app-applied-on-field").hidden = !applied;
  $("app-applied-on").disabled = !applied;
  $("app-applied-on").required = applied;
  if (applied && fillDefault && !$("app-applied-on").value) $("app-applied-on").value = todayLocal();
  if (!applied) $("app-applied-on-error").textContent = "";
}

function clearApplicationErrors() {
  for (const id of ["app-status", "app-applied-on", "app-job-url", "app-notes"]) {
    $(id).setAttribute("aria-invalid", "false");
    $(`${id}-error`).textContent = "";
  }
  $("application-editor-status").textContent = "";
  $("application-editor-status").classList.remove("error");
  $("reload-application-editor").hidden = true;
}

function openApplicationEditor(app, returnFocus = document.activeElement) {
  state.applicationEditor.jobId = app.job_id;
  state.applicationEditor.revision = Number(app.application.revision || 0);
  state.applicationEditor.returnFocus = returnFocus;
  $("application-editor-title").textContent = `Track ${app.company || "application"}`;
  $("application-editor-context").textContent = app.role || "Role not provided";
  $("app-status").value = app.application.status;
  $("app-applied-on").value = app.application.applied_on || "";
  $("app-job-url").value = app.application.job_url || "";
  $("app-notes").value = app.application.notes || "";
  clearApplicationErrors();
  syncAppliedDateField({ fillDefault: true });
  const dialog = $("application-editor-dialog");
  if (!dialog.open) dialog.showModal();
  requestAnimationFrame(() => $("app-status").focus());
}

function closeApplicationEditorDialog() {
  const dialog = $("application-editor-dialog");
  if (dialog.open) dialog.close();
}

function validateApplicationEditor() {
  clearApplicationErrors();
  const invalid = [];
  if ($("app-status").value === "applied" && !$("app-applied-on").value) {
    $("app-applied-on-error").textContent = "Choose the date you applied.";
    invalid.push($("app-applied-on"));
  }
  const url = $("app-job-url");
  if (url.value) {
    let validUrl = !url.validity.typeMismatch;
    try {
      const parsed = new URL(url.value);
      validUrl = validUrl && ["http:", "https:"].includes(parsed.protocol) && !parsed.username && !parsed.password;
    } catch {
      validUrl = false;
    }
    if (!validUrl) {
      $("app-job-url-error").textContent = "Enter a complete HTTP or HTTPS job URL without credentials.";
      invalid.push(url);
    }
  }
  for (const field of invalid) field.setAttribute("aria-invalid", "true");
  if (invalid.length) invalid[0].focus();
  return invalid.length === 0;
}

async function reloadApplicationEditor() {
  const jobId = state.applicationEditor.jobId;
  if (!jobId) return;
  try {
    const detail = await fetchJson(`/api/jobs/${jobId}`);
    const job = detail.job;
    state.jobs.set(jobId, job);
    openApplicationEditor({ ...job, resume_available: (job.artifacts || []).includes("resume.pdf") }, state.applicationEditor.returnFocus);
  } catch (error) {
    $("application-editor-status").textContent = `The latest values could not be loaded. ${String(error.message || error)}`;
    $("application-editor-status").classList.add("error");
  }
}

async function submitApplicationEditor(event) {
  event.preventDefault();
  if (state.applicationEditor.submitting || !validateApplicationEditor()) return;
  state.applicationEditor.submitting = true;
  const button = $("save-application-editor-dialog");
  button.disabled = true;
  button.textContent = "Saving…";
  try {
    const applied = $("app-status").value === "applied";
    const entry = await fetchJson(`/api/jobs/${state.applicationEditor.jobId}/application`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: $("app-status").value,
        applied_on: applied ? $("app-applied-on").value || null : null,
        job_url: $("app-job-url").value.trim() || null,
        notes: $("app-notes").value.trim(),
        revision: state.applicationEditor.revision,
      }),
    });
    upsertApplication(entry);
    renderApplicationsDashboard();
    if (state.currentDetail && state.currentDetail.job_id === entry.job_id) renderApplicationSummary(state.currentDetail);
    closeApplicationEditorDialog();
  } catch (error) {
    const status = $("application-editor-status");
    status.classList.add("error");
    if (error.status === 409) {
      status.textContent = "This record changed in another view. Reload the latest values before saving.";
      $("reload-application-editor").hidden = false;
      $("reload-application-editor").focus();
    } else {
      status.textContent = `Changes were not saved. ${String(error.message || error)}`;
    }
  } finally {
    state.applicationEditor.submitting = false;
    button.disabled = false;
    button.textContent = "Save changes";
  }
}

function openApplicationsDashboard() {
  state.workspaceMode = "applications";
  showMobileView("detail");
  renderDetailState();
  fetchApplications();
}

function renderApplicationSummary(job) {
  const application = job.application || { status: "not_applied", revision: 0 };
  const host = $("job-application-card");
  clear($("job-application-status"));
  $("job-application-status").appendChild(applicationBadge(application.status));
  $("job-application-date").textContent = application.applied_on || "No application date";
  const link = $("job-application-url");
  link.hidden = !application.job_url;
  if (application.job_url) link.href = application.job_url;
  else link.removeAttribute("href");
  $("job-application-notes").textContent = application.notes || "Add a job URL or notes when you track this application.";
  $("edit-job-application").onclick = () => openApplicationEditor({ ...job, application }, $("edit-job-application"));
  host.hidden = job.source !== "web" || job.application_tracking_available === false;
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

function renderStages(job) {
  const list = $("stage-list");
  clear(list);
  let completed = 0;
  let applicable = 0;
  for (const name of STAGE_NAMES) {
    const status = stageStatus(name, job);
    if (status !== "skipped") applicable += 1;
    if (status === "done") completed += 1;
    const item = el("li", `stage-item ${status}`);
    item.appendChild(el("span", "stage-marker", "✓"));
    item.appendChild(el("strong", null, name));
    item.appendChild(el("small", null, status === "active" ? "Active" : status === "done" ? "Done" : status === "skipped" ? "Not used" : ""));
    list.appendChild(item);
  }
  $("progress-summary").textContent = `${completed} of ${applicable} complete`;
}

function renderVerbose(job) {
  const host = $("verbose-detail");
  clear(host);
  const notes = (state.events.get(job.job_id) || []).filter((event) => !["stage_started", "stage_completed"].includes(event.kind));
  if (!notes.length) return;
  const details = el("details", "verbose");
  details.appendChild(el("summary", null, "Retries, warnings, and technical details"));
  const body = el("div", "verbose-body");
  const lines = notes.map((note) => {
    const prefix = note.stage ? `${note.stage}: ` : "";
    const attempt = note.attempt ? ` (attempt ${note.attempt})` : "";
    return `${prefix}${note.message || note.kind}${attempt}`;
  });
  body.textContent = lines.join("\n");
  details.appendChild(body);
  host.appendChild(details);
}

function renderPreview(job) {
  const frame = $("preview");
  const pending = $("preview-pending");
  const jsonView = $("preview-json");
  const hasPdf = job.artifacts.includes("resume.pdf");
  const hasJson = job.artifacts.includes("tailored.json");
  frame.hidden = true;
  jsonView.hidden = true;
  pending.hidden = false;
  if (job.state === "completed" && hasPdf) {
    const src = `/api/jobs/${job.job_id}/files/resume.pdf?download=0`;
    if (!frame.src.endsWith(src)) frame.src = src;
    frame.hidden = false;
    pending.hidden = true;
  } else if (job.state === "completed" && hasJson) {
    pending.hidden = true;
    renderTailoredJson(job.job_id);
  }
  $("dl-pdf-top").hidden = !hasPdf;
  if (hasPdf) $("dl-pdf-top").href = `/api/jobs/${job.job_id}/files/resume.pdf?download=0`;
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
    const directory = state.meta && state.meta.directory_labels ? state.meta.directory_labels.pdf_dir : "resumepdfs";
    location.textContent = `Application PDF: ${directory}/${job.pdf_library_name}`;
  }
}

function activateTab(name, focus = true) {
  if (!TAB_NAMES.includes(name)) return;
  state.activeTab = name;
  for (const tabName of TAB_NAMES) {
    const tab = $(`tab-${tabName}`);
    const panel = $(`panel-${tabName}`);
    const active = tabName === name;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    panel.hidden = !active;
  }
  if (focus) $(`tab-${name}`).focus();
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

function openJobDialog() {
  const dialog = $("new-job-dialog");
  if (!dialog.open) dialog.showModal();
  requestAnimationFrame(() => formFields.company.focus());
}

function closeJobDialog() {
  const dialog = $("new-job-dialog");
  if (dialog.open) dialog.close();
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
  const button = $("add-btn");
  const status = $("enqueue-status");
  button.disabled = true;
  button.textContent = "Adding…";
  status.textContent = "Adding the job to the queue.";
  try {
    const result = await fetchJson("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        company: formFields.company.value.trim(),
        role: formFields.role.value.trim(),
        jd_text: formFields.jd.value.trim(),
        bridge_skills: $("bridge-skills").checked,
        research_company: $("research-company").checked,
        no_pdf: $("no-pdf").checked,
      }),
    });
    $("job-form").reset();
    if (state.meta && state.meta.pdf_available === false) lockSkipPdf();
    touchedFields.clear();
    for (const name of Object.keys(formFields)) validateField(name);
    status.textContent = "Added to the queue.";
    closeJobDialog();
    await loadJobData();
    selectJob(result.job_id, { reveal: true });
  } catch (error) {
    status.textContent = `The job was not added. ${String(error.message || error)}`;
  } finally {
    state.submitting = false;
    button.disabled = false;
    button.textContent = "Add to queue";
  }
}

/* Live updates */

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
      fetchDetail(event.job_id).then(() => {
        if (kind === "job_completed" && state.currentDetail && state.currentDetail.job_id === event.job_id && (state.currentDetail.artifacts || []).includes("resume.pdf")) {
          activateTab("preview", false);
        }
      });
    }
    if (state.workspaceMode === "applications") fetchApplications().catch(() => {});
    return;
  }
  if (kind === "job_application_updated" && event.data) {
    upsertApplication(event.data);
    renderApplicationsDashboard();
    if (event.job_id === state.selectedId && state.currentDetail) renderApplicationSummary(state.currentDetail);
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
    renderStages(job);
    renderVerbose(job);
    $("detail-stage").textContent = job.current_stage || "Processing";
  }
}

function openStream() {
  const source = new EventSource("/api/events");
  source.onopen = () => loadAll();
  source.onerror = () => { /* EventSource reconnects and loadAll runs on the next open. */ };
  const kinds = ["queue_changed", "job_started", "stage_started", "stage_completed", "stage_retry", "stage_detail", "stage_warning", "job_action_required", "job_completed", "job_failed", "job_application_updated", "tracker_changed"];
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

function showMobileView(name) {
  document.body.dataset.mobileView = name;
  requestAnimationFrame(() => {
    if (name === "jobs") $("show-jobs-btn").focus();
    else $("main").focus();
  });
}

function bindEvents() {
  const openers = ["header-new-job", "rail-new-job", "empty-new-job", "add-jd-action", "apps-empty-new-job"];
  for (const id of openers) $(id).addEventListener("click", openJobDialog);
  $("close-job-dialog").addEventListener("click", closeJobDialog);
  $("cancel-job-dialog").addEventListener("click", closeJobDialog);
  $("job-form").addEventListener("submit", submitJob);
  $("review-removals-btn").addEventListener("click", openRecoveryDialog);
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
  $("header-apps").addEventListener("click", openApplicationsDashboard);
  $("rail-applications").addEventListener("click", openApplicationsDashboard);
  $("show-jobs-btn").addEventListener("click", () => showMobileView("jobs"));
  $("hide-jobs-btn").addEventListener("click", () => showMobileView("detail"));
  $("detail-back-btn").addEventListener("click", () => showMobileView("jobs"));
  $("retry-jobs-btn").addEventListener("click", loadJobData);
  $("retry-detail-btn").addEventListener("click", () => state.selectedId && fetchDetail(state.selectedId));
  $("pause-btn").addEventListener("click", () => {
    if (state.queue && state.queue.state === "paused") resumeQueue();
    else pauseQueue();
  });

  $("filter-queue").addEventListener("click", () => { state.listFilter = "queue"; renderJobLists(); });
  $("filter-recent").addEventListener("click", () => { state.listFilter = "recent"; renderJobLists(); });
  $("close-application-editor-dialog").addEventListener("click", closeApplicationEditorDialog);
  $("cancel-application-editor-dialog").addEventListener("click", closeApplicationEditorDialog);
  $("application-editor-form").addEventListener("submit", submitApplicationEditor);
  $("app-status").addEventListener("change", () => syncAppliedDateField({ fillDefault: true }));
  $("reload-application-editor").addEventListener("click", reloadApplicationEditor);
  $("application-editor-dialog").addEventListener("close", () => {
    const target = state.applicationEditor.returnFocus;
    if (target && target.isConnected) target.focus();
  });
  $("apps-search").addEventListener("input", () => {
    state.applications.search = $("apps-search").value;
    renderApplicationsDashboard();
  });
  $("apps-filter").addEventListener("change", () => {
    state.applications.filter = $("apps-filter").value;
    renderApplicationsDashboard();
  });
  $("apps-retry-btn").addEventListener("click", fetchApplications);
  $("apps-clear-filters").addEventListener("click", () => {
    state.applications.search = "";
    state.applications.filter = "all";
    $("apps-search").value = "";
    $("apps-filter").value = "all";
    renderApplicationsDashboard();
    $("apps-search").focus();
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
    if (job && job.state === "running") $("detail-elapsed").textContent = formatElapsed(job.started_at, job.finished_at);
  }, 1000);
}

function boot() {
  bindEvents();
  renderDetailState();
  renderJobLists();
  loadAll();
  openStream();
  startTicker();
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
