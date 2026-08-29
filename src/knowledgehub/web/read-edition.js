/* Read Edition CMS — REF/1 per-chapter preview, QA, edit */

(function () {
  const $ = (id) => document.getElementById(id);
  const state = {
    workId: null,
    chapterId: null,
    manifest: null,
    chapter: null,
    editIndex: null,
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
    const parts = location.pathname.replace(/^\/+/, "").split("/");
    if (parts[0] === "read-edition" && parts[1]) return decodeURIComponent(parts.slice(1).join("/"));
    return null;
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
    box.innerHTML = (chapter.blocks || [])
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
      const details = document.querySelector("details.re-edit");
      if (details) details.open = true;
    };
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
          `<button type="button" class="re-ch-item${row.chapter_id === state.chapterId ? " on" : ""}" data-ch="${escapeHtml(row.chapter_id)}">
            <span class="re-ch-title">${escapeHtml(row.title || row.chapter_id)}</span>
            ${qaBadge(row)}
            <span class="muted">${(row.word_count || 0).toLocaleString()} từ</span>
          </button>`,
      )
      .join("");
    list.onclick = (e) => {
      const btn = e.target.closest("[data-ch]");
      if (btn) void selectChapter(btn.dataset.ch);
    };
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
      renderChapterList(state.manifest);
      $("re-detail-title").textContent = chapter.title || chapterId;
      $("re-detail-meta").textContent = `${(chapter.block_count || 0)} blocks · ${(chapter.word_count || 0).toLocaleString()} từ`;
      renderChapterBody(chapter);
      const qa = chapter.qa;
      $("re-qa-panel").hidden = !qa;
      if (qa) {
        const llm = qa.llm || {};
        $("re-qa-panel").innerHTML = `<p><strong>QA:</strong> ${qa.passed ? "pass" : "fail"} · ${escapeHtml(qa.summary_vi || "")}</p>` +
          (llm.scores ? `<p class="muted">overall ${llm.scores.overall}/10 · structure ${llm.scores.block_structure}/10</p>` : "");
      }
      fillEditorForSelection();
    } catch (err) {
      if (meta) meta.innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`;
      toast(err.message);
    }
  }

  function useLlmRelabel() {
    const el = $("re-use-llm");
    return el ? el.checked : true;
  }

  function useLlmQa() {
    const el = $("re-use-llm-qa");
    return el ? el.checked : true;
  }

  function applyLlmDefaults(status) {
    const relabel = $("re-use-llm");
    const qa = $("re-use-llm-qa");
    if (relabel && status) {
      relabel.checked = status.default_use_llm_relabel !== false;
      relabel.disabled = !status.gemini_available;
    }
    if (qa && status) {
      qa.checked = !!status.gemini_available;
      qa.disabled = !status.gemini_available;
    }
  }

  function formatStatus(status) {
    const mode = status.manifest?.ref_mode || (status.default_use_llm_relabel ? "llm_hybrid (default)" : "rule");
    const llmNote = status.gemini_available ? "" : " · không có GEMINI_API_KEY — chỉ rule";
    const base = status.package_built
      ? `${status.block_count} blocks · ${status.manifest?.chapter_count || 0} chương · ${status.content_kind || ""} · ${mode}`
      : "Chưa build package";
    return base + llmNote;
  }

  async function loadReadEditionPage(workId) {
    state.workId = workId;
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
    try {
      const status = await api(`/api/works/${encodeURIComponent(workId)}/read-edition`);
      applyLlmDefaults(status);
      $("re-heading").textContent = status.title || workId;
      $("re-status").textContent = formatStatus(status);
      if (!status.package_built) {
        await api(`/api/works/${encodeURIComponent(workId)}/read-edition/build`, {
          method: "POST",
          body: { use_llm: useLlmRelabel() },
        });
      }
      const manifestResp = await api(`/api/works/${encodeURIComponent(workId)}/read-edition/manifest`);
      state.manifest = manifestResp.manifest;
      renderChapterList(state.manifest);
      const first = (state.manifest.chapters || [])[0];
      if (first) await selectChapter(first.chapter_id);
    } catch (err) {
      $("re-status").textContent = err.message;
    }
  }

  function wireReadEdition() {
    $("re-build")?.addEventListener("click", async () => {
      if (!state.workId) return;
      $("re-status").textContent = "Đang build…";
      try {
        await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/build`, {
          method: "POST",
          body: { force: true, use_llm: useLlmRelabel() },
        });
        toast("Đã build lại REF package");
        await loadReadEditionPage(state.workId);
      } catch (err) {
        toast(err.message);
      }
    });
    $("re-qa-ch")?.addEventListener("click", async () => {
      if (!state.workId || !state.chapterId) return;
      toast("Đang QA chương…");
      try {
        const qa = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/qa`, {
          method: "POST",
          body: { chapter_id: state.chapterId, use_llm: useLlmQa() },
        });
        toast(qa.passed ? "QA pass" : "QA fail");
        await selectChapter(state.chapterId);
        const manifestResp = await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/manifest`);
        state.manifest = manifestResp.manifest;
        renderChapterList(state.manifest);
      } catch (err) {
        toast(err.message);
      }
    });
    $("re-qa-all")?.addEventListener("click", async () => {
      if (!state.workId) return;
      toast("Đang QA toàn bộ (rule only)…");
      try {
        await api(`/api/works/${encodeURIComponent(state.workId)}/read-edition/qa`, {
          method: "POST",
          body: { use_llm: useLlmQa() },
        });
        toast("QA xong");
        await loadReadEditionPage(state.workId);
      } catch (err) {
        toast(err.message);
      }
    });
    $("re-save-blocks")?.addEventListener("click", async () => {
      if (!state.workId || !state.chapterId) return;
      let parsed;
      try {
        parsed = JSON.parse($("re-edit-json").value || "null");
      } catch (err) {
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
      $("re-heading").textContent = "Read Edition";
      $("re-status").textContent = "Chọn tác phẩm có file raw";
      const works = await api("/api/works");
      const rows = (works.works || []).filter((w) => w.has_raw);
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
