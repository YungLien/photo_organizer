/** Resolve /api/... for both standalone review (/) and unified app (/review/). */
function apiUrl(suffix) {
  const p = suffix.replace(/^\//, "");
  const path = window.location.pathname;
  if (path === "/" || path === "") {
    return "/" + p;
  }
  const base = path.endsWith("/") ? path : path + "/";
  return base + p;
}

function thumbUrl(kind, gid, idx, maxDim) {
  const d = maxDim ?? 400;
  return apiUrl(
    `api/thumb?kind=${encodeURIComponent(kind)}&gid=${gid}&idx=${idx}&max_dim=${d}`,
  );
}

function previewMaxDim() {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const target = Math.floor(Math.min(window.innerWidth, window.innerHeight) * dpr * 0.92);
  return Math.min(3200, Math.max(960, target));
}

const lbState = {
  kind: "",
  gid: 0,
  idx: 0,
  maxDim: 1600,
  /** Display scale (1 = fit within CSS max bounds); Pinterest-style center zoom. */
  lbScale: 1,
  lbPanX: 0,
  lbPanY: 0,
};

const lbDrag = {
  active: false,
  ptrId: null,
  lastX: 0,
  lastY: 0,
};

function groupEl(kind, gid) {
  return document.querySelector(`.group[data-kind="${kind}"][data-gid="${gid}"]`);
}

function imageIndicesInGroup(kind, gid) {
  const g = groupEl(kind, gid);
  if (!g) return [];
  return [...g.querySelectorAll(".tile.has-thumb")]
    .map((t) => parseInt(t.dataset.idx, 10))
    .filter((n) => !Number.isNaN(n))
    .sort((a, b) => a - b);
}

function imageCountInGroup(kind, gid) {
  return imageIndicesInGroup(kind, gid).length;
}

function tileEl(kind, gid, idx) {
  return document.querySelector(
    `.tile.has-thumb[data-kind="${kind}"][data-gid="${gid}"][data-idx="${idx}"]`,
  );
}

function tileCheckbox(kind, gid, idx) {
  const t = tileEl(kind, gid, idx);
  return t ? t.querySelector('input[type="checkbox"]') : null;
}

function syncLightboxTrashFromTile() {
  const cb = tileCheckbox(lbState.kind, lbState.gid, lbState.idx);
  const lb = document.getElementById("lightboxTrash");
  if (cb && lb) lb.checked = cb.checked;
}

function applyLightboxTrashToTile() {
  const lb = document.getElementById("lightboxTrash");
  const cb = tileCheckbox(lbState.kind, lbState.gid, lbState.idx);
  if (cb && lb) cb.checked = lb.checked;
}

function updateLightboxNav() {
  const n = imageCountInGroup(lbState.kind, lbState.gid);
  const one = n <= 1;
  document.querySelector(".lightbox-prev").hidden = one;
  document.querySelector(".lightbox-next").hidden = one;
}

function applyLbViewTransform() {
  const stage = document.getElementById("lbStage");
  if (!stage) return;
  const s = Math.max(1, Math.min(6, lbState.lbScale));
  lbState.lbScale = s;
  if (s <= 1) {
    lbState.lbPanX = 0;
    lbState.lbPanY = 0;
  }
  stage.style.transform = `translate(${lbState.lbPanX}px, ${lbState.lbPanY}px) scale(${s})`;
  const wrap = document.getElementById("lightboxImgWrap");
  if (wrap) wrap.style.cursor = s > 1 ? "grab" : "";
}

function resetLbView() {
  lbState.lbScale = 1;
  lbState.lbPanX = 0;
  lbState.lbPanY = 0;
  applyLbViewTransform();
}

function nudgeLbScale(factor) {
  lbState.lbScale = Math.min(6, Math.max(1, lbState.lbScale * factor));
  if (lbState.lbScale <= 1) {
    lbState.lbPanX = 0;
    lbState.lbPanY = 0;
  }
  applyLbViewTransform();
}

function resetLightboxImgStyles() {
  const img = document.getElementById("lightboxImg");
  const stage = document.getElementById("lbStage");
  if (stage) stage.style.transform = "";
  if (img) {
    img.style.width = "";
    img.style.height = "";
  }
  lbState.lbScale = 1;
  lbState.lbPanX = 0;
  lbState.lbPanY = 0;
  lbDrag.active = false;
  lbDrag.ptrId = null;
  const wrap = document.getElementById("lightboxImgWrap");
  if (wrap) wrap.style.cursor = "";
}

function refreshLightboxImage() {
  const { kind, gid, idx, maxDim } = lbState;
  const img = document.getElementById("lightboxImg");
  const cap = document.getElementById("lightboxCaption");
  const tile = tileEl(kind, gid, idx);
  const name = tile ? tile.dataset.name || "" : "";
  const idxs = imageIndicesInGroup(kind, gid);
  const pos = idxs.indexOf(idx);
  const shown = pos >= 0 ? pos + 1 : 1;
  const total = idxs.length || 1;
  img.alt = name;
  img.removeAttribute("width");
  img.removeAttribute("height");
  resetLightboxImgStyles();
  const onReady = () => {
    if (img.naturalWidth > 0) resetLbView();
  };
  img.onload = onReady;
  img.src = thumbUrl(kind, gid, idx, maxDim);
  if (img.complete && img.naturalWidth > 0) {
    requestAnimationFrame(onReady);
  }
  cap.textContent = total > 1 ? `${name} (${shown} / ${total})` : name;
  syncLightboxTrashFromTile();
  updateLightboxNav();
}

function openLightbox(kind, gid, idx) {
  const idxs = imageIndicesInGroup(kind, gid);
  if (!idxs.includes(idx)) return;
  lbState.kind = kind;
  lbState.gid = gid;
  lbState.idx = idx;
  lbState.maxDim = previewMaxDim();
  const box = document.getElementById("lightbox");
  box.hidden = false;
  document.body.style.overflow = "hidden";
  refreshLightboxImage();
  document.getElementById("lightboxTrash").focus({ preventScroll: true });
}

function closeLightbox() {
  const box = document.getElementById("lightbox");
  if (!box.hidden) {
    applyLightboxTrashToTile();
    box.hidden = true;
    document.body.style.overflow = "";
    resetLightboxImgStyles();
  }
}

function dismissLightboxForReload() {
  const box = document.getElementById("lightbox");
  const img = document.getElementById("lightboxImg");
  box.hidden = true;
  document.body.style.overflow = "";
  img.removeAttribute("src");
  resetLightboxImgStyles();
}

function lightboxStep(delta) {
  const idxs = imageIndicesInGroup(lbState.kind, lbState.gid);
  if (idxs.length <= 1) return;
  applyLightboxTrashToTile();
  const pos = idxs.indexOf(lbState.idx);
  const i = pos < 0 ? 0 : (pos + delta + idxs.length) % idxs.length;
  lbState.idx = idxs[i];
  refreshLightboxImage();
}

function showToast(msg, cls) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast " + (cls || "");
  el.hidden = false;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    el.hidden = true;
  }, 5000);
}

