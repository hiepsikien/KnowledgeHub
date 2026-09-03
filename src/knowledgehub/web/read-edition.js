/* Read Edition CMS — two-step: macro (LLM chapters) + micro (per-chapter REF parse) */

(function () {
  const $ = (id) => document.getElementById(id);
  const state = {
    workId: null,
    chapterId: null,
    manifest: null,
    chapter: null,
    status: null,
    selected: new Set(),
    editIndex: null,
    review: null,
    editionSettings: { use_llm_macro: true, use_llm_relabel: true, use_llm_qa: true },
    step: "structure",
    hitlJob: null,
    hitlOverview: null,
    suspectsOnly: true,
    chapterLoad: 0,
    pageLoad: 0,
    hitlJobLoad: 0,
    hitlOverviewLoad: 0,
    chapterAbort: null,
    jobs: [],
    jobLog: [],
    workers: null,
    pollTimer: null,
  };

  const HITL_STEPS = {
    wrap: {
      title: "Nối dòng",
      lead: "Ghép dòng bị cắt cứng. Chỗ chắc được auto OK (hoàn tác từng chỗ được). Chỉ hiện chỗ nghi ngờ — duyệt hoặc bỏ tất cả. «Parse chương này» (cạnh tiêu đề) cũng quét bước này rồi mới dựng REF.",
    },
    footnotes: {
      title: "Chú thích",
      lead: "Nối marker ([1], [2]…) với nội dung chú thích. Chỗ khớp chắc được auto OK. Ghi chú lấy từ FOOTNOTES cuối sách vẫn nghi ngờ — phải bấm OK. Có nút duyệt / bỏ tất cả nghi ngờ.",
    },
    quotes: {
      title: "Trích dẫn & nhấn mạnh",
      lead: "Đánh dấu blockquote, ngoặc kép, và in nghiêng (_…_). Chỗ chắc auto OK (hoàn tác được). Ngữ cảnh lấy quanh đúng cụm. Thiếu dấu đóng chỉ ghi nhận (Đã xem). Có nút duyệt / bỏ tất cả nghi ngờ.",
    },
  };
  const FINAL_STEP = {
    title: "Final Touch",
    lead: "Xem layout gần Read. Matcher đã gắn sidenote/gia phả/synopsis; chỉ sửa chỗ còn lệch: ẩn, hiện, ghép, tách, đổi type.",
  };

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      method: opts.method || "GET",
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      credentials: "same-origin",
      signal: opts.signal,
    });
    const text = await res.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      throw new Error(text || res.statusText);
    }
    if (!res.ok) throw new Error(data.detail || data.message || text || res.statusText);
    return data;
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function toast(msg) {
    const el = $("toast");
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(el._t);
    el._t = setTimeout(() => {
      el.hidden = true;
    }, 3200);
  }

  function activeJobs(jobs) {
    return (jobs || []).filter((job) => job.status === "queued" || job.status === "running");
  }

  function jobKindLabel(kind, job) {
    if (kind === "macro") return job?.keep_toc || job?.params?.keep_toc ? "phân loại lại" : "phân đoạn";
    if (kind === "parse") return "parse REF";
    if (kind === "qa") return "QA";
    if (kind === "hitl_scan") {
      const labels = { wrap: "nối dòng", footnotes: "chú thích", quotes: "trích dẫn" };
      const hk = job?.hitl_kind || job?.params?.hitl_kind || "";
      const scope = job?.scope || job?.params?.scope || "";
      return `quét ${labels[hk] || hk}${scope === "book" ? " (sách)" : ""}`;
    }
    return kind || "job";
  }

  function jobElapsed(job) {
    const start = job?.started_at || job?.heartbeat_at;
    if (!start || (job.status !== "running" && job.status !== "queued")) return "";
    const sec = Math.max(0, Math.round((Date.now() - Date.parse(start)) / 1000));
    if (!Number.isFinite(sec)) return "";
    if (sec < 60) return `${sec}s`;
    return `${Math.floor(sec / 60)}p${String(sec % 60).padStart(2, "0")}s`;
  }

  function workerRangeLabel() {
    const workers = state.workers || state.editionSettings || {};
    const min = Number(workers.min_workers ?? 1);
    const max = Number(workers.max_workers ?? 2);
    if (min === max) return `Worker chế bản ${max} luồng`;
    return `Worker chế bản ${min}–${max} luồng`;
  }

  function applyJobsPayload(data) {
    if (!data) return;
    if (Array.isArray(data.jobs)) state.jobs = data.jobs;
    if (Array.isArray(data.log)) state.jobLog = data.log;
    if (data.workers) state.workers = data.workers;
  }

  function chapterActiveJob(chapterId) {
    if (!chapterId) return null;
    return (
      activeJobs(state.jobs).find(
        (job) => job.chapter === chapterId && (job.kind === "parse" || job.kind === "qa" || job.kind === "hitl_scan"),
      ) || null
    );
  }

  function workScopedActive() {
    return activeJobs(state.jobs).some(
      (job) => job.kind === "macro" || (job.kind === "hitl_scan" && (job.scope || job.params?.scope) === "book"),
    );
  }

  function hitlScanBusy() {
    return activeJobs(state.jobs).some(
      (job) => job.kind === "hitl_scan" && (job.hitl_kind || job.params?.hitl_kind) === hitlKind(),
    );
  }

  function renderJobQueue() {
    const el = $("re-jobs");
    if (!el) return;
    const jobs = activeJobs(state.jobs);
    const cancelBtn = $("re-cancel-jobs");
    if (cancelBtn) {
      cancelBtn.hidden = jobs.length === 0;
      cancelBtn.disabled = jobs.length === 0;
    }
    if (!jobs.length) {
      const workers = state.workers;
      el.textContent = workers ? `${workerRangeLabel()}` : "";
      return;
    }
    const running = jobs.filter((job) => job.status === "running");
    const waiting = jobs.filter((job) => job.status === "queued");
    const parts = [];
    if (running.length) {
      parts.push(
        `Đang ${running
          .map((job) => {
            const phase = job.detail || job.phase || jobKindLabel(job.kind, job);
            const elapsed = jobElapsed(job);
            const ch = job.kind === "macro" || job.chapter === "*" ? "" : ` ${job.chapter}`;
            return `${jobKindLabel(job.kind, job)}${ch}: ${phase}${elapsed ? ` · ${elapsed}` : ""}`;
          })
          .join("; ")}`,
      );
    }
    if (waiting.length) {
      parts.push(
        `chờ ${waiting
          .map((job) => {
            const label = jobKindLabel(job.kind, job);
            const ch = job.kind === "macro" || job.chapter === "*" ? "" : ` ${job.chapter}`;
            return `${label}${ch}${job.phase === "retry" ? " (thử lại)" : ""}`;
          })
          .join(", ")}`,
      );
    }
    const alive = Number(state.workers?.alive || 0);
    if (alive > 1) parts.push(`${alive} luồng`);
    el.textContent = parts.join(" · ");
  }

  function renderJobLog() {
    const el = $("re-job-log");
    if (!el) return;
    const rows = (state.jobLog || []).slice(-12);
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

  function notifyJobChanges(prev, next) {
    for (const job of next) {
      const old = prev.find((item) => item.id === job.id);
      if (!old) continue;
      const label = jobKindLabel(job.kind, job);
      const ch = job.kind === "macro" || job.chapter === "*" ? "" : ` ${job.chapter}`;
      if (old.status !== "done" && job.status === "done") toast(`Xong ${label}${ch}`);
      if (old.status !== "error" && job.status === "error") {
        toast(`${label}${ch}: ${(job.error || "lỗi").slice(0, 140)}`);
      }
      if (old.status !== "cancelled" && job.status === "cancelled") toast(`Đã hủy ${label}${ch}`);
      if (old.status !== "interrupted" && job.status === "interrupted") {
        toast(`Ngắt ${label}${ch} — không tự chạy lại`);
      }
    }
  }

  function startJobPoll() {
    if (state.pollTimer) return;
    state.pollTimer = setInterval(() => void refreshEditionJobs(), 2500);
  }

  function stopJobPoll() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  async function refreshEditionJobs() {
    const workId = state.workId;
    if (!workId || $("view-read-edition")?.hidden || !$("re-pick")?.hidden) return;
    try {
      const prev = state.jobs || [];
      const data = await api(`/api/works/${encodeURIComponent(workId)}/read-edition`);
      if (state.workId !== workId) return;
      const next = data.jobs || [];
      notifyJobChanges(prev, next);
      applyJobsPayload(data);
      state.status = data;
      if (data.manifest) state.manifest = data.manifest;
      $("re-status").textContent = formatStatus(data);
      renderJobQueue();
      renderJobLog();
      if (state.manifest) renderChapterList(state.manifest);
      syncToolbar();
      const justDone = next.filter(
        (job) => job.status === "done" && prev.some((item) => item.id === job.id && item.status !== "done"),
      );
      if (justDone.some((job) => job.kind === "macro")) {
        await loadReadEditionPage(workId);
        return;
      }
      if (justDone.some((job) => job.kind === "parse" || job.kind === "qa")) {
        await loadReview();
        await loadHitlOverview();
        if (hitlKind()) await loadHitlJob();
        if (state.chapterId) await selectChapter(state.chapterId);
      }
      if (justDone.some((job) => job.kind === "hitl_scan")) {
        await loadHitlOverview();
        await loadHitlJob();
      }
      if (activeJobs(next).length) startJobPoll();
      else stopJobPoll();
    } catch {
      /* keep polling; next tick retries */
    }
  }

  async function enqueueEdition(body, queuedToast) {
    const result = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/jobs`, {
      method: "POST",
      body,
    });
    if (result.workers) state.workers = result.workers;
    if (Array.isArray(result.log)) state.jobLog = result.log;
    const incoming = result.job ? [result.job] : result.jobs || [];
    if (incoming.length) {
      const byId = new Map((state.jobs || []).map((job) => [job.id, job]));
      for (const job of incoming) byId.set(job.id, job);
      state.jobs = [...byId.values()];
    } else if (Array.isArray(result.jobs)) {
      state.jobs = result.jobs;
    }
    renderJobQueue();
    renderJobLog();
    if (state.manifest) renderChapterList(state.manifest);
    syncToolbar();
    startJobPoll();
    const created = result.enqueued ?? (result.job?.created ? 1 : 0);
    toast(created ? queuedToast : "Job này đang chạy hoặc đã xếp hàng");
    return result;
  }

  async function cancelActiveJobs() {
    if (!state.workId) return;
    try {
      const result = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/jobs/cancel`, {
        method: "POST",
        body: {},
      });
      applyJobsPayload(result);
      renderJobQueue();
      renderJobLog();
      syncToolbar();
      toast(result.cancelled ? `Đã hủy ${result.cancelled} job` : "Không có job đang chạy");
    } catch (err) {
      toast(err.message);
    }
  }

  function readEditionWorkFromPath() {
    const parts = location.pathname.replace(/^\/+/, "").split("/").filter(Boolean);
    if (parts[0] !== "read-edition") return null;
    if (parts[1]) return decodeURIComponent(parts.slice(1).join("/"));
    return "";
  }

  function spanClass(style) {
    return `re-span re-span-${String(style || "other").replace(/[^a-z0-9_-]/gi, "")}`;
  }

  function tooltipText(note, style) {
    const raw = note || style || "";
    if (raw.length <= 280) return raw;
    return `${raw.slice(0, 277)}…`;
  }

  function noteElementId(marker) {
    const nums = String(marker || "").match(/\d+/g) || [];
    return nums.length ? `re-note-${nums[0]}` : "";
  }

  function collectNotes(chapter) {
    const rows = [];
    const seen = new Set();
    for (const note of chapter.notes || []) {
      const marker = String(note.marker || "");
      if (!marker || !note.body || seen.has(marker)) continue;
      seen.add(marker);
      rows.push(note);
    }
    if (rows.length) return rows;
    for (const block of chapter.blocks || []) {
      for (const span of block.spans || []) {
        if (span.style !== "footnote" || !span.note || seen.has(span.text)) continue;
        seen.add(span.text);
        rows.push({ marker: span.text, body: span.note, anchor: span.anchor || "" });
      }
    }
    return rows;
  }

  function renderNotes(chapter) {
    const notes = collectNotes(chapter);
    if (!notes.length) {
      const orphan = (chapter.blocks || []).some((b) =>
        (b.spans || []).some((s) => s.style === "footnote" && !s.note),
      );
      if (!orphan) return "";
      return `<section class="re-notes"><h3>Chú thích</h3><p class="muted">Có mốc chú thích nhưng chưa gắn được nội dung từ cuối chương.</p></section>`;
    }
    const items = notes
      .map((note) => {
        const marker = escapeHtml(note.marker || "");
        const anchor = note.anchor ? `<span class="re-note-anchor">${escapeHtml(note.anchor)}</span> ` : "";
        const id = noteElementId(note.marker);
        return `<li id="${id}"><strong>${anchor}${marker}</strong> ${escapeHtml(note.body)}</li>`;
      })
      .join("");
    return `<section class="re-notes"><h3>Chú thích (${notes.length})</h3><ol>${items}</ol></section>`;
  }

  function renderBlock(block) {
    const kind = block.type || "paragraph";
    const text = String(block.text || "");
    const spans = block.spans || [];
    let inner = escapeHtml(text);
    if (spans.length) {
      const parts = [];
      let cursor = 0;
      const sorted = [...spans].sort((a, b) => (a.start || 0) - (b.start || 0));
      for (const span of sorted) {
        const start = span.start || 0;
        const end = span.end || start;
        if (start > cursor) parts.push(escapeHtml(text.slice(cursor, start)));
        const note = span.note ? String(span.note) : "";
        const title = tooltipText(note, span.style);
        const marker = String(span.text || text.slice(start, end));
        const hasNote = span.style === "footnote" && note ? " has-note" : "";
        const data = note
          ? ` data-fn="${escapeHtml(marker)}" data-note="1"`
          : span.style === "footnote"
            ? ` data-fn="${escapeHtml(marker)}"`
            : "";
        parts.push(
          `<mark class="${spanClass(span.style)}${hasNote}" title="${escapeHtml(title)}"${data}>${escapeHtml(text.slice(start, end))}</mark>`,
        );
        cursor = end;
      }
      if (cursor < text.length) parts.push(escapeHtml(text.slice(cursor)));
      inner = parts.join("");
    }
    if (kind === "heading") {
      const lvl = Math.min(4, Math.max(1, block.level || 1));
      const extra = block.suppress_in_reader ? " re-banner" : "";
      return `<h${lvl + 1} class="re-heading${extra}">${inner}</h${lvl + 1}>`;
    }
    if (kind === "blockquote") return `<blockquote class="re-blockquote">${inner}</blockquote>`;
    if (kind === "dialogue") {
      const sp = block.speaker ? `<strong class="re-speaker">${escapeHtml(block.speaker)}.</strong> ` : "";
      return `<p class="re-dialogue">${sp}${inner}</p>`;
    }
    if (kind === "stage_direction") return `<p class="re-stage">[${inner}]</p>`;
    if (kind === "verse_line" || kind === "stanza") return `<p class="re-verse">${inner}</p>`;
    if (kind === "metadata") return `<p class="re-metadata">${inner}</p>`;
    if (kind === "hr") return `<hr class="re-hr" />`;
    if (block.role === "synopsis") return `<p class="re-paragraph re-synopsis">${inner}</p>`;
    if (block.role === "figure") return `<p class="re-figure">${inner}</p>`;
    return `<p class="re-paragraph">${inner}</p>`;
  }

  function setEditJson(value) {
    const ta = $("re-edit-json");
    if (ta) ta.value = value;
  }

  function fillEditorForSelection() {
    const details = $("re-edit-json")?.closest("details");
    if (state.step !== "structure" && !details?.open && state.editIndex == null) return;
    const blocks = state.chapter?.blocks || [];
    if (state.editIndex == null || state.editIndex < 0 || state.editIndex >= blocks.length) {
      setEditJson(JSON.stringify(blocks, null, 2));
      const label = $("re-edit-label");
      if (label) label.textContent = "Chỉnh sửa blocks (JSON) — cả chương";
      return;
    }
    setEditJson(JSON.stringify(blocks[state.editIndex], null, 2));
    const label = $("re-edit-label");
    if (label) {
      label.textContent = `Chỉnh sửa block #${state.editIndex} (${blocks[state.editIndex]?.type || "?"})`;
    }
  }

  function highlightSelectedBlock() {
    const box = $("re-body");
    if (!box) return;
    box.querySelectorAll(".re-block.on").forEach((el) => el.classList.remove("on"));
    if (state.editIndex == null) return;
    const el = box.querySelector(`.re-block[data-index="${state.editIndex}"]`);
    if (el) {
      el.classList.add("on");
      el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  async function openSectionFullText() {
    if (!state.workId || !state.chapterId) return;
    const box = $("preview");
    const fullBtn = $("preview-full");
    if (!box) return;
    $("preview-title").textContent = "Đang tải…";
    $("preview-meta").textContent = "";
    $("preview-body").textContent = "";
    if (fullBtn) fullBtn.hidden = true;
    box.hidden = false;
    $("preview-body").scrollTop = 0;
    try {
      const data = await api(
        `/api/works/${encodeURIComponent(state.workId)}/read-edition/chapters/${encodeURIComponent(state.chapterId)}/source`,
      );
      $("preview-title").textContent = data.title || state.chapterId;
      const kind = data.kind ? ` · ${data.kind}` : "";
      $("preview-meta").textContent = `${(data.chars || 0).toLocaleString()} chữ · nguồn section${kind}`;
      $("preview-body").textContent = data.text || "";
    } catch (err) {
      $("preview-meta").textContent = err.message;
    }
  }

  function renderChapterBody(chapter) {
    const box = $("re-body");
    if (!box) return;
    const blocks = chapter.blocks || [];
    const parsed = chapter.micro_status === "complete" && blocks.length;
    if (!parsed) {
      const compare = chapter.compare || reviewRow(chapter.chapter_id)?.compare || {};
      const omitted = Number(chapter.source_preview_omitted) || 0;
      const gap = chapter.source_preview_truncated
        ? `<p class="preview-gap">… đã rút ${omitted.toLocaleString()} chữ giữa đầu và cuối. <button type="button" class="btn ghost" data-section-full>Toàn văn</button></p>`
        : "";
      const head = escapeHtml(chapter.source_preview_head || chapter.source_preview || "");
      const tail = chapter.source_preview_truncated
        ? `<pre>${escapeHtml(chapter.source_preview_tail || "")}</pre>`
        : "";
      const prev = compare.prev_tail
        ? `<aside class="re-rail"><h3>Rìa trước</h3><pre>${escapeHtml(compare.prev_tail)}</pre></aside>`
        : "";
      const next = compare.next_head
        ? `<aside class="re-rail"><h3>Rìa sau</h3><pre>${escapeHtml(compare.next_head)}</pre></aside>`
        : "";
      box.innerHTML = `${prev}<div class="re-preview"><pre>${head}</pre>${gap}${tail}</div>${next}<p class="muted">Chưa parse REF — bấm «Parse chương này» khi cấu trúc đã OK.</p>`;
      box.onclick = (e) => {
        if (e.target.closest("[data-section-full]")) void openSectionFullText();
      };
      return;
    }
    const staleBox = $("re-stale");
    if (staleBox) {
      const stale = chapter.stale_patches || [];
      if (stale.length) {
        staleBox.hidden = false;
        staleBox.textContent = `${stale.length} patch Final Touch không khớp block_id sau re-parse — xem lại ẩn/type.`;
      } else {
        staleBox.hidden = true;
        staleBox.textContent = "";
      }
    }
    box.innerHTML =
      blocks
        .map((b, i) => {
          const hidden = b.hidden ? " is-hidden" : "";
          const on = state.editIndex === i ? " on" : "";
          const bid = b.block_id ? ` data-block-id="${escapeHtml(b.block_id)}"` : "";
          return `<div class="re-block${hidden}${on}" data-index="${i}"${bid} tabindex="0" role="button">${renderBlock(b)}</div>`;
        })
        .join("") + renderNotes(chapter);
    box.onclick = (e) => {
      const mark = e.target.closest("mark[data-fn]");
      if (mark) {
        const id = noteElementId(mark.getAttribute("data-fn"));
        const target = id ? document.getElementById(id) : null;
        if (target) {
          box.querySelectorAll(".re-notes li.on").forEach((el) => el.classList.remove("on"));
          target.classList.add("on");
          target.scrollIntoView({ block: "nearest", behavior: "smooth" });
        }
        if (mark.getAttribute("data-note")) {
          e.stopPropagation();
          return;
        }
      }
      const hit = e.target.closest(".re-block[data-index]");
      if (!hit) return;
      state.editIndex = Number(hit.dataset.index);
      highlightSelectedBlock();
      fillEditorForSelection();
      if (state.step !== "final") {
        document.querySelector("details.re-edit")?.setAttribute("open", "");
      }
    };
  }

  function flagBadges(flags) {
    return (flags || [])
      .map((f) => `<span class="re-flag re-flag-${escapeHtml(f)}">${escapeHtml(f.replace("_", " "))}</span>`)
      .join("");
  }

  function reviewRow(chapterId) {
    return (state.review?.sections || []).find((s) => s.section_id === chapterId) || null;
  }

  function microBadge(row) {
    const job = chapterActiveJob(row.chapter_id);
    if (job) {
      const label = job.kind === "qa" ? "QA…" : job.kind === "hitl_scan" ? "quét…" : "parse…";
      return `<span class="re-micro re-micro-running">${escapeHtml(job.status === "queued" ? "chờ" : label)}</span>`;
    }
    const st = row.micro_status || "pending";
    return `<span class="re-micro re-micro-${st}">${escapeHtml(st === "complete" ? "Ready" : st)}</span>`;
  }

  function layoutConfirmed() {
    return !!(state.review?.health?.layout_ok || state.review?.hitl?.layout_ok);
  }

  function assertReadyToParse() {
    const health = state.review?.health || {};
    if (health.can_parse || (health.layout_ok && health.ready_to_parse)) return true;
    if (health.ready_to_parse && !health.layout_ok) {
      toast("Bấm «Cấu trúc OK» trước khi parse REF");
      return false;
    }
    toast(health.parse_block_reason || health.not_ready_reason || "Còn TOC chưa confirm hoặc section short/super chưa xử lý");
    return false;
  }

  function qaBadge(row) {
    const st = row.qa_status || "pending";
    const verdict = row.qa_verdict ? ` (${row.qa_verdict})` : "";
    return `<span class="re-qa re-qa-${st}">${escapeHtml(st)}${escapeHtml(verdict)}</span>`;
  }

  function renderChapterList(manifest) {
    const list = $("re-chapters");
    if (!list) return;
    const rows = manifest.chapters || [];
    const byId = Object.fromEntries(rows.map((r) => [r.chapter_id, r]));
    list.innerHTML = rows
      .map((row) => {
        const parent = row.parent_id ? byId[row.parent_id] : null;
        const nested = parent ? (parent.parent_id ? " nested-2" : " nested") : "";
        const container = row.kind === "book" || row.kind === "part" ? " container-kind" : "";
        const on = row.chapter_id === state.chapterId ? " on" : "";
        const kindBadge =
          row.kind === "book" || row.kind === "part"
            ? `<span class="re-flag re-flag-kind">${escapeHtml(row.kind)}</span>`
            : "";
        const nestMark = parent ? `<span class="re-nest-mark" aria-hidden="true">↳</span>` : "";
        const parsedCls = row.micro_status === "complete" ? " parsed" : "";
        const scannedCls = hitlKind() && hitlChapterScanned(state.hitlJob, row.chapter_id) ? " scanned" : "";
        return `<div class="re-ch-row${on}${nested}${container}${parsedCls}${scannedCls}">
            <label class="re-ch-check"><input type="checkbox" data-chk="${escapeHtml(row.chapter_id)}" ${state.selected.has(row.chapter_id) ? "checked" : ""} /></label>
            <button type="button" class="re-ch-item" data-ch="${escapeHtml(row.chapter_id)}">
              <span class="re-ch-title">${nestMark}${escapeHtml(row.title || row.chapter_id)}</span>
              ${kindBadge}
              ${hitlScanBadge(row.chapter_id)}
              ${microBadge(row)}
              ${qaBadge(row)}
              ${layoutConfirmed() ? "" : flagBadges(reviewRow(row.chapter_id)?.flags)}
              <span class="muted">${(row.word_count || 0).toLocaleString()} từ</span>
            </button>
          </div>`;
      })
      .join("");
    list.onclick = (e) => {
      const btn = e.target.closest("[data-ch]");
      if (btn) void selectChapter(btn.dataset.ch);
    };
    list.onchange = (e) => {
      const chk = e.target.closest("[data-chk]");
      if (!chk) return;
      if (chk.checked) state.selected.add(chk.dataset.chk);
      else state.selected.delete(chk.dataset.chk);
      syncToolbar();
    };
  }

  async function refreshManifest() {
    if (!state.workId) return;
    const manifestResp = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/manifest`);
    state.manifest = manifestResp.manifest;
    renderChapterList(state.manifest);
  }

  function selectedBlock() {
    const blocks = state.chapter?.blocks || [];
    if (state.editIndex == null || state.editIndex < 0 || state.editIndex >= blocks.length) return null;
    return blocks[state.editIndex];
  }

  function caretOffsetInSelectedBlock() {
    const box = $("re-body");
    if (!box || state.editIndex == null) return null;
    const blockEl = box.querySelector(`.re-block[data-index="${state.editIndex}"]`);
    const sel = window.getSelection();
    if (!blockEl || !sel || !sel.rangeCount) return null;
    const range = sel.getRangeAt(0);
    if (!blockEl.contains(range.startContainer)) return null;
    const pre = range.cloneRange();
    pre.selectNodeContents(blockEl);
    pre.setEnd(range.startContainer, range.startOffset);
    return pre.toString().length;
  }

  async function sendBlockPatches(patches, okMsg) {
    if (!state.workId || !state.chapterId || !patches.length) return;
    await api(
      `/api/works/${encodeURIComponent(state.workId)}/read-edition/chapters/${encodeURIComponent(state.chapterId)}`,
      { method: "PATCH", body: { block_patches: patches } },
    );
    toast(okMsg || "Đã lưu");
    const keepIndex = state.editIndex;
    await selectChapter(state.chapterId);
    if (keepIndex != null) {
      state.editIndex = keepIndex;
      highlightSelectedBlock();
      fillEditorForSelection();
    }
    if (state.chapter?.stale_patches?.length) {
      toast(`${state.chapter.stale_patches.length} patch stale — block_id không còn`);
    }
  }

  async function applyFinalTouch(action, extra) {
    const block = selectedBlock();
    if (!block) {
      toast("Chọn một block trước");
      return;
    }
    const patch = {
      action,
      block_id: block.block_id,
      block_index: state.editIndex,
      ...extra,
    };
    try {
      await sendBlockPatches([patch], action === "hide" ? "Đã ẩn" : "Đã lưu");
    } catch (err) {
      toast(err.message);
    }
  }

  async function selectChapter(chapterId) {
    if (!state.workId) return;
    const loadId = ++state.chapterLoad;
    state.chapterAbort?.abort();
    const ac = new AbortController();
    state.chapterAbort = ac;
    state.chapterId = chapterId;
    state.editIndex = null;
    if (state.manifest) renderChapterList(state.manifest);
    const row = (state.manifest?.chapters || []).find((c) => c.chapter_id === chapterId);
    if (row && $("re-detail-title")) $("re-detail-title").textContent = row.title || chapterId;
    if (HITL_STEPS[state.step]) renderHitlList();
    const meta = $("re-detail-meta");
    if (meta) meta.textContent = "Đang tải…";
    try {
      const chapter = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/chapters/${encodeURIComponent(chapterId)}`, {
        signal: ac.signal,
      });
      if (loadId !== state.chapterLoad) return;
      state.chapter = chapter;
      try {
        localStorage.setItem(lastSectionKey(state.workId), chapterId);
      } catch {
        /* ignore quota */
      }
      renderChapterList(state.manifest);
      if ($("re-section-full")) $("re-section-full").hidden = false;
      const parentRow = (state.manifest?.chapters || []).find((c) => c.chapter_id === chapter.parent_id);
      $("re-detail-title").textContent = chapter.title || chapterId;
      const parsed = chapter.micro_status === "complete";
      const parentBit = parentRow ? `${parentRow.title} · ` : "";
      const noteCount = collectNotes(chapter).length;
      const noteBit = parsed && noteCount ? ` · ${noteCount} chú thích` : "";
      $("re-detail-meta").textContent = parsed
        ? `${parentBit}${chapter.block_count || 0} blocks · ${(chapter.word_count || 0).toLocaleString()} từ${noteBit}`
        : chapter.source_preview_truncated
          ? `${parentBit}Chưa parse REF — preview đầu + cuối (rút ${(Number(chapter.source_preview_omitted) || 0).toLocaleString()} chữ giữa)`
          : `${parentBit}Chưa parse REF — xem preview nguồn`;
      renderChapterBody(chapter);
      const qa = chapter.qa;
      $("re-qa-panel").hidden = !qa;
      if (qa) {
        const llm = qa.llm || {};
        $("re-qa-panel").innerHTML =
          `<p><strong>QA:</strong> ${qa.passed ? "pass" : "fail"} · ${escapeHtml(qa.summary_vi || "")}</p>` +
          (llm.scores ? `<p class="muted">overall ${llm.scores.overall}/10 · structure ${llm.scores.block_structure}/10</p>` : "");
      }
      fillEditorForSelection();
      $("re-edit-json")?.closest("details")?.toggleAttribute("open", parsed && state.step === "structure");
      renderStructTools(chapter);
      renderCompare(chapter);
      applyStepVisibility();
      if (HITL_STEPS[state.step]) renderHitlList();
      syncToolbar();
    } catch (err) {
      if (loadId !== state.chapterLoad || err.name === "AbortError") return;
      if ($("re-section-full")) $("re-section-full").hidden = true;
      if (meta) meta.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
      toast(err.message);
    }
  }

  function editionFlag(name) {
    const ed = state.editionSettings || {};
    return ed[name] !== false;
  }

  function useLlmMacro() {
    return editionFlag("use_llm_macro");
  }

  function useLlmRelabel() {
    return editionFlag("use_llm_relabel");
  }

  function useLlmQa() {
    return editionFlag("use_llm_qa");
  }

  async function loadEditionSettings() {
    try {
      const data = await api("/api/settings");
      const ed = data.settings?.edition;
      if (ed && typeof ed === "object") state.editionSettings = ed;
    } catch {
      /* keep defaults */
    }
  }

  function showBtn(id, show) {
    const el = $(id);
    if (el) el.hidden = !show;
  }

  function markPrimary(id) {
    ["re-macro", "re-layout-ok", "re-parse-ch", "re-parse-ready", "re-publish"].forEach((btnId) => {
      const el = $(btnId);
      if (!el) return;
      const on = btnId === id && !el.hidden;
      el.classList.toggle("primary", on);
      if (btnId === "re-publish" || btnId === "re-parse-ready") {
        el.classList.toggle("ghost", !on && !el.hidden);
      }
    });
  }

  function syncToolbar() {
    const crumb = $("re-crumb");
    const actions = $("re-actions");
    const onDesk = !!state.workId && $("re-pick")?.hidden;
    if (crumb) crumb.hidden = !onDesk;
    if (actions) actions.hidden = !onDesk;
    if (!onDesk) return;

    const status = state.status || {};
    const health = state.review?.health || {};
    const macro = !!status.macro_complete;
    const layoutOk = !!health.layout_ok;
    const chapters = state.manifest?.chapters || [];
    const pending = chapters.filter((row) => row.micro_status !== "complete");
    const current = chapters.find((row) => row.chapter_id === state.chapterId);
    const currentPending = !!(current && current.micro_status !== "complete");
    const parsed = chapters.filter((row) => row.micro_status === "complete").length;
    const selectedPending = [...state.selected].filter((id) =>
      chapters.some((row) => row.chapter_id === id && row.micro_status !== "complete"),
    ).length;
    const onStructure = state.step === "structure";

    const tocStatus = state.review?.toc_candidate?.status || status.hitl?.toc_status;
    const tocOk = tocStatus === "yes" || tocStatus === "no" || tocStatus === "none";
    showBtn("re-macro", !macro && onStructure);
    showBtn("re-reclass", onStructure && macro && tocOk);
    showBtn("re-layout-ok", macro && !layoutOk && onStructure);
    const layoutBtn = $("re-layout-ok");
    if (layoutBtn) {
      const canConfirm = !!(health.ready_to_parse && !layoutOk);
      layoutBtn.disabled = !canConfirm;
      layoutBtn.title = canConfirm
        ? "Xác nhận cấu trúc, rồi parse REF"
        : health.not_ready_reason || "Còn TOC chưa confirm hoặc section short/super chưa xử lý";
    }
    showBtn("re-parse-ch", layoutOk && !!current);
    const parseBtn = $("re-parse-ch");
    if (parseBtn && !parseBtn.hidden) {
      parseBtn.textContent = currentPending ? "Parse chương này" : "Parse lại";
      parseBtn.title = currentPending
        ? "Parse REF và quét nối dòng, chú thích, trích dẫn cho chương này"
        : "Parse lại REF và quét lại nối dòng, chú thích, trích dẫn";
    }
    showBtn("re-parse-selected", onStructure && layoutOk && selectedPending > 1);
    showBtn("re-parse-ready", layoutOk && pending.length > 0 && !(onStructure && currentPending && pending.length === 1));
    // Publish only when every chapter is Ready (micro_status=complete).
    const allReady = layoutOk && parsed > 0 && pending.length === 0;
    showBtn("re-publish", allReady);
    const publishBtn = $("re-publish");
    if (publishBtn && !publishBtn.hidden) {
      publishBtn.disabled = false;
      publishBtn.title = "Mọi chương đã Ready — mở trang gửi Read";
    }
    showBtn("re-more", onStructure);

    const busyWork = workScopedActive();
    const currentJob = chapterActiveJob(state.chapterId);
    const parseLocked = busyWork || (currentJob && currentJob.kind !== "hitl_scan");
    const setDisabled = (id, disabled, title) => {
      const el = $(id);
      if (!el || el.hidden) return;
      el.disabled = !!disabled;
      if (title) el.title = title;
    };
    setDisabled("re-macro", busyWork || activeJobs(state.jobs).some((job) => job.kind === "macro"), busyWork ? "Đang có job chế bản trên sách này" : "");
    setDisabled("re-reclass", busyWork);
    setDisabled("re-parse-ch", parseLocked);
    setDisabled("re-parse-selected", busyWork);
    setDisabled("re-parse-ready", busyWork);
    setDisabled("re-qa-ch", parseLocked);
    const hitlBusy = hitlScanBusy();
    setDisabled("re-hitl-trial", busyWork || hitlBusy);
    setDisabled("re-hitl-book", busyWork || hitlBusy || !state.hitlJob?.trial_confirmed);
    setDisabled("re-hitl-confirm", hitlBusy);
    setDisabled("re-hitl-accept-suspects", hitlBusy);
    setDisabled("re-hitl-reject-suspects", hitlBusy);

    let primary = "re-macro";
    if (!macro) primary = "re-macro";
    else if (!layoutOk) primary = "re-layout-ok";
    else if (currentPending && onStructure) primary = "re-parse-ch";
    else if (pending.length) primary = "re-parse-ready";
    else primary = "re-publish";
    markPrimary(primary);
    if (parseBtn && !parseBtn.hidden) {
      parseBtn.classList.toggle("primary", onStructure && currentPending);
      parseBtn.classList.toggle("ghost", !(onStructure && currentPending));
    }
  }

  function formatStatus(status) {
    const llmNote = status.gemini_available ? "" : " · không có GEMINI_API_KEY — chỉ rule";
    if (!status.macro_complete) {
      return "Chưa phân đoạn — bấm Phân đoạn." + llmNote;
    }
    const parsed = status.chapters_parsed || 0;
    const total = status.chapters_total || 0;
    const health = state.review?.health || {};
    const toc = state.review?.toc_candidate?.status;
    if (!health.layout_ok) {
      if (health.ready_to_parse) {
        return `${total} phần · sẵn sàng — bấm Cấu trúc OK` + llmNote;
      }
      const why = health.not_ready_reason || (toc ? "duyệt short/super" : "chưa confirm TOC");
      return `${total} phần · ${why}` + llmNote;
    }
    if (parsed < total) return `${parsed}/${total} Ready — parse hết trước khi gửi Read` + llmNote;
    return `${total} phần Ready — đưa sang Read` + llmNote;
  }

  function hitlKind() {
    return state.step === "wrap" || state.step === "footnotes" || state.step === "quotes" ? state.step : null;
  }

  function applyStepVisibility() {
    const onStruct = state.step === "structure";
    const onFinal = state.step === "final";
    const hasMacro = !!(state.status?.macro_complete || state.review);
    const steps = $("re-steps");
    const onDesk = !!state.workId && $("re-pick")?.hidden;
    if (steps) steps.hidden = !(onDesk && hasMacro);
    document.querySelectorAll("#re-steps .re-step").forEach((btn) => {
      const step = btn.dataset.step;
      btn.classList.toggle("on", step === state.step);
      btn.disabled = step !== "structure" && !hasMacro;
      const ov = state.hitlOverview?.kinds?.[step];
      const scannedIds = ov?.scanned_chapter_ids || [];
      const chapterScanned = !!(state.chapterId && scannedIds.includes(state.chapterId));
      const structureDone = step === "structure" && layoutConfirmed();
      const chapterParsed = state.chapter?.micro_status === "complete";
      const finalDone = step === "final" && chapterParsed;
      btn.classList.toggle("done", structureDone || (step !== "structure" && step !== "final" && chapterScanned) || finalDone);
      let badge = btn.querySelector(".re-step-badge");
      let pending = ov?.summary?.pending || 0;
      if (state.chapterId && chapterScanned && state.hitlJob?.kind === step) {
        pending = (state.hitlJob.items || []).filter(
          (it) => it.chapter_id === state.chapterId && it.suspect && !it.decision,
        ).length;
      }
      if (step !== "structure" && step !== "final" && pending && (chapterScanned || !state.chapterId)) {
        if (!badge) {
          badge = document.createElement("span");
          badge.className = "re-step-badge";
          btn.appendChild(badge);
        }
        badge.textContent = String(pending);
        badge.hidden = false;
      } else if (badge) {
        badge.hidden = true;
      }
    });
    const hitl = $("re-hitl");
    if (hitl) hitl.hidden = onStruct || onFinal;
    if ($("re-body")) $("re-body").hidden = !onStruct && !onFinal;
    const edit = document.querySelector("details.re-edit");
    if (edit) edit.hidden = !onStruct && !onFinal;
    if ($("re-final-tools")) $("re-final-tools").hidden = !onFinal;
    if ($("re-stale") && !onFinal && !onStruct) $("re-stale").hidden = true;
    if ($("re-qa-ch")) $("re-qa-ch").hidden = !onStruct;
    if ($("re-qa-panel")) $("re-qa-panel").hidden = !onStruct || !state.chapter?.qa;
    if ($("re-toc")) $("re-toc").hidden = !onStruct || !state.review;
    if (!onStruct && $("re-struct-tools")) $("re-struct-tools").hidden = true;
    if (!onStruct && $("re-compare")) $("re-compare").hidden = true;
    if ($("re-section-full")) $("re-section-full").hidden = !state.chapterId;
    if (!onStruct && !onFinal) {
      const meta = HITL_STEPS[state.step];
      if (meta) {
        if ($("re-hitl-title")) $("re-hitl-title").textContent = meta.title;
        if ($("re-hitl-lead")) $("re-hitl-lead").textContent = meta.lead;
      }
      const suspectsFilter = $("re-hitl-filter-row");
      if (suspectsFilter) suspectsFilter.hidden = false;
    }
  }

  function hitlItemMatchesChapter(item, chapterId, job) {
    if (!chapterId) return false;
    const cid = item?.chapter_id || "";
    if (cid) return cid === chapterId;
    return (job?.trial_chapter_id || "") === chapterId;
  }

  function hitlChapterScanned(job, chapterId) {
    if (!job || !chapterId) return false;
    if ((job.scanned_chapter_ids || []).includes(chapterId)) return true;
    if (job.chapter_stats && Object.prototype.hasOwnProperty.call(job.chapter_stats, chapterId)) return true;
    return (job.items || []).some((it) => it.chapter_id === chapterId);
  }

  function hitlScanBadge(chapterId) {
    if (!hitlKind() || !state.hitlJob) return "";
    if (!hitlChapterScanned(state.hitlJob, chapterId)) return "";
    return `<span class="re-micro re-micro-complete">quét</span>`;
  }

  function chapterTitle(chapterId) {
    if (!chapterId) return "";
    const row = (state.manifest?.chapters || []).find((c) => c.chapter_id === chapterId);
    return (row && row.title) || chapterId;
  }

  function renderHitlList() {
    const box = $("re-hitl-list");
    const metaEl = $("re-hitl-meta");
    const job = state.hitlJob;
    if (!box) return;
    if (!job || job.status === "idle") {
      box.innerHTML = `<p class="muted">Chọn một chương bên trái, rồi bấm «Chạy thử chương này».</p>`;
      if (metaEl) metaEl.textContent = "";
      $("re-hitl-confirm").hidden = true;
      $("re-hitl-book").disabled = true;
      $("re-hitl-accept-suspects").hidden = true;
      if ($("re-hitl-reject-suspects")) $("re-hitl-reject-suspects").hidden = true;
      return;
    }
    const summary = job.summary || {};
    const suspectsOnly = !!$("re-hitl-suspects-only")?.checked;
    const focusId = state.chapterId;
    const visible = (job.items || []).filter((it) => hitlItemMatchesChapter(it, focusId, job));
    const shown = visible.filter((it) => {
      if (suspectsOnly && !it.suspect) return false;
      return true;
    });
    const pending = visible.filter((it) => it.suspect && !it.decision).length;
    const suspect = visible.filter((it) => it.suspect).length;
    const scanned = hitlChapterScanned(job, focusId);
    const stats = (job.chapter_stats && focusId && job.chapter_stats[focusId]) || {};
    const hasStats = !!(job.chapter_stats && focusId && Object.prototype.hasOwnProperty.call(job.chapter_stats, focusId));
    const useJobSummary = !hasStats && job.scope === "chapter";
    const auto = hasStats ? Number(stats.auto_join) || 0 : useJobSummary ? Number(summary.auto_join) || 0 : 0;
    const autoKeep = hasStats ? Number(stats.auto_keep) || 0 : useJobSummary ? Number(summary.auto_keep) || 0 : 0;
    const linked = hasStats ? Number(stats.linked) || 0 : useJobSummary ? Number(summary.linked) || 0 : 0;
    const unmatched = hasStats ? Number(stats.unmatched) || 0 : useJobSummary ? Number(summary.unmatched) || 0 : 0;
    if (metaEl) {
      const bits = [];
      if (job.scope === "book") bits.push("toàn sách");
      else bits.push("chương thử");
      if (!scanned) {
        bits.push("chưa quét chương này");
      } else if (state.step === "wrap") {
        bits.push(`tự ghép ${auto}`, `tự giữ ${autoKeep}`, `nghi ngờ ${suspect}`);
      } else {
        bits.push(`${visible.length} mục`, `nghi ngờ ${suspect}`);
      }
      if (scanned && linked) bits.push(`đã nối ${linked}`);
      if (scanned && unmatched) bits.push(`chưa khớp ${unmatched}`);
      if (scanned) bits.push(`chưa quyết ${pending}`);
      if (job.trial_confirmed) bits.push("đã xác nhận thử");
      metaEl.textContent = bits.join(" · ");
    }
    const viewingTrial = !job.trial_chapter_id || job.trial_chapter_id === focusId;
    const decideLocked = hitlScanBusy();
    const confirmBtn = $("re-hitl-confirm");
    if (confirmBtn) {
      confirmBtn.hidden = job.status === "idle" || !!job.trial_confirmed || !viewingTrial;
      const trialLabel = chapterTitle(job.trial_chapter_id);
      confirmBtn.textContent = trialLabel ? `Chương thử ổn · ${trialLabel}` : "Chương thử ổn";
      confirmBtn.disabled = decideLocked;
      confirmBtn.title = decideLocked ? "Đang quét — quyết định sẽ mất nếu ghi đè" : "";
    }
    $("re-hitl-book").disabled = !job.trial_confirmed || decideLocked || workScopedActive();
    $("re-hitl-accept-suspects").hidden = pending === 0;
    $("re-hitl-accept-suspects").disabled = decideLocked;
    if ($("re-hitl-reject-suspects")) {
      $("re-hitl-reject-suspects").hidden = pending === 0;
      $("re-hitl-reject-suspects").disabled = decideLocked;
      $("re-hitl-reject-suspects").title = decideLocked ? "Đang quét — quyết định sẽ mất nếu ghi đè" : "";
    }
    if ($("re-hitl-accept-suspects")) {
      $("re-hitl-accept-suspects").title = decideLocked ? "Đang quét — quyết định sẽ mất nếu ghi đè" : "";
    }
    if (!shown.length) {
      let empty;
      if (!scanned) {
        if (job.scope === "book") {
          empty = "Chương này không có chỗ cần duyệt.";
        } else if (job.trial_confirmed) {
          empty = "Chương này chưa được quét — bấm «Chạy thử chương này» hoặc «Chạy toàn văn bản». Kết quả các chương đã quét vẫn giữ.";
        } else {
          empty = "Chương này chưa được quét — bấm «Chạy thử chương này». Kết quả các chương đã quét vẫn giữ.";
        }
      } else if (visible.length) {
        empty = "Không còn mục nào khớp bộ lọc.";
      } else if (job.scope === "book" || job.trial_confirmed) {
        empty = "Chương này không có chỗ cần duyệt.";
      } else {
        empty = "Không có chỗ nghi ngờ — có thể xác nhận chương thử rồi chạy toàn văn bản.";
      }
      box.innerHTML = `<p class="muted">${empty}</p>`;
      return;
    }
    box.innerHTML = shown.map(renderHitlCard).join("");
  }

  function quoteContextParts(item) {
    const span = item.context_span;
    if (!span) return "";
    return `${escapeHtml(item.context_before || "")}<mark class="re-hitl-span">${escapeHtml(span)}</mark>${escapeHtml(item.context_after || "")}`;
  }

  function renderHitlCard(item) {
    const decision = item.decision || "";
    const cls = ["re-hitl-card"];
    if (item.suspect) cls.push("suspect");
    if (decision === "accept") cls.push("accepted");
    if (decision === "reject") cls.push("rejected");
    const tags = [];
    if (item.auto_ok && decision === "accept") tags.push(`<span class="re-hitl-tag auto-ok">auto OK</span>`);
    else if (item.suspect) tags.push(`<span class="re-hitl-tag suspect">nghi ngờ</span>`);
    else tags.push(`<span class="re-hitl-tag ok">ổn</span>`);
    if (item.proposed) tags.push(`<span class="re-hitl-tag">${escapeHtml(item.proposed === "join" ? "đề xuất: ghép" : "đề xuất: giữ tách")}</span>`);
    if (item.mark) tags.push(`<span class="re-hitl-tag">${escapeHtml(item.mark)}</span>`);
    if (item.status) tags.push(`<span class="re-hitl-tag">${escapeHtml(item.status)}</span>`);
    if (item.marker) tags.push(`<span class="re-hitl-tag">${escapeHtml(item.marker)}</span>`);
    if (item.chapter_id && state.hitlJob?.scope === "book") tags.push(`<span class="re-hitl-tag">${escapeHtml(item.chapter_id)}</span>`);
    const reasons = (item.reason_labels || []).map((r) => escapeHtml(r)).join("; ");
    let body = "";
    if (state.step === "wrap") {
      body = `<pre>${escapeHtml(item.prev || "")}\n${escapeHtml(item.next || "")}</pre>`;
      if (item.proposed === "join" && item.preview) {
        body += `<pre class="re-hitl-preview">→ ${escapeHtml(item.preview)}</pre>`;
      }
    } else if (state.step === "footnotes") {
      const anchor = item.anchor ? `<strong>${escapeHtml(item.anchor)}</strong> ` : "";
      body = `<p class="re-hitl-body">${anchor}<span class="muted">${escapeHtml(item.context || "")}</span></p>`;
      body += item.body
        ? `<p class="re-hitl-body">${escapeHtml(item.body)}</p>`
        : `<p class="muted">Chưa có nội dung chú thích.</p>`;
    } else {
      const windowed = quoteContextParts(item);
      if (windowed) {
        body = `<p class="re-hitl-context">${windowed}</p>`;
      } else {
        body = `<p class="re-hitl-body">${escapeHtml(item.text || "")}</p>`;
        if (item.context && item.context !== item.text) {
          body += `<p class="muted">${escapeHtml(item.context)}</p>`;
        }
      }
    }
    const actionable = item.actionable !== false;
    const decideLocked = hitlScanBusy();
    const lockedAttr = decideLocked ? " disabled title=\"Đang quét — không quyết định giữa chừng\"" : "";
    const acceptLabel = !actionable
      ? "Đã xem"
      : state.step === "wrap"
        ? (item.proposed === "join" ? "Ghép" : "Giữ tách")
        : "OK";
    const rejectLabel =
      item.auto_ok && decision === "accept"
        ? "Hoàn tác"
        : state.step === "wrap"
          ? item.proposed === "join"
            ? "Giữ tách"
            : "Ghép"
          : "Bỏ";
    const rejectBtn = actionable
      ? `<button type="button" class="btn ${decision === "reject" ? "primary" : "ghost"}" data-hitl-reject="${escapeHtml(item.id)}"${lockedAttr}>${rejectLabel}</button>`
      : "";
    return `<article class="${cls.join(" ")}" data-hitl-id="${escapeHtml(item.id)}">
      <div class="re-hitl-card-top">${tags.join("")}${reasons ? `<span class="muted">${reasons}</span>` : ""}</div>
      ${body}
      <div class="re-hitl-actions">
        <button type="button" class="btn ${decision === "accept" ? "primary" : "ghost"}" data-hitl-accept="${escapeHtml(item.id)}"${lockedAttr}>${acceptLabel}</button>
        ${rejectBtn}
      </div>
    </article>`;
  }

  async function loadHitlOverview() {
    if (!state.workId) return;
    const loadId = ++state.hitlOverviewLoad;
    const workId = state.workId;
    try {
      const overview = await api(`/api/works/${encodeURIComponent(workId)}/read-edition/hitl`);
      if (loadId !== state.hitlOverviewLoad || state.workId !== workId) return;
      state.hitlOverview = overview;
    } catch {
      if (loadId !== state.hitlOverviewLoad || state.workId !== workId) return;
      state.hitlOverview = null;
    }
    applyStepVisibility();
  }

  function applyHitlJob(job) {
    state.hitlJobLoad += 1;
    state.hitlJob = job;
    renderHitlList();
    if (state.manifest) renderChapterList(state.manifest);
  }

  async function loadHitlJob() {
    const kind = hitlKind();
    const workId = state.workId;
    const loadId = ++state.hitlJobLoad;
    if (!kind || !workId) {
      state.hitlJob = null;
      renderHitlList();
      if (state.manifest) renderChapterList(state.manifest);
      return;
    }
    try {
      const job = await api(`/api/works/${encodeURIComponent(workId)}/read-edition/hitl/${kind}`);
      if (loadId !== state.hitlJobLoad || state.workId !== workId || hitlKind() !== kind) return;
      state.hitlJob = job;
    } catch {
      if (loadId !== state.hitlJobLoad || state.workId !== workId) return;
      state.hitlJob = null;
    }
    renderHitlList();
    if (state.manifest) renderChapterList(state.manifest);
  }

  function persistStep(workId, step) {
    if (!workId) return;
    try {
      localStorage.setItem(lastStepKey(workId), step);
    } catch {
      /* ignore quota */
    }
  }

  function rememberedStep(workId) {
    try {
      const saved = workId ? localStorage.getItem(lastStepKey(workId)) : null;
      if (saved === "structure" || saved === "final" || HITL_STEPS[saved]) return saved;
    } catch {
      /* ignore */
    }
    return null;
  }

  async function setStep(step) {
    state.step = step;
    persistStep(state.workId, step);
    const suspectsBox = $("re-hitl-suspects-only");
    if (suspectsBox) suspectsBox.checked = true;
    applyStepVisibility();
    syncToolbar();
    if (state.manifest) renderChapterList(state.manifest);
    if (step === "structure" || step === "final") {
      if (state.chapter) {
        if (step === "structure") {
          renderStructTools(state.chapter);
          renderCompare(state.chapter);
        }
        renderChapterBody(state.chapter);
      }
      return;
    }
    await loadHitlJob();
  }

  async function runHitlScan(scope) {
    const kind = hitlKind();
    if (!kind || !state.workId) return;
    if (scope === "chapter" && !state.chapterId) {
      toast("Chọn một chương để chạy thử");
      return;
    }
    try {
      await enqueueEdition(
        {
          kind: "hitl_scan",
          hitl_kind: kind,
          scope,
          chapter_id: state.chapterId,
        },
        scope === "book" ? "Đã xếp hàng quét toàn sách" : "Đã xếp hàng quét chương",
      );
    } catch (err) {
      toast(err.message);
    }
  }

  function hitlTrialChapterId() {
    const job = state.hitlJob;
    if (!job || job.scope === "book") return null;
    return job.trial_chapter_id || null;
  }

  async function confirmHitlTrial() {
    const kind = hitlKind();
    if (!kind || !state.workId) return;
    if (hitlScanBusy()) {
      toast("Đang quét — đợi xong rồi mới xác nhận");
      return;
    }
    try {
      applyHitlJob(
        await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/hitl/${kind}/confirm`, {
          method: "POST",
          body: { chapter_id: hitlTrialChapterId() || state.chapterId },
        }),
      );
      toast("Đã xác nhận chương thử — có thể chạy toàn văn bản");
      await loadHitlOverview();
    } catch (err) {
      toast(err.message);
    }
  }

  async function decideHitl(itemId, decision, suspectsOnly) {
    const kind = hitlKind();
    if (!kind || !state.workId) return;
    if (hitlScanBusy()) {
      toast("Đang quét — đợi xong rồi mới chấp nhận/bỏ");
      return;
    }
    try {
      applyHitlJob(
        await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/hitl/${kind}/decide`, {
          method: "POST",
          body: {
            decision,
            item_ids: itemId ? [itemId] : [],
            suspects_only: !!suspectsOnly,
            chapter_id: itemId ? null : state.chapterId || hitlTrialChapterId(),
          },
        }),
      );
      await loadHitlOverview();
      if ((state.hitlJob.reparsed || []).includes(state.chapterId)) {
        toast("Đã ghi vào chương đã parse");
        await selectChapter(state.chapterId);
      } else if ((state.hitlJob.apply_errors || []).length) {
        toast(state.hitlJob.apply_errors[0]);
      }
    } catch (err) {
      toast(err.message);
    }
  }

  function renderTocPanel(review) {
    const box = $("re-toc");
    if (!box) return;
    if (!review) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    const toc = review.toc_candidate || {};
    const loc = toc.location && toc.location !== "none" ? toc.location : "không thấy";
    const src = toc.source || "none";
    $("re-toc-meta").textContent = `${toc.line_count || 0} dòng · ${src} · ${loc}`;
    const el = $("re-toc-excerpt");
    if (el && document.activeElement !== el) {
      el.value = toc.excerpt || "";
    }
    const status = toc.status;
    const answered = status === "yes" || status === "no" || status === "none";
    const title = box.querySelector(".re-toc-head strong");
    if (title) title.textContent = answered ? "Mục lục" : "Mục lục đề xuất";
    const restore = $("re-toc-reset");
    if (restore) restore.hidden = answered;
    const reclass = $("re-toc-reclass");
    if (reclass) reclass.hidden = !answered;
    const banner = $("re-toc-banner");
    if (status === "yes") {
      banner.textContent = "Đã xác nhận: đây là mục lục. Bấm «Phân loại lại» để tách chương theo mục lục này.";
    } else if (status === "no") {
      banner.textContent = "Đã ghi: đoạn này không phải mục lục. Bấm «Phân loại lại» nếu muốn tách chương lại.";
    } else if (status === "none") {
      banner.textContent = "Đã ghi: sách không có mục lục. Bấm «Phân loại lại» nếu muốn tách chương lại.";
    } else {
      banner.textContent = "Dán TOC chuẩn nếu đề xuất sai, rồi xác nhận. «Khôi phục đề xuất» chỉ lấy lại TOC máy.";
    }
  }

  function renderHealth(review) {
    const el = $("re-health");
    if (!el) return;
    if (!review) {
      el.hidden = true;
      return;
    }
    const h = review.health || {};
    const cov = review.coverage || {};
    const bits = [];
    if (h.layout_ok) {
      bits.push("cấu trúc đã xác nhận");
    } else {
      bits.push(`short ${h.short || 0}`, `super ${h.super || 0}`, `inner ${h.inner_heads || 0}`, `toc miss ${h.toc_miss || 0}`);
      if (!cov.complete) bits.push(`orphan ${(cov.orphan_chars || 0).toLocaleString()} chữ`);
      if (!h.toc_answered) bits.push("chưa confirm TOC");
      if (h.ready_to_parse) bits.push("sẵn sàng — bấm Cấu trúc OK");
    }
    if (h.layout_ok && h.ready_to_parse) bits.push("sẵn sàng parse");
    el.hidden = false;
    el.textContent = bits.join(" · ");
    el.classList.toggle("ok", !!h.layout_ok);
  }

  function applyReview(review) {
    state.review = review;
    if (review?.manifest) state.manifest = review.manifest;
    renderTocPanel(review);
    renderHealth(review);
    if (state.manifest) renderChapterList(state.manifest);
    syncToolbar();
  }

  async function loadReview() {
    if (!state.workId) return null;
    try {
      const review = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/review`);
      applyReview(review);
      return review;
    } catch {
      applyReview(null);
      return null;
    }
  }

  function renderStructTools(chapter) {
    const bar = $("re-struct-tools");
    if (!bar) return;
    const hasMacro = !!(state.review || state.status?.macro_complete);
    bar.hidden = !hasMacro || state.step !== "structure";
    const kind = $("re-kind");
    if (kind && chapter?.kind) kind.value = chapter.kind;
    const expand = $("re-expand-macro");
    if (expand) {
      const row = reviewRow(chapter?.chapter_id);
      const flags = row?.flags || chapter?.flags || [];
      const inner = row?.inner_heads || chapter?.inner_heads || [];
      const nested =
        flags.includes("super") ||
        flags.includes("inner_heads") ||
        inner.length >= 2 ||
        ["book", "part"].includes(chapter?.kind);
      expand.hidden = !nested;
    }
  }

  function renderCompare(chapter) {
    const box = $("re-compare");
    if (!box) return;
    const compare = chapter?.compare || reviewRow(chapter?.chapter_id)?.compare;
    const inner = chapter?.inner_heads || reviewRow(chapter?.chapter_id)?.inner_heads || [];
    const match = chapter?.toc_match || reviewRow(chapter?.chapter_id)?.toc_match;
    const parsed = chapter?.micro_status === "complete" && (chapter?.blocks || []).length;
    const panes = [];
    if (parsed && compare && (compare.prev_tail || compare.this_head || compare.this_tail || compare.next_head)) {
      panes.push(`<details class="re-cut"><summary>Rìa cắt</summary>
        ${compare.prev_tail ? `<div class="re-compare-pane"><h3>Cuối section trước</h3><pre>${escapeHtml(compare.prev_tail)}</pre></div>` : ""}
        ${compare.this_head ? `<div class="re-compare-pane"><h3>Đầu section này</h3><pre>${escapeHtml(compare.this_head)}</pre></div>` : ""}
        ${compare.this_tail ? `<div class="re-compare-pane"><h3>Cuối section này</h3><pre>${escapeHtml(compare.this_tail)}</pre></div>` : ""}
        ${compare.next_head ? `<div class="re-compare-pane"><h3>Đầu section sau</h3><pre>${escapeHtml(compare.next_head)}</pre></div>` : ""}
      </details>`);
    }
    if (match?.label) {
      panes.push(`<div class="re-compare-pane"><h3>Khớp TOC</h3><p>${escapeHtml(match.label)}</p></div>`);
    }
    if (inner.length) {
      const rows = inner
        .map(
          (h) =>
            `<button type="button" class="btn ghost" data-split-line="${h.line}">Tách tại L${h.line}: ${escapeHtml(h.text)}</button>`,
        )
        .join("");
      panes.push(
        `<div class="re-compare-pane"><h3>Heading lồng (${inner.length}) — bấm để tách một heading, hoặc «Phân đoạn bên trong» để tách hết chapter</h3><div class="re-inner-heads">${rows}</div></div>`,
      );
    }
    box.hidden = !panes.length || state.step !== "structure";
    box.innerHTML = panes.join("");
    box.onclick = (e) => {
      const btn = e.target.closest("[data-split-line]");
      if (!btn) return;
      void applyStructureEdit("split_at", { start_line: Number(btn.dataset.splitLine) });
    };
  }

  async function applyStructureEdit(action, extra = {}) {
    if (!state.workId || !state.chapterId) return;
    try {
      const result = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/structure/edit`, {
        method: "POST",
        body: { action, section_id: state.chapterId, ...extra },
      });
      applyReview(result);
      const focus = result.focused_section_id || (result.structure?.sections || [])[0]?.section_id;
      const toastMsg =
        action === "confirm"
          ? "Đã xác nhận section"
          : action === "expand_macro"
            ? "Đã phân đoạn bên trong"
            : "Đã sửa ranh";
      toast(toastMsg);
      if (focus) await selectChapter(focus);
    } catch (err) {
      toast(err.message);
    }
  }

  async function confirmToc(status) {
    if (!state.workId) return;
    try {
      const excerpt = $("re-toc-excerpt")?.value ?? "";
      const result = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/toc`, {
        method: "POST",
        body: { status, excerpt },
      });
      applyReview(result);
      toast(status === "yes" ? "Đã xác nhận TOC" : status === "none" ? "Không có TOC" : "Không phải TOC");
      if (state.chapterId) await selectChapter(state.chapterId);
    } catch (err) {
      toast(err.message);
    }
  }

  function resetTocProposal() {
    const proposed = state.review?.toc_candidate?.proposed_excerpt;
    const el = $("re-toc-excerpt");
    if (!el) return;
    el.value = proposed || "";
    el.focus();
  }

  function tocIsAnswered() {
    const status = state.review?.toc_candidate?.status || state.status?.hitl?.toc_status;
    return status === "yes" || status === "no" || status === "none";
  }

  async function reclassifyWithToc() {
    if (!state.workId) return;
    if (!tocIsAnswered()) {
      toast("Xác nhận TOC trước khi phân loại lại");
      return;
    }
    const status = state.review?.toc_candidate?.status;
    if (status === "yes") {
      try {
        const excerpt = $("re-toc-excerpt")?.value ?? "";
        await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/toc`, {
          method: "POST",
          body: { status: "yes", excerpt },
        });
      } catch (err) {
        toast(err.message);
        return;
      }
    }
    $("re-status").textContent = "Đã xếp hàng phân loại lại…";
    try {
      await enqueueEdition(
        { kind: "macro", keep_toc: true, use_llm: useLlmMacro() },
        status === "yes" ? "Đã xếp hàng phân loại lại — TOC đã dán được giữ" : "Đã xếp hàng phân loại lại",
      );
    } catch (err) {
      toast(err.message);
      $("re-status").textContent = err.message;
    }
  }

  function lastSectionKey(workId) {
    return `kh-re-section:${workId}`;
  }

  function lastStepKey(workId) {
    return `kh-re-step:${workId}`;
  }

  function phaseLabel(phase) {
    return (
      {
        macro: "đã phân đoạn",
        hitl: "đang duyệt cấu trúc",
        layout_ok: "cấu trúc OK",
        parsing: "đang parse REF",
        parsed: "parse xong",
        empty: "chưa bắt đầu",
      }[phase] || phase || "—"
    );
  }

  async function loadReadEditionPage(workId) {
    const loadId = ++state.pageLoad;
    const prevWork = state.workId;
    state.workId = workId;
    state.selected.clear();
    if (prevWork !== workId) {
      state.hitlJob = null;
      state.hitlOverview = null;
      state.chapter = null;
      state.chapterId = null;
    }
    document.querySelectorAll(".nav-link").forEach((b) => b.classList.remove("active"));
    document.querySelector('.nav-link[data-view="read-edition"]')?.classList.add("active");
    ["view-works", "view-publish", "view-licenses", "view-settings", "view-translation"].forEach((id) => {
      const el = $(id);
      if (el) el.hidden = true;
    });
    $("view-read-edition").hidden = false;
    $("re-pick").hidden = true;
    $("re-desk").hidden = false;
    $("re-heading").textContent = workId;
    $("re-status").textContent = "Đang tải…";
    await loadEditionSettings();
    if (loadId !== state.pageLoad) return;
    try {
      const status = await api(`/api/works/${encodeURIComponent(workId)}/read-edition`);
      if (loadId !== state.pageLoad) return;
      state.status = status;
      applyJobsPayload(status);
      renderJobQueue();
      renderJobLog();
      $("re-heading").textContent = status.title || workId;
      $("re-status").textContent = formatStatus(status);
      if (status.macro_complete && status.manifest) {
        state.manifest = status.manifest;
        await loadReview();
        if (loadId !== state.pageLoad) return;
        $("re-status").textContent = formatStatus(status);
        renderChapterList(state.manifest);
        await loadHitlOverview();
        if (loadId !== state.pageLoad) return;
        const savedStep = rememberedStep(workId) || "structure";
        state.step = savedStep;
        persistStep(workId, savedStep);
        if (hitlKind()) {
          await loadHitlJob();
          if (loadId !== state.pageLoad) return;
        } else {
          state.hitlJob = null;
        }
        const chapters = state.manifest.chapters || [];
        const remembered =
          (workId ? localStorage.getItem(lastSectionKey(workId)) : null) ||
          status.hitl?.last_section_id;
        const pick = chapters.find((row) => row.chapter_id === remembered) || chapters[0];
        if (pick) await selectChapter(pick.chapter_id);
        if (loadId !== state.pageLoad) return;
      } else {
        state.manifest = null;
        state.chapter = null;
        state.chapterId = null;
        state.step = "structure";
        state.hitlJob = null;
        applyReview(null);
        $("re-chapters").innerHTML = `<p class="muted">Bấm «Phân đoạn» để liệt kê chương.</p>`;
        $("re-body").innerHTML = "";
        if ($("re-detail-title")) $("re-detail-title").textContent = "Chương";
        if ($("re-detail-meta")) $("re-detail-meta").textContent = "";
        if ($("re-section-full")) $("re-section-full").hidden = true;
        if ($("re-compare")) $("re-compare").hidden = true;
        if ($("re-struct-tools")) $("re-struct-tools").hidden = true;
        if ($("re-qa-panel")) $("re-qa-panel").hidden = true;
        $("re-more")?.removeAttribute("open");
      }
      applyStepVisibility();
      syncToolbar();
      if (activeJobs(state.jobs).length) startJobPoll();
      else stopJobPoll();
    } catch (err) {
      if (loadId !== state.pageLoad) return;
      $("re-status").textContent = err.message;
      syncToolbar();
    }
  }

  function wireReadEdition() {
    $("re-steps")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-step]");
      if (!btn || btn.disabled) return;
      void setStep(btn.dataset.step);
    });
    $("re-hitl-trial")?.addEventListener("click", () => void runHitlScan("chapter"));
    $("re-hitl-book")?.addEventListener("click", () => void runHitlScan("book"));
    $("re-hitl-confirm")?.addEventListener("click", () => void confirmHitlTrial());
    $("re-hitl-accept-suspects")?.addEventListener("click", () => void decideHitl(null, "accept", true));
    $("re-hitl-reject-suspects")?.addEventListener("click", () => void decideHitl(null, "reject", true));
    $("re-hitl-suspects-only")?.addEventListener("change", () => renderHitlList());
    $("re-edit-json")?.closest("details")?.addEventListener("toggle", (e) => {
      if (e.target.open) fillEditorForSelection();
    });
    $("re-hitl-list")?.addEventListener("click", (e) => {
      const accept = e.target.closest("[data-hitl-accept]");
      if (accept) {
        void decideHitl(accept.dataset.hitlAccept, "accept");
        return;
      }
      const reject = e.target.closest("[data-hitl-reject]");
      if (reject) void decideHitl(reject.dataset.hitlReject, "reject");
    });
    $("re-cancel-jobs")?.addEventListener("click", () => void cancelActiveJobs());

    $("re-macro")?.addEventListener("click", async () => {
      if (!state.workId) return;
      if (state.status?.macro_complete) {
        toast("Đã có phân đoạn — xác nhận TOC rồi bấm «Phân loại lại», hoặc Reset để xóa hết");
        return;
      }
      try {
        await enqueueEdition(
          { kind: "macro", force: false, use_llm: useLlmMacro() },
          "Đã xếp hàng phân đoạn — có thể làm việc khác trong lúc chờ",
        );
      } catch (err) {
        toast(err.message);
        $("re-status").textContent = err.message;
      }
    });

    $("re-reclass")?.addEventListener("click", () => void reclassifyWithToc());

    $("re-reset")?.addEventListener("click", async () => {
      if (!state.workId) return;
      if (
        !window.confirm(
          "Xóa hết phân đoạn, parse REF, và mục lục đã dán? Sách trở về trạng thái chưa bắt đầu — không tự phân đoạn lại.",
        )
      ) {
        return;
      }
      $("re-status").textContent = "Đang reset…";
      try {
        await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/jobs/cancel`, {
          method: "POST",
          body: {},
        });
        await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/reset`, {
          method: "POST",
        });
        try {
          localStorage.removeItem(lastSectionKey(state.workId));
          localStorage.removeItem(lastStepKey(state.workId));
        } catch {
          /* ignore */
        }
        toast("Đã reset — sách trở về trạng thái ban đầu");
        await loadReadEditionPage(state.workId);
      } catch (err) {
        toast(err.message);
        $("re-status").textContent = err.message;
      }
    });

    $("re-parse-ch")?.addEventListener("click", async () => {
      if (!state.workId || !state.chapterId) return;
      if (!assertReadyToParse()) return;
      try {
        await enqueueEdition(
          { kind: "parse", chapter_id: state.chapterId, use_llm: useLlmRelabel() },
          `Đã xếp hàng parse ${state.chapterId}`,
        );
      } catch (err) {
        toast(err.message);
      }
    });

    $("re-parse-selected")?.addEventListener("click", async () => {
      if (!state.workId) return;
      if (!assertReadyToParse()) return;
      const ids = [...state.selected];
      if (!ids.length) {
        toast("Chọn ít nhất một chương");
        return;
      }
      try {
        await enqueueEdition(
          { kind: "parse", chapter_ids: ids, use_llm: useLlmRelabel() },
          `Đã xếp hàng parse ${ids.length} chương`,
        );
      } catch (err) {
        toast(err.message);
      }
    });

    $("re-layout-ok")?.addEventListener("click", async () => {
      if (!state.workId) return;
      const health = state.review?.health || {};
      if (!health.ready_to_parse) {
        toast(health.not_ready_reason || "Còn TOC chưa confirm hoặc section short/super chưa xử lý");
        return;
      }
      try {
        const result = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/layout`, {
          method: "POST",
        });
        applyReview(result);
        toast("Đã xác nhận cấu trúc");
        if (state.chapterId) await selectChapter(state.chapterId);
      } catch (err) {
        toast(err.message);
      }
    });

    $("re-parse-ready")?.addEventListener("click", async () => {
      if (!state.workId) return;
      if (!assertReadyToParse()) return;
      const ids = (state.manifest?.chapters || [])
        .filter((row) => row.micro_status !== "complete")
        .map((row) => row.chapter_id);
      if (!ids.length) {
        toast("Không còn chương pending");
        return;
      }
      try {
        await enqueueEdition(
          { kind: "parse", chapter_ids: ids, use_llm: useLlmRelabel() },
          `Đã xếp hàng parse ${ids.length} chương còn lại`,
        );
      } catch (err) {
        toast(err.message);
      }
    });

    $("re-select-all")?.addEventListener("change", (e) => {
      const on = e.target.checked;
      for (const row of state.manifest?.chapters || []) {
        if (on) state.selected.add(row.chapter_id);
        else state.selected.delete(row.chapter_id);
      }
      renderChapterList(state.manifest);
      syncToolbar();
    });

    $("re-toc-yes")?.addEventListener("click", () => void confirmToc("yes"));
    $("re-toc-no")?.addEventListener("click", () => void confirmToc("no"));
    $("re-toc-none")?.addEventListener("click", () => void confirmToc("none"));
    $("re-toc-reset")?.addEventListener("click", resetTocProposal);
    $("re-toc-reclass")?.addEventListener("click", () => void reclassifyWithToc());
    $("re-merge-prev")?.addEventListener("click", () => void applyStructureEdit("merge_prev"));
    $("re-merge-next")?.addEventListener("click", () => void applyStructureEdit("merge_next"));
    $("re-drop-start")?.addEventListener("click", () => void applyStructureEdit("drop_start"));
    $("re-expand-macro")?.addEventListener("click", () =>
      void applyStructureEdit("expand_macro", { use_llm: useLlmMacro() }),
    );
    $("re-confirm-sec")?.addEventListener("click", () => void applyStructureEdit("confirm"));
    $("re-kind")?.addEventListener("change", (e) => {
      const kind = e.target.value;
      if (kind) void applyStructureEdit("set_kind", { kind });
    });

    $("re-section-full")?.addEventListener("click", () => void openSectionFullText());

    $("re-qa-ch")?.addEventListener("click", async () => {
      if (!state.workId || !state.chapterId) return;
      if (state.chapter?.micro_status !== "complete") {
        toast("Parse REF chương trước khi QA");
        return;
      }
      try {
        await enqueueEdition(
          { kind: "qa", chapter_id: state.chapterId, use_llm: useLlmQa() },
          `Đã xếp hàng QA ${state.chapterId}`,
        );
      } catch (err) {
        toast(err.message);
      }
    });

    $("re-save-blocks")?.addEventListener("click", async () => {
      if (!state.workId || !state.chapterId) return;
      let parsed;
      try {
        parsed = JSON.parse($("re-edit-json").value || "null");
      } catch {
        toast("JSON không hợp lệ");
        return;
      }
      const origBlocks = state.chapter?.blocks || [];
      let patches = [];
      if (Array.isArray(parsed)) {
        patches = parsed
          .map((block, index) => {
            const orig = origBlocks[index] || {};
            if (JSON.stringify(orig) === JSON.stringify(block)) return null;
            return {
              block_id: orig.block_id || block.block_id,
              block_index: index,
              type: block.type,
              text: block.text,
              level: block.level,
              speaker: block.speaker,
              hidden: block.hidden,
            };
          })
          .filter(Boolean);
      } else if (parsed && typeof parsed === "object" && state.editIndex != null) {
        const orig = origBlocks[state.editIndex] || {};
        if (JSON.stringify(orig) !== JSON.stringify(parsed)) {
          patches = [
            {
              block_id: orig.block_id || parsed.block_id,
              block_index: state.editIndex,
              type: parsed.type,
              text: parsed.text,
              level: parsed.level,
              speaker: parsed.speaker,
              hidden: parsed.hidden,
            },
          ];
        }
      } else {
        toast("Chọn một block hoặc dán mảng blocks JSON");
        return;
      }
      if (!patches.length) {
        toast("Không có thay đổi");
        return;
      }
      try {
        await api(
          `/api/works/${encodeURIComponent(state.workId)}/read-edition/chapters/${encodeURIComponent(state.chapterId)}`,
          { method: "PATCH", body: { block_patches: patches } },
        );
        toast("Đã lưu chỉnh sửa");
        const keepIndex = state.editIndex;
        await selectChapter(state.chapterId);
        if (keepIndex != null) {
          state.editIndex = keepIndex;
          highlightSelectedBlock();
          fillEditorForSelection();
        }
      } catch (err) {
        toast(err.message);
      }
    });

    $("re-ft-hide")?.addEventListener("click", () => void applyFinalTouch("hide"));
    $("re-ft-show")?.addEventListener("click", () => void applyFinalTouch("show"));
    $("re-ft-merge")?.addEventListener("click", () => void applyFinalTouch("merge_with_next"));
    $("re-ft-split")?.addEventListener("click", () => {
      const at = caretOffsetInSelectedBlock();
      if (at == null) {
        toast("Đặt caret trong block rồi bấm Tách");
        return;
      }
      void applyFinalTouch("split", { at });
    });
    $("re-ft-type-apply")?.addEventListener("click", () => {
      const type = $("re-ft-type")?.value;
      if (!type) return;
      void applyFinalTouch("set_type", { type });
    });

    $("re-publish")?.addEventListener("click", () => {
      if (!state.workId) return;
      const chapters = state.manifest?.chapters || [];
      const pending = chapters.filter((row) => row.micro_status !== "complete");
      if (!chapters.length || pending.length) {
        toast(
          pending.length
            ? `Còn ${pending.length} chương chưa Ready — parse hết trước khi gửi Read`
            : "Chưa có chương Ready để gửi Read",
        );
        return;
      }
      if (!layoutConfirmed()) {
        toast("Cần Cấu trúc OK trước khi gửi Read");
        return;
      }
      location.href = `/publish/${encodeURIComponent(state.workId)}`;
    });
  }

  window.KHReadEdition = {
    fromPath: readEditionWorkFromPath,
    load: loadReadEditionPage,
    wire: wireReadEdition,
    pickWork: async function pickWork() {
      document.querySelectorAll(".nav-link").forEach((b) => b.classList.remove("active"));
      document.querySelector('.nav-link[data-view="read-edition"]')?.classList.add("active");
      ["view-works", "view-publish", "view-licenses", "view-settings", "view-translation"].forEach((id) => {
        const el = $(id);
        if (el) el.hidden = true;
      });
      $("view-read-edition").hidden = false;
      $("re-pick").hidden = false;
      $("re-desk").hidden = true;
      if (location.pathname !== "/read-edition") {
        history.replaceState({ view: "read-edition" }, "", "/read-edition");
      }
      applyReview(null);
      $("re-heading").textContent = "Chế bản";
      $("re-status").textContent = "Năm bước: phân đoạn, nối dòng, chú thích, trích dẫn, Final Touch — Parse nằm cạnh chương, rồi đưa sang Read.";
      stopJobPoll();
      state.pageLoad += 1;
      state.hitlJobLoad += 1;
      state.hitlOverviewLoad += 1;
      state.workId = null;
      state.step = "structure";
      state.hitlJob = null;
      state.hitlOverview = null;
      state.jobs = [];
      state.jobLog = [];
      renderJobQueue();
      renderJobLog();
      applyStepVisibility();
      syncToolbar();
      await loadEditionSettings();
      const [sessionResp, works] = await Promise.all([api("/api/read-editions"), api("/api/works")]);
      const sessions = sessionResp.sessions || [];
      const sessionIds = new Set(sessions.map((s) => s.work_id));
      const box = $("re-sessions");
      const sessionBody = $("re-session-rows");
      if (box && sessionBody) {
        box.hidden = !sessions.length;
        sessionBody.innerHTML = sessions
          .map((s) => {
            const toc = s.toc_status ? s.toc_status : "chưa";
            const layout = s.layout_ok ? " · layout OK" : "";
            const when = s.updated_at ? escapeHtml(String(s.updated_at).replace("T", " ").slice(0, 16)) : "—";
            return `<tr data-id="${escapeHtml(s.work_id)}">
              <td>${escapeHtml(s.title || s.work_id)}<div class="muted">${escapeHtml(s.work_id)}</div></td>
              <td><span class="re-phase re-phase-${escapeHtml(s.phase || "macro")}">${escapeHtml(phaseLabel(s.phase))}</span>${layout}</td>
              <td>${s.chapters_parsed || 0}/${s.chapters_total || 0}</td>
              <td>${escapeHtml(toc)}</td>
              <td class="muted">${when}</td>
            </tr>`;
          })
          .join("");
        sessionBody.onclick = (e) => {
          const tr = e.target.closest("tr[data-id]");
          if (tr) location.href = `/read-edition/${encodeURIComponent(tr.dataset.id)}`;
        };
      }
      const rows = (works.works || []).filter((w) => w.has_raw && !sessionIds.has(w.id));
      const catalogHead = $("re-catalog-heading");
      if (catalogHead) catalogHead.textContent = sessions.length ? "Bắt đầu sách khác" : "Chọn tác phẩm";
      $("re-pick-rows").innerHTML = rows
        .map(
          (w) =>
            `<tr data-id="${escapeHtml(w.id)}"><td>${escapeHtml(w.title)}</td><td>${escapeHtml(w.language)}</td><td>${escapeHtml(w.id)}</td></tr>`,
        )
        .join("");
      $("re-pick-rows").onclick = (e) => {
        const tr = e.target.closest("tr[data-id]");
        if (tr) location.href = `/read-edition/${encodeURIComponent(tr.dataset.id)}`;
      };
    },
  };

  document.addEventListener("DOMContentLoaded", () => wireReadEdition());
})();
