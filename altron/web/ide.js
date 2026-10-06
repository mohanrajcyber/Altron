/* ALTRON IDE — original shell. Monaco + real FS + shell + Git + Agent. Not VS Code/Copilot. */
(function () {
  const state = {
    open: false,
    tabs: [],
    active: "",
    dirty: {},
    editor: null,
    monaco: null,
    tree: [],
    flat: [],
    agentMode: "ASK",
    diffs: [],
    termId: "",
    termTimer: 0,
    paletteMode: "cmd", // cmd | file
    paletteItems: [],
    paletteIndex: 0,
    ctxPath: "",
    runPoll: 0,
    loading: false,
    xterm: null,
    fitAddon: null,
    diffEditor: null,
    diffIndex: -1,
    autosave: true,
    autosaveTimer: 0,
    split: false,
    splitEditor: null,
    prefs: {},
    dragPath: "",
    _intel: false,
  };

  const COMMANDS = [
    { id: "quickOpen", label: "Open File", run: () => openPalette("file") },
    { id: "newFile", label: "New File", run: () => createPath("file") },
    { id: "newFolder", label: "New Folder", run: () => createPath("dir") },
    { id: "save", label: "Save", run: () => saveActive() },
    { id: "saveAll", label: "Save All", run: () => saveAll() },
    { id: "search", label: "Search Workspace", run: () => searchWorkspace() },
    { id: "terminal", label: "Open Terminal", run: () => { showBottom("terminal"); ensureTerm(); } },
    { id: "run", label: "Run Project", run: () => runProject() },
    { id: "stop", label: "Stop Project", run: () => stopProject() },
    { id: "debug", label: "Debug Project", run: () => runProject(true) },
    { id: "split", label: "Split Editor", run: () => window.AltronIDE?._hooks?.toggleSplit?.() },
    { id: "preview", label: "Preview HTML", run: () => openPreview() },
    { id: "diags", label: "Refresh Diagnostics", run: () => window.AltronIDE?._hooks?.refreshDiagnostics?.() },
    { id: "undoAgent", label: "Undo Last File Change", run: async () => {
      const res = await fetch("/api/ide/history/revert", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await res.json();
      appendOut(data.message || "");
      window.AltronIDE?._hooks?.loadHistory?.();
    }},
    { id: "gitStatus", label: "Git Status", run: () => loadGit() },
    { id: "gitCommit", label: "Git Commit", run: () => gitCommit() },
    { id: "ask", label: "ALTRON Ask", run: () => setMode("ASK") },
    { id: "plan", label: "ALTRON Plan", run: () => setMode("PLAN") },
    { id: "explain", label: "ALTRON Explain", run: () => agentPreset("Explain this file.") },
    { id: "fix", label: "ALTRON Fix", run: () => agentPreset("Find and fix bugs in the open file.") },
    { id: "refactor", label: "ALTRON Refactor", run: () => agentPreset("Refactor the open file for clarity.") },
    { id: "test", label: "ALTRON Test", run: () => agentPreset("How should I test this? Then run tests if possible.") },
  ];

  const $ = (id) => document.getElementById(id);

  function els() {
    return {
      panel: $("idePanel"),
      btn: $("ideBtn"),
      close: $("ideClosePanel"),
      tree: $("ideTree"),
      tabs: $("ideTabs"),
      host: $("ideMonaco"),
      meta: $("ideMeta"),
      out: $("ideOut"),
      problems: $("ideProblems"),
      debug: $("ideDebug"),
      term: $("ideTerm"),
      agentLog: $("ideAgentLog"),
      agentIn: $("ideAgentIn"),
      agentSend: $("ideAgentSend"),
      pathLabel: $("ideActivePath"),
      diffs: $("ideDiffs"),
      overlay: $("ideOverlay"),
      paletteIn: $("idePaletteIn"),
      paletteList: $("idePaletteList"),
      ctx: $("ideCtx"),
      sbGit: $("ideSbGit"),
      sbLang: $("ideSbLang"),
      sbCursor: $("ideSbCursor"),
      sbState: $("ideSbState"),
      gitList: $("ideGitList"),
      gitBranch: $("ideGitBranch"),
      gitMsg: $("ideGitMsg"),
    };
  }

  function langFor(path) {
    const ext = (path.split(".").pop() || "").toLowerCase();
    return (
      {
        py: "python",
        js: "javascript",
        jsx: "javascript",
        ts: "typescript",
        tsx: "typescript",
        json: "json",
        md: "markdown",
        html: "html",
        htm: "html",
        css: "css",
        scss: "scss",
        sql: "sql",
        java: "java",
        c: "c",
        h: "c",
        cpp: "cpp",
        cc: "cpp",
        hpp: "cpp",
        go: "go",
        rs: "rust",
        toml: "ini",
        yml: "yaml",
        yaml: "yaml",
        txt: "plaintext",
        ps1: "powershell",
        sh: "shell",
        xml: "xml",
      }[ext] || "plaintext"
    );
  }

  function setOpen(on) {
    const e = els();
    const standalone = document.body.classList.contains("ide-standalone");
    state.open = standalone ? true : !!on;
    if (!standalone) {
      document.getElementById("app")?.classList.toggle("ide-on", state.open);
      e.btn?.classList.toggle("on", state.open);
      if (e.panel) e.panel.hidden = !state.open;
    } else if (e.panel) {
      e.panel.hidden = false;
    }
    if (state.open) {
      if (!standalone) location.hash = "ide";
      ensureEditor().then(async () => {
        await loadTree();
        await loadFlat();
        await loadGit();
        await refreshThinkBadge();
        await runDiagnose();
        const requestedFile = new URLSearchParams(location.search).get("open");
        if (requestedFile) {
          await openPath(requestedFile);
        } else if (!state.active) {
          try {
            await openPath("README.md");
          } catch {
            await openPath("altron/__init__.py");
          }
        }
        ensureTerm();
      });
    } else if (!standalone && location.hash === "#ide") {
      history.replaceState(null, "", location.pathname);
    }
  }

  function loadMonaco() {
    if (window.monaco) return Promise.resolve(window.monaco);
    return new Promise((resolve, reject) => {
      window.require = { paths: { vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs" } };
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs/editor/editor.main.css";
      document.head.appendChild(link);
      const script = document.createElement("script");
      script.src = "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs/loader.js";
      script.onload = () => window.require(["vs/editor/editor.main"], () => resolve(window.monaco));
      script.onerror = reject;
      document.body.appendChild(script);
    });
  }

  async function ensureEditor() {
    const e = els();
    if (state.editor) return state.editor;
    const monaco = await loadMonaco();
    state.monaco = monaco;
    monaco.editor.defineTheme("altron-dark", {
      base: "vs-dark",
      inherit: true,
      rules: [],
      colors: {
        "editor.background": "#0a0a0c",
        "editor.foreground": "#f4f1ea",
        "editorLineNumber.foreground": "#5c5852",
        "editorCursor.foreground": "#e11d2e",
        "editor.selectionBackground": "#e11d2e33",
        "editor.lineHighlightBackground": "#141416",
      },
    });
    const bootUri = monaco.Uri.parse("inmemory://altron/__boot__");
    const bootModel = monaco.editor.createModel("", "plaintext", bootUri);
    state.editor = monaco.editor.create(e.host, {
      model: bootModel,
      theme: "altron-dark",
      automaticLayout: true,
      minimap: { enabled: true },
      fontSize: 13,
      fontFamily: "IBM Plex Mono, ui-monospace, monospace",
      scrollBeyondLastLine: false,
      tabSize: 4,
      folding: true,
      matchBrackets: "always",
      multiCursorModifier: "alt",
      quickSuggestions: true,
      suggestOnTriggerCharacters: true,
      wordBasedSuggestions: "currentDocument",
      contextmenu: true,
      glyphMargin: true,
    });
    state.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => saveActive());
    state.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyP, () => openPalette("file"));
    state.editor.addCommand(
      monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyP,
      () => openPalette("cmd")
    );
    state.editor.onDidChangeModelContent(() => {
      if (state.loading || !state.active) return;
      state.dirty[state.active] = true;
      renderTabs();
      setSbState("Modified");
    });
    state.editor.onDidChangeCursorPosition((ev) => {
      els().sbCursor.textContent = `Ln ${ev.position.lineNumber}, Col ${ev.position.column}`;
    });
    state.editor.onMouseDown((ev) => {
      if (ev.target?.type === monaco.editor.MouseTargetType.GUTTER_GLYPH_MARGIN && state.active) {
        toggleBreakpoint(state.active, ev.target.position.lineNumber);
      }
    });
    return state.editor;
  }

  async function loadTree() {
    const e = els();
    try {
      const res = await fetch("/api/ide/tree?path=.&depth=1");
      const data = await res.json();
      state.tree = data.items || [];
      const roots = data.roots || [];
      if (roots.length > 1) {
        e.tree.innerHTML = roots
          .map((r) => {
            return `<div class="ide-root-label" title="${escapeAttr(r.path)}">${escapeHtml(r.label)}</div>${renderNodes(
              r.items || []
            )}`;
          })
          .join("");
      } else {
        e.tree.innerHTML = renderNodes(state.tree);
      }
      e.meta.textContent = data.workspace || "workspace";
      const pathEl = $("ideWsPath") || $("ideSbPath");
      if (pathEl) pathEl.textContent = data.workspace || "workspace";
      const sbPath = $("ideSbPath");
      if (sbPath) sbPath.textContent = data.workspace || "workspace";
      if (document.body.classList.contains("ide-standalone")) {
        e.meta.textContent = "Agent ready";
      }
      try {
        window.AltronIDE?._hooks?.wireDragDrop?.();
        const tree = e.tree;
        if (tree && window.AltronIDE?._hooks?.enhanceTreeHtml) {
          tree.innerHTML = window.AltronIDE._hooks.enhanceTreeHtml(tree.innerHTML);
        }
      } catch {
        /* ignore */
      }
    } catch (err) {
      e.tree.textContent = String(err);
    }
  }

  async function loadFlat() {
    try {
      const res = await fetch("/api/ide/flat");
      const data = await res.json();
      state.flat = data.files || [];
    } catch {
      state.flat = [];
    }
  }

  function renderNodes(items, depth = 0) {
    return (items || [])
      .map((n) => {
        const pad = depth * 12;
        if (n.type === "dir") {
          return `<button type="button" class="ide-node dir" data-path="${escapeAttr(
            n.path
          )}" data-depth="${depth}" style="padding-left:${pad}px"><span>▸ ${escapeHtml(
            n.name
          )}/</span></button><div class="ide-children" data-parent="${escapeAttr(n.path)}" hidden></div>`;
        }
        return `<button type="button" class="ide-node file" data-path="${escapeAttr(
          n.path
        )}" style="padding-left:${pad}px">${escapeHtml(n.name)}</button>`;
      })
      .join("");
  }

  async function toggleDir(path, depth, btn) {
    const kids = [...document.querySelectorAll(".ide-children")].find((el) => el.dataset.parent === path);
    if (!kids) return;
    const name = path.split("/").pop();
    if (!kids.hidden && kids.dataset.loaded === "1") {
      kids.hidden = true;
      btn.classList.remove("open");
      btn.querySelector("span").textContent = `▸ ${name}/`;
      return;
    }
    if (kids.dataset.loaded !== "1") {
      const res = await fetch(`/api/ide/tree?path=${encodeURIComponent(path)}&depth=1`);
      const data = await res.json();
      kids.innerHTML = renderNodes(data.items || [], (depth || 0) + 1);
      kids.dataset.loaded = "1";
    }
    kids.hidden = false;
    btn.classList.add("open");
    btn.querySelector("span").textContent = `▾ ${name}/`;
  }

  async function refreshThinkBadge() {
    try {
      const res = await fetch("/api/ide/think/status");
      const data = await res.json();
      const badge = $("ideFreeBadge");
      if (badge) {
        const short = String(data.backend || "free").replace("-free", "").toUpperCase();
        badge.textContent = `FREE · ${short}`;
        badge.title = data.label || "Free ALTRON Think";
      }
      if (els().meta && document.body.classList.contains("ide-standalone")) {
        els().meta.textContent = data.label || "Agent ready";
      }
    } catch {
      /* ignore */
    }
  }

  function bindResize() {
    const handle = $("ideResize");
    const bottom = $("ideBottom");
    if (!handle || !bottom) return;
    let dragging = false;
    handle.addEventListener("mousedown", (ev) => {
      dragging = true;
      ev.preventDefault();
    });
    window.addEventListener("mousemove", (ev) => {
      if (!dragging) return;
      const rect = bottom.parentElement.getBoundingClientRect();
      const h = Math.min(420, Math.max(100, rect.bottom - ev.clientY));
      bottom.style.height = `${h}px`;
      state.editor?.layout?.();
    });
    window.addEventListener("mouseup", () => {
      dragging = false;
    });
  }

  async function openPath(path, line) {
    await ensureEditor();
    const res = await fetch(`/api/ide/file?path=${encodeURIComponent(path)}`);
    const data = await res.json();
    if (!data.ok) {
      els().meta.textContent = data.error || "open failed";
      appendOut(`Open failed: ${path} — ${data.error || ""}`);
      return;
    }
    const monaco = state.monaco;
    const text = data.content ?? "";
    const uri = monaco.Uri.parse(`inmemory://altron/${path.replace(/\\/g, "/")}`);
    let tab = state.tabs.find((t) => t.path === path);
    state.loading = true;
    try {
      let model = monaco.editor.getModel(uri);
      if (!model) {
        model = monaco.editor.createModel(text, langFor(path), uri);
      } else if (!tab || !state.dirty[path]) {
        model.setValue(text);
        monaco.editor.setModelLanguage(model, langFor(path));
      }
      if (!tab) {
        tab = { path, model };
        state.tabs.push(tab);
      } else {
        tab.model = model;
      }
      state.active = path;
      state.dirty[path] = false;
      state.editor.setModel(model);
      state.editor.layout();
      if (state.editor.getValue() !== model.getValue()) {
        state.editor.setModel(model);
      }
      if (line && Number(line) > 0) {
        state.editor.revealLineInCenter(Number(line));
        state.editor.setPosition({ lineNumber: Number(line), column: 1 });
      }
    } finally {
      state.loading = false;
    }
    els().pathLabel.textContent = path;
    els().sbLang.textContent = langFor(path);
    const sbPath = $("ideSbPath");
    if (sbPath) sbPath.textContent = path;
    renderTabs();
    setSbState("Ready");
    renderBreakpointDecorations(path);
    try {
      window.AltronIDE?._hooks?.refreshDiagnostics?.(path);
      if (state.split && window.AltronIDE?._hooks?.state?.splitEditor && state.editor) {
        window.AltronIDE._hooks.state.splitEditor.setModel(state.editor.getModel());
      }
    } catch {
      /* ignore */
    }
  }

  function renderTabs() {
    const e = els();
    e.tabs.innerHTML = state.tabs
      .map((t) => {
        const dirty = state.dirty[t.path] ? "● " : "";
        const on = t.path === state.active ? " on" : "";
        return `<button type="button" class="ide-tab${on}" data-path="${escapeAttr(t.path)}">${dirty}${escapeHtml(
          t.path.split("/").pop()
        )} <span class="ide-tab-x" data-close="${escapeAttr(t.path)}">×</span></button>`;
      })
      .join("");
  }

  async function saveActive() {
    if (!state.active || !state.editor) return;
    const content = state.editor.getValue();
    const path = state.active;
    setSbState("Saving…");
    const res = await fetch("/api/ide/file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, content }),
    });
    const data = await res.json();
    els().meta.textContent = data.ok ? "Saved" : data.message || "save failed";
    if (data.ok) {
      state.dirty[path] = false;
      renderTabs();
      setSbState("Saved");
      try {
        window.AltronIDE?._hooks?.refreshDiagnostics?.(path);
      } catch {
        /* ignore */
      }
      // Preview auto-reload for HTML/CSS
      const frame = $("idePreview");
      const previewOn = frame && !frame.hidden;
      if (previewOn && /\.(html?|css)$/i.test(path)) {
        let target = state.previewPath || path;
        if (/\.css$/i.test(path)) {
          target = state.previewPath || path.replace(/[^/]+$/, "index.html");
        }
        openPreview(target);
      }
    }
    appendOut(data.message || "");
  }

  async function saveAll() {
    for (const t of state.tabs) {
      if (!state.dirty[t.path]) continue;
      state.active = t.path;
      state.editor.setModel(t.model);
      await saveActive();
    }
  }

  async function runActiveSnippet() {
    if (!state.editor) return;
    setSbState("Running…");
    const body = state.active?.endsWith(".py")
      ? { path: state.active, code: "" }
      : { code: state.editor.getValue(), path: "" };
    const res = await fetch("/api/ide/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    showBottom("output");
    appendOut(data.output || "");
    setSbState("Run done");
  }

  async function runProject(debug = false) {
    if (debug && state.active && state.active.endsWith(".py")) {
      return startRealDebug();
    }
    setSbState(debug ? "Debug…" : "Run…");
    showBottom(debug ? "debug" : "output");
    const res = await fetch("/api/ide/project/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.active || "", debug: !!debug }),
    });
    const data = await res.json();
    const text = (data.message || "") + "\n" + (data.log || "");
    appendOut(text);
    if (debug && els().debug) els().debug.textContent = text;
    pollRun(debug);
  }

  // Real breakpoint + step-through debugging via stdlib pdb (altron/adapters/ide_debug.py).
  state.breakpoints = {};
  state.debugSessionId = "";

  async function toggleBreakpoint(file, line) {
    const res = await fetch("/api/ide/debug/breakpoints/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file, line }),
    });
    const data = await res.json();
    if (data.ok) {
      state.breakpoints = data.breakpoints || {};
      renderBreakpointDecorations(file);
    }
  }

  async function renderBreakpointDecorations(file) {
    if (!Object.keys(state.breakpoints).length) {
      try {
        const res = await fetch("/api/ide/debug/breakpoints");
        const data = await res.json();
        if (data.ok) state.breakpoints = data.breakpoints || {};
      } catch {
        /* ignore */
      }
    }
    const monaco = state.monaco;
    const editor = state.editor;
    if (!monaco || !editor || !file) return;
    const key = file.replace(/\\/g, "/");
    const lines = state.breakpoints[key] || [];
    state.bpDecorations = editor.deltaDecorations(
      state.bpDecorations || [],
      lines.map((ln) => ({
        range: new monaco.Range(ln, 1, ln, 1),
        options: { isWholeLine: false, glyphMarginClassName: "ide-bp-dot" },
      }))
    );
  }

  async function startRealDebug() {
    setSbState("Debug…");
    showBottom("debug");
    const res = await fetch("/api/ide/debug/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.active }),
    });
    const data = await res.json();
    if (!data.ok) {
      appendOut(`Debug failed: ${data.message || ""}`);
      return;
    }
    state.debugSessionId = data.id;
    if (els().debug) els().debug.textContent = `Debugging ${state.active} (breakpoints: ${(data.breakpoints || []).join(", ") || "none"})\n`;
    pollDebugOutput();
  }

  async function debugCommand(action, expr = "") {
    if (!state.debugSessionId) return;
    await fetch("/api/ide/debug/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: state.debugSessionId, action, expr }),
    });
    setTimeout(pollDebugOutput, 200);
  }

  function pollDebugOutput() {
    clearInterval(state.debugPoll);
    state.debugPoll = setInterval(async () => {
      if (!state.debugSessionId) {
        clearInterval(state.debugPoll);
        return;
      }
      const res = await fetch(`/api/ide/debug/output?id=${encodeURIComponent(state.debugSessionId)}`);
      const data = await res.json();
      if (data.data && els().debug) els().debug.textContent += data.data;
      if (!data.alive) {
        clearInterval(state.debugPoll);
      }
    }, 400);
  }

  async function stopRealDebug() {
    if (!state.debugSessionId) return;
    await fetch("/api/ide/debug/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: state.debugSessionId }),
    });
    clearInterval(state.debugPoll);
    state.debugSessionId = "";
  }

  async function stopProject() {
    const res = await fetch("/api/ide/project/stop", { method: "POST" });
    const data = await res.json();
    appendOut(data.message || "stopped");
    setSbState("Stopped");
  }

  function pollRun(debug = false) {
    clearInterval(state.runPoll);
    state.runPoll = setInterval(async () => {
      try {
        const res = await fetch("/api/ide/project/status");
        const data = await res.json();
        if (data.log) {
          els().out.textContent = data.log;
          if (debug && els().debug) els().debug.textContent = data.log;
        }
        if (!data.running) {
          clearInterval(state.runPoll);
          setSbState(data.exit_code === 0 ? "Exit 0" : `Exit ${data.exit_code}`);
        } else setSbState(debug ? "Debugging…" : "Running…");
      } catch {
        clearInterval(state.runPoll);
      }
    }, 800);
  }

  function setMode(mode) {
    state.agentMode = mode;
    document.querySelectorAll("#ideAgentModes button").forEach((b) => {
      b.classList.toggle("on", b.dataset.mode === mode);
    });
    const hints = {
      ASK: "Chat · ask anything",
      PLAN: "Plan · numbered steps only (say «implement plan» to build)",
      EDIT: "Edit · writes files with path confirm",
      DEBUG: "Debug · diagnose → fix → re-check",
      RUN: "Run · execute project, no file writes",
    };
    const hint = $("ideModeHint");
    if (hint) hint.textContent = hints[mode] || mode;
    els().agentIn.placeholder = `${mode}: talk to ALTRON…`;
  }

  function agentPreset(msg) {
    els().agentIn.value = msg;
    askAgent();
  }

  async function askAgent() {
    const e = els();
    const msg = (e.agentIn?.value || "").trim();
    if (!msg) return;
    e.agentIn.value = "";
    appendAgent("you", msg);
    setSbState(`AGI ${state.agentMode}…`);
    let selection = "";
    try {
      selection = state.editor?.getModel()?.getValueInRange(state.editor.getSelection()) || "";
    } catch {
      /* ignore */
    }
    const buildish = /\b(develop|build|create|make|generate|index\.html|website|panni|pannu|small web)\b/i.test(
      msg
    );
    const mode = buildish && state.agentMode === "ASK" ? "EDIT" : state.agentMode;
    if (buildish) setMode(mode);

    const streamEl = appendAgent("altron", "");
    const pre = streamEl.querySelector("pre");
    let full = "";
    try {
      const res = await fetch("/api/ide/agent/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: msg,
          path: state.active || "",
          selection,
          mode,
        }),
      });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let doneMeta = null;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() || "";
        for (const block of parts) {
          const line = block.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          let ev;
          try {
            ev = JSON.parse(line.slice(6));
          } catch {
            continue;
          }
          if (ev.type === "token") {
            full += ev.text || "";
            if (pre) {
              pre.textContent = full;
              e.agentLog.scrollTop = e.agentLog.scrollHeight;
            }
          } else if (ev.type === "done") {
            doneMeta = ev;
            full = ev.reply || full;
            if (pre) pre.textContent = full;
          } else if (ev.type === "error") {
            full = ev.text || "error";
            if (pre) pre.textContent = full;
          }
        }
      }
      const data = doneMeta || { reply: full, created: [], diffs: [], backend: "" };
      if (data.backend) {
        const badge = $("ideFreeBadge");
        if (badge) badge.textContent = `FREE · ${String(data.backend).replace("-free", "").toUpperCase()}`;
        els().meta.textContent = `${data.backend} ready`;
      }
      if (data.diagnose?.problems?.length) {
        const prob = els().problems;
        if (prob) prob.textContent = data.diagnose.problems.join("\n");
        const pc = $("ideProbCount");
        if (pc) pc.textContent = String(data.diagnose.problems.length);
      }
      state.diffs = data.diffs || [];
      renderDiffs();
      if (data.plan_steps?.length) {
        appendAgent(
          "altron",
          "Plan steps:\n" + data.plan_steps.map((s, i) => `${i + 1}. ${s}`).join("\n")
        );
      }
      if (data.confirm_paths?.length || data.created?.length) {
        const paths = data.confirm_paths?.length ? data.confirm_paths : data.created;
        appendOut("Confirmed paths: " + paths.join(", "));
      }
      if (data.created?.length) {
        await loadTree();
        await loadFlat();
        for (const p of data.created) {
          try {
            // skip bare dirs for open (folders aren't files)
            if (!/\.[A-Za-z0-9]+$/.test(p)) continue;
            await openPath(p);
          } catch {
            /* ignore */
          }
        }
        appendOut("Created: " + data.created.join(", "));
        if (data.created.some((p) => /\.html?$/i.test(p))) {
          openPreview(data.created.find((p) => /\.html?$/i.test(p)));
        } else {
          showBottom("output");
        }
      }
      if (data.run_log) {
        showBottom("output");
        appendOut(data.run_log);
      }
      if (data.trace?.length) appendOut("AGI trace: " + data.trace.join(" → "));
      if (state.diffs.length) viewDiff(0);
      try {
        window.AltronIDE?._hooks?.loadHistory?.();
      } catch {
        /* ignore */
      }
    } catch (err) {
      if (pre) pre.textContent = String(err);
    }
    setSbState("Agent ready");
  }

  function appendAgent(who, text) {
    const e = els();
    if (!e.agentLog) return null;
    const div = document.createElement("div");
    div.className = `ide-agent-msg ${who}`;
    div.innerHTML = `<b>${who === "you" ? "YOU" : "ALTRON"}</b><pre>${escapeHtml(text)}</pre>`;
    e.agentLog.appendChild(div);
    e.agentLog.scrollTop = e.agentLog.scrollHeight;
    return div;
  }

  async function runDiagnose() {
    try {
      const res = await fetch("/api/ide/diagnose");
      const data = await res.json();
      const lines = (data.checks || []).map((c) => `${c.ok ? "OK" : "FAIL"}  ${c.name} — ${c.detail}`);
      const prob = els().problems;
      if (prob) prob.textContent = lines.join("\n") + `\n\n${data.summary || ""}`;
      const pc = $("ideProbCount");
      if (pc) {
        const n = (data.checks || []).filter((c) => !c.ok).length;
        pc.textContent = String(n);
      }
      const badge = $("ideFreeBadge");
      if (badge && data.backend) {
        badge.textContent = `FREE · ${String(data.backend).replace("-free", "").toUpperCase()}`;
      }
      setSbState(data.summary || "Diagnosed");
    } catch (err) {
      setSbState("Diagnose failed");
      appendOut(String(err));
    }
  }

  function renderDiffs() {
    const e = els();
    const bar = $("ideDiffsBar");
    const count = $("ideDiffsCount");
    if (!state.diffs.length) {
      e.diffs.innerHTML = "";
      if (bar) bar.hidden = true;
      return;
    }
    if (bar) bar.hidden = false;
    if (count) count.textContent = `${state.diffs.length} edit${state.diffs.length > 1 ? "s" : ""}`;
    e.diffs.innerHTML =
      state.diffs
        .map(
          (d, i) => `<div class="ide-diff-card" data-i="${i}">
          <div class="ide-diff-path">${escapeHtml(d.path)}</div>
          <pre class="ide-diff-pre">- ${escapeHtml((d.old || "").slice(0, 500))}
+ ${escapeHtml((d.new || "").slice(0, 500))}</pre>
          <div class="ide-diff-actions">
            <button type="button" data-view="${i}">View</button>
            <button type="button" data-apply="${i}">Apply</button>
            <button type="button" data-reject="${i}">Reject</button>
          </div>
        </div>`
        )
        .join("") +
      `<button type="button" class="send" id="ideApplyAll">Apply All</button>`;
  }

  async function viewDiff(i) {
    const d = state.diffs[i];
    if (!d || !state.monaco) return;
    state.diffIndex = i;
    const overlay = $("ideDiffOverlay");
    const host = $("ideDiffHost");
    if (!overlay || !host) return;
    $("ideDiffPath").textContent = d.path;
    overlay.hidden = false;
    let original = "";
    try {
      const res = await fetch(`/api/ide/file?path=${encodeURIComponent(d.path)}`);
      const data = await res.json();
      original = data.ok ? data.content || "" : "";
    } catch {
      original = d.old || "";
    }
    let modified = original;
    if (d.old && original.includes(d.old)) {
      modified = original.replace(d.old, d.new ?? "");
    } else {
      modified = (d.new ?? "") || original;
    }
    if (state.diffEditor) {
      state.diffEditor.dispose();
      state.diffEditor = null;
    }
    host.innerHTML = "";
    state.diffEditor = state.monaco.editor.createDiffEditor(host, {
      theme: "altron-dark",
      automaticLayout: true,
      readOnly: true,
      renderSideBySide: true,
      fontFamily: "IBM Plex Mono, ui-monospace, monospace",
      fontSize: 13,
    });
    const lang = langFor(d.path);
    state.diffEditor.setModel({
      original: state.monaco.editor.createModel(original, lang),
      modified: state.monaco.editor.createModel(modified, lang),
    });
  }

  function closeDiffView() {
    const overlay = $("ideDiffOverlay");
    if (overlay) overlay.hidden = true;
    if (state.diffEditor) {
      try {
        const m = state.diffEditor.getModel();
        m?.original?.dispose();
        m?.modified?.dispose();
      } catch {
        /* ignore */
      }
      state.diffEditor.dispose();
      state.diffEditor = null;
    }
    state.diffIndex = -1;
  }

  async function applyDiff(i) {
    const d = state.diffs[i];
    if (!d) return;
    const res = await fetch("/api/ide/agent/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: d.path, old: d.old, new: d.new }),
    });
    const data = await res.json();
    appendOut(data.message || "");
    if (data.ok) {
      state.diffs.splice(i, 1);
      renderDiffs();
      closeDiffView();
      if (state.active === d.path || state.tabs.some((t) => t.path === d.path)) {
        await openPath(d.path);
      }
      loadTree();
    } else {
      appendAgent("altron", "Apply failed: " + (data.message || ""));
    }
  }

  function appendOut(text) {
    const e = els();
    if (!e.out) return;
    e.out.textContent = (e.out.textContent ? e.out.textContent + "\n" : "") + text;
    e.out.scrollTop = e.out.scrollHeight;
  }

  function showBottom(name) {
    document.querySelectorAll(".ide-bottom-tabs button[data-bottom]").forEach((b) => {
      b.classList.toggle("on", b.dataset.bottom === name);
    });
    document.querySelectorAll(".ide-bottom-body > [data-pane]").forEach((p) => {
      p.hidden = p.dataset.pane !== name;
    });
    if (name === "terminal") {
      try {
        state.fitAddon?.fit?.();
      } catch {
        /* ignore */
      }
    }
  }

  async function openPreview(path) {
    let target = path || state.active || "";
    if (!target || !/\.html?$/i.test(target)) {
      target = state.previewPath || "sites/demo/index.html";
    }
    state.previewPath = target;
    const frame = $("idePreview");
    if (!frame) return;
    showBottom("preview");
    frame.src = `/api/ide/preview-page?path=${encodeURIComponent(target)}&t=${Date.now()}`;
    setSbState(`Preview · ${target}`);
  }

  async function ensureTerm() {
    const e = els();
    showBottom("terminal");
    if (!window.Terminal) {
      e.term.textContent = "xterm failed to load — refresh page.";
      return;
    }
    if (!state.xterm) {
      e.term.innerHTML = "";
      e.term.contentEditable = "false";
      const term = new window.Terminal({
        cursorBlink: true,
        fontSize: 13,
        fontFamily: "IBM Plex Mono, ui-monospace, monospace",
        theme: {
          background: "#07090c",
          foreground: "#c9d0da",
          cursor: "#e11d2e",
          selectionBackground: "#e11d2e55",
        },
        convertEol: true,
      });
      const FitCtor = window.FitAddon?.FitAddon || window.FitAddon;
      const fit = new FitCtor();
      term.loadAddon(fit);
      term.open(e.term);
      fit.fit();
      state.xterm = term;
      state.fitAddon = fit;
      term.onData((data) => {
        if (!state.termId) return;
        fetch("/api/ide/terminal/input", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: state.termId, data }),
        }).catch(() => {});
      });
      window.addEventListener("resize", () => {
        try {
          fit.fit();
        } catch {
          /* ignore */
        }
      });
    }
    if (state.termId) {
      try {
        state.fitAddon?.fit?.();
      } catch {
        /* ignore */
      }
      return;
    }
    const res = await fetch("/api/ide/terminal/create", { method: "POST" });
    const data = await res.json();
    state.termId = data.id;
    state.xterm.writeln(`ALTRON shell · ${data.cwd}`);
    clearInterval(state.termTimer);
    state.termTimer = setInterval(async () => {
      if (!state.termId || !state.xterm) return;
      try {
        const r = await fetch(`/api/ide/terminal/output?id=${encodeURIComponent(state.termId)}`);
        const o = await r.json();
        if (o.data) state.xterm.write(o.data);
      } catch {
        /* ignore */
      }
    }, 80);
  }

  async function termSend(line) {
    if (!state.termId) await ensureTerm();
    await fetch("/api/ide/terminal/input", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: state.termId, data: line.endsWith("\n") ? line : line + "\n" }),
    });
  }

  async function loadGit() {
    const e = els();
    try {
      const res = await fetch("/api/ide/git/status");
      const data = await res.json();
      if (data.error) {
        e.gitBranch.textContent = "";
        e.sbGit.textContent = "No git";
        e.gitList.innerHTML = `<div class="ide-git-empty">
          <p>${escapeHtml(data.error)}</p>
          <button type="button" class="aid-run block" id="ideGitInitCTA">Initialize Git repo</button>
          <p class="aid-hint">Creates .git in the ALTRON workspace.</p>
        </div>`;
        $("ideGitInitCTA")?.addEventListener("click", async () => {
          const r = await fetch("/api/ide/git/init", { method: "POST" });
          const d = await r.json();
          appendOut(d.message || "");
          await loadGit();
        });
        return;
      }
      e.gitBranch.textContent = data.branch || "";
      e.sbGit.textContent = data.branch || "Git";
      e.gitList.innerHTML = (data.entries || [])
        .map((ent) => {
          const mark = ent.staged ? "S" : "M";
          return `<button type="button" class="ide-git-item" data-path="${escapeAttr(ent.path)}" data-staged="${
            ent.staged ? "1" : "0"
          }">[${mark}] ${escapeHtml(ent.path)}</button>`;
        })
        .join("") || `<div class="ide-git-empty">clean working tree</div>`;
    } catch (err) {
      e.gitList.textContent = String(err);
    }
  }

  async function gitCommit() {
    const msg = els().gitMsg?.value || "";
    const res = await fetch("/api/ide/git/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg }),
    });
    const data = await res.json();
    appendOut(data.message || "");
    els().gitMsg.value = "";
    loadGit();
  }

  async function createPath(kind) {
    const name = prompt(kind === "dir" ? "Folder path (relative)" : "File path (relative)");
    if (!name) return;
    const res = await fetch("/api/ide/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: name, kind }),
    });
    const data = await res.json();
    appendOut(data.message || "");
    await loadTree();
    await loadFlat();
    if (kind === "file" && data.ok) openPath(name.replace(/\\/g, "/"));
  }

  async function renamePath(src) {
    const dst = prompt("Rename to", src);
    if (!dst || dst === src) return;
    const res = await fetch("/api/ide/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ src, dst }),
    });
    const data = await res.json();
    appendOut(data.message || "");
    loadTree();
    loadFlat();
  }

  async function deletePath(path) {
    if (!confirm(`Delete ${path}?`)) return;
    const res = await fetch("/api/ide/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    const data = await res.json();
    appendOut(data.message || "");
    loadTree();
    loadFlat();
  }

  async function searchWorkspace(q) {
    const query = (q || prompt("Search workspace") || "").trim();
    if (!query) return;
    const box = $("ideSearchOut");
    const res = await fetch(`/api/ide/search?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    const hits = data.hits || [];
    if (box) {
      box.innerHTML = hits.length
        ? hits
            .map(
              (h) =>
                `<button type="button" class="ide-search-hit" data-path="${escapeAttr(h.path)}" data-line="${
                  h.line || 1
                }"><b>${escapeHtml(h.path)}</b>${h.line ? `:${h.line}` : ""} <small>${escapeHtml(
                  h.via || ""
                )}</small><div class="snip">${escapeHtml(h.snippet || "")}</div></button>`
            )
            .join("")
        : `<div class="ide-git-empty">No hits for “${escapeHtml(query)}”</div>`;
    }
    showBottom("output");
    appendOut(`Search “${query}” → ${hits.length} hits`);
  }

  function openPalette(mode) {
    state.paletteMode = mode;
    const e = els();
    e.overlay.hidden = false;
    e.paletteIn.value = "";
    e.paletteIn.focus();
    renderPalette();
  }

  function closePalette() {
    els().overlay.hidden = true;
  }

  function renderPalette() {
    const e = els();
    const q = (e.paletteIn.value || "").trim().toLowerCase();
    let items;
    if (state.paletteMode === "file") {
      items = state.flat
        .filter((f) => !q || f.toLowerCase().includes(q))
        .slice(0, 40)
        .map((f) => ({ id: f, label: f, run: () => openPath(f) }));
    } else {
      items = COMMANDS.filter((c) => !q || c.label.toLowerCase().includes(q) || c.id.includes(q));
    }
    state.paletteItems = items;
    state.paletteIndex = 0;
    e.paletteList.innerHTML = items
      .map(
        (it, i) =>
          `<button type="button" class="ide-pal-item${i === 0 ? " on" : ""}" data-i="${i}">${escapeHtml(
            it.label
          )}</button>`
      )
      .join("");
  }

  function runPaletteItem(i) {
    const it = state.paletteItems[i];
    if (!it) return;
    closePalette();
    it.run();
  }

  function showCtx(x, y, path) {
    state.ctxPath = path;
    const e = els();
    e.ctx.hidden = false;
    e.ctx.style.left = `${x}px`;
    e.ctx.style.top = `${y}px`;
    e.ctx.innerHTML = `
      <button type="button" data-act="open">Open</button>
      <button type="button" data-act="rename">Rename</button>
      <button type="button" data-act="delete">Delete</button>
      <button type="button" data-act="newfile">New File</button>
      <button type="button" data-act="newfolder">New Folder</button>`;
  }

  function hideCtx() {
    const e = els();
    if (e.ctx) e.ctx.hidden = true;
  }

  function setSbState(s) {
    const e = els();
    if (e.sbState) e.sbState.textContent = s;
    if (e.meta) e.meta.textContent = s;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, "&#39;");
  }

  function bind() {
    const e = els();
    e.btn?.addEventListener("click", () => {
      if (document.body.classList.contains("ide-standalone")) {
        setOpen(true);
        return;
      }
      window.open("/ide", "_blank", "noopener,noreferrer");
    });
    e.close?.addEventListener("click", () => {
      if (document.body.classList.contains("ide-standalone")) return;
      setOpen(false);
    });
    $("ideRefreshTree")?.addEventListener("click", () => {
      loadTree();
      loadGit();
    });
    $("ideNewFile")?.addEventListener("click", () => createPath("file"));
    $("ideNewFolder")?.addEventListener("click", () => createPath("dir"));
    e.agentSend?.addEventListener("click", () => askAgent());
    e.agentIn?.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        askAgent();
      }
    });
    document.getElementById("ideAgentModes")?.addEventListener("click", (ev) => {
      const b = ev.target.closest("button[data-mode]");
      if (b) setMode(b.dataset.mode);
    });
    document.querySelector(".ide-menu-actions")?.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-ide-cmd]");
      if (!b) return;
      const cmd = COMMANDS.find((c) => c.id === b.dataset.ideCmd);
      if (cmd) cmd.run();
      else if (b.dataset.ideCmd === "run") runProject();
      else if (b.dataset.ideCmd === "stop") stopProject();
      else if (b.dataset.ideCmd === "debug") runProject(true);
      else if (b.dataset.ideCmd === "save") saveActive();
      else if (b.dataset.ideCmd === "terminal") {
        showBottom("terminal");
        ensureTerm();
      } else if (b.dataset.ideCmd === "palette") openPalette("cmd");
      else if (b.dataset.ideCmd === "quickOpen") openPalette("file");
    });
    document.querySelector(".aid-actions")?.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-ide-cmd]");
      if (!b) return;
      if (b.dataset.ideCmd === "run") runProject();
      if (b.dataset.ideCmd === "stop") stopProject();
      if (b.dataset.ideCmd === "debug") runProject(true);
    });
    $("idePreviewBtn")?.addEventListener("click", () => openPreview());
    $("ideDiffApply")?.addEventListener("click", async () => {
      if (state.diffIndex >= 0) await applyDiff(state.diffIndex);
    });
    $("ideDiffReject")?.addEventListener("click", () => {
      if (state.diffIndex >= 0) {
        state.diffs.splice(state.diffIndex, 1);
        renderDiffs();
        closeDiffView();
      }
    });
    $("ideDiffClose")?.addEventListener("click", () => closeDiffView());
    $("ideTopSearch")?.addEventListener("click", () => openPalette("file"));
    document.querySelector(".aid-activity")?.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-act-view]");
      if (b) {
        document.querySelectorAll(".aid-activity button[data-act-view]").forEach((x) => {
          x.classList.toggle("on", x === b);
        });
        document.querySelectorAll(".aid-side-panel").forEach((p) => {
          p.hidden = p.dataset.side !== b.dataset.actView;
        });
        if (b.dataset.actView === "git") loadGit();
        return;
      }
      const cmd = ev.target.closest("[data-ide-cmd]");
      if (cmd?.dataset.ideCmd === "palette") openPalette("cmd");
    });
    document.querySelectorAll("[data-ide-cmd]").forEach((el) => {
      if (el.closest(".aid-actions") || el.closest(".ide-menu-actions") || el.id === "ideTopSearch") return;
      el.addEventListener("click", () => {
        const id = el.dataset.ideCmd;
        if (id === "run") runProject();
        if (id === "stop") stopProject();
        if (id === "debug") runProject(true);
        if (id === "palette") openPalette("cmd");
        if (id === "quickOpen") openPalette("file");
      });
    });
    document.querySelector(".ide-debug-controls")?.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-dbg-cmd]");
      if (!b) return;
      const cmd = b.dataset.dbgCmd;
      if (cmd === "stop") stopRealDebug();
      else debugCommand(cmd);
    });
    $("ideDebugExpr")?.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      const expr = ev.target.value.trim();
      if (!expr) return;
      debugCommand("print", expr);
      ev.target.value = "";
    });
    $("ideSearchIn")?.addEventListener("keydown", async (ev) => {
      if (ev.key !== "Enter") return;
      searchWorkspace(ev.target.value.trim());
    });
    $("ideSearchOut")?.addEventListener("click", (ev) => {
      const b = ev.target.closest(".ide-search-hit");
      if (!b) return;
      openPath(b.dataset.path, Number(b.dataset.line || 1));
    });
    async function undoLastWrite() {
      try {
        const res = await fetch("/api/ide/history");
        const data = await res.json();
        const item = (data.items || [])[0];
        if (!item) {
          appendOut("No undo history");
          return;
        }
        const r = await fetch("/api/ide/history/revert", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: item.id }),
        });
        const d = await r.json();
        appendOut(d.message || "");
        if (d.ok && item.path) await openPath(item.path);
        window.AltronIDE?._hooks?.loadHistory?.();
      } catch (err) {
        appendOut(String(err));
      }
    }
    $("ideUndoLast")?.addEventListener("click", () => undoLastWrite());
    $("ideUndoBar")?.addEventListener("click", () => undoLastWrite());
    $("ideViewDiffs")?.addEventListener("click", () => {
      if (state.diffs.length) viewDiff(0);
    });
    $("ideApplyAllBar")?.addEventListener("click", async () => {
      while (state.diffs.length) await applyDiff(0);
    });
    $("ideRejectAll")?.addEventListener("click", () => {
      state.diffs = [];
      renderDiffs();
      closeDiffView();
    });
    document.querySelector(".ide-bottom-tabs")?.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-bottom]");
      if (b) showBottom(b.dataset.bottom);
      if (ev.target.id === "ideTermNew") {
        if (state.termId) {
          fetch("/api/ide/terminal/kill", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: state.termId }),
          }).catch(() => {});
        }
        state.termId = "";
        if (state.xterm) {
          state.xterm.clear();
          state.xterm.reset();
        }
        ensureTerm();
      }
    });
    e.tree?.addEventListener("click", (ev) => {
      const dir = ev.target.closest("button.ide-node.dir");
      if (dir) {
        toggleDir(dir.dataset.path, Number(dir.dataset.depth || 0), dir);
        return;
      }
      const btn = ev.target.closest("button.ide-node.file");
      if (btn) openPath(btn.dataset.path);
    });
    e.tree?.addEventListener("contextmenu", (ev) => {
      const node = ev.target.closest("[data-path]");
      if (!node) return;
      ev.preventDefault();
      showCtx(ev.clientX, ev.clientY, node.dataset.path);
    });
    e.ctx?.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-act]");
      if (!b) return;
      const act = b.dataset.act;
      hideCtx();
      if (act === "open") openPath(state.ctxPath);
      if (act === "rename") renamePath(state.ctxPath);
      if (act === "delete") deletePath(state.ctxPath);
      if (act === "newfile") createPath("file");
      if (act === "newfolder") createPath("dir");
    });
    e.tabs?.addEventListener("click", (ev) => {
      const close = ev.target.closest("[data-close]");
      if (close) {
        const path = close.dataset.close;
        state.tabs = state.tabs.filter((t) => t.path !== path);
        if (state.active === path) {
          const next = state.tabs[0];
          if (next) {
            state.active = next.path;
            state.editor.setModel(next.model);
            e.pathLabel.textContent = next.path;
          } else {
            state.active = "";
            e.pathLabel.textContent = "no file";
          }
        }
        renderTabs();
        return;
      }
      const btn = ev.target.closest("button.ide-tab");
      if (!btn) return;
      const tab = state.tabs.find((t) => t.path === btn.dataset.path);
      if (!tab) return;
      state.active = tab.path;
      state.editor.setModel(tab.model);
      e.pathLabel.textContent = tab.path;
      e.sbLang.textContent = langFor(tab.path);
      renderTabs();
    });
    e.diffs?.addEventListener("click", (ev) => {
      const view = ev.target.closest("[data-view]");
      const apply = ev.target.closest("[data-apply]");
      const reject = ev.target.closest("[data-reject]");
      if (view) viewDiff(Number(view.dataset.view));
      if (apply) applyDiff(Number(apply.dataset.apply));
      if (reject) {
        state.diffs.splice(Number(reject.dataset.reject), 1);
        renderDiffs();
        closeDiffView();
      }
      if (ev.target.id === "ideApplyAll") {
        (async () => {
          while (state.diffs.length) await applyDiff(0);
        })();
      }
    });
    e.paletteIn?.addEventListener("input", () => renderPalette());
    e.paletteIn?.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") {
        closePalette();
        return;
      }
      if (ev.key === "ArrowDown") {
        ev.preventDefault();
        state.paletteIndex = Math.min(state.paletteIndex + 1, state.paletteItems.length - 1);
        renderPaletteHighlight();
      }
      if (ev.key === "ArrowUp") {
        ev.preventDefault();
        state.paletteIndex = Math.max(state.paletteIndex - 1, 0);
        renderPaletteHighlight();
      }
      if (ev.key === "Enter") {
        ev.preventDefault();
        runPaletteItem(state.paletteIndex);
      }
    });
    e.paletteList?.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-i]");
      if (b) runPaletteItem(Number(b.dataset.i));
    });
    e.overlay?.addEventListener("click", (ev) => {
      if (ev.target === e.overlay) closePalette();
    });
    $("ideGitCommit")?.addEventListener("click", () => gitCommit());
    $("ideGitInit")?.addEventListener("click", async () => {
      const res = await fetch("/api/ide/git/init", { method: "POST" });
      const data = await res.json();
      appendOut(data.message || "");
      loadGit();
    });
    $("ideGitPull")?.addEventListener("click", async () => {
      const res = await fetch("/api/ide/git/pull", { method: "POST" });
      appendOut((await res.json()).message || "");
      loadGit();
    });
    $("ideGitPush")?.addEventListener("click", async () => {
      const res = await fetch("/api/ide/git/push", { method: "POST" });
      appendOut((await res.json()).message || "");
      loadGit();
    });
    e.gitList?.addEventListener("click", async (ev) => {
      const b = ev.target.closest(".ide-git-item");
      if (!b) return;
      const staged = b.dataset.staged === "1";
      const path = b.dataset.path;
      await fetch(staged ? "/api/ide/git/unstage" : "/api/ide/git/stage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ files: [path] }),
      });
      loadGit();
    });
    document.addEventListener("click", (ev) => {
      if (!ev.target.closest("#ideCtx")) hideCtx();
    });
    document.addEventListener("keydown", (ev) => {
      if (!state.open) return;
      if ((ev.ctrlKey || ev.metaKey) && ev.shiftKey && ev.key.toLowerCase() === "p") {
        ev.preventDefault();
        openPalette("cmd");
      } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "p") {
        ev.preventDefault();
        openPalette("file");
      } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") {
        ev.preventDefault();
        saveActive();
      } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "`") {
        ev.preventDefault();
        showBottom("terminal");
        ensureTerm();
      }
    });
  }

  function renderPaletteHighlight() {
    document.querySelectorAll(".ide-pal-item").forEach((el, i) => {
      el.classList.toggle("on", i === state.paletteIndex);
    });
  }

  window.AltronIDE = {
    open: () => setOpen(true),
    close: () => setOpen(false),
    isOpen: () => state.open,
    _hooks: {
      state,
      ensureEditor,
      saveActive,
      loadTree,
      loadFlat,
      loadGit,
      openPath,
      appendOut,
      setSbState,
    },
    init: () => {
      bind();
      bindResize();
      const standalone = document.body.classList.contains("ide-standalone");
      if (standalone || location.hash === "#ide") setOpen(true);
      const project = new URLSearchParams(location.search).get("project");
      if (project) {
        const banner = document.createElement("div");
        banner.className = "forge-return-banner";
        banner.textContent = `FORGE BUILD COMPLETE · ${project}`;
        document.querySelector(".aid-top")?.after(banner);
      }
    },
  };
})();
