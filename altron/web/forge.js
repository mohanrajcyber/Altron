(function () {
  const $ = (id) => document.getElementById(id);
  const form = $("forgeForm");
  const prompt = $("forgePrompt");
  let latestBuild = null;
  let runActive = false;

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  }

  async function checkReadiness() {
    try {
      const [health, tree] = await Promise.all([fetch("/health"), fetch("/api/ide/tree?path=.&depth=0")]);
      const workspace = await tree.json();
      const online = health.ok && workspace.ok;
      $("coreDot").classList.toggle("online", online);
      $("coreState").textContent = online ? "CORE ONLINE" : "CORE OFFLINE";
      $("agentState").textContent = "AGENT IDLE";
      $("workspaceState").textContent = workspace.ok ? "Trusted workspace ready" : "Workspace unavailable";
    } catch {
      $("coreState").textContent = "CORE OFFLINE";
      $("workspaceState").textContent = "Workspace unavailable";
    }
  }

  function setEvents(events) {
    $("eventList").innerHTML = events.map((event) => `<li class="${escapeHtml(event.state)}"><span class="event-marker"></span><div><b>${escapeHtml(event.title)}</b><small>${escapeHtml(event.detail || "")}</small></div></li>`).join("");
  }

  function renderValidations(validations) {
    const items = validations.length ? validations : [
      { name: "Project files", status: "WAITING", detail: "" },
      { name: "Python syntax", status: "WAITING", detail: "" },
      { name: "Generated tests", status: "NOT RUN", detail: "" },
      { name: "Security review", status: "NOT RUN", detail: "" },
    ];
    $("validationList").innerHTML = items.map((item) => {
      const state = item.status === "PASSED" ? "passed" : item.status === "FAILED" ? "failed" : item.status === "RUNNING" ? "running" : "";
      const icon = item.status === "PASSED" ? "✓" : item.status === "FAILED" ? "×" : item.status === "RUNNING" ? "◌" : "○";
      return `<li class="${state}"><span class="validation-icon">${icon}</span><span>${escapeHtml(item.name)}</span><b>${escapeHtml(item.status)}</b>${item.detail ? `<small class="validation-detail">${escapeHtml(item.detail)}</small>` : ""}</li>`;
    }).join("");
    $("validationState").textContent = validations.some((item) => item.status === "FAILED") ? "ISSUES FOUND" : validations.some((item) => item.status === "PASSED") ? "CHECKED" : "NOT RUN";
  }

  function renderFiles(files) {
    $("fileCount").textContent = String(files.length);
    $("filesEmpty").hidden = files.length > 0;
    $("fileList").innerHTML = files.map((path) => `<li><button type="button" data-open-path="${escapeHtml(path)}"><span class="forge-file-icon">▣</span><span>${escapeHtml(path)}</span></button></li>`).join("");
  }

  function showIntent(command, projectDir) {
    const words = projectDir.split("/").pop().split("-").map((word) => word.charAt(0).toUpperCase() + word.slice(1));
    $("intentLanguage").textContent = /\bpython\b/i.test(command) ? "Python" : /\b(typescript|ts)\b/i.test(command) ? "TypeScript" : /\b(javascript|js)\b/i.test(command) ? "JavaScript" : "Not specified";
    $("intentProject").textContent = words.join(" ");
    $("intentUi").textContent = /\b(clean|ui|interface|dashboard|visual)\b/i.test(command) ? "Requested" : "Not specified";
    $("intentSummary").hidden = false;
  }

  function recordJobEvent(events, event) {
    if (event.event === "request_accepted") {
      events.push({ state: "passed", title: "Build intent detected", detail: `BUILD_PROJECT · ${event.project_dir}` });
    } else if (event.event === "workspace_created") {
      events.push({ state: "passed", title: "Workspace prepared", detail: `Created ${event.project_dir}` });
    } else if (event.event === "generation_started") {
      events.push({ state: "running", title: "Generating project", detail: "Existing ALTRON IDE agent is creating files." });
    } else if (event.event === "file_written") {
      const active = events.find((item) => item.title === "Generating project");
      if (active) active.detail = `Confirmed write: ${event.path}`;
      else events.push({ state: "passed", title: "File written", detail: event.path });
    } else if (event.event === "validation_started") {
      const active = events.find((item) => item.title === "Generating project");
      if (active) active.state = "passed";
      events.push({ state: "running", title: "Validating project", detail: `Checking ${event.files} confirmed file(s).` });
    } else if (event.event === "validation_finished") {
      const active = events.find((item) => item.title === "Validating project");
      if (active) {
        active.state = event.status === "PASSED" ? "passed" : "failed";
        active.detail = `${event.status} · ${event.files} files · ${event.errors} errors`;
      }
    }
    setEvents(events);
  }

  async function waitForBuild(jobId, events, expectedCommand) {
    let eventIndex = 0;
    while (true) {
      const response = await fetch(`/api/forge/jobs/${encodeURIComponent(jobId)}`);
      const data = await response.json();
      if (!response.ok || !data.ok || !data.job) throw new Error(data.error || "Forge job was not found.");
      const job = data.job;
      if (job.command !== expectedCommand) {
        throw new Error("Forge received a command that does not match the Chat handoff.");
      }
      for (const event of job.events.slice(eventIndex)) recordJobEvent(events, event);
      eventIndex = job.events.length;
      if (job.status !== "RUNNING") {
        if (job.result) return job.result;
        throw new Error(job.error || "Forge job failed without a result.");
      }
      await new Promise((resolve) => window.setTimeout(resolve, 450));
    }
  }

  function openIde() {
    if (!latestBuild?.files?.length) return;
    const firstPython = latestBuild.files.find((path) => path.toLowerCase().endsWith(".py"));
    const openPath = firstPython || latestBuild.files[0];
    const target = `/ide?open=${encodeURIComponent(openPath)}&project=${encodeURIComponent(latestBuild.project_dir)}`;
    if (ideWindow && !ideWindow.closed) ideWindow.location.href = target;
    else window.open(target, "_blank", "noopener,noreferrer");
  }

  async function startBuild(command, planOnly = false, openIdeTab = false) {
    const value = String(command || "").trim();
    if (!value) {
      $("commandError").textContent = "Enter a build request first.";
      prompt.focus();
      return;
    }
    $("commandError").textContent = "";
    $("buildButton").disabled = true;
    $("planButton").disabled = true;
    $("resultPanel").hidden = true;
    $("explanationPanel").hidden = true;
    $("receivedCommand").textContent = value;
    $("runState").textContent = planOnly ? "PLANNING" : "AGENT ACTIVE";
    $("agentState").textContent = planOnly ? "PLANNER ACTIVE" : "AGENT ACTIVE";
    $("intentSummary").hidden = true;
    const events = [{ state: "passed", title: "Command received", detail: "Submitted to ALTRON's existing Forge pipeline." }];
    if (planOnly) events.push({ state: "running", title: "Preparing plan", detail: "IDE agent Plan mode; project writes are disabled." });
    setEvents(events);
    renderValidations([]);
    if (!planOnly) renderFiles([]);

    try {
      const response = await fetch(planOnly ? "/api/forge/build" : "/api/forge/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: value, plan_only: planOnly }),
      });
      let result = await response.json();
      if (!response.ok || result.ok === false) throw new Error(result.error || result.detail || result.message || `Request failed (${response.status})`);
      if (!planOnly) result = await waitForBuild(result.id, events, value);
      latestBuild = result;
      showIntent(value, result.project_dir);
      if (result.status === "PLANNED") {
        $("runState").textContent = "PLAN READY";
        $("agentState").textContent = "AGENT IDLE";
        setEvents([{ state: "passed", title: "Plan returned by IDE agent", detail: result.reply || "No plan text was returned." }]);
        $("resultStamp").textContent = "PLAN READY · NO FILES WRITTEN";
        $("resultTitle").textContent = result.project_dir;
        $("resultDetail").textContent = result.reply || "The existing IDE agent returned no plan details.";
        $("resultExplain").hidden = true;
        $("resultActions").hidden = true;
        $("resultPanel").hidden = false;
        return;
      }

      if (result.files.length) events.push({ state: "passed", title: "Workspace files verified", detail: `${result.files.length} file(s) exist on disk.` });
      for (const item of result.validations) {
        if (!events.some((event) => event.title === item.name)) {
          events.push({ state: item.status === "PASSED" ? "passed" : item.status === "FAILED" ? "failed" : "idle", title: item.name, detail: `${item.status}${item.detail ? ` · ${item.detail}` : ""}` });
        }
      }
      setEvents(events);
      renderFiles(result.files);
      renderValidations(result.validations);
      $("runState").textContent = result.status === "COMPLETED" ? "BUILD COMPLETE" : "BUILD FAILED";
      $("agentState").textContent = "AGENT IDLE";
      $("resultStamp").textContent = result.status === "COMPLETED" ? "FORGE COMPLETE" : "BUILD NOT VERIFIED";
      $("resultTitle").textContent = result.project_dir.split("/").pop().split("-").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
      const passed = result.validations.filter((item) => item.status === "PASSED").length;
      const errors = result.errors?.length || 0;
      $("resultDetail").textContent = result.status === "COMPLETED"
        ? `Files ${result.files.length} · Validation ${passed}/${result.validations.length} passed · Errors ${errors}. Tests and security review were not run.`
        : (result.errors || []).join(" · ") || result.reply || "No project files were verified.";
      $("resultExplain").hidden = result.files.length === 0;
      $("resultActions").hidden = result.files.length === 0;
      $("runProjectButton").hidden = result.status !== "COMPLETED" || !result.files.some((path) => /\.(py|mjs|cjs|js)$/i.test(path));
      $("resultPanel").hidden = false;
      if (result.files.length) localStorage.setItem("altron.forge.latest", JSON.stringify({ project_dir: result.project_dir, files: result.files }));
      if (result.status === "COMPLETED" && new URLSearchParams(location.search).has("fromChat")) {
        const firstPython = result.files.find((path) => path.toLowerCase().endsWith(".py"));
        const openPath = firstPython || result.files[0];
        $("resultDetail").textContent = `Workspace ready · ${result.files.length} confirmed file(s) · Opening ALTRON IDE…`;
        setTimeout(() => {
          location.assign(`/ide?open=${encodeURIComponent(openPath)}&project=${encodeURIComponent(result.project_dir)}`);
        }, 1400);
      }
    } catch (error) {
      $("runState").textContent = "BUILD FAILED";
      $("agentState").textContent = "AGENT IDLE";
      $("commandError").textContent = error.message || "Forge request failed.";
      setEvents([{ state: "failed", title: "Build request failed", detail: error.message || "No result returned." }]);
      $("resultStamp").textContent = "BUILD FAILED";
      $("resultTitle").textContent = "No verified project created";
      $("resultDetail").textContent = error.message || "No result returned.";
      $("resultExplain").hidden = true;
      $("resultActions").hidden = true;
      $("resultPanel").hidden = false;
    } finally {
      $("buildButton").disabled = false;
      $("planButton").disabled = false;
    }
  }

  async function runProject() {
    if (!latestBuild?.files?.length) return;
    const runnable = latestBuild.files.find((path) => /\.(py|mjs|cjs|js)$/i.test(path));
    if (!runnable) {
      $("commandError").textContent = "No Python or JavaScript entry file was confirmed for this project.";
      return;
    }
    if (runActive) {
      await fetch("/api/ide/project/stop", { method: "POST" });
      runActive = false;
      $("runProjectButton").textContent = "RUN";
      return;
    }
    const button = $("runProjectButton");
    button.textContent = "STARTING…";
    button.disabled = true;
    try {
      const response = await fetch("/api/forge/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_dir: latestBuild.project_dir, path: runnable }),
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.message || `Run failed (${response.status})`);
      runActive = true;
      button.disabled = false;
      document.querySelectorAll("#runProjectButton").forEach((item) => { item.textContent = "STOP PROJECT"; });
      $("resultDetail").textContent = `${result.message} · ${runnable}`;
      const poll = async () => {
        const statusResponse = await fetch("/api/ide/project/status");
        const status = await statusResponse.json();
        if (!status.running) {
          runActive = false;
          document.querySelectorAll("#runProjectButton").forEach((item) => { item.textContent = "RUN"; });
          $("resultDetail").textContent = `Process ended with exit code ${status.exit_code}. ${runnable}`;
          return;
        }
        $("resultDetail").textContent = `Running ${runnable} · output available in the ALTRON IDE terminal.`;
        window.setTimeout(poll, 800);
      };
      window.setTimeout(poll, 800);
    } catch (error) {
      button.textContent = "RUN";
      $("resultDetail").textContent = error.message || "Run failed.";
    } finally {
      button.disabled = false;
    }
  }

  async function explainProject(message = "Explain what you created.") {
    if (!latestBuild?.project_dir) return;
    $("explanationPanel").hidden = false;
    $("explanationText").textContent = "ALTRON is reading the confirmed project files…";
    try {
      const response = await fetch("/api/forge/explain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, project_dir: latestBuild.project_dir }),
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || `Request failed (${response.status})`);
      $("explanationText").textContent = result.reply || "ALTRON returned no explanation.";
    } catch (error) {
      $("explanationText").textContent = error.message || "Could not read this project.";
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    startBuild(prompt.value, false);
  });
  $("planButton").addEventListener("click", () => startBuild(prompt.value, true));
  $("openIdeButton").addEventListener("click", openIde);
  $("runProjectButton").addEventListener("click", runProject);
  $("resultExplain").addEventListener("click", () => explainProject());
  $("closeExplanation").addEventListener("click", () => { $("explanationPanel").hidden = true; });
  $("fileList").addEventListener("click", (event) => {
    const button = event.target.closest("[data-open-path]");
    if (button && latestBuild) window.open(`/ide?open=${encodeURIComponent(button.dataset.openPath)}&project=${encodeURIComponent(latestBuild.project_dir)}`, "_blank", "noopener,noreferrer");
  });

  const query = new URLSearchParams(location.search);
  const handoffId = query.get("handoff") || "";
  let handoff = null;
  if (handoffId) {
    try {
      const pending = JSON.parse(sessionStorage.getItem("altron.forge.handoff") || "null");
      if (pending?.id === handoffId && typeof pending.command === "string" && Date.now() - pending.createdAt < 120000) {
        handoff = pending;
      }
      if (pending?.id === handoffId) sessionStorage.removeItem("altron.forge.handoff");
    } catch {
      handoff = null;
    }
    history.replaceState(null, "", query.has("fromChat") ? "/forge?fromChat=1" : "/forge");
  }
  const legacyCommand = handoff ? "" : query.get("command") || "";
  const initialCommand = handoff?.command || legacyCommand;
  if (initialCommand) prompt.value = initialCommand;
  if (handoff) console.debug("[forge] accepted same-tab command handoff", { id: handoff.id, length: handoff.command.length });
  checkReadiness();
  if (handoff || legacyCommand) startBuild(initialCommand, false, false);
  else if (handoffId) $("commandError").textContent = "Chat handoff expired or unavailable. Return to Chat and resend the build request.";
})();