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
    busy: false,
    lastError: "",
  },
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
      </tr>`;
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
        <a class="btn primary" id="apply" href="/publish/${encodeURIComponent(id)}">Publish to Read</a>
      </div>
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
  $("preview-meta").textContent = `${(n.published_chars || 0).toLocaleString()} chữ đã normalize` +
    (n.source_chars ? ` · nguồn ${(n.source_chars).toLocaleString()}` : "") +
    (dropped.length ? ` · đã cắt: ${dropped.join(", ")}` : " · không cắt thêm");
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

function statusBadge(status, hasFinal) {
  if (status === "draft_ready" && hasFinal) return `<span class="badge ok">draft_ready</span>`;
  if (status === "approved") return `<span class="badge ok">approved</span>`;
  if (hasFinal) return `<span class="badge ok">${escapeHtml(status || "có bản dịch")}</span>`;
  return `<span class="badge">${escapeHtml(status || "chưa dịch")}</span>`;
}

function kindBadge(kind) {
  const map = {
    footnote: ["kind-footnote", "footnote"],
    glossary: ["kind-glossary", "glossary"],
    context: ["kind-context", "context"],
  };
  const [cls, label] = map[kind] || ["", kind || "note"];
  return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
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
}

function renderTranslationRows() {
  const chapters = state.translation.chapters || [];
  const selected = state.translation.selectedChapter;
  $("tr-rows").innerHTML = chapters
    .map((c) => {
      const on = selected === c.chapter ? "on" : "";
      const qa = c.qa_overall != null ? `${c.qa_overall}/10` : "—";
      const ann = c.annotations_generated_at ? "✓" : "—";
      return `<tr class="pick ${on}" data-chapter="${escapeHtml(c.chapter)}">
        <td><div class="title">Chương ${escapeHtml(c.chapter)}</div><div class="sub">${escapeHtml(String(c.words || "—"))} từ</div></td>
        <td>${statusBadge(c.status, c.has_final)}</td>
        <td>${escapeHtml(qa)}${c.issue_count ? `<div class="sub">${c.issue_count} vấn đề</div>` : ""}</td>
        <td>${escapeHtml(ann)}</td>
      </tr>`;
    })
    .join("");
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
  const hasTranslation = Boolean((seg.translation || "").trim());
  const scoreHtml = qa.scores
    ? `<div class="tr-score-grid">
        ${scoreBar("Trung thực", scores.fidelity)}
        ${scoreBar("Mạch lạc", scores.fluency)}
        ${scoreBar("Thuật ngữ", scores.terminology)}
        ${scoreBar("Đầy đủ", scores.completeness)}
        ${scoreBar("Tổng thể", scores.overall)}
      </div>`
    : `<p class="muted">Chưa chạy QA cho chương này.</p>`;
  box.innerHTML = `
    <h2>Chương ${escapeHtml(chapter)}</h2>
    <p class="sub">${escapeHtml(seg.status || "")} · ${escapeHtml(String(seg.words || "—"))} từ</p>
    ${scoreHtml}
    ${qa.summary_vi ? `<div class="tr-summary">${escapeHtml(qa.summary_vi)}</div>` : ""}
    ${
      issues.length
        ? `<ul class="tr-issues">${issues
            .map(
              (issue) => `<li>
                <div class="meta">
                  <span class="badge ${issue.severity === "major" ? "major" : "minor"}">${escapeHtml(issue.severity || "minor")}</span>
                  <span class="badge">${escapeHtml(issue.category || "other")}</span>
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
              </li>`,
            )
            .join("")}</ul>`
        : qa.scores
          ? `<p class="muted">Không có vấn đề được ghi nhận.</p>`
          : ""
    }
    <div class="row">
      <button class="btn ghost" id="tr-btn-segment" type="button" ${hasTranslation ? "" : "disabled"}>Xem đoạn EN ↔ VI</button>
      <button class="btn ${hasTranslation ? "ghost" : "primary"}" id="tr-btn-draft" type="button" ${state.translation.busy ? "disabled" : ""}>${hasTranslation ? "Dịch lại" : "Dịch chương"}</button>
      <button class="btn ghost" id="tr-btn-qa" type="button" ${state.translation.busy || !hasTranslation ? "disabled" : ""}>${qa.scores ? "Chạy lại QA" : "Chạy QA"}</button>
      <button class="btn" id="tr-btn-annotate" type="button" ${state.translation.busy || !hasTranslation ? "disabled" : ""}>${seg.annotations_generated_at ? "Tạo lại chú thích" : "Tạo chú thích"}</button>
    </div>
    <pre class="err" id="tr-action-out">${escapeHtml(state.translation.lastError || "")}</pre>
  `;
  $("tr-btn-segment").onclick = () => showTranslationSegment(true);
  $("tr-btn-draft").onclick = () => runTranslationDraft();
  $("tr-btn-qa").onclick = () => runTranslationQA();
  $("tr-btn-annotate").onclick = () => runTranslationAnnotate();
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
              ${a.marker ? `<strong>${escapeHtml(a.title_vi || a.marker)}</strong>` : `<strong>${escapeHtml(a.title_vi || "Chú thích")}</strong>`}
              ${a.anchor_text ? `<span class="anchor">↳ ${escapeHtml(a.anchor_text)}</span>` : ""}
            </div>
            <p>${escapeHtml(a.body_vi || "")}</p>
          </article>`,
        )
        .join("")
    : `<p class="muted">Chưa có chú thích. Bấm “Tạo chú thích” ở panel bên phải.</p>`;
}

