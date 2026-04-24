function thumbUrl(idx) {
  return `/api/thumb-shot?idx=${idx}&max_dim=400`;
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

function renderTile(idx, item) {
  const div = document.createElement("div");
  div.className = "tile";
  const img = document.createElement("img");
  img.loading = "lazy";
  img.alt = item.name;
  img.src = thumbUrl(idx);
  img.onerror = () => {
    img.replaceWith(
      Object.assign(document.createElement("div"), {
        className: "nonimg",
        textContent: "Thumbnail unavailable",
      })
    );
  };
  div.appendChild(img);
  const fn = document.createElement("footer");
  fn.textContent = item.name + " · " + item.reason;
  div.appendChild(fn);
  const lab = document.createElement("label");
  const cb = document.createElement("input");
  cb.type = "checkbox";
  if (item.path != null) cb.setAttribute("data-path", String(item.path));
  lab.appendChild(cb);
  lab.appendChild(document.createTextNode(" Move to Trash"));
  div.appendChild(lab);
  return div;
}

async function load() {
  const r = await fetch("/api/meta");
  if (!r.ok) throw new Error(await r.text());
  const data = await r.json();
  const scanEl = document.getElementById("scanLine");
  const n = data.count ?? 0;
  scanEl.textContent =
    n === 0
      ? "No candidates in this scan."
      : `${n} candidate${n === 1 ? "" : "s"} found.`;
  scanEl.title = data.scan_dir || "";
  const main = document.getElementById("main");
  main.innerHTML = "";
  if (!data.items || !data.items.length) {
    main.innerHTML = "<p class=\"sub\">No screenshot candidates found.</p>";
    return;
  }
  const wrap = document.createElement("div");
  wrap.className = "group";
  const head = document.createElement("div");
  head.className = "group-head";
  head.textContent = "All candidates";
  wrap.appendChild(head);
  const tiles = document.createElement("div");
  tiles.className = "tiles";
  data.items.forEach((item, idx) => {
    tiles.appendChild(renderTile(idx, item));
  });
  wrap.appendChild(tiles);
  main.appendChild(wrap);
}

function collectQuarantine() {
  const paths = [];
  document.querySelectorAll('.tile input[type="checkbox"]:checked').forEach((cb) => {
    const p = cb.getAttribute("data-path") || cb.dataset.path;
    if (typeof p === "string" && p.trim()) paths.push(p);
  });
  return paths;
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
  if (!r.ok) throw new Error(data.detail || data.raw || r.statusText);
  return data;
}

document.getElementById("btnApply").addEventListener("click", async () => {
  const paths = collectQuarantine();
  if (!paths.length) {
    showToast("Check the files you want to move to Trash.", "err");
    return;
  }
  if (!confirm(`Move ${paths.length} file(s) to the Trash?`)) return;
  try {
    const res = await postJson("/api/move-to-trash", { paths });
    const errn = res.errors && res.errors.length;
    showToast(
      `Moved ${res.moved.length} to Trash${errn ? `; ${errn} failed` : ""}.`,
      errn ? "err" : "ok",
    );
    await load();
  } catch (e) {
    showToast(String(e.message || e), "err");
  }
});

load().catch((e) => {
  document.getElementById("main").innerHTML = `<p class="sub">Failed to load: ${e}</p>`;
});