function renderTile(kind, gid, idx, item) {
  const div = document.createElement("div");
  div.className = "tile";
  const pathStr = item.path != null ? String(item.path) : "";
  const shownName =
    item.display_name != null && String(item.display_name).trim() !== ""
      ? String(item.display_name)
      : item.name != null
        ? String(item.name)
        : "";
  if (item.is_image) {
    div.classList.add("has-thumb");
    div.dataset.kind = kind;
    div.dataset.gid = String(gid);
    div.dataset.idx = String(idx);
    div.dataset.name = shownName;
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = shownName;
    img.src = thumbUrl(kind, gid, idx, 400);
    img.onerror = () => {
      div.classList.remove("has-thumb");
      delete div.dataset.kind;
      delete div.dataset.gid;
      delete div.dataset.idx;
      delete div.dataset.name;
      img.replaceWith(
        Object.assign(document.createElement("div"), {
          className: "nonimg",
          textContent: "Thumbnail unavailable",
        }),
      );
    };
    div.appendChild(img);
  } else {
    const nv = document.createElement("div");
    nv.className = "nonimg";
    nv.textContent = "Not an image (no preview)";
    div.appendChild(nv);
  }
  const fn = document.createElement("footer");
  fn.textContent = shownName;
  div.appendChild(fn);
  const lab = document.createElement("label");
  const cb = document.createElement("input");
  cb.type = "checkbox";
  if (pathStr) cb.setAttribute("data-path", pathStr);
  lab.appendChild(cb);
  lab.appendChild(document.createTextNode(" Move to Trash"));
  div.appendChild(lab);
  return div;
}

