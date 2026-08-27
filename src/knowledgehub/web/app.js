const $ = (id) => document.getElementById(id);

const state = {
  works: [],
  selected: null,
  health: null,
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
    n.gutenberg && "Gutenberg",
    n.dropped_electronic_note && "note eBook",
    n.dropped_contents && "TOC",
    n.dropped_produced_by && "Produced by",
    n.dropped_tail_index && "index",
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
      document.querySelectorAll(".nav-link").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const view = btn.dataset.view;
      $("view-works").hidden = view !== "works";
      $("view-licenses").hidden = view !== "licenses";
      $("view-publish").hidden = true;
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
  await loadDesk();
}

async function loadDesk() {
  await refresh();
  await loadLicenses();
}

boot();