function showTranslationSegment(show) {
  const seg = state.translation.segment;
  const block = $("tr-segment");
  if (!show || !seg) {
    block.hidden = true;
    return;
  }
  $("tr-segment-title").textContent = `Chương ${seg.chapter}`;
  $("tr-source").textContent = seg.source_text || "";
  $("tr-translation").textContent = seg.translation || "";
  renderTranslationAnnotations();
  block.hidden = false;
  block.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadTranslationProjects() {
  const data = await api("/api/translations");
  state.translation.projects = data.projects || [];
  const select = $("tr-project");
  select.innerHTML = (data.projects || [])
    .map(
      (p) =>
        `<option value="${escapeHtml(p.source_work_id)}" ${p.source_work_id === state.translation.projectId ? "selected" : ""}>${escapeHtml(p.source_title || p.source_work_id)} (${escapeHtml(p.target_language || "vi")})</option>`,
    )
    .join("");
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
  renderTranslationStats();
  renderTranslationRows();
  const pick =
    chapterHint && data.chapters.some((c) => c.chapter === chapterHint)
      ? chapterHint
      : data.chapters.find((c) => c.has_final)?.chapter || data.chapters[0]?.chapter || null;
  if (pick) await selectTranslationChapter(pick, false);
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
  state.translation.selectedChapter = chapter;
  state.translation.segment = null;
  state.translation.lastError = "";
  renderTranslationRows();
  renderTranslationDetail();
  setTranslationPath(workId, chapter);
  try {
    const [seg, ann] = await Promise.all([
      api(`/api/translations/${encodeURIComponent(workId)}/segments/${encodeURIComponent(chapter)}`),
      api(`/api/translations/${encodeURIComponent(workId)}/annotations?chapter=${encodeURIComponent(chapter)}`),
    ]);
    state.translation.segment = seg;
    state.translation.annotations = ann.annotations || [];
    renderTranslationDetail();
    if (showSegment) showTranslationSegment(true);
    else renderTranslationAnnotations();
  } catch (err) {
    $("tr-detail").innerHTML = `<p class="err">${escapeHtml(err.message)}</p>`;
  }
}

async function runTranslationAction(kind) {
  const workId = state.translation.projectId;
  const chapter = state.translation.selectedChapter;
  if (!workId || !chapter) return;
  const labels = {
    draft: "Đang dịch (DeepSeek → Gemini)… có thể mất vài phút.",
    qa: "Đang chấm QA (DeepSeek)… có thể mất 1–2 phút.",
    annotate: "Đang tạo chú thích (Gemini)…",
  };
  const paths = {
    draft: `/api/translations/${encodeURIComponent(workId)}/draft/${encodeURIComponent(chapter)}`,
    qa: `/api/translations/${encodeURIComponent(workId)}/qa/${encodeURIComponent(chapter)}`,
    annotate: `/api/translations/${encodeURIComponent(workId)}/annotate/${encodeURIComponent(chapter)}`,
  };
  state.translation.lastError = "";
  state.translation.busy = true;
  renderTranslationDetail();
  const out = $("tr-action-out");
  if (out) out.textContent = labels[kind];
  try {
    const result = await api(paths[kind], { method: "POST" });
    if (kind === "qa") toast(`QA xong — tổng thể ${result.scores?.overall ?? "?"}/10`);
    if (kind === "annotate") toast(`Đã cập nhật ${result.added_or_updated} chú thích (tổng ${result.total})`);
    if (kind === "draft") toast(`Đã dịch chương ${chapter} (${result.final_chars || "?"} chữ)`);
    await loadTranslationProject(workId, chapter);
    showTranslationSegment(true);
  } catch (err) {
    state.translation.lastError = err.message;
  } finally {
    state.translation.busy = false;
    renderTranslationDetail();
  }
}

async function runTranslationDraft() {
  await runTranslationAction("draft");
}

async function runTranslationQA() {
  await runTranslationAction("qa");
}

async function runTranslationAnnotate() {
  await runTranslationAction("annotate");
}

async function loadTranslationView(workId, chapter) {
  document.querySelectorAll(".nav-link").forEach((b) => b.classList.remove("active"));
  document.querySelector('.nav-link[data-view="translation"]')?.classList.add("active");
  $("view-works").hidden = true;
  $("view-licenses").hidden = true;
  $("view-publish").hidden = true;
  $("view-translation").hidden = false;
  await loadTranslationProjects();
  if (workId) {
    $("tr-project").value = workId;
    await loadTranslationProject(workId, chapter);
  } else if (state.translation.projectId) {
    await loadTranslationProject(state.translation.projectId, chapter);
  }
  if (state.translation.projectId) {
    setTranslationPath(state.translation.projectId, state.translation.selectedChapter);
  }
}

function wireTranslation() {
  $("tr-project").onchange = async () => {
    const workId = $("tr-project").value;
    if (workId) await loadTranslationProject(workId, null);
  };
  $("tr-rows").onclick = (e) => {
    const tr = e.target.closest("tr[data-chapter]");
    if (tr) selectTranslationChapter(tr.dataset.chapter, false);
  };
  $("tr-segment-close").onclick = () => showTranslationSegment(false);
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
  $("view-works").hidden = true;
  $("view-licenses").hidden = true;
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
      if (publishWorkIdFromPath()) {
        location.href = "/";
        return;
      }
      if (translationFromPath()) {
        location.href = "/";
        return;
      }
      document.querySelectorAll(".nav-link").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const view = btn.dataset.view;
      $("view-works").hidden = view !== "works";
      $("view-licenses").hidden = view !== "licenses";
      $("view-publish").hidden = true;
      $("view-translation").hidden = view !== "translation";
      if (view === "translation") loadTranslationView(null, null);
    };
  });
}

async function refresh() {
  const [stats, works] = await Promise.all([api("/api/stats"), api("/api/works")]);
  state.works = works.works;
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
  await loadDesk();
}

async function loadDesk() {
  await refresh();
  await loadLicenses();
}

boot();
