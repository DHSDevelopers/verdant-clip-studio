/* ============================================================
   Verdant Clip Studio — frontend controller
   ============================================================ */

const S = {
  meta: null,
  jobs: [],
  settings: null,
  readiness: null,
  health: null,
  activeJobId: null,
  view: "studio",
  filter: "all",
  preset: null,
  sourceTab: "url",
  uploadFile: null,
  stream: null,
  streamJobId: null,
  monitorLog: {},
};

const STAGES = [
  { key: "download", label: "Acquire source", hint: "yt-dlp / upload / Drive" },
  { key: "transcribe", label: "Word-level transcript", hint: "Faster-Whisper or JSON3" },
  { key: "analyze", label: "Hook & score ranking", hint: "Gemini / NIM / vLLM" },
  { key: "metadata", label: "Metadata normalization", hint: "titles, captions, tags" },
  { key: "diarization", label: "Speaker analysis", hint: "pyannote (optional)" },
  { key: "render", label: "Smart framing & mux", hint: "faces, ASS, FFmpeg" },
  { key: "finalize", label: "Manifest & thumbnails", hint: "render_manifest.json" },
];

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function fmtClock(seconds) {
  const s = Math.max(0, Number(seconds) || 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

function fmtRange(a, b) {
  return `${fmtClock(a)} → ${fmtClock(b)}`;
}

function fmtDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function ago(value) {
  if (!value) return "";
  const diff = (Date.now() - new Date(value).getTime()) / 1000;
  if (Number.isNaN(diff)) return "";
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function toast(message, kind = "ok") {
  const node = document.createElement("div");
  node.className = `toast ${kind === "err" ? "err" : ""}`;
  node.innerHTML = `<span class="dot ${kind === "err" ? "off" : "on"}"></span><span>${esc(message)}</span>`;
  $("#toasts").appendChild(node);
  setTimeout(() => node.remove(), 5200);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  let data = null;
  const text = await res.text();
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (!res.ok) {
    const detail = data && (data.detail || data.message);
    throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`);
  }
  return data;
}

const STATUS_LABEL = {
  queued: "Queued",
  downloading: "Downloading",
  transcribing: "Transcribing",
  analyzing: "Analyzing",
  rendering: "Rendering",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

function statusBadge(status) {
  const running = ["queued", "downloading", "transcribing", "analyzing", "rendering"].includes(status);
  const cls = running ? (status === "queued" ? "queued" : "running") : status;
  const dot = running ? '<span class="dot"></span>' : "";
  return `<span class="badge ${cls}">${dot}${esc(STATUS_LABEL[status] || status)}</span>`;
}

function jobClips(job) {
  return Array.isArray(job && job.clips) ? job.clips : [];
}

function findJob(id) {
  return S.jobs.find((j) => j.id === id) || null;
}

function primaryThumb(job) {
  const clip = jobClips(job).find((c) => c.thumbnail_url);
  return clip ? clip.thumbnail_url : null;
}

function bestScore(job) {
  const scores = jobClips(job).map((c) => Number(c.viral_score) || 0).filter(Boolean);
  return scores.length ? Math.max(...scores) : null;
}

/* ------------------------------- boot ------------------------------- */

async function boot() {
  bindGlobalEvents();
  try {
    const [meta, jobs, settings, health, readiness] = await Promise.all([
      api("/api/meta"),
      api("/api/jobs"),
      api("/api/settings"),
      api("/api/health"),
      fetch("/api/ready").then((r) => r.json().catch(() => null)),
    ]);
    S.meta = meta;
    S.jobs = jobs.jobs || [];
    S.settings = settings;
    S.health = health;
    S.readiness = readiness;
    buildPresetPicker();
    buildRatioGrid();
    renderPresets();
    renderSettings();
    renderAll();
    updateSystemStatus();
    autoSelectJob();
  } catch (err) {
    toast(err.message || "Could not reach the backend.", "err");
  }
}

function autoSelectJob() {
  const running = S.jobs.find((j) => !["completed", "failed", "cancelled"].includes(j.status));
  if (running) {
    S.activeJobId = running.id;
    ensureStream(running.id);
    renderMonitor();
  } else if (S.jobs[0]) {
    S.activeJobId = S.jobs[0].id;
    renderMonitor();
  }
}

/* ------------------------------ routing ----------------------------- */

function setView(view) {
  S.view = view;
  $$(".view").forEach((node) => node.classList.add("hide"));
  const target = $(`#view-${view}`);
  if (target) target.classList.remove("hide");
  $$(".nav-item").forEach((btn) => btn.classList.toggle("active", btn.dataset.view === view));
  const labels = { studio: "Overview", jobs: "Jobs", presets: "Presets", settings: "Settings" };
  $("#crumb").textContent = labels[view] || "Studio";
  if (view === "studio") renderStudio();
  if (view === "jobs") renderJobs();
  if (view === "presets") renderPresets();
  if (view === "settings") renderSettings();
}

/* ------------------------------ render ------------------------------ */

function renderAll() {
  renderStudio();
  renderJobs();
  renderMonitor();
  $("#nav-job-count").textContent = String(S.jobs.length);
}

function renderStudio() {
  const clips = S.jobs.flatMap((job) => jobClips(job));
  const scores = clips.map((c) => Number(c.viral_score) || 0).filter(Boolean);
  const totalSeconds = clips.reduce((sum, c) => sum + (Number(c.duration) || 0), 0);
  const active = S.jobs.find((j) => !["completed", "failed", "cancelled"].includes(j.status));

  $("#stat-clips").textContent = String(clips.length);
  $("#stat-score").textContent = scores.length
    ? String(Math.round(scores.reduce((a, b) => a + b, 0) / scores.length))
    : "—";
  $("#stat-active").textContent = active ? STATUS_LABEL[active.status] || active.status : "Idle";
  $("#stat-active-foot").textContent = active ? `job ${active.id}` : "no job running";
  $("#stat-minutes").innerHTML = `${Math.round(totalSeconds / 60)}<span class="unit">min</span>`;
  $("#pill-jobs").innerHTML = active
    ? '<span class="dot on"></span><span>pipeline active</span>'
    : '<span class="dot"></span><span>idle</span>';

  const recent = S.jobs
    .filter((j) => j.status === "completed")
    .flatMap((j) => jobClips(j).map((c) => ({ ...c, jobId: j.id })))
    .slice(0, 8);
  const holder = $("#recent-clips");
  holder.innerHTML = recent.length
    ? recent.map((c) => clipCard(c, c.jobId)).join("")
    : emptyState(
        "No clips yet",
        "Configure a job with a video URL or upload to run the seven-stage pipeline.",
        '<button class="btn small primary" data-action="new-job">New clip job</button>'
      );
}

function renderJobs() {
  const list = $("#jobs-list");
  const running = ["queued", "downloading", "transcribing", "analyzing", "rendering"];
  const filtered = S.jobs.filter((job) => {
    if (S.filter === "all") return true;
    if (S.filter === "running") return running.includes(job.status);
    return job.status === S.filter;
  });
  $("#jobs-total").textContent = `${S.jobs.length} total`;

  if (!filtered.length) {
    list.innerHTML = emptyState(
      S.jobs.length ? "Nothing matches this filter" : "The queue is empty",
      S.jobs.length
        ? "Try a different job state."
        : "Start with a YouTube link, a local upload, or reuse a finished job.",
      '<button class="btn small primary" data-action="new-job">New clip job</button>'
    );
    return;
  }

  list.innerHTML = filtered.map((job) => {
    const clips = jobClips(job);
    const thumb = primaryThumb(job);
    const pct = job.progress ? Math.round(Number(job.progress.percent) || 0) : (job.status === "completed" ? 100 : 0);
    const title = clips[0] && (clips[0].title_en || clips[0].title)
      ? clips[0].title_en || clips[0].title
      : job.url || job.upload_filename || "Uploaded source";
    const score = bestScore(job);
    return `
      <div class="job-row" data-job="${esc(job.id)}">
        <div class="job-thumb">${thumb ? `<img src="${esc(thumb)}" alt="" loading="lazy" />` : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M8 5l11 7-11 7z"/></svg>`}</div>
        <div class="job-title">
          <div class="t">${esc(title)}</div>
          <div class="u">${esc(job.id)} · ${esc(ago(job.updated_at))}</div>
          ${running.includes(job.status) ? `<div class="mini-bar"><i style="width:${pct}%"></i></div>` : ""}
        </div>
        <div class="job-cell hide-sm"><span class="lbl">Status</span>${statusBadge(job.status)}</div>
        <div class="job-cell hide-sm"><span class="lbl">Clips</span>${clips.length || "—"}</div>
        <div class="job-cell hide-sm"><span class="lbl">Score</span>${score || "—"}</div>
        <div class="job-cell hide-sm"><span class="lbl">Created</span>${esc(fmtDate(job.created_at))}</div>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" style="color:var(--sage-dim)"><path d="M9 6l6 6-6 6"/></svg>
      </div>`;
  }).join("");
}

function clipCard(clip, jobId) {
  const meta = clip.metadata || {};
  const thumb = clip.thumbnail_url;
  const score = clip.viral_score != null ? clip.viral_score : meta.viral_score;
  const title = clip.title_en || clip.title || meta.title_inggris || "Untitled clip";
  return `
    <article class="clip-card" data-clip="${esc(jobId)}:${esc(clip.rank)}">
      <div class="clip-thumb">
        ${thumb ? `<img src="${esc(thumb)}" alt="" loading="lazy" />` : ""}
        <div class="play"><span><svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5l11 7-11 7z"/></svg></span></div>
        ${score != null ? `<span class="score">${esc(score)}</span>` : ""}
        <span class="dur">${fmtClock(clip.duration)}</span>
      </div>
      <div class="clip-info">
        <div class="rank">RANK ${String(clip.rank).padStart(2, "0")}</div>
        <div class="title">${esc(title)}</div>
        <div class="time">${fmtRange(clip.start_time, clip.end_time)}</div>
      </div>
    </article>`;
}

function emptyState(title, body, action = "") {
  return `<div class="empty" style="grid-column:1/-1">
    <div class="icon"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 5.5h16v13H4z"/><path d="M9.5 9l5 3-5 3z"/></svg></div>
    <h4>${esc(title)}</h4><p>${esc(body)}</p>${action}
  </div>`;
}

/* ----------------------------- monitor ------------------------------ */

function stageIndexFromProgress(progress) {
  if (!progress) return -1;
  const map = {
    download: 0, transcribe: 1, analyze: 2, metadata: 3,
    diarization: 4, render: 5, done: 6, error: -1, cancelled: -1,
  };
  return map[progress.step] != null ? map[progress.step] : -1;
}

function renderMonitor() {
  const job = findJob(S.activeJobId);
  const stepsNode = $("#monitor-steps");
  const logNode = $("#monitor-log");
  $("#btn-open-detail").disabled = !job;

  if (!job) {
    $("#monitor-job").textContent = "—";
    $("#monitor-badge").outerHTML = '<span class="badge" id="monitor-badge">idle</span>';
    $("#monitor-label").textContent = "Nothing rendering";
    $("#monitor-pct").textContent = "0%";
    $("#monitor-bar").style.width = "0%";
    $("#monitor-step").textContent = "stage 0 / 7";
    $("#monitor-eta").textContent = "—";
    stepsNode.innerHTML = STAGES.map((s, i) => stepRow(s, i, "idle")).join("");
    return;
  }

  const progress = job.progress || {};
  const pct = Math.round(Number(progress.percent) || (job.status === "completed" ? 100 : 0));
  const activeIdx = stageIndexFromProgress(progress);
  const done = job.status === "completed";
  const failed = job.status === "failed" || job.status === "cancelled";

  $("#monitor-job").textContent = `${job.id} · ${ago(job.updated_at)}`;
  const badge = $("#monitor-badge");
  badge.className = `badge ${["completed", "failed", "cancelled"].includes(job.status) ? job.status : "running"}`;
  badge.innerHTML = ["queued", "downloading", "transcribing", "analyzing", "rendering"].includes(job.status)
    ? '<span class="dot"></span>' + esc(STATUS_LABEL[job.status])
    : esc(STATUS_LABEL[job.status] || job.status);

  $("#monitor-label").textContent = progress.message || (job.error ? job.error : STATUS_LABEL[job.status]);
  $("#monitor-pct").textContent = `${pct}%`;
  $("#monitor-bar").style.width = `${Math.min(100, pct)}%`;
  $("#monitor-step").textContent = `stage ${activeIdx + 1 > 0 ? activeIdx + 1 : 0} / 7`;
  $("#monitor-eta").textContent = job.error ? "error" : (done ? "complete" : STATUS_LABEL[job.status] || "");
  $("#monitor-sub").textContent = `${jobClips(job).length} clip(s) · ${job.config && job.config.clips ? job.config.clips : "—"} requested`;

  stepsNode.innerHTML = STAGES.map((s, i) => {
    let state = "idle";
    if (done) state = "done";
    else if (failed && i === Math.max(0, activeIdx)) state = "active";
    else if (i < activeIdx) state = "done";
    else if (i === activeIdx) state = "active";
    return stepRow(s, i, state);
  }).join("");

  const lines = (job.log || []).slice(-120);
  logNode.innerHTML = lines.length
    ? lines.map((line) => {
        const m = String(line).match(/^\[([^\]]+)\]\s*(.*)$/);
        const stage = m ? m[1] : "log";
        const msg = m ? m[2] : line;
        const cls = /error|fail/i.test(stage + msg) ? "err" : "ok";
        return `<div class="line"><span class="t">${esc(stage.slice(0, 10))}</span><span class="m ${cls}">${esc(msg)}</span></div>`;
      }).join("")
    : `<div class="line"><span class="t">--:--</span><span class="m dim">Waiting for the job to report a stage.</span></div>`;
  logNode.scrollTop = logNode.scrollHeight;
}

function stepRow(stage, index, state) {
  const label = state === "active" ? "running" : state === "done" ? "done" : "pending";
  return `<div class="step ${state}">
    <span class="idx">${String(index + 1).padStart(2, "0")}</span>
    <span>${esc(stage.label)} <span class="dim" style="font-size:10px">· ${esc(stage.hint)}</span></span>
    <span class="state">${label}</span>
  </div>`;
}

/* ------------------------------ presets ----------------------------- */

function renderPresets() {
  const holder = $("#presets-grid");
  if (!holder || !S.meta) return;
  const icons = [
    '<path d="M6 4h12v16H6z"/><path d="M9 8h6M9 12h6M9 16h3"/>',
    '<path d="M12 3l2.6 6.2L21 12l-6.4 2.8L12 21l-2.6-6.2L3 12l6.4-2.8z"/>',
    '<path d="M12 4a3 3 0 013 3v4a3 3 0 01-6 0V7a3 3 0 013-3z"/><path d="M5 11a7 7 0 0014 0M12 18v3"/>',
    '<rect x="6" y="3" width="12" height="18" rx="2"/><path d="M10 7h4M10 11h4M10 15h4"/>',
  ];
  holder.innerHTML = S.meta.presets.map((preset, i) => {
    const s = preset.settings;
    const chips = [
      `${s.clips} clips`,
      `${s.ratio}`,
      `${s.words_per_sub}w captions`,
      s.hook_v2 ? "multi-hook" : `${s.hook_duration}s hook`,
      s.camera_switch ? "camera switch" : s.use_broll ? "B-roll" : "no B-roll",
      s.use_auto_bgm ? `BGM ${s.bgm_mode || "ducking"}` : "no BGM",
    ];
    return `<article class="preset-card">
      <div class="preset-top">
        <div>
          <div class="preset-name">${esc(preset.name)}</div>
          <div class="preset-tagline">${esc(preset.tagline)}</div>
        </div>
        <div class="preset-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">${icons[i % icons.length]}</svg></div>
      </div>
      <div class="chips">${chips.map((c) => `<span class="chip">${esc(c)}</span>`).join("")}</div>
      <button class="btn small" data-preset="${esc(preset.id)}">Use preset</button>
    </article>`;
  }).join("");
}

function buildPresetPicker() {
  const holder = $("#preset-picker");
  if (!holder || !S.meta) return;
  holder.innerHTML = S.meta.presets.map((preset) => `
    <button type="button" class="preset-opt" data-pick-preset="${esc(preset.id)}">
      <strong>${esc(preset.name)}</strong>
      <span>${preset.settings.clips} clips · ${esc(preset.settings.ratio)}</span>
    </button>`).join("") + `
    <button type="button" class="preset-opt" data-pick-preset="custom">
      <strong>Custom</strong><span>all defaults</span>
    </button>`;
}

function applyPreset(id) {
  if (!S.meta) return;
  S.preset = id === "custom" ? null : id;
  const preset = S.meta.presets.find((p) => p.id === id);
  $$("[data-pick-preset]").forEach((b) => b.classList.toggle("active", b.dataset.pickPreset === id));

  if (preset) {
    const s = preset.settings;
    setValue("#job-clips", s.clips ?? 7);
    $("#clips-val").textContent = String(s.clips ?? 7);
    chooseRatio(s.ratio || "9:16");
    setValue("#job-words", s.words_per_sub ?? 5);
    setValue("#job-hook", s.hook_duration ?? 3);
    setValue("#job-font", s.font_style || "HORMOZI");
    setChecked("#job-hook-v2", Boolean(s.hook_v2));
    setChecked("#job-hook-glitch", true);
    setChecked("#job-karaoke", s.use_karaoke_effect !== false);
    setChecked("#job-broll", Boolean(s.use_broll));
    setChecked("#job-bgm", s.use_auto_bgm !== false);
    setChecked("#job-trim", s.no_segment_trim !== true);
    setChecked("#job-camera", Boolean(s.camera_switch));
    setValue("#job-bgm-mode", s.bgm_mode || "ducking");
    setValue("#job-naming", s.output_naming || "highlight_rank_{rank}_ready.mp4");
    setValue("#job-crf", s.video_crf ?? 20);
    setValue("#job-cq", s.video_cq ?? 23);
    setValue("#job-render-height", String(s.render_height || "1080"));
    setValue("#job-speakers", String(s.diarization_speakers || "auto"));
    $("#job-estimate").textContent = `${s.clips} clips · ${s.ratio} · ~${s.clips * 20}s+ render`;
  }
  updateEstimate();
}

/* ------------------------------ settings ---------------------------- */

function renderSettings() {
  const st = S.settings;
  if (!st) return;
  const setKey = (id, val, label) => {
    const node = $(id);
    if (!node) return;
    node.textContent = val ? (label || "Configured") : "Not set";
    node.className = `v ${val ? "" : "off"}`;
  };
  setKey("#key-google", st.google_api_key_set);
  setKey("#key-nvidia", st.nvidia_api_key_set);
  setKey("#key-pexels", st.pexels_api_key_set);
  setKey("#key-hf", st.hf_token_set);
  $("#vllm-model").textContent = st.vllm_model || "—";
  $("#vllm-tokens").textContent = st.local_max_tokens ? String(st.local_max_tokens) : "—";

  setValue("#set-clips", st.default_clips);
  setValue("#set-ratio", st.default_ratio);
  setValue("#set-font", st.default_font_style);
  setValue("#set-provider", st.default_ai_provider);
  setValue("#set-whisper", st.default_whisper_model);
  setValue("#set-device", st.default_whisper_device);

  const checks = (S.readiness && S.readiness.checks) || {};
  $("#ready-badge").className = `badge ${S.readiness && S.readiness.ready ? "completed" : "failed"}`;
  $("#ready-badge").textContent = S.readiness && S.readiness.ready ? "ready" : "not ready";
  $("#ready-checks").innerHTML = Object.keys(checks).length
    ? Object.entries(checks).map(([key, ok]) =>
        `<div class="kv"><span class="k">${esc(key)}</span><span class="v ${ok ? "" : "off"}">${ok ? "available" : "missing"}</span></div>`
      ).join("")
    : `<div class="kv"><span class="k">probe</span><span class="v off">unavailable</span></div>`;
}

function updateSystemStatus() {
  const health = S.health || {};
  const ready = S.readiness || {};
  const settings = S.settings || {};
  const mark = (dotId, textId, ok, text) => {
    const dot = $(dotId);
    if (dot) dot.className = `dot ${ok ? "on" : "off"}`;
    const node = $(textId);
    if (node) node.textContent = text;
  };
  mark("#dot-ffmpeg", "#sys-ffmpeg", health.ffmpeg_available, health.ffmpeg_available ? "ready" : "missing");
  mark("#dot-gpu", "#sys-gpu", health.gpu_available, health.gpu_available ? "cuda" : "cpu");
  const providerReady = settings.google_api_key_set || settings.nvidia_api_key_set || settings.vllm_api_key_set;
  mark("#dot-provider", "#sys-provider", providerReady, providerReady ? "configured" : "missing");

  const pill = $("#pill-ready");
  pill.className = `pill ${ready.ready ? "good" : "warn"}`;
  pill.innerHTML = `<span class="dot ${ready.ready ? "on" : "off"}"></span><span>${ready.ready ? "renderer ready" : "renderer incomplete"}</span>`;
}

/* ------------------------------ detail ------------------------------ */

async function openJob(jobId) {
  S.activeJobId = jobId;
  try {
    const job = await api(`/api/jobs/${jobId}`);
    mergeJob(job);
    renderJobDetail(job);
    const dlg = $("#job-dialog");
    if (!dlg.open) dlg.showModal();
    if (!["completed", "failed", "cancelled"].includes(job.status)) ensureStream(job.id);
    renderMonitor();
    renderStudio();
  } catch (err) {
    toast(err.message, "err");
  }
}

function mergeJob(job) {
  const idx = S.jobs.findIndex((j) => j.id === job.id);
  if (idx >= 0) S.jobs[idx] = { ...S.jobs[idx], ...job };
  else S.jobs.unshift(job);
}

function renderJobDetail(job) {
  const clips = jobClips(job);
  const progress = job.progress || {};
  const pct = Math.round(Number(progress.percent) || (job.status === "completed" ? 100 : 0));
  const activeIdx = stageIndexFromProgress(progress);
  const done = job.status === "completed";

  $("#detail-title").textContent = clips[0] ? (clips[0].title_en || clips[0].title) : (job.url || job.upload_filename || "Clipping job");
  $("#detail-sub").textContent = `${job.id} · ${job.source} · ${fmtDate(job.created_at)}`;
  const badge = $("#detail-badge");
  badge.className = `badge ${["completed", "failed", "cancelled"].includes(job.status) ? job.status : "running"}`;
  badge.textContent = STATUS_LABEL[job.status] || job.status;
  $("#detail-percent").textContent = `${pct}%`;
  $("#detail-clips").textContent = String(clips.length);
  $("#detail-bar").style.width = `${pct}%`;
  $("#detail-created").textContent = fmtDate(job.created_at);
  $("#detail-ratio").textContent = (job.config && job.config.ratio) || "—";
  $("#detail-provider").textContent = (job.config && job.config.ai_provider) || "—";
  $("#detail-whisper").textContent = job.config ? `${job.config.whisper_model || "—"} · ${job.config.whisper_device || "—"}` : "—";
  $("#detail-clip-count").textContent = clips.length ? `${clips.length} export(s)` : "";

  $("#detail-steps").innerHTML = STAGES.map((s, i) => {
    let state = "idle";
    if (done) state = "done";
    else if (i < activeIdx) state = "done";
    else if (i === activeIdx) state = "active";
    return stepRow(s, i, state);
  }).join("");

  const errorNode = $("#detail-error");
  if (job.error) {
    errorNode.classList.remove("hide");
    errorNode.textContent = job.error;
  } else {
    errorNode.classList.add("hide");
  }

  $("#detail-clips-grid").innerHTML = clips.length
    ? clips.map((c) => clipCard(c, job.id)).join("")
    : emptyState(
        job.status === "completed" ? "No successful clips" : "Clips appear when rendering completes",
        job.status === "completed"
          ? "The render manifest reported no successful exports. Check the log below."
          : "The pipeline streams each stage here while it works."
      );

  const logNode = $("#detail-log");
  logNode.innerHTML = (job.log || []).length
    ? job.log.map((line) => {
        const m = String(line).match(/^\[([^\]]+)\]\s*(.*)$/);
        return `<div class="line"><span class="t">${esc((m ? m[1] : "log").slice(0, 10))}</span><span class="m ${/error|fail/i.test(line) ? "err" : ""}">${esc(m ? m[2] : line)}</span></div>`;
      }).join("")
    : `<div class="line"><span class="t">--:--</span><span class="m dim">No log entries yet.</span></div>`;
  logNode.scrollTop = logNode.scrollHeight;

  const cancel = $("#btn-cancel-job");
  cancel.disabled = ["completed", "failed", "cancelled"].includes(job.status);
  cancel.textContent = job.cancel_requested ? "Cancelling…" : "Cancel job";
}

/* ------------------------------- SSE -------------------------------- */

function ensureStream(jobId) {
  if (S.streamJobId === jobId && S.stream) return;
  if (S.stream) S.stream.close();
  S.streamJobId = jobId;
  const source = new EventSource(`/api/jobs/${jobId}/status`);
  S.stream = source;
  source.onmessage = (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }
    if (data.type === "deleted") {
      source.close();
      S.stream = null;
      S.streamJobId = null;
      return;
    }
    const job = findJob(jobId);
    if (!job) return;
    job.status = data.status || job.status;
    if (data.progress) job.progress = data.progress;
    if (data.error !== undefined) job.error = data.error;
    job.cancel_requested = Boolean(data.cancel_requested);
    if (Array.isArray(data.log_tail)) {
      const existing = Array.isArray(job.log) ? job.log : [];
      data.log_tail.forEach((line) => { if (!existing.includes(line)) existing.push(line); });
      job.log = existing;
    }
    if (["completed", "failed", "cancelled"].includes(data.status)) {
      job.clips = data.clips || job.clips;
      source.close();
      S.stream = null;
      S.streamJobId = null;
      api(`/api/jobs/${jobId}`).then((full) => {
        mergeJob(full);
        if ($("#job-dialog").open && S.activeJobId === jobId) renderJobDetail(full);
        renderAll();
        if (full.status === "completed") toast(`Job ${jobId} completed · ${jobClips(full).length} clips`);
        else if (full.status === "failed") toast(full.error || "Render failed.", "err");
      }).catch(() => renderAll());
    } else {
      renderMonitor();
      if ($("#job-dialog").open && S.activeJobId === jobId) renderJobDetail(job);
      $("#nav-job-count").textContent = String(S.jobs.length);
      renderStudio();
    }
  };
  source.onerror = () => {
    source.close();
    S.stream = null;
    S.streamJobId = null;
  };
}

/* ----------------------------- clip modal --------------------------- */

function openClip(jobId, rank) {
  const job = findJob(jobId);
  if (!job) return;
  const clip = jobClips(job).find((c) => String(c.rank) === String(rank));
  if (!clip) return;
  const meta = clip.metadata || {};
  const title = clip.title_en || clip.title || meta.title_inggris || "Clip";
  $("#clip-title").textContent = title;
  $("#clip-sub").textContent = `Job ${jobId} · rank ${clip.rank}`;
  $("#clip-score").textContent = clip.viral_score != null ? `${clip.viral_score} / 100` : "unscored";
  $("#clip-time").textContent = `${fmtRange(clip.start_time, clip.end_time)} · ${fmtClock(clip.duration)}`;
  $("#clip-hook").textContent = `${fmtRange(meta.hook_start_time, meta.hook_end_time)} · ${meta.bgm_mood || "no bgm"}`;
  $("#clip-title-en").textContent = clip.title_en || meta.title_inggris || "—";
  $("#clip-title-id").textContent = clip.title || meta.title_indonesia || "—";
  $("#clip-caption").value = meta.tiktok_caption_final || meta.tiktok_caption || "";
  $("#clip-desc").value = meta.youtube_description_final || "";
  $("#clip-tags").textContent = meta.hastag || "—";
  $("#clip-path").textContent = clip.filename || "";
  const exportLink = $("#clip-export");
  exportLink.href = clip.download_url;
  exportLink.setAttribute("download", clip.filename || "clip.mp4");
  const video = $("#clip-video");
  video.src = clip.download_url;
  video.load();
  $("#clip-dialog").showModal();
}

async function copyText(text, label) {
  try {
    await navigator.clipboard.writeText(text || "");
    toast(`${label} copied.`);
  } catch {
    toast("Clipboard unavailable; select the text manually.", "err");
  }
}

/* ----------------------------- new job ------------------------------ */

function buildRatioGrid() {
  const holder = $("#ratio-grid");
  const ratios = S.meta ? S.meta.ratios : ["9:16", "16:9", "1:1", "3:4", "4:5"];
  holder.innerHTML = ratios.map((r) => {
    const [w, h] = r.split(":").map(Number);
    const maxW = 16;
    const maxH = 18;
    const scale = Math.min(maxW / w, maxH / h);
    return `<button type="button" class="ratio-opt" data-ratio="${r}">
      <span class="shape" style="width:${Math.round(w * scale)}px;height:${Math.round(h * scale)}px"></span>${r}
    </button>`;
  }).join("");
  chooseRatio("9:16");
}

function chooseRatio(ratio) {
  $$("[data-ratio]").forEach((b) => b.classList.toggle("active", b.dataset.ratio === ratio));
}

function selectedRatio() {
  const active = $("[data-ratio].active");
  return active ? active.dataset.ratio : "9:16";
}

function openNewJob(presetId) {
  $("#job-error").classList.add("hide");
  const dlg = $("#new-job-dialog");
  if (!dlg.open) dlg.showModal();
  if (presetId && S.meta) applyPreset(presetId);
  else if (S.preset) applyPreset(S.preset);
  updateEstimate();
}

function setValue(sel, value) {
  const node = $(sel);
  if (node && value != null) node.value = value;
}

function setChecked(sel, checked) {
  const node = $(sel);
  if (node) node.checked = Boolean(checked);
}

function updateEstimate() {
  const clips = Number($("#job-clips").value) || 7;
  const words = Number($("#job-words").value) || 5;
  $("#clips-val").textContent = String(clips);
  $("#job-estimate").textContent = `${clips} clip(s) · ${selectedRatio()} · ${words}w captions · ≥ ${clips * 20}s render`;
}

async function uploadSelectedFile() {
  if (!S.uploadFile) return null;
  const state = $("#upload-state");
  state.textContent = `Uploading ${S.uploadFile.name}…`;
  const body = new FormData();
  body.append("file", S.uploadFile);
  const result = await api("/api/upload", { method: "POST", body });
  state.textContent = `Uploaded ${result.filename} · ${result.size_mb} MB`;
  return result.filename;
}

async function submitJob(event) {
  event.preventDefault();
  const btn = $("#btn-start-job");
  const errorNode = $("#job-error");
  errorNode.classList.add("hide");
  btn.disabled = true;
  btn.textContent = "Starting…";

  try {
    let uploadFilename = null;
    if (S.sourceTab === "upload") {
      if (!S.uploadFile) throw new Error("Choose a video file to upload first.");
      uploadFilename = await uploadSelectedFile();
    }

    const payload = {
      source: $("#job-source").value,
      clips: Number($("#job-clips").value) || 7,
      ratio: selectedRatio(),
      words_per_sub: Number($("#job-words").value) || 5,
      hook_duration: Number($("#job-hook").value) || 3,
      font_style: $("#job-font").value,
      use_hook_glitch: $("#job-hook-glitch").checked,
      hook_v2: $("#job-hook-v2").checked,
      use_karaoke_effect: $("#job-karaoke").checked,
      use_broll: $("#job-broll").checked,
      use_auto_bgm: $("#job-bgm").checked,
      bgm_mode: $("#job-bgm-mode").value,
      no_segment_trim: !$("#job-trim").checked,
      output_naming: $("#job-naming").value || null,
      ai_provider: $("#job-provider").value,
      whisper_model: $("#job-whisper").value || "large-v3",
      whisper_device: $("#job-device").value,
      source_height: $("#job-source-height").value,
      render_height: $("#job-render-height").value,
      video_crf: Number($("#job-crf").value),
      video_cq: Number($("#job-cq").value),
      video_scale_algo: $("#job-scale").value,
      face_detector: $("#job-face").value,
      diarization_speakers: $("#job-speakers").value || "auto",
      static_crop: $("#job-static").checked,
      video_sharpen: $("#job-sharpen").checked,
      use_camera_switch: $("#job-camera").checked,
      load_gemini_json: $("#job-bypass").checked,
      preset: S.preset,
    };

    const vllmModel = $("#job-vllm-model").value.trim();
    if (vllmModel) payload.vllm_model = vllmModel;
    const watermark = $("#job-watermark").value.trim();
    if (watermark) {
      payload.watermark = true;
      payload.text = watermark;
      payload.position = $("#job-watermark-position").value;
    }

    if (S.sourceTab === "url") {
      const url = $("#job-url").value.trim();
      if (!url) throw new Error("Enter a video URL.");
      payload.url = url;
    } else if (S.sourceTab === "upload") {
      payload.upload_filename = uploadFilename;
      payload.source = "youtube";
    } else {
      const reuse = $("#job-reuse").value.trim();
      if (!reuse) throw new Error("Enter the job ID to reuse.");
      payload.reuse_job_id = reuse;
      delete payload.load_gemini_json;
    }

    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    mergeJob(job);
    S.activeJobId = job.id;
    renderAll();
    $("#new-job-dialog").close();
    toast(`Job ${job.id} queued.`);
    renderMonitor();
    ensureStream(job.id);
    openJob(job.id);
    S.uploadFile = null;
  } catch (err) {
    errorNode.textContent = err.message || "Could not start the job.";
    errorNode.classList.remove("hide");
    errorNode.scrollIntoView({ block: "nearest", behavior: "smooth" });
  } finally {
    btn.disabled = false;
    btn.textContent = "Start clipping";
  }
}

/* ---------------------------- event wiring -------------------------- */

function bindGlobalEvents() {
  $$(".nav-item").forEach((btn) => btn.addEventListener("click", () => setView(btn.dataset.view)));
  $$("[data-view-link]").forEach((btn) => btn.addEventListener("click", () => setView(btn.dataset.viewLink)));

  document.addEventListener("click", (event) => {
    const action = event.target.closest("[data-action]");
    if (action && action.dataset.action === "new-job") openNewJob();

    const close = event.target.closest("[data-close]");
    if (close) {
      const dlg = document.getElementById(close.dataset.close);
      if (dlg) dlg.close();
    }

    const presetUse = event.target.closest("[data-preset]");
    if (presetUse) openNewJob(presetUse.dataset.preset);

    const pickPreset = event.target.closest("[data-pick-preset]");
    if (pickPreset) applyPreset(pickPreset.dataset.pickPreset);

    const ratio = event.target.closest("[data-ratio]");
    if (ratio) { chooseRatio(ratio.dataset.ratio); updateEstimate(); }

    const clip = event.target.closest("[data-clip]");
    if (clip) {
      const [jobId, rank] = clip.dataset.clip.split(":");
      openClip(jobId, rank);
    }

    const jobRow = event.target.closest("[data-job]");
    if (jobRow) openJob(jobRow.dataset.job);

    const filter = event.target.closest("[data-filter]");
    if (filter) {
      S.filter = filter.dataset.filter;
      $$("[data-filter]").forEach((b) => b.classList.toggle("active", b === filter));
      renderJobs();
    }

    const sourceTab = event.target.closest("[data-source-tab]");
    if (sourceTab) {
      S.sourceTab = sourceTab.dataset.sourceTab;
      $$("[data-source-tab]").forEach((b) => b.classList.toggle("active", b === sourceTab));
      $("#source-url").classList.toggle("hide", S.sourceTab !== "url");
      $("#source-upload").classList.toggle("hide", S.sourceTab !== "upload");
      $("#source-reuse").classList.toggle("hide", S.sourceTab !== "reuse");
    }
  });

  $("#job-clips").addEventListener("input", updateEstimate);
  $("#job-words").addEventListener("input", updateEstimate);
  $("#new-job-form").addEventListener("submit", submitJob);

  $("#job-file").addEventListener("change", (event) => {
    S.uploadFile = event.target.files[0] || null;
    if (S.uploadFile) $("#upload-state").textContent = `Selected ${S.uploadFile.name} (${(S.uploadFile.size / 1048576).toFixed(1)} MB)`;
  });

  $("#btn-open-detail").addEventListener("click", () => {
    if (S.activeJobId) openJob(S.activeJobId);
  });

  $("#btn-cancel-job").addEventListener("click", async () => {
    if (!S.activeJobId) return;
    try {
      await api(`/api/jobs/${S.activeJobId}`, { method: "DELETE" });
      toast("Cancellation requested.");
      openJob(S.activeJobId);
    } catch (err) { toast(err.message, "err"); }
  });

  $("#btn-reuse").addEventListener("click", () => {
    const job = findJob(S.activeJobId);
    if (!job) return;
    $("#job-dialog").close();
    openNewJob();
    S.sourceTab = "reuse";
    $$("[data-source-tab]").forEach((b) => b.classList.toggle("active", b.dataset.sourceTab === "reuse"));
    $("#source-url").classList.add("hide");
    $("#source-upload").classList.add("hide");
    $("#source-reuse").classList.remove("hide");
    setValue("#job-reuse", job.id);
    setChecked("#job-bypass", true);
  });

  $("#btn-copy-caption").addEventListener("click", () => copyText($("#clip-caption").value, "Caption"));
  $("#btn-copy-desc").addEventListener("click", () => copyText($("#clip-desc").value, "Description"));

  $("#btn-save-keys").addEventListener("click", async () => {
    const body = {};
    const map = { "#set-google": "google_api_key", "#set-pexels": "pexels_api_key", "#set-hf": "hf_token", "#set-nvidia": "nvidia_api_key" };
    Object.entries(map).forEach(([sel, key]) => {
      const value = $(sel).value.trim();
      if (value) { body[key] = value; $(sel).value = ""; }
    });
    if (!Object.keys(body).length) return toast("Enter at least one key.", "err");
    try {
      S.settings = await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
      renderSettings(); updateSystemStatus();
      toast("Keys applied for this backend session.");
    } catch (err) { toast(err.message, "err"); }
  });

  $("#btn-save-defaults").addEventListener("click", async () => {
    const body = {
      default_clips: Number($("#set-clips").value) || 7,
      default_ratio: $("#set-ratio").value,
      default_font_style: $("#set-font").value,
      default_ai_provider: $("#set-provider").value,
      default_whisper_model: $("#set-whisper").value || "large-v3",
      default_whisper_device: $("#set-device").value,
    };
    try {
      S.settings = await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
      renderSettings(); updateSystemStatus();
      toast("Editor defaults saved for this session.");
    } catch (err) { toast(err.message, "err"); }
  });

  [$("#clip-dialog"), $("#job-dialog"), $("#new-job-dialog")].forEach((dlg) => {
    dlg.addEventListener("close", () => {
      if (dlg.id === "clip-dialog") {
        const video = $("#clip-video");
        video.pause();
        video.removeAttribute("src");
        video.load();
      }
    });
  });

  setInterval(async () => {
    if (S.view !== "studio" && !$("#job-dialog").open) return;
    try {
      const data = await api("/api/jobs");
      S.jobs = data.jobs || [];
      renderAll();
    } catch { /* transient */ }
  }, 15000);
}

document.addEventListener("DOMContentLoaded", boot);
