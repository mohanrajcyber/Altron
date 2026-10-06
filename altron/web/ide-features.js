/* ALTRON IDE feature pack — loaded after ide.js core */
(function () {
  const api = window.AltronIDE;
  if (!api || !api._hooks) return;

  const H = api._hooks;
  const $ = (id) => document.getElementById(id);

  H.enhanceRenderNodes = function (html, items, depth) {
    /* already handled in core patch */
    return html;
  };

  async function loadPrefs() {
    try {
      const res = await fetch("/api/ide/prefs");
      const data = await res.json();
      H.state.prefs = data.prefs || {};
      H.state.autosave = H.state.prefs.autosave !== false;
      const box = $("ideAutosave");
      if (box) box.checked = !!H.state.autosave;
      const er = $("ideExtraRoot");
      if (er) er.value = (H.state.prefs.extra_roots || [])[0] || "";
      applyLayoutPrefs();
    } catch {
      /* ignore */
    }
  }

  function applyLayoutPrefs() {
    const p = H.state.prefs || {};
    const bottom = $("ideBottom");
    const body = $("ideBody");
    const sideW = p.side_width || 250;
    const agentW = p.agent_width || 320;
    if (bottom && p.bottom_height) bottom.style.height = `${p.bottom_height}px`;
    if (body) {
      body.style.gridTemplateColumns = `48px ${sideW}px 4px minmax(0, 1fr) 4px ${agentW}px`;
    }
  }

  function currentLayoutWidths() {
    const body = $("ideBody");
    const cols = (body?.style.gridTemplateColumns || "").split(/\s+/);
    // 48px SIDE 4px CENTER 4px AGENT
    let side = 250;
    let agent = 320;
    if (cols.length >= 6) {
      side = parseInt(cols[1], 10) || side;
      agent = parseInt(cols[5], 10) || agent;
    }
    return { side_width: side, agent_width: agent };
  }

  function wireColumnResize() {
    const body = $("ideBody");
    const sideHandle = $("ideSideResize");
    const agentHandle = $("ideAgentResize");
    if (!body || body.dataset.colResize === "1") return;
    body.dataset.colResize = "1";
    let mode = null;
    function onMove(ev) {
      if (!mode) return;
      const rect = body.getBoundingClientRect();
      const w = currentLayoutWidths();
      if (mode === "side") {
        const side = Math.min(420, Math.max(160, ev.clientX - rect.left - 48));
        body.style.gridTemplateColumns = `48px ${side}px 4px minmax(0, 1fr) 4px ${w.agent_width}px`;
      } else if (mode === "agent") {
        const agent = Math.min(480, Math.max(220, rect.right - ev.clientX));
        body.style.gridTemplateColumns = `48px ${w.side_width}px 4px minmax(0, 1fr) 4px ${agent}px`;
      }
      H.state.editor?.layout?.();
    }
    function onUp() {
      if (!mode) return;
      mode = null;
      const w = currentLayoutWidths();
      savePrefs(w);
    }
    sideHandle?.addEventListener("mousedown", (ev) => {
      mode = "side";
      ev.preventDefault();
    });
    agentHandle?.addEventListener("mousedown", (ev) => {
      mode = "agent";
      ev.preventDefault();
    });
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  function scheduleLiveDiagnostics() {
    clearTimeout(H.state.diagTimer);
    H.state.diagTimer = setTimeout(() => {
      if (H.state.active) refreshDiagnostics(H.state.active);
    }, 700);
  }

  function registerLightLsp() {
    const monaco = H.state.monaco;
    if (!monaco || H.state._lsp) return;
    H.state._lsp = true;
    monaco.languages.registerHoverProvider("python", {
      provideHover: async (model, position) => {
        const path = H.state.active || "";
        if (!path.endsWith(".py")) return null;
        try {
          const res = await fetch(
            `/api/ide/hover?path=${encodeURIComponent(path)}&line=${position.lineNumber}&column=${position.column}`
          );
          const data = await res.json();
          if (!data.contents) return null;
          return { contents: [{ value: data.contents }] };
        } catch {
          return null;
        }
      },
    });
    monaco.languages.registerDefinitionProvider("python", {
      provideDefinition: async (model, position) => {
        const path = H.state.active || "";
        const word = model.getWordAtPosition(position);
        if (!word || !path) return null;
        try {
          const res = await fetch(
            `/api/ide/symbol?q=${encodeURIComponent(word.word)}&path=${encodeURIComponent(path)}`
          );
          const data = await res.json();
          const hit = (data.hits || [])[0];
          if (!hit) return null;
          // Same-file jump preferred
          if (hit.path === path || hit.path.replace(/\\/g, "/") === path.replace(/\\/g, "/")) {
            return {
              uri: model.uri,
              range: new monaco.Range(hit.line, 1, hit.line, 1),
            };
          }
          await H.openPath?.(hit.path, hit.line);
          return null;
        } catch {
          return null;
        }
      },
    });
  }

  async function savePrefs(patch) {
    const res = await fetch("/api/ide/prefs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch || {}),
    });
    const data = await res.json();
    H.state.prefs = data.prefs || H.state.prefs;
    return data;
  }

  function scheduleAutosave() {
    if (!H.state.autosave || !H.state.active) return;
    clearTimeout(H.state.autosaveTimer);
    H.state.autosaveTimer = setTimeout(() => {
      if (H.state.dirty[H.state.active]) H.saveActive?.();
    }, 1200);
  }

  async function loadHistory() {
    const box = $("ideHistory");
    if (!box) return;
    try {
      const res = await fetch("/api/ide/history");
      const data = await res.json();
      box.innerHTML = (data.items || [])
        .slice(0, 12)
        .map(
          (it) =>
            `<button type="button" class="ide-hist-item" data-id="${it.id}" data-path="${it.path}">↩ ${it.path} <small>${it.source || ""}</small></button>`
        )
        .join("") || `<div class="ide-git-empty">no history</div>`;
    } catch (err) {
      box.textContent = String(err);
    }
  }

  async function loadBranches() {
    const box = $("ideGitBranches");
    if (!box) return;
    try {
      const res = await fetch("/api/ide/git/branches");
      const data = await res.json();
      if (!data.ok) {
        box.innerHTML = "";
        return;
      }
      box.innerHTML = (data.branches || [])
        .map((b) => {
          const on = b === data.current ? " on" : "";
          return `<button type="button" class="ide-branch${on}" data-branch="${b}">${b === data.current ? "● " : ""}${b}</button>`;
        })
        .join("");
    } catch {
      box.innerHTML = "";
    }
  }

  async function refreshDiagnostics(path) {
    const target = path || H.state.active || "";
    if (!target) return;
    try {
      const res = await fetch(`/api/ide/diagnostics?path=${encodeURIComponent(target)}`);
      const data = await res.json();
      const items = data.items || [];
      const prob = $("ideProblems");
      if (prob) {
        prob.textContent = items.length
          ? items.map((x) => `${x.severity.toUpperCase()} L${x.line}: ${x.message}`).join("\n")
          : "No problems.";
      }
      const pc = $("ideProbCount");
      if (pc) pc.textContent = String(items.filter((x) => x.severity === "error").length);
      if (H.state.monaco && H.state.editor) {
        const model = H.state.editor.getModel();
        if (model) {
          const markers = items.map((x) => ({
            severity:
              x.severity === "error"
                ? H.state.monaco.MarkerSeverity.Error
                : x.severity === "warning"
                  ? H.state.monaco.MarkerSeverity.Warning
                  : H.state.monaco.MarkerSeverity.Info,
            startLineNumber: x.line || 1,
            startColumn: 1,
            endLineNumber: x.line || 1,
            endColumn: 200,
            message: x.message,
          }));
          H.state.monaco.editor.setModelMarkers(model, "altron", markers);
        }
      }
    } catch {
      /* ignore */
    }
  }

  function toggleSplit() {
    const wrap = $("ideMonacoWrap");
    const splitEl = $("ideMonacoSplit");
    const gutter = $("ideSplitGutter");
    if (!wrap || !splitEl) return;
    H.state.split = !H.state.split;
    wrap.classList.toggle("split-on", H.state.split);
    splitEl.hidden = !H.state.split;
    if (gutter) gutter.hidden = !H.state.split;
    if (H.state.split) {
      ensureSplitEditor().then(() => {
        if (H.state.active && H.state.editor) {
          H.state.splitEditor.setModel(H.state.editor.getModel());
        }
        H.state.editor?.layout?.();
        H.state.splitEditor?.layout?.();
      });
    } else if (H.state.splitEditor) {
      H.state.splitEditor.dispose();
      H.state.splitEditor = null;
      H.state.editor?.layout?.();
    }
  }

  async function ensureSplitEditor() {
    if (H.state.splitEditor) return H.state.splitEditor;
    await H.ensureEditor?.();
    const monaco = H.state.monaco;
    const host = $("ideMonacoSplit");
    H.state.splitEditor = monaco.editor.create(host, {
      theme: "altron-dark",
      automaticLayout: true,
      fontSize: 13,
      fontFamily: "IBM Plex Mono, ui-monospace, monospace",
      minimap: { enabled: false },
    });
    return H.state.splitEditor;
  }

  function registerIntelliSense() {
    const monaco = H.state.monaco;
    if (!monaco || H.state._intel) return;
    H.state._intel = true;
    monaco.languages.registerCompletionItemProvider("python", {
      triggerCharacters: [".", "_"],
      provideCompletionItems: () => {
        const words = [
          "def", "class", "import", "from", "return", "async", "await", "self",
          "print", "Path", "dict", "list", "Optional", "True", "False", "None",
          "altron", "settings", "get_settings", "ide_agent",
        ];
        const suggestions = words.map((w) => ({
          label: w,
          kind: monaco.languages.CompletionItemKind.Keyword,
          insertText: w,
        }));
        for (const f of H.state.flat || []) {
          suggestions.push({
            label: f,
            kind: monaco.languages.CompletionItemKind.File,
            insertText: f,
          });
        }
        return { suggestions: suggestions.slice(0, 60) };
      },
    });
  }

  function wireDragDrop() {
    const tree = $("ideTree");
    if (!tree || tree.dataset.dnd === "1") return;
    tree.dataset.dnd = "1";
    tree.addEventListener("dragstart", (ev) => {
      const node = ev.target.closest("[data-path]");
      if (!node) return;
      H.state.dragPath = node.dataset.path;
      ev.dataTransfer.setData("text/plain", node.dataset.path);
    });
    tree.addEventListener("dragover", (ev) => {
      ev.preventDefault();
    });
    tree.addEventListener("drop", async (ev) => {
      ev.preventDefault();
      const src = H.state.dragPath || ev.dataTransfer.getData("text/plain");
      const destNode = ev.target.closest("[data-path]");
      if (!src || !destNode) return;
      let dstDir = destNode.dataset.path;
      // if dropping on file, use its parent
      if (destNode.classList.contains("file")) {
        const parts = dstDir.split("/");
        parts.pop();
        dstDir = parts.join("/") || ".";
      }
      const res = await fetch("/api/ide/move", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ src, dst_dir: dstDir }),
      });
      const data = await res.json();
      H.appendOut?.(data.message || "");
      H.loadTree?.();
      H.loadFlat?.();
    });
  }

  function enhanceTreeHtml(html) {
    return html
      .replace(/class="ide-node file"/g, 'class="ide-node file" draggable="true"')
      .replace(/class="ide-node dir"/g, 'class="ide-node dir" draggable="true"');
  }

  // Hook into core after open
  const prevInit = api.init;
  api.init = function () {
    prevInit?.();
    loadPrefs();
    setTimeout(() => {
      wireDragDrop();
      wireColumnResize();
      loadHistory();
      loadBranches();
      registerIntelliSense();
      registerLightLsp();
      if (H.state.editor) {
        H.state.editor.onDidChangeModelContent(() => {
          scheduleAutosave();
          scheduleLiveDiagnostics();
        });
      }
      // status bar git refresh
      H.loadGit?.();
    }, 800);
  };

  $("ideAutosave")?.addEventListener("change", (ev) => {
    H.state.autosave = !!ev.target.checked;
    savePrefs({ autosave: H.state.autosave });
  });
  $("ideSavePrefs")?.addEventListener("click", async () => {
    const root = ($("ideExtraRoot")?.value || "").trim();
    const bottom = $("ideBottom");
    const w = currentLayoutWidths();
    await savePrefs({
      autosave: !!$("ideAutosave")?.checked,
      extra_roots: root ? [root] : [],
      bottom_height: bottom ? parseInt(bottom.style.height || "200", 10) : 200,
      side_width: w.side_width,
      agent_width: w.agent_width,
    });
    H.setSbState?.("Prefs saved");
    loadHistory();
    H.loadTree?.();
  });
  $("ideSplitBtn")?.addEventListener("click", () => toggleSplit());
  $("ideHistory")?.addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-id]");
    if (!b) return;
    const res = await fetch("/api/ide/history/revert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: b.dataset.id }),
    });
    const data = await res.json();
    H.appendOut?.(data.message || "");
    if (data.ok && b.dataset.path) H.openPath?.(b.dataset.path);
    loadHistory();
  });
  $("ideGitBranches")?.addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-branch]");
    if (!b) return;
    const res = await fetch("/api/ide/git/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ branch: b.dataset.branch }),
    });
    const data = await res.json();
    H.appendOut?.(data.message || "");
    H.loadGit?.();
    loadBranches();
  });

  document.addEventListener("keydown", (ev) => {
    if (!H.state.open && !document.body.classList.contains("ide-standalone")) return;
    if ((ev.ctrlKey || ev.metaKey) && ev.key === "\\") {
      ev.preventDefault();
      toggleSplit();
    }
  });

  // Expose helpers for core
  H.loadPrefs = loadPrefs;
  H.loadHistory = loadHistory;
  H.loadBranches = loadBranches;
  H.refreshDiagnostics = refreshDiagnostics;
  H.toggleSplit = toggleSplit;
  H.enhanceTreeHtml = enhanceTreeHtml;
  H.scheduleAutosave = scheduleAutosave;
  H.wireDragDrop = wireDragDrop;
  H.registerIntelliSense = registerIntelliSense;
  H.registerLightLsp = registerLightLsp;
  H.wireColumnResize = wireColumnResize;

  // Patch loadGit to also load branches
  const lg = H.loadGit;
  if (lg) {
    H.loadGit = async function () {
      await lg();
      loadBranches();
    };
  }

  // Patch openPath to run diagnostics
  const op = H.openPath;
  if (op) {
    H.openPath = async function (path, line) {
      await op(path, line);
      refreshDiagnostics(path);
      if (H.state.split && H.state.splitEditor && H.state.editor) {
        H.state.splitEditor.setModel(H.state.editor.getModel());
      }
    };
  }

  // Patch loadTree to make nodes draggable
  const lt = H.loadTree;
  if (lt) {
    H.loadTree = async function () {
      await lt();
      const tree = $("ideTree");
      if (tree && H.enhanceTreeHtml) {
        tree.innerHTML = H.enhanceTreeHtml(tree.innerHTML);
      }
      wireDragDrop();
    };
  }

  // Persist layout on resize handle mouseup
  window.addEventListener("mouseup", () => {
    const bottom = $("ideBottom");
    if (!bottom || !H.state.prefs) return;
    const h = parseInt(bottom.style.height || "0", 10);
    if (h > 80) savePrefs({ bottom_height: h });
  });
})();
