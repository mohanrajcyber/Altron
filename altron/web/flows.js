/* ALTRON Flows — canvas architecture fix (vanilla graph editor) */
(function () {
  const $ = (id) => document.getElementById(id);
  const NODE_W = 236;
  const NODE_H = 96;

  const state = {
    flows: [],
    catalog: [],
    categories: {},
    roots: [],
    flow: null,
    activeId: "",
    selected: "",
    selectedIds: [],
    selectedEdge: "",
    clipboard: null,
    dirty: false,
    zoom: 1,
    pan: { x: 0, y: 0 },
    panning: false,
    panStart: null,
    dragNode: null,
    connectFrom: null,
    nodeStates: {},
    nodeOrder: {},
    activeEdge: "",
    lastRunId: "",
    lastRunVars: {},
    lastRunNodes: {},
    lastNodeOutputs: {},
    lastNodeInputs: {},
    undo: [],
    redo: [],
    bottomTab: "log",
    issues: [],
    panelLog: "Build a flow · drag nodes · connect handles · Save · Run.",
    running: false,
    runEs: null,
  };

  async function api(path, opts) {
    const res = await fetch(path, opts);
    return res.json();
  }

  function pos(n) {
    const p = n.position || {};
    return { x: Number(p.x ?? n.x ?? 0), y: Number(p.y ?? n.y ?? 0) };
  }

  function setPos(n, x, y) {
    n.position = { x: Math.round(x), y: Math.round(y) };
    delete n.x;
    delete n.y;
  }

  function meta(type) {
    return (
      state.catalog.find((c) => c.type === type) || {
        label: type,
        desc: "",
        icon: "◉",
        fields: [],
        category: "",
      }
    );
  }

  function dedupeNodes(nodes) {
    const seen = new Set();
    const out = [];
    for (const n of nodes || []) {
      if (!n || !n.id || seen.has(n.id)) continue;
      seen.add(n.id);
      out.push(n);
    }
    return out;
  }

  function snapshotUndo() {
    if (!state.flow) return;
    state.undo.push(JSON.stringify(state.flow));
    if (state.undo.length > 40) state.undo.shift();
    state.redo = [];
  }

  function pushUndo() {
    snapshotUndo();
    markDirty();
  }

  function markDirty() {
    state.dirty = true;
    const pill = $("afSaveState");
    if (pill) {
      pill.textContent = "Unsaved";
      pill.className = "af-pill dirty";
    }
  }

  function markSaved() {
    state.dirty = false;
    const pill = $("afSaveState");
    if (pill) {
      pill.textContent = "Saved";
      pill.className = "af-pill saved";
    }
  }

  function setStatus(msg) {
    if ($("afStatus")) $("afStatus").textContent = msg;
  }

  async function boot() {
    const [cat, flows, roots, st] = await Promise.all([
      api("/api/flows/catalog"),
      api("/api/flows"),
      api("/api/flows/roots"),
      api("/api/flows/status"),
    ]);
    state.catalog = cat.nodes || [];
    state.categories = cat.categories || {};
    state.flows = flows.flows || [];
    state.roots = roots.roots || [];
    if ($("afMode")) $("afMode").textContent = st.mode === "local" ? "Local Mode" : st.mode || "Local";
    if ($("afTrusted")) $("afTrusted").textContent = `${st.trusted_roots || 0} Trusted Paths`;
    bind();
    renderCategories();
    renderRoots();
    renderFlowList();
    if (state.flows[0]) await loadFlow(state.flows[0].id);
    window.addEventListener("resize", () => {
      if (state.flow) fitView();
    });
  }

  function renderCategories() {
    const q = ($("afNodeSearch")?.value || "").trim().toLowerCase();
    const box = $("afCategories");
    if (!box) return;
    const cats = Object.keys(state.categories).length ? state.categories : groupCatalog();
    box.innerHTML = Object.entries(cats)
      .map(([cat, nodes]) => {
        const filtered = nodes.filter(
          (n) =>
            !q ||
            n.label.toLowerCase().includes(q) ||
            n.type.toLowerCase().includes(q) ||
            cat.toLowerCase().includes(q) ||
            (n.desc || "").toLowerCase().includes(q)
        );
        if (!filtered.length) return "";
        return `<details class="af-cat" open><summary>${escapeHtml(cat)} (${filtered.length})</summary>
          <div class="af-cat-nodes">${filtered
            .map((n) => {
              const ai = n.accent === "ai" || String(n.type).startsWith("ai.");
              const impl = n.implemented !== false;
              return `<button type="button" data-add="${escapeAttr(n.type)}" draggable="true" title="${escapeAttr(
                n.desc || n.type
              )}" class="${impl ? "" : "not-impl"}">
                <span class="lib-ico ${ai ? "ai" : ""}">${escapeHtml(n.icon || "◉")}</span>
                <span><b>${escapeHtml(n.label)}</b>${impl ? "" : ' <small style="color:#ff5c5c">NOT IMPL</small>'}<br><small>${escapeHtml(
                n.desc || n.type
              )}</small></span>
              </button>`;
            })
            .join("")}</div></details>`;
      })
      .join("");
  }

  function groupCatalog() {
    const out = {};
    for (const n of state.catalog) {
      const c = n.category || "OTHER";
      (out[c] ||= []).push(n);
    }
    return out;
  }

  function renderRoots() {
    if (!$("afRoots")) return;
    $("afRoots").innerHTML =
      state.roots
        .map(
          (r) =>
            `<button type="button" data-root="${escapeAttr(r.path)}" title="${escapeAttr(r.path)}">${escapeHtml(
              r.name
            )} <small>${r.ok ? "ok" : "missing"}</small></button>`
        )
        .join("") || `<div class="af-empty">No trusted paths</div>`;
  }

  function renderFlowList() {
    if (!$("afFlowList")) return;
    $("afFlowList").innerHTML = state.flows
      .map(
        (f) =>
          `<button type="button" class="${f.id === state.activeId ? "on" : ""}" data-flow="${escapeAttr(f.id)}"><b>${escapeHtml(
            f.name
          )}</b><br><small>${f.node_count || 0} nodes</small></button>`
      )
      .join("");
  }

  async function loadFlow(id) {
    const data = await api(`/api/flows/${encodeURIComponent(id)}`);
    if (!data.ok) {
      setStatus(data.message || "load failed");
      return;
    }
    state.activeId = id;
    state.flow = data.flow;
    state.flow.nodes = dedupeNodes(state.flow.nodes);
    state.selected = state.flow.nodes[0]?.id || "";
    state.selectedIds = state.selected ? [state.selected] : [];
    state.selectedEdge = "";
    state.nodeStates = {};
    state.undo = [];
    state.redo = [];
    if ($("afFlowName")) $("afFlowName").value = state.flow.name || "";
    if ($("afFlowMeta")) $("afFlowMeta").textContent = `${state.flow.name} · ${state.flow.nodes.length} nodes`;
    const badge = $("afAiBadge");
    if (badge) {
      const aiGen = !!(state.flow.settings && (state.flow.settings.ai_generated || Number(state.flow.settings.phase || 0) >= 2));
      badge.hidden = !aiGen;
    }
    renderFlowList();
    renderGraph();
    renderInspect();
    markSaved();
    setStatus(`Loaded ${state.flow.name}`);
    requestAnimationFrame(() => {
      fitView();
      requestAnimationFrame(() => fitView());
    });
  }

  function fitView() {
    const vp = $("afViewport");
    const flow = state.flow;
    if (!vp || !flow || !flow.nodes.length) {
      state.zoom = 1;
      state.pan = { x: 48, y: 48 };
      applyTransform();
      return;
    }
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const n of flow.nodes) {
      const p = pos(n);
      minX = Math.min(minX, p.x);
      minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x + NODE_W);
      maxY = Math.max(maxY, p.y + NODE_H);
    }
    const bw = Math.max(maxX - minX, 1);
    const bh = Math.max(maxY - minY, 1);
    const pad = 56;
    const vw = Math.max(vp.clientWidth, 200);
    const vh = Math.max(vp.clientHeight, 160);
    const zoom = Math.min(1.15, Math.max(0.45, Math.min((vw - pad * 2) / bw, (vh - pad * 2) / bh)));
    state.zoom = zoom;
    state.pan = {
      x: (vw - bw * zoom) / 2 - minX * zoom,
      y: (vh - bh * zoom) / 2 - minY * zoom,
    };
    applyTransform();
  }

  function renderGraph() {
    const host = $("afNodes");
    const flow = state.flow;
    if (!host || !flow) return;
    flow.nodes = dedupeNodes(flow.nodes);
    host.innerHTML = flow.nodes
      .map((n) => {
        const m = meta(n.type);
        const p = pos(n);
        const st = (state.nodeStates[n.id] || "").toLowerCase();
        const isAi = m.accent === "ai" || String(n.type).startsWith("ai.");
        const order = state.nodeOrder[n.id];
        const notImpl = m.implemented === false;
        const cls = [
          "af-node",
          String(n.type).startsWith("trigger.") ? "trigger" : "",
          isAi ? "ai" : "",
          n.id === state.selected || (state.selectedIds || []).includes(n.id) ? "on" : "",
          st,
          n.disabled ? "disabled" : "",
          notImpl ? "not-impl" : "",
        ]
          .filter(Boolean)
          .join(" ");
        const ports =
          n.type === "logic.if"
            ? `<div class="af-node-ports">
                <span class="af-handle in" data-handle="in" data-node="${escapeAttr(n.id)}" title="Input"></span>
                <span class="type-tag">${escapeHtml(n.type)}</span>
                <div class="af-out-branches">
                  <span class="af-branch yes">Yes <span class="af-handle out" data-handle="yes" data-node="${escapeAttr(n.id)}"></span></span>
                  <span class="af-branch no">No <span class="af-handle out" data-handle="no" data-node="${escapeAttr(n.id)}"></span></span>
                </div>
              </div>`
            : `<div class="af-node-ports">
                <span class="af-handle in" data-handle="in" data-node="${escapeAttr(n.id)}" title="Input"></span>
                <span class="type-tag">${escapeHtml(n.type)}</span>
                <span class="af-handle out" data-handle="default" data-node="${escapeAttr(n.id)}" title="Output"></span>
              </div>`;
        const badge = order ? `<span class="exec-order">${order}</span>` : "";
        return `<div class="${cls}" data-id="${escapeAttr(n.id)}" style="left:${p.x}px;top:${p.y}px">
          ${badge}
          <div class="af-node-head">
            <span class="ico ${isAi ? "ai" : ""}">${escapeHtml(m.icon || "◉")}</span>
            <span>${escapeHtml(n.label || m.label)}</span>
            <span class="status-dot" title="${escapeAttr(st || "idle")}"></span>
          </div>
          <div class="af-node-desc">${escapeHtml(
            notImpl ? "NOT IMPLEMENTED" : n.description || m.desc || "Configure in inspector"
          )}</div>
          ${ports}
        </div>`;
      })
      .join("");
    drawEdges();
    drawMinimap();
  }

  function nodeCenter(nid, side, handle) {
    const n = (state.flow?.nodes || []).find((x) => x.id === nid);
    if (!n) return { x: 0, y: 0 };
    const p = pos(n);
    const x = side === "out" ? p.x + NODE_W : p.x;
    let y = p.y + 70;
    if (side === "out" && n.type === "logic.if") {
      y = handle === "no" ? p.y + 88 : p.y + 62;
    }
    return { x, y };
  }

  function drawEdges() {
    const svg = $("afEdges");
    const flow = state.flow;
    if (!svg || !flow) return;
    const paths = (flow.edges || [])
      .map((e) => {
        const a = nodeCenter(e.source, "out", e.sourceHandle || "default");
        const b = nodeCenter(e.target, "in");
        const mx = (a.x + b.x) / 2;
        const label = e.label || (e.sourceHandle && !["default", "out"].includes(e.sourceHandle) ? e.sourceHandle : "");
        const on = e.id === state.selectedEdge ? " on" : "";
        const flowing = e.id === state.activeEdge ? " flowing" : "";
        const path = `<path data-edge="${escapeAttr(e.id)}" class="${(on + flowing).trim()}" d="M ${a.x} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${b.x} ${b.y}" stroke="#e11d2e" stroke-width="2.5" fill="none" opacity="0.9" marker-end="url(#afArrow)"/>`;
        const lx = mx;
        const ly = (a.y + b.y) / 2 - 8;
        const lbl = label
          ? `<text class="af-edge-label" x="${lx}" y="${ly}" text-anchor="middle">${escapeHtml(String(label).toUpperCase())}</text>`
          : "";
        return path + lbl;
      })
      .join("");
    svg.innerHTML = `<defs><marker id="afArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#e11d2e"/></marker></defs>${paths}`;
  }

  function drawMinimap() {
    const c = $("afMinimap");
    const flow = state.flow;
    if (!c || !flow) return;
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.fillStyle = "rgba(20,22,28,0.9)";
    ctx.fillRect(0, 0, c.width, c.height);
    const selected = new Set(selectedNodeIds());
    for (const n of flow.nodes || []) {
      const p = pos(n);
      ctx.fillStyle = selected.has(n.id) ? "rgba(225,29,46,0.85)" : "rgba(225,29,46,0.28)";
      ctx.fillRect(8 + p.x / 28, 8 + p.y / 28, 10, 5);
    }
    // viewport hint
    ctx.strokeStyle = "rgba(255,255,255,0.35)";
    ctx.strokeRect(4, 4, c.width - 8, c.height - 8);
  }

  function applyTransform() {
    const w = $("afWorld");
    if (w) w.style.transform = `translate(${state.pan.x}px, ${state.pan.y}px) scale(${state.zoom})`;
    if ($("afZoomPct")) $("afZoomPct").textContent = `${Math.round(state.zoom * 100)}%`;
  }

  function renderInspect() {
    const empty = $("afInspectEmpty");
    const box = $("afInspect");
    const node = (state.flow?.nodes || []).find((n) => n.id === state.selected);
    if (!node) {
      if (empty) empty.hidden = false;
      if (box) box.hidden = true;
      return;
    }
    if (empty) empty.hidden = true;
    if (box) box.hidden = false;
    const m = meta(node.type);
    if ($("afInspectMeta")) {
      const impl = m.implemented === false ? ' · <span style="color:#ff5c5c">NOT IMPLEMENTED</span>' : "";
      $("afInspectMeta").innerHTML = `<b>${escapeHtml(m.category || "NODE")}</b> · ${escapeHtml(node.type)} · id ${escapeHtml(node.id)}${impl}`;
    }
    if ($("afNodeLabel")) $("afNodeLabel").value = node.label || "";
    if ($("afNodeDesc")) $("afNodeDesc").value = node.description || m.desc || "";
    const cfg = node.config || {};
    if ($("afNodeFields")) {
      let fieldsHtml = (m.fields || [])
        .map((f) => {
          const val = cfg[f.key] ?? "";
          if (f.type === "textarea") {
            return `<div class="af-field"><label>${escapeHtml(f.label)}</label><textarea data-cfg="${escapeAttr(
              f.key
            )}" placeholder="${escapeAttr(f.placeholder || "")}">${escapeHtml(val)}</textarea></div>`;
          }
          return `<div class="af-field"><label>${escapeHtml(f.label)}</label><input data-cfg="${escapeAttr(
            f.key
          )}" type="text" value="${escapeAttr(val)}" placeholder="${escapeAttr(f.placeholder || "")}" /></div>`;
        })
        .join("");
      if (String(node.type).startsWith("trigger.")) {
        fieldsHtml =
          `<div class="af-field"><label>Trigger type</label><input type="text" value="${escapeAttr(
            node.type.replace("trigger.", "")
          )}" readonly /></div>` + fieldsHtml;
      }
      if (String(node.type).startsWith("files.") || String(node.type).startsWith("apps.open_path")) {
        fieldsHtml += `<div class="af-perm">✓ Trusted-path permission required</div>`;
      }
      if (!fieldsHtml) {
        fieldsHtml = `<div class="af-empty" style="padding:8px 12px">No config fields for this node.</div>`;
      }
      const st = state.nodeStates[node.id];
      const out = state.lastNodeOutputs[node.id];
      if (st || out) {
        fieldsHtml += `<div class="af-field"><label>Last run</label><pre class="af-panel" style="min-height:40px;max-height:100px;border:1px solid var(--af-line)">${escapeHtml(
          `${(st || "").toUpperCase()}${out ? "\n" + out : ""}`
        )}</pre></div>`;
      }
      $("afNodeFields").innerHTML = fieldsHtml;
    }
    if ($("afIoIn")) {
      const incoming = (state.flow.edges || []).filter((e) => e.target === node.id).map((e) => e.source);
      const runtimeIn = state.lastNodeInputs[node.id] || state.lastRunNodes[node.id]?.input;
      const graph = incoming.length ? `edges ← ${incoming.join(", ")}\n` : "";
      $("afIoIn").textContent = runtimeIn
        ? graph + JSON.stringify(runtimeIn, null, 2)
        : graph + "(run flow to see runtime input)";
    }
    if ($("afIoOut")) {
      const outgoing = (state.flow.edges || [])
        .filter((e) => e.source === node.id)
        .map((e) => `${e.target} [${e.sourceHandle || "default"}]`);
      const runtimeOut = state.lastRunNodes[node.id]?.output ?? state.lastNodeOutputs[node.id];
      const err = state.lastRunNodes[node.id]?.error;
      const graph = outgoing.length ? `edges → ${outgoing.join(", ")}\n` : "";
      if (err) {
        $("afIoOut").textContent = graph + `ERROR:\n${err}`;
      } else if (runtimeOut != null && runtimeOut !== "") {
        $("afIoOut").textContent =
          graph + (typeof runtimeOut === "string" ? runtimeOut : JSON.stringify(runtimeOut, null, 2));
      } else {
        $("afIoOut").textContent = graph + "(run flow to see runtime output)";
      }
    }
  }

  function selectNode(id, opts) {
    opts = opts || {};
    state.selectedEdge = "";
    if (!id) {
      state.selected = "";
      state.selectedIds = [];
      renderGraph();
      renderInspect();
      return;
    }
    if (opts.toggle) {
      const set = new Set(state.selectedIds || []);
      if (set.has(id)) set.delete(id);
      else set.add(id);
      state.selectedIds = Array.from(set);
      state.selected = state.selectedIds.includes(id) ? id : state.selectedIds[state.selectedIds.length - 1] || "";
    } else if (opts.additive) {
      const set = new Set(state.selectedIds || []);
      set.add(id);
      state.selectedIds = Array.from(set);
      state.selected = id;
    } else {
      state.selected = id;
      state.selectedIds = [id];
    }
    renderGraph();
    renderInspect();
  }

  function selectedNodeIds() {
    if (state.selectedIds && state.selectedIds.length) return state.selectedIds.slice();
    return state.selected ? [state.selected] : [];
  }

  function deleteSelectedNodes() {
    if (!state.flow) return;
    const ids = new Set(selectedNodeIds());
    if (!ids.size && state.selectedEdge) {
      pushUndo();
      state.flow.edges = (state.flow.edges || []).filter((e) => e.id !== state.selectedEdge);
      state.selectedEdge = "";
      drawEdges();
      return;
    }
    if (!ids.size) return;
    pushUndo();
    state.flow.nodes = state.flow.nodes.filter((n) => !ids.has(n.id));
    state.flow.edges = (state.flow.edges || []).filter((e) => !ids.has(e.source) && !ids.has(e.target));
    state.selected = state.flow.nodes[0]?.id || "";
    state.selectedIds = state.selected ? [state.selected] : [];
    renderGraph();
    renderInspect();
  }

  function duplicateSelectedNodes() {
    if (!state.flow) return;
    const ids = selectedNodeIds();
    if (!ids.length) return;
    pushUndo();
    const created = [];
    for (const sid of ids) {
      const src = state.flow.nodes.find((n) => n.id === sid);
      if (!src) continue;
      const id = "n" + Math.random().toString(36).slice(2, 8);
      const p = pos(src);
      state.flow.nodes.push({
        ...JSON.parse(JSON.stringify(src)),
        id,
        position: { x: p.x + 40, y: p.y + 40 },
      });
      created.push(id);
    }
    if (created.length) {
      state.selectedIds = created;
      state.selected = created[created.length - 1];
      renderGraph();
      renderInspect();
    }
  }

  function copySelectedNodes() {
    const ids = selectedNodeIds();
    if (!ids.length || !state.flow) return;
    const nodes = state.flow.nodes.filter((n) => ids.includes(n.id)).map((n) => JSON.parse(JSON.stringify(n)));
    const idset = new Set(ids);
    const edges = (state.flow.edges || [])
      .filter((e) => idset.has(e.source) && idset.has(e.target))
      .map((e) => JSON.parse(JSON.stringify(e)));
    state.clipboard = { nodes, edges };
    setStatus(`Copied ${nodes.length} node(s)`);
  }

  function pasteClipboard() {
    if (!state.flow || !state.clipboard?.nodes?.length) return;
    pushUndo();
    const idMap = {};
    const created = [];
    for (const src of state.clipboard.nodes) {
      const id = "n" + Math.random().toString(36).slice(2, 8);
      idMap[src.id] = id;
      const p = pos(src);
      state.flow.nodes.push({
        ...JSON.parse(JSON.stringify(src)),
        id,
        position: { x: p.x + 56, y: p.y + 56 },
      });
      created.push(id);
    }
    for (const e of state.clipboard.edges || []) {
      if (!idMap[e.source] || !idMap[e.target]) continue;
      state.flow.edges = state.flow.edges || [];
      state.flow.edges.push({
        ...JSON.parse(JSON.stringify(e)),
        id: "e" + Math.random().toString(36).slice(2, 7),
        source: idMap[e.source],
        target: idMap[e.target],
      });
    }
    state.selectedIds = created;
    state.selected = created[created.length - 1] || "";
    renderGraph();
    renderInspect();
    setStatus(`Pasted ${created.length} node(s)`);
  }

  function alignSelected(axis) {
    const ids = selectedNodeIds();
    if (ids.length < 2 || !state.flow) return;
    pushUndo();
    const nodes = state.flow.nodes.filter((n) => ids.includes(n.id));
    if (axis === "left") {
      const x = Math.min(...nodes.map((n) => pos(n).x));
      nodes.forEach((n) => setPos(n, x, pos(n).y));
    } else if (axis === "top") {
      const y = Math.min(...nodes.map((n) => pos(n).y));
      nodes.forEach((n) => setPos(n, pos(n).x, y));
    } else if (axis === "hcenter") {
      const xs = nodes.map((n) => pos(n).x);
      const mid = (Math.min(...xs) + Math.max(...xs)) / 2;
      nodes.forEach((n) => setPos(n, mid, pos(n).y));
    }
    renderGraph();
  }

  function autoLayout() {
    if (!state.flow?.nodes?.length) return;
    pushUndo();
    const nodes = state.flow.nodes.slice();
    const indeg = {};
    nodes.forEach((n) => (indeg[n.id] = 0));
    (state.flow.edges || []).forEach((e) => {
      if (indeg[e.target] != null) indeg[e.target]++;
    });
    const ordered = nodes.slice().sort((a, b) => (indeg[a.id] || 0) - (indeg[b.id] || 0) || String(a.id).localeCompare(String(b.id)));
    ordered.forEach((n, i) => setPos(n, 80 + (i % 5) * 260, 100 + Math.floor(i / 5) * 140));
    renderGraph();
    setStatus("Auto-layout applied");
  }

  function focusNodeSearch() {
    const el = $("afNodeSearch");
    if (el) {
      el.focus();
      el.select();
    }
  }

  function addNode(type, x, y) {
    if (!state.flow) return;
    pushUndo();
    const m = meta(type);
    const id = "n" + Math.random().toString(36).slice(2, 8);
    const node = {
      id,
      type,
      label: m.label || type,
      description: m.desc || "",
      position: {
        x: x ?? 120 + state.flow.nodes.length * 28,
        y: y ?? 100 + state.flow.nodes.length * 20,
      },
      config: {},
    };
    if (type === "files.list" || type === "apps.open_path") {
      node.config.path = state.roots[0]?.path || "";
    }
    if (type === "logic.if") {
      node.config.condition = "{{$file.extension}} == pdf";
    }
    state.flow.nodes.push(node);
    selectNode(id);
    setStatus(`Added ${m.label}`);
  }

  async function saveFlow() {
    if (!state.flow) return;
    $("afSaveState").textContent = "Saving…";
    $("afSaveState").className = "af-pill saving";
    state.flow.name = $("afFlowName").value.trim() || "Untitled flow";
    state.flow.nodes = dedupeNodes(state.flow.nodes);
    const data = await api("/api/flows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.flow),
    });
    if (data.ok) {
      state.flow = data.flow;
      state.flow.nodes = dedupeNodes(state.flow.nodes);
      state.activeId = data.flow.id;
      const list = await api("/api/flows");
      state.flows = list.flows || [];
      renderFlowList();
      renderGraph();
      markSaved();
      setStatus("Saved");
    } else {
      setStatus(data.message || "Save failed");
      $("afSaveState").textContent = "Save failed";
    }
  }

  async function newFlow() {
    const data = await api("/api/flows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: "Untitled Flow",
        nodes: [],
        edges: [],
      }),
    });
    if (data.ok) {
      const list = await api("/api/flows");
      state.flows = list.flows || [];
      await loadFlow(data.flow.id);
    }
  }

  async function runFlow() {
    if (!state.activeId || state.running) return;
    if (!(state.flow?.nodes || []).length) {
      setStatus("Add nodes before running");
      return;
    }
    await saveFlow();
    state.running = true;
    state.nodeStates = {};
    state.nodeOrder = {};
    state.activeEdge = "";
    state.lastNodeOutputs = {};
    state.lastNodeInputs = {};
    state.lastRunNodes = {};
    state.issues = [];
    state.panelLog = "";
    for (const n of state.flow.nodes || []) state.nodeStates[n.id] = "queued";
    renderGraph();
    $("afStop").disabled = false;
    $("afRun").disabled = true;
    setStatus("Running…");
    setPanel("log", "");

    if (state.runEs) {
      try {
        state.runEs.close();
      } catch (_) {}
    }
    const es = new EventSource(`/api/flows/${encodeURIComponent(state.activeId)}/run/stream`);
    state.runEs = es;
    let finalOk = true;
    let finished = false;

    const finish = (msg) => {
      if (finished) return;
      finished = true;
      state.running = false;
      state.activeEdge = "";
      $("afStop").disabled = true;
      $("afRun").disabled = false;
      drawEdges();
      setStatus(msg);
      try {
        es.close();
      } catch (_) {}
      state.runEs = null;
    };

    es.onmessage = (ev) => {
      let data;
      try {
        data = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (data.type === "flow_start") {
        state.lastRunId = data.runId || "";
        appendLog("FLOW STARTED");
      } else if (data.type === "log") {
        const t = new Date((data.t || Date.now() / 1000) * 1000).toTimeString().slice(0, 8);
        appendLog(`[${t}] ${data.message}`);
      } else if (data.type === "node_state") {
        let st = String(data.status || "").toLowerCase();
        if (st === "failed") st = "error";
        if (st === "pending") st = "queued";
        state.nodeStates[data.nodeId] = st;
        if (data.order) state.nodeOrder[data.nodeId] = data.order;
        if (data.output != null) state.lastNodeOutputs[data.nodeId] = data.output;
        if (data.data != null) {
          state.lastRunNodes[data.nodeId] = {
            ...(state.lastRunNodes[data.nodeId] || {}),
            output: data.data,
            message: data.output,
            status: st,
          };
        }
        if (data.input != null) {
          state.lastNodeInputs[data.nodeId] = data.input;
          state.lastRunNodes[data.nodeId] = {
            ...(state.lastRunNodes[data.nodeId] || {}),
            input: data.input,
          };
        }
        if (data.error) {
          state.issues.push(data.error);
          state.lastNodeOutputs[data.nodeId] = data.error;
          state.lastRunNodes[data.nodeId] = {
            ...(state.lastRunNodes[data.nodeId] || {}),
            error: data.error,
            status: "error",
          };
        }
        if (data.activeEdge) state.activeEdge = data.activeEdge;
        renderGraph();
        if (state.selected === data.nodeId) renderInspect();
      } else if (data.type === "edge_active") {
        state.activeEdge = data.edgeId || "";
        drawEdges();
      } else if (data.type === "flow_done") {
        state.lastRunVars = data.variables || {};
        if (data.nodes) state.lastRunNodes = { ...state.lastRunNodes, ...data.nodes };
        finalOk = !!data.ok;
        $("afErrors").textContent = finalOk ? "No errors" : `${state.issues.length || 1} error(s)`;
        appendLog(finalOk ? "FLOW COMPLETED" : "FLOW FAILED");
        if (state.selected) renderInspect();
        finish(finalOk ? "Run OK" : "Run failed");
      } else if (data.type === "run_complete") {
        const run = data.run || {};
        state.lastRunId = run.id || state.lastRunId;
        state.lastRunVars = run.variables || state.lastRunVars;
        if (run.nodes) state.lastRunNodes = { ...state.lastRunNodes, ...run.nodes };
        finalOk = !!run.ok;
        $("afErrors").textContent = finalOk ? "No errors" : `${state.issues.length || 1} error(s)`;
        if (state.selected) renderInspect();
        finish(finalOk ? "Run OK" : "Run failed");
      } else if (data.type === "error") {
        finalOk = false;
        appendLog(data.message || "Run error");
        finish("Run failed");
      }
    };

    es.onerror = () => {
      if (state.running) {
        appendLog("Stream closed");
        finish(finalOk ? "Run OK" : "Run ended");
      }
    };
  }

  function appendLog(line) {
    state.panelLog = (state.panelLog ? state.panelLog + "\n" : "") + line;
    if (state.bottomTab === "log") setPanel("log", state.panelLog);
  }

  async function stopFlow() {
    if (!state.lastRunId) {
      setStatus("No active run id yet");
      appendLog("Cancellation requested (waiting for run id)");
      return;
    }
    const data = await api("/api/flows/run/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: state.lastRunId }),
    });
    appendLog(data.ok ? "Cancellation requested" : data.message || "Stop failed");
    setStatus("Cancellation requested");
  }

  async function testNode() {
    const node = (state.flow?.nodes || []).find((n) => n.id === state.selected);
    if (!node) return;
    setStatus("Testing node…");
    const data = await api("/api/flows/test-node", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node }),
    });
    if (data.ok) {
      state.lastNodeOutputs[node.id] = data.output;
      state.lastRunNodes[node.id] = {
        input: node.config || {},
        output: data.data,
        message: data.output,
        status: "success",
      };
      renderInspect();
    }
    setPanel(
      "log",
      data.ok
        ? `Test OK (${data.ms}ms)\n\n${data.output || ""}\n\n${JSON.stringify(data.data || {}, null, 2)}`
        : `Test FAILED\n\n${data.error || ""}`
    );
    setStatus(data.ok ? "Test OK" : "Test failed");
  }

  async function loadHistory() {
    const data = await api("/api/flows/runs");
    const panel = $("afPanel");
    if (!panel) return;
    state.bottomTab = "history";
    document.querySelectorAll(".af-tabs [data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === "history"));
    const runs = data.runs || [];
    if (!runs.length) {
      panel.textContent = "No runs yet.";
      return;
    }
    panel.innerHTML = runs
      .map((r) => {
        const when = new Date((r.started || 0) * 1000).toLocaleString();
        return `<button type="button" data-run="${escapeAttr(r.id)}" style="display:block;width:100%;text-align:left;margin:0 0 6px;padding:8px;border:1px solid rgba(225,29,46,0.25);background:#0a0c10;color:#d5d0c6;cursor:pointer;font-family:var(--af-mono);font-size:11px">
RUN ${escapeHtml(r.id)} · ${escapeHtml(r.status || (r.ok ? "SUCCESS" : "FAIL"))} · ${r.duration_ms || "?"}ms · ${escapeHtml(r.flow_name || "")}<br><small>${escapeHtml(when)} · ${r.steps || 0} nodes</small>
</button>`;
      })
      .join("");
  }

  async function openVersionHistory() {
    const modal = $("afHistoryModal");
    const list = $("afHistoryList");
    if (!modal || !list) return;
    modal.hidden = false;
    if (!state.activeId) {
      list.textContent = "Save the flow first to start version history.";
      return;
    }
    list.textContent = "Loading…";
    const data = await api(`/api/flows/${encodeURIComponent(state.activeId)}/versions`);
    const versions = data.versions || [];
    if (!versions.length) {
      list.textContent = "No saved versions yet — versions are snapshotted automatically on each Save.";
      return;
    }
    list.innerHTML = versions
      .map((v) => {
        const when = v.saved_at ? new Date(v.saved_at * 1000).toLocaleString() : "";
        return `<div class="af-version-row">
          <span>${escapeHtml(v.version_id || "")} · ${escapeHtml(v.reason || "edit")}<br><small>${escapeHtml(when)} · ${v.node_count || 0} nodes</small></span>
          <button type="button" data-restore="${escapeAttr(v.version_id || "")}">Restore</button>
        </div>`;
      })
      .join("");
    list.querySelectorAll("[data-restore]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Restore this version? Current unsaved edits will be replaced.")) return;
        const res = await api(`/api/flows/${encodeURIComponent(state.activeId)}/versions/${encodeURIComponent(btn.dataset.restore)}/restore`, { method: "POST" });
        if (res.ok) {
          modal.hidden = true;
          await loadFlow(state.activeId);
          setStatus("Version restored");
        } else {
          setStatus(res.message || "Restore failed");
        }
      });
    });
  }

  async function openCompileHints() {
    const modal = $("afHintsModal");
    const body = $("afHintsBody");
    if (!modal || !body) return;
    modal.hidden = false;
    body.textContent = "Loading…";
    const data = await api("/api/flows/compile-hints");
    body.textContent = data.hints || "No hints yet.";
  }

  async function openRun(runId) {
    const data = await api(`/api/flows/runs/${encodeURIComponent(runId)}`);
    const run = data.run || data;
    if (!run || !run.id) {
      setPanel("history", "Run not found");
      return;
    }
    state.lastRunId = run.id;
    state.lastRunVars = run.variables || {};
    state.lastRunNodes = run.nodes || {};
    state.nodeStates = {};
    state.nodeOrder = {};
    for (const r of run.nodeResults || []) {
      const st = String(r.status || "").toLowerCase();
      state.nodeStates[r.nodeId] = st === "failed" ? "error" : st;
      if (r.order) state.nodeOrder[r.nodeId] = r.order;
      if (r.input) state.lastNodeInputs[r.nodeId] = r.input;
    }
    renderGraph();
    const lines = (run.logs || []).map((l) => {
      const t = new Date((l.t || run.started || 0) * 1000).toTimeString().slice(0, 8);
      return `[${t}] ${l.message}`;
    });
    let extra = "";
    const p3 = run.phase3;
    if (p3 && typeof p3 === "object") {
      extra += `\n\nPHASE3 autonomous=${!!p3.autonomous} attempts=${p3.attempts || 0}`;
      extra += `\nVerification: ${p3.verification?.ok ? "PASS" : "FAIL"}`;
      if ((p3.retries || []).length) extra += `\nRetries: ${p3.retries.length}`;
      if ((p3.recovery || []).length) {
        const last = p3.recovery[p3.recovery.length - 1];
        extra += `\nRecovery: ${last.action} — ${last.message || ""}`;
      }
      if (p3.checkpoint_id) extra += `\nCheckpoint: ${p3.checkpoint_id}`;
      if ((p3.timeline || []).length) {
        extra += "\nTimeline:";
        for (const ev of p3.timeline.slice(-12)) {
          extra += `\n  - ${ev.event}${ev.attempt ? " #" + ev.attempt : ""}${ev.status ? " " + ev.status : ""}`;
        }
      }
    }
    setPanel(
      "log",
      `RUN ${run.id} · ${run.status} · ${run.duration_ms}ms\n\n` + (lines.join("\n") || "(no logs)") + extra
    );
    setStatus(`Opened run ${run.id}`);
    if (state.selected) renderInspect();
  }

  function setPanel(tab, text) {
    state.bottomTab = tab;
    if (tab === "log" && text != null) state.panelLog = text;
    document.querySelectorAll(".af-tabs [data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
    const panel = $("afPanel");
    if (!panel) return;
    if (tab === "log") panel.textContent = text != null ? text : state.panelLog;
    else if (tab === "vars") {
      const payload = {
        variables: state.lastRunVars,
        nodes: state.lastRunNodes,
      };
      panel.textContent =
        Object.keys(state.lastRunVars || {}).length || Object.keys(state.lastRunNodes || {}).length
          ? JSON.stringify(payload, null, 2)
          : "Run a flow to see variables.";
    } else if (tab === "issues") panel.textContent = state.issues.join("\n") || "No issues.";
    else if (text != null) panel.textContent = text;
  }

  function bind() {
    $("afNodeSearch")?.addEventListener("input", () => renderCategories());
    $("afCategories")?.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-add]");
      if (b) addNode(b.dataset.add);
    });
    $("afCategories")?.addEventListener("dragstart", (ev) => {
      const b = ev.target.closest("[data-add]");
      if (!b) return;
      ev.dataTransfer.setData("text/altron-node", b.dataset.add);
    });
    $("afFlowList")?.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-flow]");
      if (b) loadFlow(b.dataset.flow);
    });
    $("afSave")?.addEventListener("click", () => saveFlow());
    $("afNew")?.addEventListener("click", () => newFlow());
    $("afRun")?.addEventListener("click", () => runFlow());
    $("afStop")?.addEventListener("click", () => stopFlow());
    $("afTestNode")?.addEventListener("click", () => testNode());

    $("afZoomIn")?.addEventListener("click", () => {
      state.zoom = Math.min(2, state.zoom + 0.1);
      applyTransform();
    });
    $("afZoomOut")?.addEventListener("click", () => {
      state.zoom = Math.max(0.35, state.zoom - 0.1);
      applyTransform();
    });
    $("afFit")?.addEventListener("click", () => fitView());

    $("afBottomToggle")?.addEventListener("click", () => {
      document.getElementById("afApp")?.classList.toggle("bottom-collapsed");
      const collapsed = document.getElementById("afApp")?.classList.contains("bottom-collapsed");
      $("afBottomToggle").textContent = collapsed ? "▴" : "▾";
      requestAnimationFrame(() => fitView());
    });

    $("afRootAdd")?.addEventListener("click", async () => {
      const path = $("afRootIn").value.trim();
      if (!path) return;
      const data = await api("/api/flows/roots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      state.roots = data.roots || [];
      renderRoots();
      $("afRootIn").value = "";
    });

    document.querySelector(".af-inspect-tabs")?.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-itab]");
      if (!b) return;
      document.querySelectorAll(".af-inspect-tabs button").forEach((x) => x.classList.toggle("on", x === b));
      const io = b.dataset.itab === "io";
      if ($("afInspectConfig")) $("afInspectConfig").hidden = io;
      if ($("afInspectIo")) $("afInspectIo").hidden = !io;
    });

    const vp = $("afViewport");
    vp?.addEventListener("dragover", (ev) => ev.preventDefault());
    vp?.addEventListener("drop", (ev) => {
      ev.preventDefault();
      const type = ev.dataTransfer.getData("text/altron-node");
      if (!type) return;
      const rect = vp.getBoundingClientRect();
      const x = (ev.clientX - rect.left - state.pan.x) / state.zoom;
      const y = (ev.clientY - rect.top - state.pan.y) / state.zoom;
      addNode(type, Math.max(20, x - NODE_W / 2), Math.max(20, y - 40));
    });

    vp?.addEventListener(
      "wheel",
      (ev) => {
        ev.preventDefault();
        if (ev.ctrlKey || ev.metaKey) {
          const rect = vp.getBoundingClientRect();
          const mx = ev.clientX - rect.left;
          const my = ev.clientY - rect.top;
          const prev = state.zoom;
          const next = Math.min(2, Math.max(0.35, state.zoom + (ev.deltaY > 0 ? -0.08 : 0.08)));
          const wx = (mx - state.pan.x) / prev;
          const wy = (my - state.pan.y) / prev;
          state.zoom = next;
          state.pan.x = mx - wx * next;
          state.pan.y = my - wy * next;
          applyTransform();
        } else {
          state.pan.x -= ev.deltaX || 0;
          state.pan.y -= ev.deltaY || 0;
          applyTransform();
        }
      },
      { passive: false }
    );

    vp?.addEventListener("mousedown", (ev) => {
      if (ev.target.closest(".af-node") || ev.target.closest(".af-handle") || ev.target.closest("path[data-edge]")) return;
      state.selected = "";
      state.selectedIds = [];
      state.selectedEdge = "";
      renderGraph();
      renderInspect();
      state.panning = true;
      state.panStart = { x: ev.clientX - state.pan.x, y: ev.clientY - state.pan.y };
      vp.classList.add("panning");
    });

    $("afEdges")?.addEventListener("mousedown", (ev) => {
      const path = ev.target.closest("path[data-edge]");
      if (!path) return;
      state.selectedEdge = path.dataset.edge;
      state.selected = "";
      state.selectedIds = [];
      drawEdges();
      renderInspect();
      ev.stopPropagation();
    });

    $("afNodes")?.addEventListener("mousedown", (ev) => {
      const handle = ev.target.closest(".af-handle");
      if (handle?.dataset.handle && handle.dataset.handle !== "in") {
        state.connectFrom = { node: handle.dataset.node, handle: handle.dataset.handle };
        ev.stopPropagation();
        return;
      }
      if (handle?.dataset.handle === "in" && state.connectFrom) {
        if (state.connectFrom.node === handle.dataset.node) {
          state.connectFrom = null;
          return;
        }
        pushUndo();
        const srcHandle = state.connectFrom.handle === "out" ? "default" : state.connectFrom.handle;
        const targetId = handle.dataset.node;
        state.flow.edges = state.flow.edges || [];
        // no duplicate edges (same source/target/handle)
        const dup = state.flow.edges.some(
          (e) =>
            e.source === state.connectFrom.node &&
            e.target === targetId &&
            (e.sourceHandle || "default") === srcHandle
        );
        if (dup) {
          state.connectFrom = null;
          setStatus("Edge already exists");
          ev.stopPropagation();
          return;
        }
        // reconnect: replace existing edge from same source+handle
        state.flow.edges = state.flow.edges.filter(
          (e) => !(e.source === state.connectFrom.node && (e.sourceHandle || "default") === srcHandle)
        );
        state.flow.edges.push({
          id: "e" + Math.random().toString(36).slice(2, 7),
          source: state.connectFrom.node,
          target: targetId,
          sourceHandle: srcHandle,
          targetHandle: "in",
          label: ["yes", "no"].includes(srcHandle) ? srcHandle : "",
        });
        state.connectFrom = null;
        drawEdges();
        markDirty();
        ev.stopPropagation();
        return;
      }
      const node = ev.target.closest(".af-node");
      if (!node) return;
      const additive = ev.ctrlKey || ev.metaKey || ev.shiftKey;
      selectNode(node.dataset.id, additive ? { additive: true, toggle: ev.ctrlKey || ev.metaKey } : {});
      const dragIds = selectedNodeIds();
      const origins = {};
      for (const id of dragIds) {
        const nn = state.flow.nodes.find((x) => x.id === id);
        if (nn) origins[id] = { ...pos(nn) };
      }
      state.dragNode = {
        id: state.selected,
        ids: dragIds,
        origins,
        ox: ev.clientX,
        oy: ev.clientY,
        moved: false,
        snapshot: false,
      };
      ev.stopPropagation();
    });

    window.addEventListener("mousemove", (ev) => {
      if (state.panning && state.panStart) {
        state.pan.x = ev.clientX - state.panStart.x;
        state.pan.y = ev.clientY - state.panStart.y;
        applyTransform();
      }
      if (state.dragNode && state.flow) {
        const dx = (ev.clientX - state.dragNode.ox) / state.zoom;
        const dy = (ev.clientY - state.dragNode.oy) / state.zoom;
        if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
          if (!state.dragNode.snapshot) {
            snapshotUndo();
            state.dragNode.snapshot = true;
          }
          state.dragNode.moved = true;
        }
        const ids = state.dragNode.ids || [state.dragNode.id];
        for (const id of ids) {
          const n = state.flow.nodes.find((x) => x.id === id);
          const origin = (state.dragNode.origins || {})[id];
          if (!n || !origin) continue;
          setPos(n, Math.max(0, origin.x + dx), Math.max(0, origin.y + dy));
          const el = $("afNodes").querySelector(`[data-id="${CSS.escape(id)}"]`);
          if (el) {
            el.style.left = pos(n).x + "px";
            el.style.top = pos(n).y + "px";
          }
        }
        drawEdges();
        drawMinimap();
      }
    });

    window.addEventListener("mouseup", () => {
      if (state.dragNode?.moved) markDirty();
      state.dragNode = null;
      state.connectFrom = null;
      if (state.panning) {
        state.panning = false;
        state.panStart = null;
        vp?.classList.remove("panning");
      }
    });

    $("afNodeLabel")?.addEventListener("input", (ev) => {
      const n = state.flow?.nodes.find((x) => x.id === state.selected);
      if (!n) return;
      n.label = ev.target.value;
      markDirty();
      const el = $("afNodes")?.querySelector(`[data-id="${CSS.escape(n.id)}"] .af-node-head span:nth-child(2)`);
      if (el) el.textContent = n.label;
    });
    $("afNodeDesc")?.addEventListener("input", (ev) => {
      const n = state.flow?.nodes.find((x) => x.id === state.selected);
      if (!n) return;
      n.description = ev.target.value;
      markDirty();
      const el = $("afNodes")?.querySelector(`[data-id="${CSS.escape(n.id)}"] .af-node-desc`);
      if (el) el.textContent = n.description;
    });
    $("afNodeFields")?.addEventListener("input", (ev) => {
      const inp = ev.target.closest("[data-cfg]");
      if (!inp) return;
      const n = state.flow?.nodes.find((x) => x.id === state.selected);
      if (!n) return;
      n.config = n.config || {};
      n.config[inp.dataset.cfg] = inp.value;
      markDirty();
    });

    $("afDelNode")?.addEventListener("click", () => deleteSelectedNodes());
    $("afDupNode")?.addEventListener("click", () => duplicateSelectedNodes());

    $("afUndo")?.addEventListener("click", () => {
      if (!state.undo.length) return;
      state.redo.push(JSON.stringify(state.flow));
      state.flow = JSON.parse(state.undo.pop());
      state.flow.nodes = dedupeNodes(state.flow.nodes);
      state.selected = state.flow.nodes[0]?.id || "";
      state.selectedIds = state.selected ? [state.selected] : [];
      renderGraph();
      renderInspect();
      markDirty();
    });
    $("afRedo")?.addEventListener("click", () => {
      if (!state.redo.length) return;
      state.undo.push(JSON.stringify(state.flow));
      state.flow = JSON.parse(state.redo.pop());
      state.flow.nodes = dedupeNodes(state.flow.nodes);
      state.selected = state.flow.nodes[0]?.id || "";
      state.selectedIds = state.selected ? [state.selected] : [];
      renderGraph();
      renderInspect();
      markDirty();
    });

    $("afHistoryBtn")?.addEventListener("click", () => openVersionHistory());
    $("afHistoryClose")?.addEventListener("click", () => {
      $("afHistoryModal").hidden = true;
    });
    $("afHintsBtn")?.addEventListener("click", () => openCompileHints());
    $("afHintsClose")?.addEventListener("click", () => {
      $("afHintsModal").hidden = true;
    });

    document.querySelector(".af-tabs")?.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-tab]");
      if (!b) return;
      if (b.dataset.tab === "history") loadHistory();
      else setPanel(b.dataset.tab);
    });

    $("afPanel")?.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-run]");
      if (b) openRun(b.dataset.run);
    });

    document.addEventListener("keydown", (ev) => {
      const tag = (ev.target && ev.target.tagName) || "";
      const typing = tag === "INPUT" || tag === "TEXTAREA" || (ev.target && ev.target.isContentEditable);
      const mod = ev.ctrlKey || ev.metaKey;
      const key = ev.key.toLowerCase();

      if (mod && key === "s") {
        ev.preventDefault();
        saveFlow();
        return;
      }
      if (mod && key === "z" && !ev.shiftKey) {
        if (typing) return;
        ev.preventDefault();
        $("afUndo")?.click();
        return;
      }
      if ((mod && key === "y") || (mod && ev.shiftKey && key === "z")) {
        if (typing) return;
        ev.preventDefault();
        $("afRedo")?.click();
        return;
      }
      if (mod && key === "c") {
        if (typing) return;
        ev.preventDefault();
        copySelectedNodes();
        return;
      }
      if (mod && key === "v") {
        if (typing) return;
        ev.preventDefault();
        pasteClipboard();
        return;
      }
      if (mod && key === "d") {
        if (typing) return;
        ev.preventDefault();
        duplicateSelectedNodes();
        return;
      }
      if (mod && key === "a") {
        if (typing || !state.flow) return;
        ev.preventDefault();
        state.selectedIds = (state.flow.nodes || []).map((n) => n.id);
        state.selected = state.selectedIds[0] || "";
        renderGraph();
        renderInspect();
        return;
      }
      if (mod && key === "f") {
        ev.preventDefault();
        focusNodeSearch();
        return;
      }
      if (mod && key === "l") {
        if (typing) return;
        ev.preventDefault();
        autoLayout();
        return;
      }
      if (!typing && mod && key === "arrowleft") {
        ev.preventDefault();
        alignSelected("left");
        return;
      }
      if (!typing && mod && key === "arrowup") {
        ev.preventDefault();
        alignSelected("top");
        return;
      }
      if (ev.key === "Delete" || ev.key === "Backspace") {
        if (typing) return;
        ev.preventDefault();
        deleteSelectedNodes();
        return;
      }
      if (ev.key === "f" && !mod) {
        if (typing) return;
        fitView();
      }
      if (ev.key === "+" || ev.key === "=") {
        if (typing || !mod) return;
        ev.preventDefault();
        state.zoom = Math.min(2.4, state.zoom + 0.1);
        applyTransform();
      }
      if (ev.key === "-" || ev.key === "_") {
        if (typing || !mod) return;
        ev.preventDefault();
        state.zoom = Math.max(0.35, state.zoom - 0.1);
        applyTransform();
      }
    });

    window.addEventListener("beforeunload", (ev) => {
      if (state.dirty) {
        ev.preventDefault();
        ev.returnValue = "";
      }
    });

    const ctx = $("afCtx");
    const hideCtx = () => ctx?.classList.remove("open");
    document.addEventListener("click", hideCtx);
    $("afViewport")?.addEventListener("contextmenu", (ev) => {
      const nodeEl = ev.target.closest(".af-node");
      const edgeEl = ev.target.closest("path[data-edge]");
      ev.preventDefault();
      if (!ctx) return;
      let html = "";
      if (nodeEl) {
        selectNode(nodeEl.dataset.id);
        html = `
          <button type="button" data-act="dup">Duplicate</button>
          <button type="button" data-act="test">Test Node</button>
          <button type="button" class="danger" data-act="del">Delete Node</button>`;
      } else if (edgeEl) {
        state.selectedEdge = edgeEl.dataset.edge;
        state.selected = "";
        drawEdges();
        html = `<button type="button" class="danger" data-act="del-edge">Delete Connection</button>`;
      } else {
        html = `<button type="button" data-act="fit">Fit View</button>
          <button type="button" data-act="add-manual">Add Manual Trigger</button>`;
      }
      ctx.innerHTML = html;
      ctx.style.left = Math.min(ev.clientX, window.innerWidth - 180) + "px";
      ctx.style.top = Math.min(ev.clientY, window.innerHeight - 140) + "px";
      ctx.classList.add("open");
    });
    ctx?.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-act]");
      if (!b) return;
      const act = b.dataset.act;
      hideCtx();
      if (act === "dup") $("afDupNode")?.click();
      else if (act === "test") testNode();
      else if (act === "del") $("afDelNode")?.click();
      else if (act === "del-edge" && state.selectedEdge) {
        pushUndo();
        state.flow.edges = (state.flow.edges || []).filter((e) => e.id !== state.selectedEdge);
        state.selectedEdge = "";
        drawEdges();
      } else if (act === "fit") fitView();
      else if (act === "add-manual") addNode("trigger.manual");
    });
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

  document.addEventListener("DOMContentLoaded", () => boot());
})();