function renderGroup(kind, gid, group) {
  const wrap = document.createElement("div");
  wrap.className = "group";
  wrap.dataset.kind = kind;
  wrap.dataset.gid = String(gid);
  const head = document.createElement("div");
  head.className = "group-head";
  const n = group.items.length;
  head.textContent = `${n} files · ${kind === "similar" ? "Similar group" : "Exact duplicate"} #${gid + 1}`;
  wrap.appendChild(head);
  const tiles = document.createElement("div");
  tiles.className = "tiles";
  group.items.forEach((item, idx) => {
    tiles.appendChild(renderTile(kind, gid, idx, item));
  });
  wrap.appendChild(tiles);
  return wrap;
}

async function load() {
  const r = await fetch(apiUrl("api/meta"));
  if (!r.ok) throw new Error(await r.text());
  const data = await r.json();
  const main = document.getElementById("main");
  main.innerHTML = "";

  if (data.exact_groups && data.exact_groups.length) {
    const t = document.createElement("h2");
    t.className = "section-title";
    t.textContent = "Exact duplicates";
    main.appendChild(t);
    data.exact_groups.forEach((g, gid) => {
      main.appendChild(renderGroup("exact", gid, g));
    });
  }

  if (data.similar_groups && data.similar_groups.length) {
    const t = document.createElement("h2");
    t.className = "section-title";
    t.textContent = "Similar photos";
    main.appendChild(t);
    data.similar_groups.forEach((g, gid) => {
      main.appendChild(renderGroup("similar", gid, g));
    });
  }

  if (!main.querySelector(".group")) {
    main.innerHTML =
      "<p class=\"sub\">No duplicate or similar groups to show. Tap <strong>Done</strong> to return home.</p>";
  }
}

function collectTrashPaths() {
  const paths = [];
  document.querySelectorAll('.tile input[type="checkbox"]:checked').forEach((cb) => {
    const p = cb.getAttribute("data-path") || cb.dataset.path;
    if (typeof p === "string" && p.trim()) paths.push(p);
  });
  return paths;
}

