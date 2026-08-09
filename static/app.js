/* ATS Resume Tailor web client.
   One EventSource, explicit async states, and text-only rendering for untrusted data. */

"use strict";

const STAGE_NAMES = [
  "Preflight",
  "Parse job description",
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
const BRIDGE_INDEX = 5;
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

function stageStatus(stageName, job) {
  const index = STAGE_NAMES.indexOf(stageName);
  if (index === BRIDGE_INDEX && job.options && !job.options.bridge_skills) return "skipped";
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
    throw new Error(detail);
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
    const active = jobs.find((job) => job.active);
    const newest = jobs.find((job) => job.state === "completed" || job.state === "failed");
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
    .filter((job) => job.state === "completed" || job.state === "failed")
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
  $("detail-empty").hidden = state.detailStatus !== "empty";
  $("detail-loading").hidden = state.detailStatus !== "loading";
  $("detail-error").hidden = state.detailStatus !== "error";
  $("detail-body").hidden = state.detailStatus !== "success";
  $("detail-error-copy").textContent = state.detailError;
}

function selectJob(jobId, { reveal = true } = {}) {
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
  if (changed) state.activeTab = job && job.state === "completed" && job.artifacts.includes("resume.pdf") ? "preview" : "progress";
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
  badge.textContent = job.state;

  const stage = job.current_stage || (job.state === "queued" ? "Waiting to start" : job.state === "completed" ? "Tailoring complete" : job.state === "failed" ? "Run stopped" : "Preparing");
  $("detail-stage").textContent = stage;
  $("detail-elapsed").textContent = job.started_at ? formatElapsed(job.started_at, job.finished_at) : "—";
  $("detail-position").textContent = job.queue_position ? `#${job.queue_position}` : job.active ? "Active" : "—";
  $("detail-output").textContent = job.artifacts && job.artifacts.length ? `${job.artifacts.length} ${job.artifacts.length === 1 ? "file" : "files"}` : "Pending";
  $("detail-message").hidden = !job.message;
  $("detail-message").textContent = job.message || "";
  $("detail-export-warning").hidden = !job.export_warning;
  $("detail-export-warning").textContent = job.export_warning || "";
  renderStages(job);
  renderVerbose(job);
  renderPreview(job);
  renderFiles(job);
  activateTab(state.activeTab, false);
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
  if (kind === "job_started" || kind === "job_completed" || kind === "job_failed") {
    loadJobData().catch(() => {});
    if (event.job_id === state.selectedId) fetchDetail(event.job_id);
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
  const kinds = ["queue_changed", "job_started", "stage_started", "stage_completed", "stage_retry", "stage_detail", "stage_warning", "job_completed", "job_failed", "tracker_changed"];
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
  const openers = ["header-new-job", "rail-new-job", "empty-new-job", "add-jd-action"];
  for (const id of openers) $(id).addEventListener("click", openJobDialog);
  $("close-job-dialog").addEventListener("click", closeJobDialog);
  $("cancel-job-dialog").addEventListener("click", closeJobDialog);
  $("job-form").addEventListener("submit", submitJob);
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
