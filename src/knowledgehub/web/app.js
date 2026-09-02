const $ = (id) => document.getElementById(id);

const state = {
  works: [],
  selected: null,
  health: null,
  translation: {
    projects: [],
    projectId: null,
    project: null,
    chapters: [],
    selectedChapter: null,
    segment: null,
    annotations: [],
    qaFixes: {},
    jobs: [],
    jobLog: [],
    workers: null,
    pollTimer: null,
    busy: false,
    lastError: "",
    selectGen: 0,
    modes: [],
    defaultMode: "normal",
    startOpen: false,
    startWorkId: null,
    startMode: "normal",
    startWorks: [],
  },
  workMode: "normal",
  settings: null,
};

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : data?.message || res.statusText);
  }
  return data;
}

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    el.hidden = true;
  }, 4200);
}

function badge(ok, yes, no) {
  return `<span class="badge ${ok ? "ok" : "bad"}">${ok ? yes : no}</span>`;
}

function filtered() {
  const q = $("q").value.trim().toLowerCase();
  const filter = $("filter").value;
  const lang = $("lang").value;
  return state.works.filter((w) => {
    if (lang && w.language !== lang) return false;
    if (filter === "allowed" && !w.read_allowed) return false;
    if (filter === "blocked" && w.read_allowed) return false;
    if (filter === "raw" && !w.has_raw) return false;
    if (filter === "missing" && w.has_raw) return false;
    if (filter === "ready" && !(w.read_allowed && w.has_raw && w.has_hash)) return false;
    if (!q) return true;
    const hay = `${w.title} ${w.id} ${w.author_id} ${w.license}`.toLowerCase();
    return hay.includes(q);
  });
}

function renderStats(stats) {
  const items = [
    [stats.works, "Tác phẩm"],
    [stats.authors, "Tác giả"],
    [stats.read_allowed, "Allow Read"],
    [stats.has_raw, "Có raw"],
    [stats.missing_raw, "Thiếu raw"],
    [stats.hashed, "Đã hash"],
  ];
  $("stats").innerHTML = items
    .map(([n, label]) => `<div class="stat"><b>${n}</b><span>${label}</span></div>`)
    .join("");
  const lang = $("lang");
  const current = lang.value;
  lang.innerHTML =
    `<option value="">Mọi ngôn ngữ</option>` +
    (stats.languages || []).map((l) => `<option value="${l}">${l}</option>`).join("");
  lang.value = current;
}

function editionBadge(workId) {
  const s = (state.editionByWork || {})[workId];
  if (!s) return `<span class="muted">—</span>`;
  const parsed = s.chapters_parsed || 0;
  const total = s.chapters_total || 0;
  const phase = s.phase || "macro";
  const tone = phase === "parsed" ? "ok" : phase === "parsing" || phase === "layout_ok" ? "warn" : "";
  const klass = tone ? `badge ${tone}` : "badge";
  return `<span class="${klass}" title="${escapeHtml(phase)}">${parsed}/${total}</span>`;
}

function renderRows() {
  const rows = filtered();
  $("count").textContent = `${rows.length} / ${state.works.length} tác phẩm`;
  $("rows").innerHTML = rows
    .map((w) => {
      const on = state.selected === w.id ? "on" : "";
      return `<tr class="pick ${on}" data-id="${w.id}">
        <td><div class="title">${escapeHtml(w.title)}</div><div class="sub">${escapeHtml(w.id)}</div></td>
        <td>${escapeHtml(w.author_id)}</td>
        <td>${escapeHtml(w.language)}</td>
        <td>${badge(w.read_allowed, "allowed", "blocked")}</td>
        <td>${badge(w.has_raw, "raw", "missing")}</td>
        <td>${editionBadge(w.id)}</td>
      </tr>`;
    })
    .join("");
}

const TRANSLATION_MODES = [
  { id: "tight", label: "Sát nguyên bản", hint: "Giữ cấu trúc và thuật ngữ." },
  { id: "normal", label: "Cân bằng", hint: "Đủ sát, đọc tự nhiên." },
  { id: "loose", label: "Dễ đọc", hint: "Thoát ý có kiểm soát." },
];

function translationModes() {
  return state.translation.modes?.length ? state.translation.modes : TRANSLATION_MODES;
}

function translateBlockReason(code) {
  if (code === "no_raw") return "Cần file raw trước khi dịch.";
  if (code === "not_english") return "Hiện chỉ dịch bản tiếng Anh.";
  if (code === "hub_translation") return "Đây đã là bản dịch Hub.";
  return "";
}

