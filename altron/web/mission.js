/* ALTRON Mission Control — observes existing runtime via GET /api/mission-control (polling). */
(function () {
  const $ = (id) => document.getElementById(id);
  const POLL_MS = 4000;

  async function fetchSnapshot() {
    try {
      const res = await fetch("/api/mission-control");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn("Mission Control fetch failed:", err);
      return null;
    }
  }

  function fmtPct(v) {
    return v === null || v === undefined ? "—" : `${Math.round(v)}%`;
  }

  function fmtTime(ts) {
    if (!ts) return "";
    let ms = typeof ts === "number" ? ts * (ts < 2e10 ? 1000 : 1) : Date.parse(ts);
    if (!ms || Number.isNaN(ms)) return "";
    const d = new Date(ms);
    return d.toLocaleTimeString();
  }

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function render(data) {
    if (!data) {
      $("mcSystemState").textContent = "OFFLINE";
      $("mcSystemState").className = "mc-stat-val bad";
      return;
    }

    $("mcDatetime").textContent = data.datetime || "—";
    $("mcSystemState").textContent = data.system_online ? "ONLINE" : "OFFLINE";
    $("mcSystemState").className = `mc-stat-val ${data.system_online ? "ok" : "bad"}`;

    const sys = data.system || {};
    $("mcModel").textContent = sys.think ? sys.model || "—" : "no key (fallback)";

    const health = data.health || {};
    $("mcCpu").textContent = health.cpu_percent === null || health.cpu_percent === undefined ? "n/a" : fmtPct(health.cpu_percent);
    $("mcRam").textContent = health.ram_percent === null || health.ram_percent === undefined ? "n/a" : fmtPct(health.ram_percent);

    const sec = data.security || {};
    const secEl = $("mcSecurity");
    secEl.textContent = sec.label || "—";
    secEl.className = `mc-stat-val ${sec.pending_approvals ? "warn" : "ok"}`;

    // Current mission
    const mission = data.mission || {};
    $("mcMissionTitle").textContent = mission.title || "All systems idle";
    $("mcMissionDetail").textContent = mission.detail || "";
    const track = $("mcProgressTrack");
    const fill = $("mcProgressFill");
    if (typeof mission.progress === "number") {
      track.hidden = false;
      fill.style.width = `${Math.max(0, Math.min(100, mission.progress))}%`;
    } else {
      track.hidden = true;
    }
    const metaBits = [];
    if (mission.status) metaBits.push(mission.status);
    if (mission.step_label) metaBits.push(mission.step_label);
    if (typeof mission.step_index === "number" && typeof mission.step_total === "number" && mission.step_total) {
      metaBits.push(`Step ${mission.step_index}/${mission.step_total}`);
    }
    if (typeof mission.elapsed_sec === "number") metaBits.push(`Elapsed ${mission.elapsed_sec}s`);
    $("mcMissionMeta").textContent = metaBits.join(" · ");

    // Active flows (workflows.items includes both active + recent per mission_control.py)
    const items = (data.workflows && data.workflows.items) || [];
    const active = items.filter((it) => it.status === "RUNNING");
    const flowsEl = $("mcFlows");
    if (!active.length) {
      flowsEl.innerHTML = '<div class="mc-empty">No active flow runs.</div>';
    } else {
      flowsEl.innerHTML = active
        .map((it) => {
          const pct = typeof it.progress === "number" ? it.progress : null;
          return `<div class="mc-row">
            <div class="mc-row-head">
              <span class="mc-row-title">${escapeHtml(it.name || "Flow")}</span>
              <span class="mc-row-state running">RUNNING</span>
            </div>
            <div class="mc-row-detail">run ${escapeHtml(it.id || "")}</div>
            ${pct !== null ? `<div class="mc-progress-track"><div class="mc-progress-fill" style="width:${pct}%"></div></div>` : ""}
          </div>`;
        })
        .join("");
    }

    // System health / organs
    const organs = sys.organs || {};
    const healthItems = [
      { name: "Ollama", ok: !!organs.ollama?.ok, why: organs.ollama?.why },
      { name: "Qdrant", ok: !!organs.qdrant?.ok, why: organs.qdrant?.why },
      { name: "n8n", ok: !!(sys.n8n && sys.n8n.ok), why: sys.n8n?.webhook ? "webhook configured" : "local queue only" },
      { name: "ComfyUI", ok: !!organs.comfy?.ok, why: organs.comfy?.why },
      { name: "E2B", ok: !!organs.e2b?.ok, why: organs.e2b?.why },
      { name: "IDE", ok: !!(sys.ide && sys.ide.running), why: "" },
      { name: "Voice", ok: sys.voice === "livekit+browser" || sys.voice === "browser", why: sys.voice || "" },
    ];
    $("mcHealth").innerHTML = healthItems
      .map(
        (h) => `<div class="mc-health-item" title="${escapeHtml(h.why || "")}">
          <span class="mc-health-item-title"><span class="mc-health-dot ${h.ok ? "ok" : "bad"}"></span>${escapeHtml(h.name)}</span>
        </div>`
      )
      .join("");

    // Safety / approvals
    const approvals = data.approvals || [];
    const safetyEl = $("mcSafety");
    if (!approvals.length) {
      safetyEl.innerHTML = '<div class="mc-empty">No pending approvals.</div>';
    } else {
      safetyEl.innerHTML = approvals
        .map(
          (a) => `<div class="mc-row">
            <div class="mc-row-head"><span class="mc-row-title">${escapeHtml(a.kind || "Approval")}</span><span class="mc-row-state running">${a.ttl_sec}s left</span></div>
            <div class="mc-row-detail">${escapeHtml(a.hint || "")}</div>
          </div>`
        )
        .join("");
    }

    // Insights
    const insights = data.insights || [];
    $("mcInsights").innerHTML = insights.length
      ? insights.map((i) => `<div class="mc-row"><div class="mc-row-detail">${escapeHtml(i.text || "")}</div></div>`).join("")
      : '<div class="mc-empty">—</div>';

    // Autonomous Goal (Phase 2) — reads data/goals/<run_id>.json via /api/mission-control
    const goal = data.autonomous_goal;
    const goalEl = $("mcGoal");
    if (!goal) {
      goalEl.innerHTML = '<div class="mc-empty">No goal executed yet.</div>';
    } else {
      const stateCls = goal.status === "COMPLETED" ? "ok" : goal.status === "FAILED" ? "failed" : "running";
      const stepsHtml = (goal.plan || [])
        .map((s) => `<div>${escapeHtml(s.step)} — <span class="mc-row-state ${s.status === "done" ? "ok" : s.status === "failed" ? "failed" : ""}">${escapeHtml(s.status)}</span></div>`)
        .join("");
      goalEl.innerHTML = `<div class="mc-row">
        <div class="mc-row-head"><span class="mc-row-title">${escapeHtml(goal.goal || "")}</span><span class="mc-row-state ${stateCls}">${escapeHtml(goal.status || "")}</span></div>
        <div class="mc-row-detail">Capability: ${escapeHtml(goal.capability || "sandbox_python")}</div>
        <div class="mc-row-detail">${escapeHtml(goal.result || goal.current_step || "")}</div>
        <div class="mc-row-detail">Attempt ${goal.attempt || 0}/${goal.max_attempts || 0}</div>
        <div class="mc-row-detail">${stepsHtml}</div>
      </div>`;
    }

    // Recent activity
    const activity = data.activity || [];
    $("mcActivity").innerHTML = activity.length
      ? activity
          .map(
            (e) => `<div class="mc-activity-row">
              <span class="mc-activity-icon ${escapeHtml(e.icon || "")}"></span>
              <div>
                <div class="mc-activity-text">${escapeHtml(e.text || "")}</div>
                <div class="mc-activity-time">${escapeHtml(fmtTime(e.ts))} · ${escapeHtml(e.source || "")}</div>
              </div>
            </div>`
          )
          .join("")
      : '<div class="mc-empty">No recent activity.</div>';

    $("mcBackgroundMsg").textContent = data.background_message || "Standing by…";
    $("mcUpdatedAt").textContent = `Updated ${new Date().toLocaleTimeString()}`;
  }

  async function tick() {
    const data = await fetchSnapshot();
    render(data);
  }

  tick();
  setInterval(tick, POLL_MS);
})();