function formatApiError(data, statusText) {
  const d = data.detail;
  if (Array.isArray(d)) {
    return d
      .map((e) => (typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
      .join("; ");
  }
  if (typeof d === "string") return d;
  if (d != null && typeof d === "object") return JSON.stringify(d);
  if (data.raw) return String(data.raw);
  return statusText || "Request failed";
}

async function postJson(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await r.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    data = { raw: text };
  }
  if (!r.ok) throw new Error(formatApiError(data, r.statusText));
  return data;
}

document.getElementById("main").addEventListener("click", (e) => {
  const img = e.target.closest(".tile.has-thumb > img");
  if (!img) return;
  e.preventDefault();
  const tile = img.closest(".tile");
  const kind = tile.dataset.kind;
  const gid = parseInt(tile.dataset.gid, 10);
  const idx = parseInt(tile.dataset.idx, 10);
  openLightbox(kind, gid, idx);
});

document.querySelector(".lightbox-backdrop").addEventListener("click", () => {
  closeLightbox();
});

document.querySelector(".lightbox-close").addEventListener("click", () => {
  closeLightbox();
});

document.querySelector(".lightbox-prev").addEventListener("click", (e) => {
  e.stopPropagation();
  lightboxStep(-1);
});

document.querySelector(".lightbox-next").addEventListener("click", (e) => {
  e.stopPropagation();
  lightboxStep(1);
});

document.getElementById("lightboxTrash").addEventListener("change", () => {
  applyLightboxTrashToTile();
});

document.addEventListener("keydown", (e) => {
  const box = document.getElementById("lightbox");
  if (box.hidden) return;
  if (e.key === "Escape") {
    e.preventDefault();
    closeLightbox();
  } else if (e.key === "ArrowLeft") {
    e.preventDefault();
    lightboxStep(-1);
  } else if (e.key === "ArrowRight") {
    e.preventDefault();
    lightboxStep(1);
  } else if (e.key === "+" || e.key === "=") {
    e.preventDefault();
    nudgeLbScale(1.12);
  } else if (e.key === "-" || e.key === "_") {
    e.preventDefault();
    nudgeLbScale(1 / 1.12);
  } else if (e.key === "0") {
    e.preventDefault();
    resetLbView();
  }
});

function bindLightboxZoomControls() {
  const wrap = document.getElementById("lightboxImgWrap");
  if (!wrap || wrap.dataset.zoomBound === "1") return;
  wrap.dataset.zoomBound = "1";
  wrap.addEventListener(
    "wheel",
    (e) => {
      const box = document.getElementById("lightbox");
      if (box.hidden) return;
      e.preventDefault();
      const up = e.deltaY < 0;
      const factor = up ? 1.08 : 1 / 1.08;
      nudgeLbScale(factor);
    },
    { passive: false },
  );

  document.getElementById("lbZoomIn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    nudgeLbScale(1.2);
  });
  document.getElementById("lbZoomOut")?.addEventListener("click", (e) => {
    e.stopPropagation();
    nudgeLbScale(1 / 1.2);
  });

  function endPan(e) {
    if (!lbDrag.active || e.pointerId !== lbDrag.ptrId) return;
    lbDrag.active = false;
    lbDrag.ptrId = null;
    try {
      wrap.releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
    wrap.style.cursor = lbState.lbScale > 1 ? "grab" : "";
  }

  wrap.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const box = document.getElementById("lightbox");
    if (box.hidden || lbState.lbScale <= 1) return;
    if (e.target.closest && e.target.closest("button")) return;
    lbDrag.active = true;
    lbDrag.ptrId = e.pointerId;
    lbDrag.lastX = e.clientX;
    lbDrag.lastY = e.clientY;
    wrap.setPointerCapture(e.pointerId);
    wrap.style.cursor = "grabbing";
  });
  wrap.addEventListener("pointermove", (e) => {
    if (!lbDrag.active || e.pointerId !== lbDrag.ptrId) return;
    const dx = e.clientX - lbDrag.lastX;
    const dy = e.clientY - lbDrag.lastY;
    lbDrag.lastX = e.clientX;
    lbDrag.lastY = e.clientY;
    lbState.lbPanX += dx;
    lbState.lbPanY += dy;
    applyLbViewTransform();
  });
  wrap.addEventListener("pointerup", endPan);
  wrap.addEventListener("pointercancel", endPan);
}

window.addEventListener("resize", () => {
  const box = document.getElementById("lightbox");
  if (!box || box.hidden) return;
  const img = document.getElementById("lightboxImg");
  if (img && img.naturalWidth > 0) resetLbView();
});

bindLightboxZoomControls();

function pipelineUrl() {
  return "/api/pipeline";
}

async function pollPipelineJobRoot(jobId) {
  const tick = 300;
  while (true) {
    await new Promise((resolve) => setTimeout(resolve, tick));
    const r = await fetch(`/api/pipeline/job/${encodeURIComponent(jobId)}`);
    const text = await r.text();
    let j;
    try {
      j = JSON.parse(text);
    } catch {
      throw new Error(text || r.statusText);
    }
    if (!r.ok) throw new Error(formatApiError(j, r.statusText));
    if (j.status === "complete" || j.status === "failed") {
      if (!j.result) throw new Error("No result from pipeline job.");
      return j.result;
    }
  }
}