function modeOptionsHtml(current) {
  return translationModes()
    .map((opt) => {
      const on = opt.id === current ? "on" : "";
      return `<button type="button" class="split-opt ${on}" data-mode="${escapeHtml(opt.id)}">
        <strong>${escapeHtml(opt.label)}</strong>
        <small>${escapeHtml(opt.hint)}</small>
      </button>`;
    })
    .join("");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function selectWork(id) {
  state.selected = id;
  renderRows();
  const box = $("detail");
  box.innerHTML = `<p class="muted">Đang tải…</p>`;
  try {
    const data = await api(`/api/works/${encodeURIComponent(id)}`);
    const { work, summary } = data;
    const ready = summary.read_allowed && summary.has_raw && summary.has_hash;
    box.innerHTML = `
      <h2>${escapeHtml(work.title)}</h2>
      <p class="sub">${escapeHtml(work.id)}</p>
      <dl>
        <dt>Tác giả</dt><dd>${escapeHtml(work.author_id)}</dd>
        <dt>Năm · ngôn ngữ</dt><dd>${escapeHtml(work.year)} · ${escapeHtml(work.language)}</dd>
        <dt>License</dt><dd>${escapeHtml(work.license)}</dd>
        <dt>Category Read</dt><dd>${escapeHtml(summary.category_slug)}</dd>
        <dt>Hash</dt><dd>${escapeHtml(summary.content_hash || "—")}</dd>
        <dt>Nguồn</dt><dd>${
          work.source_url
            ? `<a href="${escapeHtml(work.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(work.source_url)}</a>`
            : "—"
        }</dd>
      </dl>
      <div class="row">
        <button class="btn ghost" id="btn-preview" type="button" ${summary.has_raw ? "" : "disabled"}>Preview</button>
        <button class="btn" id="toggle-read" type="button">${
          summary.read_allowed ? "Block Read" : "Allow Read"
        }</button>
        <a class="btn" href="/read-edition/${encodeURIComponent(id)}">Chế bản</a>
        <a class="btn primary" id="apply" href="/publish/${encodeURIComponent(id)}">Publish to Read</a>
      </div>
      ${workTranslateHtml(work, summary)}
      ${ready ? "" : `<p class="err">Publish cần allow Read + file raw + content_hash. Mở trang để điền category / split trước.</p>`}
      <pre class="err" id="pub-out"></pre>
    `;
    $("toggle-read").onclick = async () => {
      await api(`/api/works/${encodeURIComponent(id)}/allow-read`, {
        method: "POST",
        body: { allowed: !summary.read_allowed },
      });
      await refresh();
      await selectWork(id);
    };
    $("btn-preview").onclick = () => openPreview(id, false);
    wireWorkTranslate(work, summary);
  } catch (err) {
    box.innerHTML = `<p class="err">${escapeHtml(err.message)}</p>`;
  }
}

function closePreview() {
  $("preview").hidden = true;
}

function renderPreview(data) {
  $("preview-title").textContent = data.title || data.id;
  const n = data.normalize || {};
  const dropped = [
    n.family && n.family !== "plain" ? n.family : "",
    n.gutenberg && "Gutenberg",
    n.dropped_electronic_note && "note eBook",
    n.dropped_contents && "TOC",
    n.dropped_produced_by && "Produced by",
    n.dropped_transcriber && "transcriber",
    n.dropped_tail_index && "index",
    n.dropped_library_stamp && "library stamp",
    n.dropped_publisher_ads && "catalog NXB",
    n.dropped_scan_boilerplate && "Google scan",
    n.kept_notes && "giữ notes",
    n.unwrapped && "unwrap dòng",
    n.aozora && "Aozora",
  ].filter(Boolean);
  const incompleteNote = n.incomplete
    ? ` · chưa parse hết${n.incomplete_count ? ` (${n.incomplete_count} chương còn thiếu)` : ""}`
    : "";
  $("preview-meta").textContent = `${(n.published_chars || n.assembled_chars || 0).toLocaleString()} chữ đã normalize` +
    (n.origin === "read_edition" ? " · chế bản REF" : "") +
    incompleteNote +
    (n.source_chars ? ` · nguồn ${(n.source_chars).toLocaleString()}` : "") +
    (dropped.length ? ` · đã cắt: ${dropped.join(", ")}` : n.origin === "read_edition" ? "" : " · không cắt thêm");
  $("preview-full").hidden = !data.truncated;
  const body = $("preview-body");
  body.replaceChildren();
  if (data.truncated) {
    body.append(document.createTextNode(data.head || ""));
    const gap = document.createElement("p");
    gap.className = "preview-gap";
    gap.textContent = "… đã rút gọn giữa đầu và cuối. Bấm Toàn văn để đọc hết.";
    body.append(gap);
    body.append(document.createTextNode(data.tail || ""));
  } else {
    body.append(document.createTextNode(data.text || ""));
  }
}

async function openPreview(id, full) {
  const box = $("preview");
  $("preview-title").textContent = "Đang tải…";
  $("preview-meta").textContent = "";
  $("preview-body").textContent = "";
  box.hidden = false;
  try {
    const q = full ? "?full=true" : "";
    const data = await api(`/api/works/${encodeURIComponent(id)}/preview${q}`);
    state.previewId = id;
    renderPreview(data);
  } catch (err) {
    $("preview-meta").textContent = err.message;
  }
}

async function publish(id, apply) {
  const out = $("pub-out");
  if (!out) return;
  out.textContent = "Đang gửi…";
  try {
    const result = await api(`/api/works/${encodeURIComponent(id)}/publish-read`, {
      method: "POST",
      body: { apply },
    });
    out.textContent = JSON.stringify(result, null, 2);
    toast(apply ? "Đã gửi sang Read" : "Dry-run xong — chưa gọi Read");
  } catch (err) {
    out.textContent = err.message;
  }
}

function publishWorkIdFromPath() {
  const parts = location.pathname.replace(/\/+$/, "").split("/").filter(Boolean);
  if (parts[0] === "publish" && parts[1]) return decodeURIComponent(parts.slice(1).join("/"));
  return null;
}

function settingsFromPath() {
  const parts = location.pathname.replace(/\/+$/, "").split("/").filter(Boolean);
  return parts[0] === "settings";
}

function hideAllViews() {
  $("view-works").hidden = true;
  $("view-licenses").hidden = true;
  $("view-publish").hidden = true;
  $("view-translation").hidden = true;
  $("view-settings").hidden = true;
  if ($("view-read-edition")) $("view-read-edition").hidden = true;
  stopJobPoll();
}

function readEditionFromPath() {
  if (window.KHReadEdition) return window.KHReadEdition.fromPath();
  const parts = location.pathname.replace(/^\/+/, "").split("/");
  if (parts[0] === "read-edition" && parts[1]) return decodeURIComponent(parts.slice(1).join("/"));
  if (parts[0] === "read-edition") return "";
  return null;
}

function translationFromPath() {
  const parts = location.pathname.replace(/\/+$/, "").split("/").filter(Boolean);
  if (parts[0] !== "translation" || !parts[1]) return null;
  return {
    workId: decodeURIComponent(parts[1]),
    chapter: parts[2] ? decodeURIComponent(parts[2]) : null,
  };
}

function setTranslationPath(workId, chapter) {
  if (!workId) return;
  const path = chapter
    ? `/translation/${encodeURIComponent(workId)}/${encodeURIComponent(chapter)}`
    : `/translation/${encodeURIComponent(workId)}`;
  if (location.pathname !== path) {
    history.replaceState({ view: "translation", workId, chapter }, "", path);
  }
}

function scoreBar(label, value) {
  const n = Number(value) || 0;
  const pct = Math.max(0, Math.min(100, n * 10));
  return `<div class="tr-score">
    <span>${escapeHtml(label)}</span>
    <div class="tr-score-bar"><span style="width:${pct}%"></span></div>
    <span class="tr-score-val">${n || "—"}</span>
  </div>`;
}

function annotationIssueLabel(issue) {
  const found = (state.translation.annotations || []).find((a) => a.id === issue.annotation_id);
  if (found?.title_vi) return `chú thích: ${found.title_vi}`;
  if (found?.marker) return `chú thích ${found.marker}`;
  const tail = String(issue.annotation_id || "").split("--").pop();
  return tail ? `chú thích: ${tail}` : "chú thích";
}

function chapterStatusLabel(chapter) {
  if (chapter?.completeness === "truncated") return "bản dịch cụt";
  if (chapter?.completeness === "incomplete_parts") return "thiếu phần";
  if (chapter?.completeness === "polish_pending") return "chờ chỉnh văn";
  if (chapter?.has_final) return chapter.status === "approved" ? "đã duyệt" : "có bản dịch";
  if (chapter?.has_draft_raw || chapter?.polish_pending) return "có nháp";
  return "chưa dịch";
}

function shortJobError(error) {
  const text = String(error || "");
  if (!text) return "";
  if (/interrupted|worker restarted/i.test(text)) {
    return "Worker restart (uvicorn --reload) — job không tự chạy lại";
  }
  if (/503|UNAVAILABLE|high demand/i.test(text)) return "Gemini quá tải (503) — thử lại sau";
  if (/429|RESOURCE_EXHAUSTED|rate.?limit|quota/i.test(text)) {
    return "Gemini hết hạn mức (429) — đợi khoảng 1 phút rồi chạy lại chú thích/QA";
  }
  const line = text.split("\n").find((part) => part.trim()) || text;
  return line.length > 140 ? `${line.slice(0, 137)}…` : line;
}

function lastErrorBadgeLabel(kind, status) {
  if (status === "interrupted") {
    return { annotate: "chú thích bị ngắt", qa: "QA bị ngắt", draft: "dịch bị ngắt" }[kind] || "bị ngắt";
  }
  return { annotate: "lỗi chú thích", qa: "lỗi QA", draft: "lỗi dịch" }[kind] || "lỗi";
}

function statusBadge(chapter) {
  const ok = Boolean(chapter?.has_final);
  const bad = chapter?.completeness === "truncated" || chapter?.completeness === "incomplete_parts";
  return `<span class="badge ${ok ? "ok" : ""} ${bad ? "bad" : ""}">${escapeHtml(chapterStatusLabel(chapter))}</span>`;
}

function kindBadge(kind) {
  const map = {
    footnote: ["kind-footnote", "footnote"],
    glossary: ["kind-glossary", "glossary"],
    term: ["kind-glossary", "glossary"],
    context: ["kind-context", "context"],
  };
  const [cls, label] = map[kind] || ["", kind || "note"];
  return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
}

function annotationLabel(a) {
  const marker = String(a.marker || "").trim();
  const anchor = String(a.anchor_text || "").trim();
  if (marker && /^\[[0-9]+\]$/.test(marker) && anchor && !anchor.includes(marker)) {
    return `${anchor} ${marker}`;
  }
  return String(a.title_vi || marker || anchor || "Chú thích").trim();
}

function highlightAnnotatedText(text, annotations) {
  const source = String(text || "");
  if (!source) return "";
  const ranges = [];
  const seen = new Set();
  for (const item of annotations || []) {
    const marker = String(item.marker || "").trim();
    if (/^\[[0-9]+\]$/.test(marker) && !seen.has(marker)) {
      seen.add(marker);
      let from = 0;
      while (from < source.length) {
        const at = source.indexOf(marker, from);
        if (at < 0) break;
        ranges.push({ start: at, end: at + marker.length, kind: item.kind || "footnote" });
        from = at + marker.length;
      }
    }
  }
  ranges.sort((a, b) => a.start - b.start || b.end - a.end);
  const picked = [];
  let cursor = 0;
  for (const range of ranges) {
    if (range.start < cursor) continue;
    picked.push(range);
    cursor = range.end;
  }
  let html = "";
  let at = 0;
  for (const range of picked) {
    html += escapeHtml(source.slice(at, range.start));
    const kind = range.kind === "glossary" || range.kind === "term" ? "glossary" : range.kind === "context" ? "context" : "footnote";
    html += `<mark class="ann-hl ann-${kind}">${escapeHtml(source.slice(range.start, range.end))}</mark>`;
    at = range.end;
  }
  html += escapeHtml(source.slice(at));
  return html;
}

function jobKindLabel(kind) {
  return { draft: "dịch", qa: "QA", annotate: "chú thích" }[kind] || kind;
}

function jobElapsed(job) {
  const start = job?.started_at || job?.heartbeat_at;
  if (!start || (job.status !== "running" && job.status !== "queued")) return "";
  const sec = Math.max(0, Math.round((Date.now() - Date.parse(start)) / 1000));
  if (!Number.isFinite(sec)) return "";
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}p${String(sec % 60).padStart(2, "0")}s`;
}

function jobStatusLine(job) {
  const phase = job.detail || job.phase || jobKindLabel(job.kind);
  const elapsed = jobElapsed(job);
  return `chương ${job.chapter}: ${phase}${elapsed ? ` · ${elapsed}` : ""}`;
}

function activeJobs(jobs) {
  return (jobs || []).filter((job) => job.status === "queued" || job.status === "running");
}

function chapterActiveJob(chapterRow, kind) {
  const jobs = chapterRow?.jobs || [];
  const match = kind ? jobs.filter((job) => job.kind === kind) : jobs;
  return match.find((job) => job.status === "running") || match.find((job) => job.status === "queued") || null;
}

function workerRangeLabel() {
  const p = pipelineSettings();
  const workers = state.translation.workers || {};
  const min = Number(workers.min_workers ?? p.min_workers ?? 1);
  const max = Number(workers.max_workers ?? p.max_workers ?? 2);
  if (min === max) return `Worker ${max} luồng`;
  return `Worker ${min}–${max} luồng`;
}

function renderJobQueue() {
  const el = $("tr-jobs");
  if (!el) return;
  const jobs = activeJobs(state.translation.jobs);
  const missingBtn = $("tr-draft-missing");
  const missing = (state.translation.project?.missing_chapters || []).length;
  if (missingBtn) missingBtn.disabled = missing === 0;
  const cancelBtn = $("tr-cancel-jobs");
  if (cancelBtn) {
    cancelBtn.hidden = jobs.length === 0;
    cancelBtn.disabled = jobs.length === 0;
  }
  if (!jobs.length) {
    el.textContent = missing
      ? `${workerRangeLabel()} — còn ${missing} chương chưa dịch. Xếp hàng rồi làm việc khác trong lúc chờ.`
      : "";
    return;
  }
  const running = jobs.filter((job) => job.status === "running");
  const waiting = jobs.filter((job) => job.status === "queued");
  const parts = [];
  if (running.length) {
    parts.push(`Đang ${running.map(jobStatusLine).join("; ")}`);
  }
  if (waiting.length) {
    parts.push(
      `chờ ${waiting
        .map(
          (job) =>
            `${job.chapter}/${jobKindLabel(job.kind)}${job.phase === "retry" ? " (thử lại)" : ""}`,
        )
        .join(", ")}`,
    );
  }
  const alive = Number(state.translation.workers?.alive || 0);
  if (alive > 1) parts.push(`${alive} luồng`);
  el.textContent = parts.join(" · ");
}

function renderJobLog() {
  const el = $("tr-job-log");
  if (!el) return;
  const rows = (state.translation.jobLog || []).slice(-12);
  if (!rows.length) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = rows
    .map((row) => {
      const at = String(row.at || "").replace("T", " ").replace("+00:00", "Z");
      const rest = Object.entries(row)
        .filter(([key]) => key !== "at" && key !== "event")
        .map(([key, value]) => `${key}=${value}`)
        .join(" ");
      return `${at} ${row.event}${rest ? ` ${rest}` : ""}`;
    })
    .join("\n");
}

function pipelineSettings() {
  return state.translation.project?.pipeline || state.settings?.settings?.translation || {};
}

function renderPipelineNote() {
  const el = $("tr-pipeline-note");
  if (!el) return;
  const p = pipelineSettings();
  const bits = [];
  if (p.auto_annotate) bits.push("chú thích");
  if (p.auto_qa) bits.push("QA");
  if (!bits.length) {
    el.textContent = "Sau khi dịch cần chạy chú thích và QA riêng — đổi ở Cài đặt.";
    return;
  }
  el.textContent =
    bits.length === 2
      ? "Sau khi dịch sẽ tự tạo chú thích rồi chạy QA (đổi ở Cài đặt)."
      : `Sau khi dịch sẽ tự chạy ${bits[0]} (đổi ở Cài đặt).`;
}

function followupToast(kind, chapter) {
  const p = pipelineSettings();
  const extra = [];
  if (kind === "draft") {
    if (p.auto_annotate) extra.push("chú thích");
    if (p.auto_qa) extra.push("QA");
  } else if (kind === "annotate" && p.auto_qa) {
    extra.push("QA");
  }
  const base = `Đã xếp hàng ${jobKindLabel(kind)} chương ${chapter}`;
  return extra.length ? `${base} — tiếp theo: ${extra.join(" rồi ")}` : base;
}

function notifyJobChanges(prev, next) {
  for (const job of next) {
    const old = prev.find((item) => item.id === job.id);
    if (!old) continue;
    if (old.status !== "done" && job.status === "done") {
      toast(`Xong ${jobKindLabel(job.kind)} chương ${job.chapter}`);
    }
    if (old.status !== "error" && job.status === "error") {
      toast(`${jobKindLabel(job.kind)} chương ${job.chapter}: ${shortJobError(job.error) || "lỗi"}`);
    }
    if (old.status !== "cancelled" && job.status === "cancelled") {
      toast(`Đã hủy ${jobKindLabel(job.kind)} chương ${job.chapter}`);
    }
    if (old.status !== "interrupted" && job.status === "interrupted") {
      toast(`Ngắt ${jobKindLabel(job.kind)} chương ${job.chapter} — không tự chạy lại`);
    }
  }
}

function startJobPoll() {
  if (state.translation.pollTimer) return;
  state.translation.pollTimer = setInterval(() => void refreshTranslationJobs(), 2500);
}

function stopJobPoll() {
  if (state.translation.pollTimer) {
    clearInterval(state.translation.pollTimer);
    state.translation.pollTimer = null;
  }
}

async function refreshTranslationJobs() {
  const workId = state.translation.projectId;
  if (!workId || $("view-translation")?.hidden) return;
  try {
    const prev = state.translation.jobs || [];
    const data = await api(`/api/translations/${encodeURIComponent(workId)}`);
    const next = data.jobs || [];
    notifyJobChanges(prev, next);
    state.translation.jobs = next;
    state.translation.jobLog = data.log || [];
    state.translation.workers = data.workers || state.translation.workers;
    state.translation.project = data;
    state.translation.chapters = data.chapters || [];
    renderTranslationStats();
    renderTranslationRows();
    renderJobQueue();
    renderJobLog();
    renderPipelineNote();
    const selected = state.translation.selectedChapter;
    const justDone = next.filter(
      (job) =>
        job.chapter === selected &&
        job.status === "done" &&
        prev.some((item) => item.id === job.id && item.status !== "done"),
    );
    if (justDone.length && selected) {
      await selectTranslationChapter(selected, !$("tr-segment").hidden);
    }
    if (activeJobs(next).length) startJobPoll();
    else stopJobPoll();
  } catch {
    /* keep polling; next tick retries */
  }
}

function renderTranslationStats() {
  const p = state.translation.project;
  const chapters = state.translation.chapters || [];
  if (!p) {
    $("tr-stats").innerHTML = "";
    return;
  }
  const withFinal = chapters.filter((c) => c.has_final).length;
  const withQa = chapters.filter((c) => c.qa_overall != null).length;
  const withAnn = chapters.filter((c) => c.annotations_generated_at).length;
  const items = [
    [chapters.length, "Chương"],
    [withFinal, "Có bản dịch"],
    [withQa, "Đã QA"],
    [withAnn, "Đã chú thích"],
    [p.project?.translation_mode || "—", "Mode"],
  ];
  $("tr-stats").innerHTML = items
    .map(([n, label]) => `<div class="stat"><b>${escapeHtml(String(n))}</b><span>${escapeHtml(label)}</span></div>`)
    .join("");
  const note = $("tr-promote-note");
  const btn = $("tr-promote");
  const catalogId = p.translation_work_id || "";
  if (note) {
    if (!p.ready_to_promote) {
      const missing = (p.missing_chapters || []).join(", ") || "—";
      note.textContent = `Chưa đủ chương final — còn ${missing}. Catalog: ${catalogId}`;
      if (btn) btn.disabled = true;
    } else {
      note.textContent = `Đủ bản dịch. Đưa vào catalog rồi allow-read / publish-read trên ${catalogId}.`;
      if (btn) btn.disabled = false;
    }
  }
}

function renderTranslationRows() {
  const chapters = state.translation.chapters || [];
  const selected = state.translation.selectedChapter;
  const html = chapters
    .map((c) => {
      const on = selected === c.chapter ? "on" : "";
      const open = c.open_issue_count != null ? c.open_issue_count : c.issue_count;
      const qa = c.qa_overall != null ? `${c.qa_overall}/10` : "—";
      const qaSub = c.issue_count
        ? `<div class="sub">${open ? `${open}/${c.issue_count} còn mở` : `${c.issue_count} đã duyệt`}</div>`
        : "";
      const annCount = c.annotation_count || 0;
      const ann = annCount ? `${annCount}` : c.annotations_generated_at ? "✓" : "—";
      const job = chapterActiveJob(c);
      const jobBadge = job
        ? `<span class="badge ${job.status === "running" ? "warn" : ""}">${escapeHtml(
            job.status === "running" ? job.detail || "đang…" : `chờ ${jobKindLabel(job.kind)}`,
          )}</span>`
        : "";
      const errBadge =
        c.last_error && !job
          ? `<span class="badge ${c.last_error_status === "interrupted" ? "warn" : "bad"}">${escapeHtml(
              lastErrorBadgeLabel(c.last_error_kind, c.last_error_status),
            )}</span>`
          : "";
      const errSub =
        c.last_error && !job
          ? `<div class="sub">${escapeHtml(shortJobError(c.last_error))}</div>`
          : "";
      return `<tr class="pick ${on}" data-chapter="${escapeHtml(c.chapter)}">
        <td><div class="title">Chương ${escapeHtml(c.chapter)}</div><div class="sub">${escapeHtml(String(c.words || "—"))} từ${
          c.part_count ? ` · ${c.parts_ready || 0}/${c.part_count} phần` : ""
        }</div></td>
        <td><div class="tr-status">${statusBadge(c)}${jobBadge}${errBadge}${errSub}</div></td>
        <td>${escapeHtml(qa)}${qaSub}</td>
        <td>${escapeHtml(String(ann))}</td>
      </tr>`;
    })
    .join("");
  if ($("tr-rows").innerHTML === html) return;
  $("tr-rows").innerHTML = html;
}

function renderTranslationDetail() {
  const box = $("tr-detail");
  const chapter = state.translation.selectedChapter;
  const seg = state.translation.segment;
  if (!chapter) {
    box.innerHTML = `<p class="muted">Chọn một chương để xem QA và chú thích.</p>`;
    return;
  }
  if (!seg) {
    box.innerHTML = `<p class="muted">Đang tải chương ${escapeHtml(chapter)}…</p>`;
    return;
  }
  const qa = seg.qa || {};
  const scores = qa.scores || {};
  const issues = qa.issues || [];
  const openIssues = issues.filter((issue) => !issue.approved);
  const annotations = state.translation.annotations || [];
  const approvedIssues = issues.filter((issue) => issue.approved);
  const hasTranslation = Boolean((seg.translation || "").trim());
  const chapterRow = (state.translation.chapters || []).find((row) => row.chapter === chapter);
  const draftJob = chapterActiveJob(chapterRow, "draft");
  const qaJob = chapterActiveJob(chapterRow, "qa");
  const annJob = chapterActiveJob(chapterRow, "annotate");
  const lastError =
    chapterRow?.last_error && !draftJob && !qaJob && !annJob
      ? shortJobError(chapterRow.last_error)
      : "";
  const longNote =
    Number(seg.words) >= 3000
      ? `<p class="muted">Chương dài (${escapeHtml(String(seg.words))} từ) — dịch có thể mất vài phút, hoặc Gemini trả 503 khi quá tải.</p>`
      : "";
  const scoreHtml = qa.scores
    ? `<div class="tr-score-grid">
        ${scoreBar("Trung thực", scores.fidelity)}
        ${scoreBar("Mạch lạc", scores.fluency)}
        ${scoreBar("Thuật ngữ", scores.terminology)}
        ${scoreBar("Đầy đủ", scores.completeness)}
        ${scoreBar("Tổng thể", scores.overall)}
        ${scores.annotations != null ? scoreBar("Chú thích", scores.annotations) : ""}
      </div>`
    : `<p class="muted">Chưa chạy QA cho chương này.</p>`;
  const issueHtml = issues.length
    ? `<ul class="tr-issues">${issues
        .map((issue, index) => {
          const done = Boolean(issue.approved);
          return `<li class="${done ? "approved" : ""}">
            <div class="meta">
              <span class="badge ${issue.severity === "major" ? "major" : "minor"}">${escapeHtml(issue.severity || "minor")}</span>
              <span class="badge">${escapeHtml(issue.category || "other")}</span>
              ${issue.annotation_id ? `<span class="badge">${escapeHtml(annotationIssueLabel(issue))}</span>` : ""}
              ${done ? `<span class="badge ok">đã duyệt</span>` : ""}
            </div>
            <div>${escapeHtml(issue.note_vi || "")}</div>
            ${
              issue.source_excerpt || issue.translation_excerpt
                ? `<div class="excerpt">
                    ${issue.source_excerpt ? `EN: ${escapeHtml(issue.source_excerpt)}<br />` : ""}
                    ${issue.translation_excerpt ? `VI: ${escapeHtml(issue.translation_excerpt)}` : ""}
                  </div>`
                : ""
            }
            ${
              done && issue.applied_replacement
                ? `<div class="excerpt">Đã sửa thành: ${escapeHtml(issue.applied_replacement)}</div>`
                : ""
            }
            ${
              done
                ? `<button class="btn ghost" type="button" data-reopen-index="${index}" ${state.translation.busy ? "disabled" : ""}>Mở lại</button>`
                : `<label class="tr-fix">Sửa thành
                    <textarea data-fix-index="${index}" rows="2">${escapeHtml(
                      state.translation.qaFixes?.[String(index)] ??
                        issue.applied_replacement ??
                        issue.translation_excerpt ??
                        "",
                    )}</textarea>
                  </label>
                  <button class="btn ghost" type="button" data-approve-index="${index}" ${state.translation.busy ? "disabled" : ""}>Duyệt</button>`
            }
          </li>`;
        })
        .join("")}</ul>
      ${
        openIssues.length || approvedIssues.length
          ? `<div class="row">
              ${openIssues.length ? `<button class="btn" type="button" id="tr-btn-approve-all" ${state.translation.busy ? "disabled" : ""}>Duyệt hết ${openIssues.length} nhận xét</button>` : ""}
              ${approvedIssues.length ? `<button class="btn ghost" type="button" id="tr-btn-reopen-all" ${state.translation.busy ? "disabled" : ""}>Mở lại ${approvedIssues.length} nhận xét</button>` : ""}
            </div>`
          : ""
      }`
    : qa.scores
      ? `<p class="muted">Không có vấn đề được ghi nhận.</p>`
      : "";
  const annHtml = `<div class="tr-ann-side">
      <h3>Chú thích (${annotations.length})</h3>
      ${
        annotations.length
          ? `<div class="tr-annotations">${annotations
              .map(
                (a) => `<article class="tr-ann">
                  <div class="tr-ann-head">
                    ${kindBadge(a.kind)}
                    <strong>${escapeHtml(annotationLabel(a))}</strong>
                    ${a.anchor_text && annotationLabel(a) !== a.anchor_text ? `<span class="anchor">↳ ${escapeHtml(a.anchor_text)}</span>` : ""}
                  </div>
                  <p>${escapeHtml(a.body_vi || "")}</p>
                </article>`,
              )
              .join("")}</div>`
          : `<p class="muted">${seg.annotations_generated_at ? "File chú thích trống cho chương này." : "Chưa tạo chú thích."}</p>`
      }
    </div>`;
  box.innerHTML = `
    <h2>Chương ${escapeHtml(chapter)}</h2>
    <p class="sub">${escapeHtml(chapterStatusLabel(chapterRow || { has_final: hasTranslation, status: seg.status }))} · ${escapeHtml(String(seg.words || "—"))} từ</p>
    ${
      lastError
        ? `<p class="err">${escapeHtml(
            chapterRow?.last_error_status === "interrupted"
              ? "Job bị ngắt khi server reload: "
              : hasTranslation && chapterRow?.last_error_kind === "annotate"
                ? "Bản dịch đã có. Lỗi chú thích: "
                : hasTranslation && chapterRow?.last_error_kind === "qa"
                  ? "Bản dịch đã có. Lỗi QA: "
                  : "",
          )}${escapeHtml(lastError)}</p>`
        : ""
    }
    ${longNote}
    ${scoreHtml}
    ${qa.summary_vi ? `<div class="tr-summary">${escapeHtml(qa.summary_vi)}</div>` : ""}
    ${issueHtml}
    ${annHtml}
    <div class="row">
      <button class="btn ghost" id="tr-btn-segment" type="button">Xem EN / nháp / chỉnh</button>
      <button class="btn ${hasTranslation ? "ghost" : "primary"}" id="tr-btn-draft" type="button">${draftJob ? (draftJob.status === "running" ? draftJob.detail || "Đang dịch…" : "Đã xếp hàng dịch") : hasTranslation ? "Dịch lại" : "Dịch chương"}</button>
      <button class="btn ghost" id="tr-btn-qa" type="button" ${!hasTranslation ? "disabled" : ""}>${qaJob ? (qaJob.status === "running" ? "Đang QA…" : "Đã xếp hàng QA") : qa.scores ? "Chạy lại QA" : "Chạy QA"}</button>
      <button class="btn" id="tr-btn-annotate" type="button" ${!hasTranslation ? "disabled" : ""}>${annJob ? (annJob.status === "running" ? "Đang tạo chú thích…" : "Đã xếp hàng chú thích") : seg.annotations_generated_at || annotations.length ? "Tạo lại chú thích" : "Tạo chú thích"}</button>
    </div>
    <pre class="err" id="tr-action-out">${escapeHtml(state.translation.lastError || "")}</pre>
  `;
  $("tr-btn-segment").onclick = () => showTranslationSegment(true);
  $("tr-btn-draft").onclick = () => runTranslationDraft();
  $("tr-btn-qa").onclick = () => runTranslationQA();
  $("tr-btn-annotate").onclick = () => runTranslationAnnotate();
  box.querySelectorAll("[data-fix-index]").forEach((input) => {
    input.oninput = () => {
      state.translation.qaFixes = state.translation.qaFixes || {};
      state.translation.qaFixes[input.dataset.fixIndex] = input.value;
    };
  });
  box.querySelectorAll("[data-approve-index]").forEach((btn) => {
    btn.onclick = () => void approveQaIssue(Number(btn.dataset.approveIndex));
  });
  const approveAll = $("tr-btn-approve-all");
  if (approveAll) approveAll.onclick = () => void approveQaIssue(null);
  box.querySelectorAll("[data-reopen-index]").forEach((btn) => {
    btn.onclick = () => void reopenQaIssue(Number(btn.dataset.reopenIndex));
  });
  const reopenAll = $("tr-btn-reopen-all");
  if (reopenAll) reopenAll.onclick = () => void reopenQaIssue(null);
}

function renderTranslationAnnotations() {
  const items = state.translation.annotations || [];
  $("tr-ann-count").textContent = String(items.length);
  $("tr-annotations").innerHTML = items.length
    ? items
        .map(
          (a) => `<article class="tr-ann">
            <div class="tr-ann-head">
              ${kindBadge(a.kind)}
              <strong>${escapeHtml(annotationLabel(a))}</strong>
              ${a.anchor_text && annotationLabel(a) !== a.anchor_text ? `<span class="anchor">↳ ${escapeHtml(a.anchor_text)}</span>` : ""}
            </div>
            <p>${escapeHtml(a.body_vi || "")}</p>
          </article>`,
        )
        .join("")
    : `<p class="muted">Chưa có chú thích. Bấm “Tạo chú thích” ở panel bên phải.</p>`;
}

function compareSlice() {
  const seg = state.translation.segment || {};
  const parts = seg.parts || [];
  const pick = state.translation.comparePart;
  if (pick && pick !== "all") {
    const part = parts.find((row) => String(row.id) === String(pick));
    if (part) {
      return {
        title: `Chương ${seg.chapter} · phần ${part.id}`,
        source: part.source_text || "",
        draft: part.draft_raw_text || "",
        polish: part.translation || "",
      };
    }
  }
  return {
    title: `Chương ${seg.chapter || ""}`,
    source: seg.source_text || "",
    draft: seg.draft_raw_text || "",
    polish: seg.translation || "",
  };
}

function showTranslationSegment(show) {
  const seg = state.translation.segment;
  const block = $("tr-segment");
  if (!show || !seg) {
    block.hidden = true;
    return;
  }
  const slice = compareSlice();
  $("tr-segment-title").textContent = slice.title;
  $("tr-source").textContent = slice.source || "";
  $("tr-draft").textContent = slice.draft || "Chưa có nháp DeepSeek.";
  const polish = slice.polish || "";
  const translation = $("tr-translation");
  if (polish && (state.translation.annotations || []).length) {
    translation.innerHTML = highlightAnnotatedText(polish, state.translation.annotations);
  } else {
    translation.textContent = polish || "Chưa có bản Gemini.";
  }
  const parts = seg.parts || [];
  const wrap = $("tr-part-wrap");
  const select = $("tr-part-select");
  if (wrap && select) {
    wrap.hidden = parts.length === 0;
    if (parts.length) {
      const current = state.translation.comparePart || "all";
      select.innerHTML =
        `<option value="all">Cả chương</option>` +
        parts
          .map(
            (part) =>
              `<option value="${escapeHtml(String(part.id))}" ${String(part.id) === String(current) ? "selected" : ""}>Phần ${escapeHtml(String(part.id))} (${escapeHtml(String(part.words || "—"))} từ)</option>`,
          )
          .join("");
    }
  }
  const tabs = $("tr-compare-tabs");
  if (tabs) tabs.hidden = false;
  renderTranslationAnnotations();
  block.hidden = false;
}

function setCompareTab(name) {
  document.querySelectorAll("[data-compare-tab]").forEach((btn) => {
    btn.classList.toggle("on", btn.dataset.compareTab === name);
  });
  document.querySelectorAll("[data-compare-col]").forEach((col) => {
    col.classList.toggle("on", col.dataset.compareCol === name);
  });
}

function workTranslateHtml(work, summary) {
  const openId = summary.translation_source_id;
  if (summary.has_translation_project || (summary.translate_block === "hub_translation" && openId)) {
    return `<div class="row">
      <button class="btn" type="button" id="btn-translate-open">Mở bàn dịch</button>
    </div>`;
  }
  if (summary.can_translate) {
    const mode = state.workMode || state.translation.defaultMode || "normal";
    return `<fieldset class="split-set" id="work-translate">
      <legend>Dịch sang tiếng Việt</legend>
      <p class="muted">Chọn một cách dịch. Không cần dịch thử một đoạn mẫu.</p>
      <div class="split-opts" id="work-mode-opts">${modeOptionsHtml(mode)}</div>
      <div class="row">
        <button class="btn primary" type="button" id="btn-translate-start">Bắt đầu dịch</button>
      </div>
      <p class="err" id="work-translate-err"></p>
    </fieldset>`;
  }
  const reason = translateBlockReason(summary.translate_block);
  return reason ? `<p class="muted">${escapeHtml(reason)}</p>` : "";
}

function wireWorkTranslate(work, summary) {
  const openId = summary.translation_source_id || work.id;
  const openBtn = $("btn-translate-open");
  if (openBtn) {
    openBtn.onclick = () => {
      void loadTranslationView(openId, null);
    };
  }
  const opts = $("work-mode-opts");
  if (opts) {
    opts.onclick = (event) => {
      const btn = event.target.closest("[data-mode]");
      if (!btn) return;
      state.workMode = btn.dataset.mode;
      opts.querySelectorAll(".split-opt").forEach((el) => el.classList.toggle("on", el === btn));
    };
  }
  const startBtn = $("btn-translate-start");
  if (startBtn) {
    startBtn.onclick = async () => {
      const err = $("work-translate-err");
      startBtn.disabled = true;
      if (err) err.textContent = "";
      try {
        await beginTranslation(work.id, state.workMode || state.translation.defaultMode || "normal");
      } catch (error) {
        if (err) err.textContent = error.message;
      } finally {
        startBtn.disabled = false;
      }
    };
  }
}

function setTranslationStartVisible(open) {
  const start = $("tr-start");
  const desk = $("tr-desk");
  const pick = $("tr-pick-work");
  state.translation.startOpen = open;
  if (start) start.hidden = !open;
  if (desk) desk.hidden = open || !state.translation.projectId;
  if (pick) pick.hidden = open;
}

async function ensureStartWorks() {
  if (!state.works?.length) {
    const data = await api("/api/works");
    state.works = data.works || [];
  }
  state.translation.startWorks = state.works;
}

function startWorkRows() {
  const q = ($("tr-work-q")?.value || "").trim().toLowerCase();
  return (state.translation.startWorks || []).filter((work) => {
    if (work.translate_block === "hub_translation") return false;
    if (!work.can_translate && !work.has_translation_project) return false;
    if (!q) return true;
    const hay = `${work.title} ${work.id} ${work.author_id}`.toLowerCase();
    return hay.includes(q);
  });
}

function renderStartWorks() {
  const rows = startWorkRows();
  const selected = state.translation.startWorkId;
  const count = $("tr-work-count");
  const body = $("tr-work-rows");
  if (count) count.textContent = `${rows.length} tác phẩm`;
  if (body) {
    body.innerHTML = rows
      .map((work) => {
        const on = selected === work.id ? "on" : "";
        const status = work.has_translation_project ? "Đã có dự án" : "Chưa dịch";
        return `<tr class="pick ${on}" data-id="${escapeHtml(work.id)}">
          <td><div class="title">${escapeHtml(work.title)}</div><div class="sub">${escapeHtml(work.id)}</div></td>
          <td>${escapeHtml(work.author_id)}</td>
          <td>${escapeHtml(status)}</td>
        </tr>`;
      })
      .join("");
  }
  const chosen = rows.find((work) => work.id === selected);
  const wrap = $("tr-mode-wrap");
  if (wrap) wrap.hidden = !chosen || chosen.has_translation_project;
  const go = $("tr-start-go");
  if (go) go.disabled = !chosen || chosen.has_translation_project || !state.translation.startMode;
}

function renderStartModes() {
  const box = $("tr-mode-opts");
  if (!box) return;
  const current = state.translation.startMode || state.translation.defaultMode || "normal";
  box.innerHTML = modeOptionsHtml(current);
}

async function openTranslationStart() {
  await ensureStartWorks();
  state.translation.startWorkId = null;
  state.translation.startMode = state.translation.defaultMode || "normal";
  const err = $("tr-start-err");
  if (err) err.textContent = "";
  setTranslationStartVisible(true);
  renderStartWorks();
  renderStartModes();
}

async function pickStartWork(id) {
  const work = (state.translation.startWorks || []).find((row) => row.id === id);
  if (!work) return;
  if (work.has_translation_project) {
    await loadTranslationProject(id, null);
    setTranslationStartVisible(false);
    if (state.translation.projectId) {
      setTranslationPath(id, state.translation.selectedChapter);
    }
    return;
  }
  state.translation.startWorkId = id;
  renderStartWorks();
  renderStartModes();
}

async function beginTranslation(workId, mode) {
  try {
    await api("/api/translations", {
      method: "POST",
      body: { source_work_id: workId, mode },
    });
    toast(`Đã tạo dự án · ${mode}`);
  } catch (err) {
    if (!/exists/i.test(err.message || "")) throw err;
  }
  await loadTranslationView(workId, null);
}

async function confirmStartTranslation() {
  const workId = state.translation.startWorkId;
  const mode = state.translation.startMode;
  const err = $("tr-start-err");
  const go = $("tr-start-go");
  if (!workId || !mode) return;
  if (go) go.disabled = true;
  if (err) err.textContent = "";
  try {
    await beginTranslation(workId, mode);
  } catch (error) {
    if (err) err.textContent = error.message;
  } finally {
    if (go) go.disabled = false;
  }
}

async function loadTranslationProjects() {
  const data = await api("/api/translations");
  state.translation.projects = data.projects || [];
  state.translation.modes = data.modes || TRANSLATION_MODES;
  state.translation.defaultMode = data.default_mode || "normal";
  if (!state.translation.startMode) {
    state.translation.startMode = state.translation.defaultMode;
  }
  const select = $("tr-project");
  select.innerHTML = (data.projects || [])
    .map(
      (p) =>
        `<option value="${escapeHtml(p.source_work_id)}" ${p.source_work_id === state.translation.projectId ? "selected" : ""}>${escapeHtml(p.source_title || p.source_work_id)} (${escapeHtml(p.target_language || "vi")})</option>`,
    )
    .join("");
  if (!data.projects?.length) {
    state.translation.projectId = null;
    return;
  }
  if (!state.translation.projectId && data.projects?.length) {
    state.translation.projectId = data.projects[0].source_work_id;
    select.value = state.translation.projectId;
  }
}

async function loadTranslationProject(workId, chapterHint) {
  state.translation.projectId = workId;
  const data = await api(`/api/translations/${encodeURIComponent(workId)}`);
  state.translation.project = data;
  state.translation.chapters = data.chapters || [];
  state.translation.jobs = data.jobs || [];
  state.translation.jobLog = data.log || [];
  state.translation.workers = data.workers || null;
  renderTranslationStats();
  renderTranslationRows();
  renderJobQueue();
  renderJobLog();
  renderPipelineNote();
  if (activeJobs(state.translation.jobs).length) startJobPoll();
  const pick =
    chapterHint && data.chapters.some((c) => c.chapter === chapterHint)
      ? chapterHint
      : data.chapters.find((c) => c.has_final)?.chapter || data.chapters[0]?.chapter || null;
  if (pick) await selectTranslationChapter(pick, true);
  else {
    state.translation.selectedChapter = null;
    state.translation.segment = null;
    renderTranslationDetail();
    showTranslationSegment(false);
  }
}

async function selectTranslationChapter(chapter, showSegment) {
  const workId = state.translation.projectId;
  if (!workId || !chapter) return;
  if (state.translation.selectedChapter !== chapter) {
    state.translation.qaFixes = {};
    state.translation.comparePart = "all";
  }
  const gen = (state.translation.selectGen = (state.translation.selectGen || 0) + 1);
  const keepPanel =
    state.translation.selectedChapter === chapter && Boolean(state.translation.segment);
  state.translation.selectedChapter = chapter;
  state.translation.lastError = "";
  if (!keepPanel) {
    state.translation.segment = null;
    state.translation.annotations = [];
    renderTranslationDetail();
  }
  renderTranslationRows();
  setTranslationPath(workId, chapter);
  try {
    const [seg, ann] = await Promise.all([
      api(`/api/translations/${encodeURIComponent(workId)}/segments/${encodeURIComponent(chapter)}`),
      api(`/api/translations/${encodeURIComponent(workId)}/annotations?chapter=${encodeURIComponent(chapter)}`),
    ]);
    if (state.translation.selectGen !== gen) return;
    state.translation.segment = seg;
    state.translation.annotations = ann.annotations || [];
    renderTranslationDetail();
    if (showSegment) showTranslationSegment(true);
    else renderTranslationAnnotations();
  } catch (err) {
    if (state.translation.selectGen !== gen) return;
    $("tr-detail").innerHTML = `<p class="err">${escapeHtml(err.message)}</p>`;
  }
}

async function runTranslationAction(kind) {
  const workId = state.translation.projectId;
  const chapter = state.translation.selectedChapter;
  if (!workId || !chapter) return;
  state.translation.lastError = "";
  try {
    const result = await api(`/api/translations/${encodeURIComponent(workId)}/jobs`, {
      method: "POST",
      body: { kind, chapter },
    });
    const job = result.job || result.jobs?.[0];
    toast(
      job?.created === false
        ? `Chương ${chapter} đã có trong hàng đợi`
        : followupToast(kind, chapter),
    );
    await refreshTranslationJobs();
    renderTranslationDetail();
  } catch (err) {
    state.translation.lastError = err.message;
    renderTranslationDetail();
  }
}

async function enqueueMissingDrafts() {
  const workId = state.translation.projectId;
  if (!workId) return;
  try {
    const result = await api(`/api/translations/${encodeURIComponent(workId)}/jobs`, {
      method: "POST",
      body: { kind: "draft", missing: true },
    });
    const n = Number(result.enqueued || 0);
    toast(n ? `Đã xếp hàng ${n} chương còn thiếu` : "Không còn chương nào để dịch");
    await refreshTranslationJobs();
    renderTranslationDetail();
  } catch (err) {
    toast(err.message);
  }
}

async function cancelActiveJobs() {
  const workId = state.translation.projectId;
  if (!workId) return;
  const btn = $("tr-cancel-jobs");
  if (btn) btn.disabled = true;
  try {
    const result = await api(`/api/translations/${encodeURIComponent(workId)}/jobs/cancel`, {
      method: "POST",
      body: {},
    });
    const n = Number(result.cancelled || 0);
    toast(n ? `Đã hủy ${n} job` : "Không có job đang chạy");
    await refreshTranslationJobs();
    renderTranslationDetail();
  } catch (err) {
    toast(err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function runTranslationDraft() {
  const chapter = state.translation.selectedChapter;
  const chapterRow = (state.translation.chapters || []).find((row) => row.chapter === chapter);
  if (chapterActiveJob(chapterRow, "draft")) {
    toast(`Chương ${chapter} đã có trong hàng đợi`);
    return;
  }
  const hasTranslation = Boolean((state.translation.segment?.translation || "").trim());
  if (
    hasTranslation &&
    !confirm("Chương này đã có bản dịch. Dịch lại sẽ ghi đè cả các sửa QA. Tiếp tục?")
  ) {
    return;
  }
  await runTranslationAction("draft");
}

async function runTranslationQA() {
  await runTranslationAction("qa");
}

async function runTranslationAnnotate() {
  await runTranslationAction("annotate");
}

function collectQaFixes() {
  const fixes = { ...(state.translation.qaFixes || {}) };
  document.querySelectorAll("[data-fix-index]").forEach((input) => {
    fixes[input.dataset.fixIndex] = input.value;
  });
  state.translation.qaFixes = fixes;
  return fixes;
}

async function approveQaIssue(index) {
  const workId = state.translation.projectId;
  const chapter = state.translation.selectedChapter;
  if (!workId || !chapter) return;
  const fixes = collectQaFixes();
  const segmentOpen = !$("tr-segment").hidden;
  const body =
    index == null
      ? { all: true, replacements: fixes }
      : { index, replacement: fixes[String(index)] ?? "" };
  state.translation.lastError = "";
  state.translation.busy = true;
  renderTranslationDetail();
  try {
    const result = await api(
      `/api/translations/${encodeURIComponent(workId)}/qa/${encodeURIComponent(chapter)}/approve`,
      { method: "POST", body },
    );
    const applied = Number(result.applied_count || 0);
    toast(
      applied
        ? index == null
          ? `Đã duyệt hết và sửa ${applied} chỗ trong bản dịch`
          : "Đã duyệt và sửa bản dịch"
        : index == null
          ? "Đã duyệt hết nhận xét QA"
          : "Đã duyệt nhận xét",
    );
    if (index == null) state.translation.qaFixes = {};
    else delete state.translation.qaFixes[String(index)];
    await loadTranslationProject(workId, chapter);
    if (segmentOpen) showTranslationSegment(true);
  } catch (err) {
    state.translation.lastError = err.message;
  } finally {
    state.translation.busy = false;
    renderTranslationDetail();
  }
}

async function reopenQaIssue(index) {
  const workId = state.translation.projectId;
  const chapter = state.translation.selectedChapter;
  if (!workId || !chapter) return;
  const segmentOpen = !$("tr-segment").hidden;
  const body = index == null ? { all: true } : { index };
  state.translation.lastError = "";
  state.translation.busy = true;
  renderTranslationDetail();
  try {
    await api(
      `/api/translations/${encodeURIComponent(workId)}/qa/${encodeURIComponent(chapter)}/reopen`,
      { method: "POST", body },
    );
    toast(index == null ? "Đã mở lại mọi nhận xét QA" : "Đã mở lại nhận xét");
    await loadTranslationProject(workId, chapter);
    if (segmentOpen) showTranslationSegment(true);
  } catch (err) {
    state.translation.lastError = err.message;
  } finally {
    state.translation.busy = false;
    renderTranslationDetail();
  }
}

async function loadTranslationView(workId, chapter) {
  document.querySelectorAll(".nav-link").forEach((b) => b.classList.remove("active"));
  document.querySelector('.nav-link[data-view="translation"]')?.classList.add("active");
  hideAllViews();
  $("view-translation").hidden = false;
  await loadTranslationProjects();
  if (workId) {
    try {
      $("tr-project").value = workId;
      await loadTranslationProject(workId, chapter);
      setTranslationStartVisible(false);
    } catch {
      await openTranslationStart();
      state.translation.startWorkId = workId;
      renderStartWorks();
      renderStartModes();
      return;
    }
  } else if (state.translation.projectId) {
    await loadTranslationProject(state.translation.projectId, chapter);
    setTranslationStartVisible(false);
  } else {
    await openTranslationStart();
    return;
  }
  if (state.translation.projectId) {
    setTranslationPath(state.translation.projectId, state.translation.selectedChapter);
  }
}

async function syncTranslationRefChapters() {
  const workId = state.translation.projectId;
  if (!workId) return;
  const overwrite = confirm(
    "Tách lại segments theo REF split_hints?\nCần overwrite=true nếu đã có segment — bản dịch cũ sẽ mất.",
  );
  if (!overwrite) return;
  try {
    const result = await api(`/api/translations/${encodeURIComponent(workId)}/sync-ref-chapters`, {
      method: "POST",
      body: { overwrite: true },
    });
    toast(`Đã sync ${result.segments_written} segments từ REF`);
    await loadTranslationView(workId, null);
  } catch (err) {
    toast(err.message);
  }
}

async function runTranslationPromote() {
  const workId = state.translation.projectId;
  if (!workId) return;
  const btn = $("tr-promote");
  const note = $("tr-promote-note");
  if (btn) btn.disabled = true;
  if (note) note.textContent = "Đang đưa vào catalog…";
  try {
    const result = await api(`/api/translations/${encodeURIComponent(workId)}/promote`, {
      method: "POST",
      body: {},
    });
    toast(`Catalog: ${result.work?.id || ""}`);
    await loadTranslationProject(workId, state.translation.selectedChapter);
  } catch (err) {
    if (note) note.textContent = err.message;
  }
}

function wireTranslation() {
  $("tr-pick-work").onclick = () => void openTranslationStart();
  $("tr-start-cancel").onclick = () => {
    if (state.translation.projectId) {
      setTranslationStartVisible(false);
      return;
    }
    state.translation.startWorkId = null;
    renderStartWorks();
  };
  $("tr-work-q").oninput = renderStartWorks;
  $("tr-work-rows").onclick = (event) => {
    const row = event.target.closest("tr[data-id]");
    if (row) void pickStartWork(row.dataset.id);
  };
  $("tr-mode-opts").onclick = (event) => {
    const btn = event.target.closest("[data-mode]");
    if (!btn) return;
    state.translation.startMode = btn.dataset.mode;
    renderStartModes();
    renderStartWorks();
  };
  $("tr-start-go").onclick = () => void confirmStartTranslation();
  $("tr-project").onchange = async () => {
    const workId = $("tr-project").value;
    if (workId) await loadTranslationProject(workId, null);
  };
  $("tr-rows").onclick = (e) => {
    const tr = e.target.closest("tr[data-chapter]");
    if (tr) selectTranslationChapter(tr.dataset.chapter, true);
  };
  $("tr-segment-close").onclick = () => showTranslationSegment(false);
  const partSelect = $("tr-part-select");
  if (partSelect) {
    partSelect.onchange = () => {
      state.translation.comparePart = partSelect.value || "all";
      showTranslationSegment(true);
    };
  }
  document.querySelectorAll("[data-compare-tab]").forEach((btn) => {
    btn.onclick = () => setCompareTab(btn.dataset.compareTab);
  });
  $("tr-promote").onclick = () => void runTranslationPromote();
  $("tr-sync-ref")?.addEventListener("click", () => void syncTranslationRefChapters());
  $("tr-draft-missing").onclick = () => void enqueueMissingDrafts();
  $("tr-cancel-jobs").onclick = () => void cancelActiveJobs();
}

function modelSelectOptions(catalog, current) {
  const groups = { deepseek: [], gemini: [], other: [] };
  const ids = new Set();
  for (const model of catalog || []) {
    if (!model?.id || ids.has(model.id)) continue;
    ids.add(model.id);
    const group = model.provider === "deepseek" || model.provider === "gemini" ? model.provider : "other";
    groups[group].push(model);
  }
  if (current && !ids.has(current)) {
    groups.other.unshift({ id: current, label: `${current} (đang chọn)`, provider: "" });
  }
  const titles = { deepseek: "DeepSeek", gemini: "Gemini", other: "Đang chọn / khác" };
  return ["deepseek", "gemini", "other"]
    .filter((key) => groups[key].length)
    .map((key) => {
      const options = groups[key]
        .map((model) => {
          const thinking = model.thinking ? " · thinking" : "";
          const title = model.description ? ` title="${escapeHtml(model.description)}"` : "";
          return `<option value="${escapeHtml(model.id)}"${title}${model.id === current ? " selected" : ""}>${escapeHtml(
            model.label || model.id,
          )}${thinking}</option>`;
        })
        .join("");
      return `<optgroup label="${titles[key]}">${options}</optgroup>`;
    })
    .join("");
}

function renderModelCatalogStatus(data) {
  const el = $("settings-models-status");
  if (!el) return;
  const counts = data.model_catalog_counts || {};
  const errors = data.model_catalog_errors || {};
  const deepseek = Number(counts.deepseek || 0);
  const gemini = Number(counts.gemini || 0);
  const parts = [`DeepSeek: ${deepseek} model`, `Gemini: ${gemini} model`];
  if (data.model_catalog_fetched_at) parts.push(`lúc ${data.model_catalog_fetched_at}`);
  const errText = Object.entries(errors)
    .map(([provider, message]) => `${provider}: ${message}`)
    .join(" · ");
  el.textContent = errText ? `${parts.join(" · ")} — ${errText}` : parts.join(" · ");
}

function renderSettingsKeys(secrets) {
  const s = secrets || {};
  const rows = [
    ["DeepSeek", s.deepseek ? "đã set" : "chưa set", s.deepseek],
    ["Gemini", s.gemini ? "đã set" : "chưa set", s.gemini],
    ["Read token", s.read_token ? "đã set" : "chưa set", s.read_token],
    ["Read API", s.read_api || "—", Boolean(s.read_token)],
  ];
  $("settings-keys").innerHTML = rows
    .map(
      ([label, value, ok]) =>
        `<div class="settings-key"><b>${escapeHtml(label)}</b><span class="badge ${ok ? "ok" : "bad"}">${escapeHtml(
          String(value),
        )}</span></div>`,
    )
    .join("");
}

function fillNumberInput(id, value, fallback) {
  const el = $(id);
  if (!el) return;
  const n = Number(value);
  const text = String(Number.isFinite(n) ? n : fallback);
  el.value = text;
  el.defaultValue = text;
}

function readNumberInput(id, fallback) {
  const n = Number($(id)?.value);
  return Number.isFinite(n) ? n : fallback;
}

function renderSettingsForm(data) {
  state.settings = data;
  const tr = data.settings?.translation || {};
  const models = tr.models || {};
  const catalog = data.model_catalog || [];
  const stages = data.stages || [];
  $("settings-models").innerHTML = stages
    .map(
      (stage) => `<label>${escapeHtml(stage.label)}
        <select data-model-slot="${escapeHtml(stage.id)}">${modelSelectOptions(catalog, models[stage.id])}</select>
        <span>${escapeHtml(stage.hint || "")}</span>
      </label>`,
    )
    .join("");
  $("set-auto-annotate").checked = Boolean(tr.auto_annotate);
  $("set-auto-qa").checked = Boolean(tr.auto_qa);
  const ed = data.settings?.edition || {};
  const gemini = Boolean(data.secrets?.gemini);
  const fillEdition = (id, value) => {
    const el = $(id);
    if (!el) return;
    el.checked = value !== false;
    el.disabled = !gemini;
  };
  fillEdition("set-llm-macro", ed.use_llm_macro);
  fillEdition("set-llm-relabel", ed.use_llm_relabel);
  fillEdition("set-llm-qa", ed.use_llm_qa);
  fillNumberInput("set-ed-min-workers", ed.min_workers, 1);
  fillNumberInput("set-ed-max-workers", ed.max_workers, 2);
  fillNumberInput("set-ed-max-attempts", ed.max_attempts, 2);
  fillNumberInput("set-ed-job-timeout", ed.job_timeout_sec, 600);
  fillNumberInput("set-min-workers", tr.min_workers, 1);
  fillNumberInput("set-max-workers", tr.max_workers, 2);
  fillNumberInput("set-max-attempts", tr.max_attempts, 2);
  fillNumberInput("set-job-timeout", tr.job_timeout_sec, 600);
  fillNumberInput("set-max-part-words", tr.max_part_words, 1200);
  fillNumberInput("set-hard-max-part-words", tr.hard_max_part_words, 1500);
  fillNumberInput("set-llm-retries", tr.llm_retries, 3);
  fillNumberInput("set-gemini-rpm", tr.gemini_rpm, 12);
  fillNumberInput("set-deepseek-rpm", tr.deepseek_rpm, 30);
  $("set-default-mode").value = tr.default_mode || "normal";
  renderSettingsKeys(data.secrets);
  renderModelCatalogStatus(data);
  const note = $("settings-note");
  if (note) {
    note.textContent = data.updated_at ? `Đã lưu ${data.updated_at}` : "Chưa lưu file — đang dùng mặc định Hub.";
  }
  $("settings-err").textContent = "";
}

async function refreshModelCatalog() {
  const selected = {};
  document.querySelectorAll("[data-model-slot]").forEach((el) => {
    selected[el.dataset.modelSlot] = el.value;
  });
  const btn = $("settings-refresh-models");
  if (btn) btn.disabled = true;
  $("settings-err").textContent = "";
  try {
    const data = await api("/api/settings?refresh=true");
    if (data.settings?.translation) {
      data.settings.translation.models = {
        ...(data.settings.translation.models || {}),
        ...selected,
      };
    }
    renderSettingsForm(data);
    toast("Đã tải danh sách model từ API");
  } catch (err) {
    $("settings-err").textContent = err.message;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function loadSettings() {
  const data = await api("/api/settings");
  renderSettingsForm(data);
  return data;
}

async function loadSettingsView() {
  document.querySelectorAll(".nav-link").forEach((b) => b.classList.remove("active"));
  document.querySelector('.nav-link[data-view="settings"]')?.classList.add("active");
  hideAllViews();
  $("view-settings").hidden = false;
  if (location.pathname !== "/settings") {
    history.replaceState({ view: "settings" }, "", "/settings");
  }
  try {
    await loadSettings();
  } catch (err) {
    $("settings-err").textContent = err.message;
  }
}

async function saveSettings(e) {
  e.preventDefault();
  const models = {};
  document.querySelectorAll("[data-model-slot]").forEach((el) => {
    models[el.dataset.modelSlot] = el.value;
  });
  $("settings-err").textContent = "";
  const btn = $("settings-save");
  if (btn) btn.disabled = true;
  try {
    const data = await api("/api/settings", {
      method: "POST",
      body: {
        translation: {
          models,
          auto_annotate: $("set-auto-annotate").checked,
          auto_qa: $("set-auto-qa").checked,
          min_workers: readNumberInput("set-min-workers", 1),
          max_workers: readNumberInput("set-max-workers", 2),
          max_attempts: readNumberInput("set-max-attempts", 2),
          job_timeout_sec: readNumberInput("set-job-timeout", 600),
          max_part_words: readNumberInput("set-max-part-words", 1200),
          hard_max_part_words: readNumberInput("set-hard-max-part-words", 1500),
          llm_retries: readNumberInput("set-llm-retries", 3),
          gemini_rpm: readNumberInput("set-gemini-rpm", 12),
          deepseek_rpm: readNumberInput("set-deepseek-rpm", 30),
          default_mode: $("set-default-mode").value,
        },
        edition: {
          use_llm_macro: $("set-llm-macro").checked,
          use_llm_relabel: $("set-llm-relabel").checked,
          use_llm_qa: $("set-llm-qa").checked,
          min_workers: readNumberInput("set-ed-min-workers", 1),
          max_workers: readNumberInput("set-ed-max-workers", 2),
          max_attempts: readNumberInput("set-ed-max-attempts", 2),
          job_timeout_sec: readNumberInput("set-ed-job-timeout", 600),
        },
      },
    });
    renderSettingsForm(data);
    const n = Number(data.projects_updated || 0);
    toast(n ? `Đã lưu cài đặt · cập nhật ${n} dự án dịch` : "Đã lưu cài đặt");
  } catch (err) {
    $("settings-err").textContent = err.message;
  } finally {
    if (btn) btn.disabled = false;
  }
}

function wireSettings() {
  $("settings-form").onsubmit = (e) => void saveSettings(e);
  $("settings-refresh-models").onclick = () => void refreshModelCatalog();
}

function collectPublishPayload(apply) {
  const paid = document.querySelector("input[name=pricing]:checked")?.value === "paid";
  const dollars = Number($("pub-price").value || 0);
  return {
    apply,
    persist: $("pub-persist").checked,
    title: $("pub-title").value.trim(),
    description: $("pub-description").value,
    category_slug: $("pub-category").value,
    price_cents: paid ? Math.max(0, Math.round(dollars * 100)) : 0,
    split_length: state.splitLength || "standard",
  };
}

async function sendPublish(apply) {
  const id = state.publishId;
  const out = $("pub-result");
  out.textContent = "Đang gửi…";
  try {
    const result = await api(`/api/works/${encodeURIComponent(id)}/publish-read`, {
      method: "POST",
      body: collectPublishPayload(apply),
    });
    out.textContent = JSON.stringify(result, null, 2);
    toast(apply ? "Đã gửi sang Read (pending_review)" : "Dry-run xong — chưa gọi Read");
  } catch (err) {
    out.textContent = err.message;
  }
}

async function loadPublishPage(id) {
  state.publishId = id;
  hideAllViews();
  $("view-publish").hidden = false;
  document.querySelectorAll(".nav-link").forEach((b) => b.classList.remove("active"));
  $("pub-heading").textContent = "Đang tải…";
  $("pub-form").hidden = true;
  $("pub-gate").hidden = true;
  const [data, options] = await Promise.all([
    api(`/api/works/${encodeURIComponent(id)}`),
    api("/api/read-options"),
  ]);
  const { work, summary } = data;
  $("pub-heading").textContent = work.title;
  $("pub-title").value = work.title || "";
  $("pub-description").value = work.description || work.title || "";
  $("pub-author").textContent = work.author_id || "";
  $("pub-lang").textContent = `${work.language || "en"} · ${work.year ?? "—"}`;
  $("pub-license").textContent = work.license || "—";
  $("pub-split-note").textContent = options.split_note || "";
  const cat = $("pub-category");
  const currentCat = summary.category_slug || "essays";
  cat.innerHTML = (options.categories || [])
    .map(
      (c) =>
        `<option value="${escapeHtml(c.slug)}" ${c.slug === currentCat ? "selected" : ""}>${escapeHtml(c.label)}</option>`,
    )
    .join("");
  state.splitLength = summary.split_length || "standard";
  $("pub-split").innerHTML = (options.split_lengths || [])
    .map((opt) => {
      const on = opt.value === state.splitLength ? "on" : "";
      return `<button type="button" class="split-opt ${on}" data-split="${escapeHtml(opt.value)}">
        <strong>${escapeHtml(opt.label)}</strong>
        <small>${escapeHtml(opt.hint)} · ~${opt.target_words} từ</small>
      </button>`;
    })
    .join("");
  const cents = Number(summary.price_cents || 0);
  const paid = cents > 0;
  document.querySelector(`input[name=pricing][value=${paid ? "paid" : "free"}]`).checked = true;
  $("pub-price").disabled = !paid;
  if (paid) $("pub-price").value = (cents / 100).toFixed(2);
  const ready = summary.read_allowed && summary.has_raw && summary.has_hash;
  $("pub-form").hidden = false;
  $("pub-dry").disabled = !ready;
  $("pub-apply").disabled = !ready;
  if (!ready) {
    $("pub-gate").hidden = false;
    $("pub-gate").textContent =
      "Cần Allow Read + file raw + content_hash (Hash raw trên trang tác phẩm) trước khi gửi Read. Vẫn sửa được category / split rồi lưu khi publish.";
  }
  if (!state.health?.read_token_set) {
    $("pub-gate").hidden = false;
    $("pub-gate").textContent =
      ($("pub-gate").textContent ? `${$("pub-gate").textContent}\n` : "") +
      `Set READ_HUB_TOKEN (trùng HUB_SYNC_TOKEN) và READ_API_URL=${state.health?.read_api || ""}.`;
  }
}

function wirePublishForm() {
  $("pub-split").onclick = (e) => {
    const btn = e.target.closest("[data-split]");
    if (!btn) return;
    state.splitLength = btn.dataset.split;
    $("pub-split").querySelectorAll(".split-opt").forEach((el) => el.classList.toggle("on", el === btn));
  };
  document.querySelectorAll("input[name=pricing]").forEach((el) => {
    el.addEventListener("change", () => {
      const paid = document.querySelector("input[name=pricing]:checked")?.value === "paid";
      $("pub-price").disabled = !paid;
    });
  });
  $("pub-preview").onclick = () => {
    if (state.publishId) openPreview(state.publishId, false);
  };
  $("pub-dry").onclick = () => sendPublish(false);
  $("pub-form").onsubmit = (e) => {
    e.preventDefault();
    const title = $("pub-title").value.trim();
    if (!title) return;
    if (confirm(`Gửi “${title}” lên Read (pending_review)?`)) sendPublish(true);
  };
}

function wireNav() {
  document.querySelectorAll(".nav-link").forEach((btn) => {
    btn.onclick = () => {
      const view = btn.dataset.view;
      if (publishWorkIdFromPath()) {
        location.href = "/";
        return;
      }
      if (translationFromPath() && view !== "translation" && view !== "settings") {
        location.href = "/";
        return;
      }
      if (readEditionFromPath() !== null && view !== "read-edition" && view !== "settings") {
        location.href = "/";
        return;
      }
      document.querySelectorAll(".nav-link").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      if (view === "settings") {
        void loadSettingsView();
        return;
      }
      if (settingsFromPath()) history.replaceState({ view }, "", "/");
      hideAllViews();
      $("view-works").hidden = view !== "works";
      $("view-licenses").hidden = view !== "licenses";
      if (view === "translation") {
        $("view-translation").hidden = false;
        void loadTranslationView(null, null);
      }
      if (view === "read-edition") {
        // Nav always opens Đang làm, even when already on /read-edition/<work>.
        void window.KHReadEdition?.pickWork();
      }
    };
  });
}

async function refresh() {
  const [stats, works, sessions] = await Promise.all([
    api("/api/stats"),
    api("/api/works"),
    api("/api/read-editions").catch(() => ({ sessions: [] })),
  ]);
  state.works = works.works;
  state.editionByWork = Object.fromEntries((sessions.sessions || []).map((s) => [s.work_id, s]));
  renderStats(stats);
  renderRows();
}

async function loadLicenses() {
  const data = await api("/api/licenses");
  $("licenses").innerHTML = (data.licenses || [])
    .map(
      (l) =>
        `<li><strong>${escapeHtml(l.label)}</strong><br /><code>${escapeHtml(l.id)}</code><br />${escapeHtml(
          l.description || "",
        )}</li>`,
    )
    .join("");
}

async function boot() {
  wireNav();
  wirePublishForm();
  wireTranslation();
  wireSettings();
  $("preview-close").onclick = closePreview;
  $("preview").onclick = (e) => {
    if (e.target.id === "preview") closePreview();
  };
  $("preview-full").onclick = () => {
    if (state.previewId) openPreview(state.previewId, true);
  };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("preview").hidden) closePreview();
  });
  $("q").oninput = renderRows;
  $("filter").onchange = renderRows;
  $("lang").onchange = renderRows;
  $("rows").onclick = (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (tr) selectWork(tr.dataset.id);
  };
  $("btn-validate").onclick = async () => {
    const r = await api("/api/validate", { method: "POST" });
    toast(r.ok ? "Catalog ok" : `${r.errors.length} lỗi`);
    if (!r.ok) alert(r.errors.join("\n"));
  };
  $("btn-hash").onclick = async () => {
    const r = await api("/api/hash", { method: "POST" });
    toast(`Hash: ${r.updated} cập nhật, ${r.missing_raw} thiếu raw`);
    await refresh();
  };
  $("login-form").onsubmit = async (e) => {
    e.preventDefault();
    $("login-err").textContent = "";
    try {
      await api("/api/login", { method: "POST", body: { secret: $("login-secret").value } });
      $("login").hidden = true;
      await afterAuth();
    } catch (err) {
      $("login-err").textContent = err.message;
    }
  };
  try {
    state.health = await api("/api/health");
    $("health").innerHTML = `Read API<br />${escapeHtml(state.health.read_api)}<br />token: ${
      state.health.read_token_set ? "đã set" : "chưa set"
    }`;
    if (state.health.auth) {
      try {
        await api("/api/stats");
      } catch {
        $("login").hidden = false;
        return;
      }
    }
    await afterAuth();
  } catch (err) {
    toast(err.message);
  }
}

async function afterAuth() {
  const pubId = publishWorkIdFromPath();
  if (pubId) {
    await loadPublishPage(pubId);
    return;
  }
  const tr = translationFromPath();
  if (tr) {
    await loadTranslationView(tr.workId, tr.chapter);
    return;
  }
  if (settingsFromPath()) {
    await loadSettingsView();
    return;
  }
  const reId = readEditionFromPath();
  if (reId !== null) {
    if (reId) await window.KHReadEdition?.load(reId);
    else await window.KHReadEdition?.pickWork();
    return;
  }
  await loadDesk();
}

async function loadDesk() {
  await refresh();
  await loadLicenses();
}

boot();
