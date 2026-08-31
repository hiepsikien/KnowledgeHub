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
  };

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      method: opts.method || "GET",
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      credentials: "same-origin",
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

  function readEditionWorkFromPath() {
    const parts = location.pathname.replace(/^\/+/, "").split("/").filter(Boolean);
    if (parts[0] !== "read-edition") return null;
    if (parts[1]) return decodeURIComponent(parts.slice(1).join("/"));
    return "";
  }

  function spanClass(style) {
    return `re-span re-span-${String(style || "other").replace(/[^a-z0-9_-]/gi, "")}`;
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
        parts.push(`<mark class="${spanClass(span.style)}" title="${escapeHtml(span.style)}">${escapeHtml(text.slice(start, end))}</mark>`);
        cursor = end;
      }
      if (cursor < text.length) parts.push(escapeHtml(text.slice(cursor)));
      inner = parts.join("");
    }
    if (kind === "heading") {
      const lvl = Math.min(4, Math.max(1, block.level || 1));
      return `<h${lvl + 1} class="re-heading">${inner}</h${lvl + 1}>`;
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
    return `<p class="re-paragraph">${inner}</p>`;
  }

  function setEditJson(value) {
    const ta = $("re-edit-json");
    if (ta) ta.value = value;
  }

  function fillEditorForSelection() {
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

  function renderChapterBody(chapter) {
    const box = $("re-body");
    if (!box) return;
    const blocks = chapter.blocks || [];
    const parsed = chapter.micro_status === "complete" && blocks.length;
    if (!parsed) {
      const compare = chapter.compare || reviewRow(chapter.chapter_id)?.compare || {};
      const omitted = Number(chapter.source_preview_omitted) || 0;
      const gap = chapter.source_preview_truncated
        ? `<p class="preview-gap">… đã rút ${omitted.toLocaleString()} chữ giữa đầu và cuối …</p>`
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
      return;
    }
    box.innerHTML = blocks
      .map(
        (b, i) =>
          `<div class="re-block${state.editIndex === i ? " on" : ""}" data-index="${i}" tabindex="0" role="button">${renderBlock(b)}</div>`,
      )
      .join("");
    box.onclick = (e) => {
      const hit = e.target.closest(".re-block[data-index]");
      if (!hit) return;
      state.editIndex = Number(hit.dataset.index);
      highlightSelectedBlock();
      fillEditorForSelection();
      document.querySelector("details.re-edit")?.setAttribute("open", "");
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
    const st = row.micro_status || "pending";
    return `<span class="re-micro re-micro-${st}">${escapeHtml(st === "complete" ? "parsed" : st)}</span>`;
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
    list.innerHTML = (manifest.chapters || [])
      .map(
        (row) =>
          `<div class="re-ch-row${row.chapter_id === state.chapterId ? " on" : ""}">
            <label class="re-ch-check"><input type="checkbox" data-chk="${escapeHtml(row.chapter_id)}" ${state.selected.has(row.chapter_id) ? "checked" : ""} /></label>
            <button type="button" class="re-ch-item" data-ch="${escapeHtml(row.chapter_id)}">
              <span class="re-ch-title">${escapeHtml(row.title || row.chapter_id)}</span>
              ${microBadge(row)}
              ${qaBadge(row)}
              ${layoutConfirmed() ? "" : flagBadges(reviewRow(row.chapter_id)?.flags)}
              <span class="muted">${(row.word_count || 0).toLocaleString()} từ</span>
            </button>
          </div>`,
      )
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

  async function selectChapter(chapterId) {
    if (!state.workId) return;
    state.chapterId = chapterId;
    state.editIndex = null;
    const meta = $("re-detail-meta");
    if (meta) meta.textContent = "Đang tải…";
    try {
      const chapter = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/chapters/${encodeURIComponent(chapterId)}`);
      state.chapter = chapter;
      try {
        localStorage.setItem(lastSectionKey(state.workId), chapterId);
      } catch {
        /* ignore quota */
      }
      renderChapterList(state.manifest);
      $("re-detail-title").textContent = chapter.title || chapterId;
      const parsed = chapter.micro_status === "complete";
      $("re-detail-meta").textContent = parsed
        ? `${chapter.block_count || 0} blocks · ${(chapter.word_count || 0).toLocaleString()} từ`
        : chapter.source_preview_truncated
          ? `Chưa parse REF — preview đầu + cuối (rút ${(Number(chapter.source_preview_omitted) || 0).toLocaleString()} chữ giữa)`
          : "Chưa parse REF — xem preview nguồn";
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
      $("re-edit-json")?.closest("details")?.toggleAttribute("open", parsed);
      renderStructTools(chapter);
      renderCompare(chapter);
      syncToolbar();
    } catch (err) {
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

    showBtn("re-macro", !macro);
    showBtn("re-layout-ok", macro && !layoutOk);
    const layoutBtn = $("re-layout-ok");
    if (layoutBtn) layoutBtn.disabled = !(health.ready_to_parse && !layoutOk);
    showBtn("re-parse-ch", layoutOk && currentPending);
    showBtn("re-parse-selected", layoutOk && selectedPending > 1);
    showBtn("re-parse-ready", layoutOk && pending.length > 0 && !(currentPending && pending.length === 1));
    showBtn("re-publish", layoutOk && parsed > 0);
    showBtn("re-more", true);

    let primary = "re-macro";
    if (!macro) primary = "re-macro";
    else if (!layoutOk) primary = "re-layout-ok";
    else if (currentPending) primary = "re-parse-ch";
    else if (pending.length) primary = "re-parse-ready";
    else primary = "re-publish";
    markPrimary(primary);
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
    if (parsed < total) return `${parsed}/${total} đã parse REF` + llmNote;
    return `${total} phần đã parse — đưa sang Read` + llmNote;
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
    $("re-toc-excerpt").textContent = toc.excerpt || "(không tìm thấy mục lục — chọn «Không có TOC» nếu đúng)";
    const status = toc.status;
    const banner = $("re-toc-banner");
    if (status === "yes") banner.textContent = "Đã xác nhận: đây là mục lục.";
    else if (status === "no") banner.textContent = "Đã ghi: đoạn này không phải mục lục.";
    else if (status === "none") banner.textContent = "Đã ghi: sách không có mục lục.";
    else banner.textContent = "Đây có phải mục lục của sách không?";
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
    bar.hidden = !hasMacro;
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
    box.hidden = !panes.length;
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
      const result = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/toc`, {
        method: "POST",
        body: { status },
      });
      applyReview(result);
      toast(status === "yes" ? "Đã xác nhận TOC" : status === "none" ? "Không có TOC" : "Không phải TOC");
      if (state.chapterId) await selectChapter(state.chapterId);
    } catch (err) {
      toast(err.message);
    }
  }

  function lastSectionKey(workId) {
    return `kh-re-section:${workId}`;
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
    state.workId = workId;
    state.selected.clear();
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
    try {
      const status = await api(`/api/works/${encodeURIComponent(workId)}/read-edition`);
      state.status = status;
      $("re-heading").textContent = status.title || workId;
      $("re-status").textContent = formatStatus(status);
      if (status.macro_complete && status.manifest) {
        state.manifest = status.manifest;
        await loadReview();
        $("re-status").textContent = formatStatus(status);
        renderChapterList(state.manifest);
        const chapters = state.manifest.chapters || [];
        const remembered =
          (workId ? localStorage.getItem(lastSectionKey(workId)) : null) ||
          status.hitl?.last_section_id;
        const pick = chapters.find((row) => row.chapter_id === remembered) || chapters[0];
        if (pick) await selectChapter(pick.chapter_id);
      } else {
        applyReview(null);
        $("re-chapters").innerHTML = `<p class="muted">Bấm «Phân đoạn» để liệt kê chương.</p>`;
        $("re-body").innerHTML = "";
        if ($("re-compare")) $("re-compare").hidden = true;
        if ($("re-struct-tools")) $("re-struct-tools").hidden = true;
      }
      syncToolbar();
    } catch (err) {
      $("re-status").textContent = err.message;
      syncToolbar();
    }
  }

  function wireReadEdition() {
    $("re-macro")?.addEventListener("click", async () => {
      if (!state.workId) return;
      if (state.status?.macro_complete) {
        toast("Đã có phân đoạn đã lưu — bấm Reset phân đoạn nếu muốn làm lại từ đầu");
        return;
      }
      $("re-status").textContent = "Đang phân đoạn (macro)…";
      try {
        await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/macro`, {
          method: "POST",
          body: { force: false, use_llm: useLlmMacro() },
        });
        toast("Đã phân đoạn xong");
        await loadReadEditionPage(state.workId);
      } catch (err) {
        toast(err.message);
        $("re-status").textContent = err.message;
      }
    });

    $("re-reset")?.addEventListener("click", async () => {
      if (!state.workId) return;
      if (!window.confirm("Xóa cấu trúc HITL và parse REF của sách này, làm lại từ Phân đoạn?")) return;
      $("re-status").textContent = "Đang reset phân đoạn…";
      try {
        await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/macro`, {
          method: "POST",
          body: { force: true, use_llm: useLlmMacro() },
        });
        try {
          localStorage.removeItem(lastSectionKey(state.workId));
        } catch {
          /* ignore */
        }
        toast("Đã reset — phân đoạn lại từ đầu");
        await loadReadEditionPage(state.workId);
      } catch (err) {
        toast(err.message);
        $("re-status").textContent = err.message;
      }
    });

    $("re-parse-ch")?.addEventListener("click", async () => {
      if (!state.workId || !state.chapterId) return;
      if (!assertReadyToParse()) return;
      toast("Đang parse REF chương…");
      try {
        await api(
          `/api/works/${encodeURIComponent(state.workId)}/read-edition/chapters/${encodeURIComponent(state.chapterId)}/parse`,
          { method: "POST", body: { use_llm: useLlmRelabel() } },
        );
        toast("Parse xong");
        const status = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition`);
        state.status = status;
        $("re-status").textContent = formatStatus(status);
        await refreshManifest();
        await selectChapter(state.chapterId);
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
      toast(`Đang parse ${ids.length} chương…`);
      try {
        const result = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/chapters/parse`, {
          method: "POST",
          body: { chapter_ids: ids, use_llm: useLlmRelabel() },
        });
        const errCount = Object.keys(result.errors || {}).length;
        toast(errCount ? `Xong ${result.count}, lỗi ${errCount}` : `Parse xong ${result.count} chương`);
        const status = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition`);
        state.status = status;
        await loadReview();
        $("re-status").textContent = formatStatus(status);
        await refreshManifest();
        if (state.chapterId) await selectChapter(state.chapterId);
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
      toast(`Đang parse ${ids.length} chương…`);
      try {
        const result = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/chapters/parse`, {
          method: "POST",
          body: { chapter_ids: ids, use_llm: useLlmRelabel() },
        });
        const errCount = Object.keys(result.errors || {}).length;
        toast(errCount ? `Xong ${result.count}, lỗi ${errCount}` : `Parse xong ${result.count} chương`);
        const status = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition`);
        state.status = status;
        await loadReview();
        $("re-status").textContent = formatStatus(status);
        await refreshManifest();
        if (state.chapterId) await selectChapter(state.chapterId);
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

    $("re-qa-ch")?.addEventListener("click", async () => {
      if (!state.workId || !state.chapterId) return;
      if (state.chapter?.micro_status !== "complete") {
        toast("Parse REF chương trước khi QA");
        return;
      }
      toast("Đang QA chương…");
      try {
        const qa = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/qa`, {
          method: "POST",
          body: { chapter_id: state.chapterId, use_llm: useLlmQa() },
        });
        toast(qa.passed ? "QA pass" : "QA fail");
        await selectChapter(state.chapterId);
        await refreshManifest();
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
              block_index: index,
              type: block.type,
              text: block.text,
              level: block.level,
              speaker: block.speaker,
            };
          })
          .filter(Boolean);
      } else if (parsed && typeof parsed === "object" && state.editIndex != null) {
        const orig = origBlocks[state.editIndex] || {};
        if (JSON.stringify(orig) !== JSON.stringify(parsed)) {
          patches = [
            {
              block_index: state.editIndex,
              type: parsed.type,
              text: parsed.text,
              level: parsed.level,
              speaker: parsed.speaker,
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

    $("re-publish")?.addEventListener("click", () => {
      if (state.workId) location.href = `/publish/${encodeURIComponent(state.workId)}`;
    });

    document.querySelector('.nav-link[data-view="read-edition"]')?.addEventListener("click", () => {
      location.href = "/read-edition";
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
      $("re-status").textContent = "Cấu trúc chương, định dạng REF, đưa sang Read.";
      state.workId = null;
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