document.getElementById("btnFinishNoDelete").addEventListener("click", async () => {
  const btn = document.getElementById("btnFinishNoDelete");
  try {
    const mr = await fetch(apiUrl("api/meta"));
    const meta = await mr.json();
    const inputDir = (meta.last_input_dir || "").trim();
    if (!inputDir) {
      showToast("No import folder on record. Returning home.", "ok");
      window.location.href = "/";
      return;
    }
    if (meta.last_run_organize === true) {
      showToast("Already sorted by date. Returning home.", "ok");
      setTimeout(() => {
        window.location.href = "/";
      }, 400);
      return;
    }
    btn.disabled = true;
    const r = await fetch(pipelineUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        input_dir: inputDir,
        organized_root: meta.last_organized_root || "~/Desktop/Organized",
        run_organize: true,
        run_duplicates: false,
        copy_files: meta.last_copy_files !== false,
        scan_import_folder_for_duplicates: meta.last_scan_import_folder_for_duplicates !== false,
        include_similar_duplicates: meta.last_include_similar_duplicates === true,
      }),
    });
    const text = await r.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      showToast(text || r.statusText, "err");
      btn.disabled = false;
      return;
    }
    if (!r.ok) {
      showToast(formatApiError(data, r.statusText), "err");
      btn.disabled = false;
      return;
    }
    if (data.accepted === false) {
      showToast((data.errors && data.errors.join(" ")) || "Sort failed.", "err");
      btn.disabled = false;
      return;
    }
    if (!data.job_id) {
      showToast("Unexpected server response.", "err");
      btn.disabled = false;
      return;
    }
    let result;
    try {
      result = await pollPipelineJobRoot(data.job_id);
    } catch (err) {
      showToast(String(err.message || err), "err");
      btn.disabled = false;
      return;
    }
    if (!result.ok) {
      showToast((result.errors && result.errors.join(" ")) || "Sort failed.", "err");
      btn.disabled = false;
      return;
    }
    showToast(result.message || "Sorted by date.", "ok");
    setTimeout(() => {
      window.location.href = "/";
    }, 500);
  } catch (e) {
    showToast(String(e.message || e), "err");
    btn.disabled = false;
  }
});

document.getElementById("btnDelete").addEventListener("click", async () => {
  const paths = collectTrashPaths();
  if (!paths.length) {
    showToast("Check the photos you want to move to Trash.", "err");
    return;
  }
  if (
    !confirm(
      `Move ${paths.length} checked file(s) to the Trash? You can restore them from Trash if needed.`,
    )
  ) {
    return;
  }
  try {
    const res = await postJson(apiUrl("api/move-to-trash"), { paths });
    const errn = (res.errors && res.errors.length) || 0;
    const movedn = (res.moved && res.moved.length) || 0;
    if (errn === 0 && movedn > 0) {
      const logPath = res.audit_log && String(res.audit_log).trim() ? String(res.audit_log).trim() : "";
      if (logPath) console.info("Trash audit log:", logPath);
      const hint =
        res.trash_locations_hint && String(res.trash_locations_hint).trim()
          ? String(res.trash_locations_hint).trim()
          : "Open Finder → Trash.";
      showToast(`Moved ${movedn} to Trash. ${hint}`, "ok");
      dismissLightboxForReload();
      setTimeout(() => {
        window.location.href = "/";
      }, 500);
      return;
    }
    const errPreview =
      res.errors && res.errors.length
        ? res.errors
            .slice(0, 3)
            .map((x) => String(x))
            .join("; ")
        : "";
    showToast(
      movedn
        ? `Moved ${movedn}; ${errn} failed${errPreview ? `: ${errPreview}` : ""}`
        : `Nothing moved${errPreview ? `: ${errPreview}` : ""}`,
      "err",
    );
    if (res.errors && res.errors.length) console.warn(res.errors);
    if (movedn > 0) {
      dismissLightboxForReload();
      await load();
    }
  } catch (e) {
    showToast(String(e.message || e), "err");
  }
});

load().catch((e) => {
  document.getElementById("main").innerHTML = `<p class="sub">Failed to load: ${e}</p>`;
});
