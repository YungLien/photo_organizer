function setStatus(el, text, cls) {
  el.textContent = text;
  el.className = "dash-status" + (cls ? " " + cls : "");
}

/** Poll background pipeline until complete or failed; returns the final `result` dict. */
async function pollPipelineJob(statusEl, jobId) {
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
    if (!r.ok) {
      const msg = j.detail || text || r.statusText;
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    if (j.message && statusEl) {
      statusEl.textContent = j.message;
      statusEl.className = "dash-status";
    }
    if (j.status === "complete" || j.status === "failed") {
      if (!j.result) throw new Error("No result from pipeline job.");
      return j.result;
    }
  }
}

function formatPickFolderError(data, statusText) {
  const d = data && data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d
      .map((e) => (typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
      .join("; ");
  }
  if (data && data.raw) return String(data.raw);
  return statusText || "Request failed";
}

async function pickFolderIntoField(fieldId, browseBtn) {
  const status = document.getElementById("dashStatus");
  const field = document.getElementById(fieldId);
  const startBtn = document.getElementById("btnStart");
  const btns = [browseBtn, startBtn].filter(Boolean);
  btns.forEach((b) => {
    b.disabled = true;
  });
  setStatus(status, "Opening folder picker…", "");
  try {
    const r = await fetch("/api/pick-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target: "input" }),
    });
    let data = {};
    try {
      data = await r.json();
    } catch {
      data = {};
    }
    if (!r.ok) {
      setStatus(status, formatPickFolderError(data, r.statusText), "err");
      return;
    }
    if (data.cancelled) {
      setStatus(status, "");
      return;
    }
    if (typeof data.path === "string" && data.path.trim()) {
      field.value = data.path.trim();
      setStatus(status, "Path updated.", "ok");
      setTimeout(() => {
        if (status.textContent === "Path updated.") setStatus(status, "");
      }, 2000);
    }
  } catch (err) {
    setStatus(status, String(err.message || err), "err");
  } finally {
    btns.forEach((b) => {
      b.disabled = false;
    });
  }
}

document.getElementById("btnBrowseInput").addEventListener("click", () => {
  pickFolderIntoField("inputDir", document.getElementById("btnBrowseInput"));
});

document.getElementById("pipelineForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const status = document.getElementById("dashStatus");
  const btn = document.getElementById("btnStart");
  const inputDir = document.getElementById("inputDir").value.trim();

  if (!inputDir) {
    setStatus(status, "Select an import folder to continue.", "err");
    return;
  }

  btn.disabled = true;
  setStatus(status, "Starting…", "");

  try {
    const r = await fetch("/api/pipeline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        input_dir: inputDir,
        organized_root: "~/Desktop/Organized",
        run_organize: true,
        run_duplicates: true,
        copy_files: true,
        scan_import_folder_for_duplicates: true,
        include_similar_duplicates: true,
      }),
    });
    const text = await r.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      setStatus(status, text || r.statusText, "err");
      btn.disabled = false;
      return;
    }
    if (!r.ok) {
      const d = data.detail;
      const msg = Array.isArray(d)
        ? d.map((e) => (typeof e.msg === "string" ? e.msg : JSON.stringify(e))).join(" ")
        : d || data.raw || r.statusText;
      setStatus(status, String(msg), "err");
      btn.disabled = false;
      return;
    }
    if (data.accepted === false) {
      const msg = (data.errors && data.errors.length ? data.errors.join(" ") : "") || "Invalid input.";
      setStatus(status, msg, "err");
      btn.disabled = false;
      return;
    }
    if (!data.job_id) {
      setStatus(status, "Unexpected server response.", "err");
      btn.disabled = false;
      return;
    }
    const result = await pollPipelineJob(status, data.job_id);
    if (!result.ok) {
      const msg = (result.errors && result.errors.length ? result.errors.join(" ") : "") || "Pipeline failed.";
      setStatus(status, msg, "err");
      btn.disabled = false;
      return;
    }
    setStatus(status, "Opening review…", "ok");
    window.location.href = "/review/";
  } catch (err) {
    setStatus(status, String(err.message || err), "err");
    btn.disabled = false;
  }
});
