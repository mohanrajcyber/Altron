const STORE = "altron.threads.v1";
const STARTERS = [
  { title: "Open IDE", body: "open ide" },
  { title: "Open Flows", body: "open flows" },
  { title: "See screen", body: "what's on my screen" },
  { title: "Open browser", body: "open browser" },
  { title: "Open YouTube", body: "open youtube" },
  { title: "WhatsApp", body: "open whatsapp" },
];

const els = {
  app: document.getElementById("app"),
  threads: document.getElementById("threads"),
  log: document.getElementById("log"),
  empty: document.getElementById("empty"),
  starters: document.getElementById("starters"),
  form: document.getElementById("form"),
  input: document.getElementById("input"),
  sendBtn: document.getElementById("sendBtn"),
  stopBtn: document.getElementById("stopBtn"),
  newChat: document.getElementById("newChat"),
  menuBtn: document.getElementById("menuBtn"),
  topTitle: document.getElementById("topTitle"),
  ideBtn: document.getElementById("ideBtn"),
  flowsBtn: document.getElementById("flowsBtn"),
  forgeBtn: document.getElementById("forgeBtn"),
  statusDot: document.getElementById("statusDot"),
  statusText: document.getElementById("statusText"),
  composerMeta: document.getElementById("composerMeta"),
  micBtn: document.getElementById("micBtn"),
  speakBtn: document.getElementById("speakBtn"),
  coreKv: document.getElementById("coreKv"),
  trace: document.getElementById("trace"),
  traces: document.getElementById("traces"),
  mem: document.getElementById("mem"),
  identity: document.getElementById("identity"),
};

let threads = loadThreads();
let activeId = threads[0]?.id || createThread().id;
let abort = null;
let speakOn = localStorage.getItem("altron.speak") === "1";
let micOn = localStorage.getItem("altron.mic") === "1";
let voiceStickyMode = localStorage.getItem("altron.voiceStickyMode") || "normal";
let recognizing = false;
let micPaused = false;
let micKickTimer = 0;
let micWatchTimer = 0;
let micFailStreak = 0;
let micRetryPending = false;
const MIC_RETRY_LIMIT = 3;
let micFinalBuf = "";
let micFinalTimer = 0;
let wakeListeningUntil = 0;
const WAKE_FOLLOW_UP_MS = 8000;
const SpeechEngine = window.SpeechRecognition || window.webkitSpeechRecognition;
const rec = SpeechEngine ? new SpeechEngine() : null;
console.info("[ALTRON voice] speech engine initialized", {
  engine: window.SpeechRecognition ? "SpeechRecognition" : window.webkitSpeechRecognition ? "webkitSpeechRecognition" : "unavailable",
  language: "en-IN",
});
if (rec) {
  // en-IN matches this PC; continuous keeps Chrome from dropping after short silence.
  rec.lang = "en-IN";
  rec.interimResults = true;
  rec.continuous = true;
  rec.maxAlternatives = 1;
  rec.onnomatch = () => {
    if (micOn && !micPaused && !abort) {
      els.composerMeta.textContent = "Mic heard nothing yet — try again";
    }
  };
  rec.onresult = (ev) => {
    if (abort || micPaused || !micOn) return;
    let interim = "";
    let finalBits = [];
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const piece = (ev.results[i][0]?.transcript || "").trim();
      if (!piece) continue;
      if (ev.results[i].isFinal) finalBits.push(piece);
      else interim = piece;
    }
    if (interim && !finalBits.length) {
      els.composerMeta.textContent = `Hearing: ${interim.slice(0, 48)}`;
      return;
    }
    if (!finalBits.length) return;
    micFailStreak = 0;
    micFinalBuf = `${micFinalBuf} ${finalBits.join(" ")}`.replace(/\s+/g, " ").trim();
    console.info("[ALTRON voice] final speech result received", {
      language: rec.lang,
      characters: micFinalBuf.length,
      parts: finalBits.length,
    });
    els.composerMeta.textContent = `Hearing: ${micFinalBuf.slice(0, 48)}`;
    clearTimeout(micFinalTimer);
    // Chrome often splits one sentence into several finals — wait for a short pause.
    micFinalTimer = setTimeout(() => {
      const raw = micFinalBuf.trim();
      micFinalBuf = "";
      if (!raw || abort || micPaused || !micOn) return;
      const wakeWordHeard = hasWakeWord(raw);
      if (!wakeWordHeard && Date.now() > wakeListeningUntil) {
        els.composerMeta.textContent = 'Ignored — start with "hey ALTRON".';
        return;
      }
      const said = wakeWordHeard ? stripWakeWord(raw) : raw;
      if (!said) {
        wakeListeningUntil = Date.now() + WAKE_FOLLOW_UP_MS;
        els.composerMeta.textContent = "Hey ALTRON heard — say your request within 8 seconds.";
        return;
      }
      wakeListeningUntil = 0;
      els.input.value = said;
      resize();
      pauseMic("Thinking");
      send({ fromMic: true });
    }, 320);
  };
  rec.onstart = () => {
    recognizing = true;
    els.micBtn.classList.add("live");
    console.info("[ALTRON voice] recognition session started", { language: rec.lang });
    if (!micPaused) els.composerMeta.textContent = 'Listening — say "Hey ALTRON, open YouTube" …';
  };
  rec.onend = () => {
    recognizing = false;
    console.info("[ALTRON voice] recognition session ended", { micOn, micPaused });
    if (micOn && !micPaused && !abort) {
      if (micRetryPending) return;
      startMicListen(180);
      return;
    }
    if (!micOn) {
      els.micBtn.classList.remove("live");
      if (!abort) els.composerMeta.textContent = "Ready";
    }
  };
  rec.onerror = (ev) => {
    recognizing = false;
    const err = ev.error || "";
    console.warn("[ALTRON voice] recognition error", { code: err || "unknown", language: rec.lang });
    if (err === "aborted") return;
    if (err === "no-speech") {
      if (micOn && !micPaused && !abort) {
        els.composerMeta.textContent = "No speech detected — mic is still on.";
        startMicListen(500);
      }
      return;
    }
    if (err === "not-allowed") {
      stopMicWithMessage("Microphone permission denied. Allow mic access for this app, then click Mic to retry.");
      return;
    }
    if (err === "service-not-allowed") {
      stopMicWithMessage("Browser speech service is blocked. Check browser speech/privacy settings and network; text input is still available.");
      return;
    }
    if (err === "audio-capture") {
      stopMicWithMessage("No microphone audio device is available. Check the Windows input device, then click Mic to retry.");
      return;
    }
    if (err === "network") {
      queueMicRetry("Browser speech service network error. Check internet/browser speech availability, then click Mic to retry. Text input is still available.");
      return;
    }
    queueMicRetry(`Speech recognition failed (${err || "unknown error"}). Click Mic to retry; text input is still available.`);
  };
}
syncSpeakBtn();
syncMicBtn();
if (micOn && rec) {
  els.composerMeta.textContent = "Mic on — starting…";
  startMicListen(400);
}
armMicWatch();

els.micBtn.addEventListener("click", async () => {
  if (!rec) {
    els.composerMeta.textContent = "Mic needs Chrome or Edge with browser speech support.";
    return;
  }
  if (micOn) {
    stopMic();
    return;
  }

  const granted = await ensureMicPermission();
  if (!granted) {
    els.composerMeta.textContent = "Microphone blocked — allow mic in this site and refresh.";
    return;
  }

  micOn = true;
  micPaused = false;
  micFailStreak = 0;
  micRetryPending = false;
  localStorage.setItem("altron.mic", "1");
  syncMicBtn();
  startMicListen();
});
els.speakBtn.addEventListener("click", () => {
  speakOn = !speakOn;
  localStorage.setItem("altron.speak", speakOn ? "1" : "0");
  if (!speakOn) window.speechSynthesis?.cancel();
  syncSpeakBtn();
});

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && micOn && !micPaused && !abort) {
    startMicListen(300);
  }
});
window.addEventListener("focus", () => {
  if (micOn && !micPaused && !abort) startMicListen(300);
});

els.starters.innerHTML = STARTERS.map(
  (s) =>
    `<button class="starter" type="button" data-body="${escapeAttr(s.body)}"><b>${escapeHtml(
      s.title
    )}</b><span>${escapeHtml(s.body)}</span></button>`
).join("");

els.starters.addEventListener("click", (e) => {
  const btn = e.target.closest(".starter");
  if (!btn) return;
  els.input.value = btn.dataset.body;
  resize();
  send();
});

els.newChat.addEventListener("click", () => {
  activeId = createThread().id;
  render();
  els.input.focus();
});

els.menuBtn.addEventListener("click", () => els.app.classList.toggle("rail-open"));
els.flowsBtn?.addEventListener("click", () => {
  window.open("/flows", "_blank", "noopener,noreferrer");
});
els.forgeBtn?.addEventListener("click", () => {
  window.open("/forge", "_blank", "noopener,noreferrer");
});
els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  send();
});

window.AltronIDE?.init?.();

els.stopBtn.addEventListener("click", () => abort?.abort());
els.input.addEventListener("input", resize);
els.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    els.newChat.click();
  }
  // Hold Space (when not typing in input) = push-to-talk
  if (e.code === "Space" && !e.repeat && document.activeElement !== els.input && !e.ctrlKey && !e.metaKey && !e.altKey) {
    if (!rec) return;
    e.preventDefault();
    if (!micOn) {
      micOn = true;
      micPaused = false;
      localStorage.setItem("altron.mic", "1");
      syncMicBtn();
      startMicListen();
      els.composerMeta.textContent = "Push-to-talk — listening";
    }
  }
});
document.addEventListener("keyup", (e) => {
  if (e.code === "Space" && document.activeElement !== els.input) {
    // leave mic latched (AGI style); user clicks Mic to stop
  }
});

function hasWakeWord(text) {
  return /^(?:(?:um+|uh+)\s+)*hey\s+(?:altron|alron|ultron)\b/i.test(String(text || "").trim());
}

function stripWakeWord(text) {
  const raw = String(text || "").trim();
  return raw.replace(/^(?:(?:um+|uh+)\s+)*hey\s+(?:altron|alron|ultron)\b[\s,:-]*/i, "").trim();
}

function updateVoiceStickyModeFromAssistant(text) {
  const t = String(text || "").toLowerCase();
  if (/browser.*control|browser is listening|under altron control|under .* control/i.test(t)) {
    voiceStickyMode = "browser";
  } else if (/youtube.*control|youtube.*listening|youtub.*under/i.test(t)) {
    voiceStickyMode = "youtube";
  } else if (/whatsapp.*control|whatsapp.*listening/i.test(t)) {
    voiceStickyMode = "whatsapp";
  } else if (/ide.*control|flows.*control/i.test(t)) {
    voiceStickyMode = "desktop";
  } else {
    voiceStickyMode = "normal";
  }
  localStorage.setItem("altron.voiceStickyMode", voiceStickyMode);
}

render();
ping();
loadMemory();
loadIdentity();
loadTraces();
setInterval(ping, 15000);
setInterval(loadTraces, 15000);

async function send(opts = {}) {
  const text = els.input.value.trim();
  if (!text || abort) return;

  // Instant local clear — do not wait for NVIDIA / Think.
  if (isClearChat(text)) {
    els.input.value = "";
    resize();
    clearActiveChat();
    if (micOn) resumeMic();
    return;
  }

  // Instant mic off (voice often says "mike off")
  if (isMicOff(text)) {
    els.input.value = "";
    resize();
    stopMic();
    els.composerMeta.textContent = "Mic off";
    return;
  }

  if (await isForgeBuildRequest(text)) {
    transitionToForge(text);
    return;
  }

  const latestBuild = readLatestForgeBuild();
  if (latestBuild && isForgeExplanationRequest(text)) {
    await explainForgeProjectInChat(text, latestBuild, !!opts.fromMic);
    return;
  }

  const fromMic = !!opts.fromMic;
  const thread = getActive();
  thread.messages.push({ role: "user", content: text });
  if (thread.title === "New thread") thread.title = text.slice(0, 42);
  thread.updated = Date.now();
  els.input.value = "";
  resize();
  const assistant = { role: "assistant", content: "" };
  thread.messages.push(assistant);
  save();
  render();
  abort = new AbortController();
  els.stopBtn.hidden = false;
  els.sendBtn.disabled = true;
  if (micOn) pauseMic("Thinking");
  else els.composerMeta.textContent = "Thinking";
  try {
    const payload = {
      model: "altron",
      stream: true,
      messages: thread.messages
        .filter((m) => m.content || m.role === "user")
        .slice(0, -1)
        .concat([{ role: "user", content: text }])
        .map((m) => ({ role: m.role, content: m.content })),
    };
    const res = await fetch("/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: abort.signal,
    });
    if (!res.ok) {
      assistant.content = `ALTRON could not complete this turn (${res.status}).`;
      save();
      render();
      return;
    }
    await readSse(res, (delta, meta) => {
      if (delta) assistant.content += delta;
      if (meta?.trace) els.trace.textContent = (meta.trace || []).join(" → ");
      save();
      renderMessages();
    });
  } catch (err) {
    if (err.name !== "AbortError" && !assistant.content) {
      assistant.content = "Connection dropped. Is ALTRON running?";
    }
  } finally {
    abort = null;
    els.stopBtn.hidden = true;
    els.sendBtn.disabled = false;
    updateVoiceStickyModeFromAssistant(assistant.content);
    save();
    render();
    loadMemory();
    loadIdentity();
    loadTraces();
    const afterReply = () => {
      if (micOn) resumeMic();
      else els.composerMeta.textContent = "Ready";
    };
    if (speakOn && assistant.content) speakReply(assistant.content, afterReply);
    else afterReply();
    void fromMic;
  }
}

function transitionToForge(command) {
  const handoffId = (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`);
  const handoff = { id: handoffId, command: String(command), createdAt: Date.now() };
  let handoffStored = false;
  try {
    sessionStorage.setItem("altron.forge.handoff", JSON.stringify(handoff));
    handoffStored = true;
  } catch {
    /* Query fallback is only for browsers that disable sessionStorage. */
  }
  const overlay = document.getElementById("forgeTransition");
  if (!overlay) {
    const state = handoffStored ? `handoff=${encodeURIComponent(handoffId)}` : `command=${encodeURIComponent(command)}`;
    window.location.assign(`/forge?${state}&fromChat=1`);
    return;
  }
  const title = document.getElementById("forgeTransitionTitle");
  const stage = document.getElementById("forgeTransitionStage");
  title.textContent = "BUILD REQUEST DETECTED";
  overlay.classList.add("active");
  overlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("forge-transitioning");
  window.setTimeout(() => { stage.textContent = "INITIALIZING FORGE"; }, 320);
  window.setTimeout(() => {
    const state = handoffStored ? `handoff=${encodeURIComponent(handoffId)}` : `command=${encodeURIComponent(command)}`;
    window.location.assign(`/forge?${state}&fromChat=1`);
  }, 900);
}

function readLatestForgeBuild() {
  try {
    const value = JSON.parse(localStorage.getItem("altron.forge.latest") || "null");
    return value && typeof value.project_dir === "string" && Array.isArray(value.files) ? value : null;
  } catch {
    return null;
  }
}

function isForgeExplanationRequest(text) {
  return /\b(explain|describe)\b.*\b(project|created|built|this|it)\b|\bwhat did you (create|build)\b|\bhow does this work\b/i.test(String(text || ""));
}

async function explainForgeProjectInChat(text, project, fromMic) {
  const thread = getActive();
  thread.messages.push({ role: "user", content: text });
  if (thread.title === "New thread") thread.title = text.slice(0, 42);
  thread.updated = Date.now();
  const assistant = { role: "assistant", content: "" };
  thread.messages.push(assistant);
  save();
  render();
  abort = new AbortController();
  els.stopBtn.hidden = false;
  els.sendBtn.disabled = true;
  if (micOn) pauseMic("Reading project");
  else els.composerMeta.textContent = "Reading project files";
  try {
    const response = await fetch("/api/forge/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, project_dir: project.project_dir }),
      signal: abort.signal,
    });
    const result = await response.json();
    assistant.content = response.ok && result.ok
      ? result.reply || "ALTRON returned no project explanation."
      : result.error || `ALTRON could not read the project (${response.status}).`;
  } catch (error) {
    if (error.name !== "AbortError") assistant.content = "Project explanation failed. Is ALTRON running?";
  } finally {
    abort = null;
    els.stopBtn.hidden = true;
    els.sendBtn.disabled = false;
    updateVoiceStickyModeFromAssistant(assistant.content);
    save();
    render();
    loadMemory();
    loadIdentity();
    loadTraces();
    const afterReply = () => {
      if (micOn) resumeMic();
      else els.composerMeta.textContent = "Ready";
    };
    if (speakOn && assistant.content) speakReply(assistant.content, afterReply);
    else afterReply();
  }
}

function isForgeBuildRequest(text) {
  return fetch("/api/forge/intent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command: String(text || "") }),
  })
    .then((response) => response.ok ? response.json() : null)
    .then((result) => result?.build === true)
    .catch(() => false);
}

function isClearChat(text) {
  const t = String(text || "")
    .toLowerCase()
    .replace(/[.!?]+$/g, "")
    .trim();
  return (
    /^(clear|clear chat|clear the chat|clear conversation|reset chat|wipe chat)$/.test(t) ||
    t.includes("clear the chat") ||
    t.includes("clear chat") ||
    t.includes("chat clear")
  );
}

function isMicOff(text) {
  const t = String(text || "")
    .toLowerCase()
    .replace(/[.!?]+$/g, "")
    .trim();
  return /^(mic|mike|microphone)\s*off$/.test(t) || t === "stop listening" || t === "stop mic";
}

function clearActiveChat() {
  const thread = getActive();
  if (!thread) return;
  thread.messages = [];
  thread.title = "New thread";
  thread.updated = Date.now();
  voiceStickyMode = "normal";
  localStorage.setItem("altron.voiceStickyMode", "normal");
  save();
  render();
  els.composerMeta.textContent = "Chat cleared";
  els.trace.textContent = "ready";
}

async function readSse(res, onEvent) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() || "";
    for (const block of parts) {
      const dataLines = block
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trim());
      const data = dataLines.join("\n");
      if (!data || data === "[DONE]") continue;
      try {
        const json = JSON.parse(data);
        if (json.type === "altron.meta" || json.type === "altron.done") {
          onEvent("", json);
          continue;
        }
        const token = json.choices?.[0]?.delta?.content;
        if (token) onEvent(token, null);
      } catch {
        /* ignore keepalives */
      }
    }
  }
}

async function ping() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    els.statusDot.className = "dot " + (data.think || data.ollama ? "ok" : "bad");
    els.statusText.textContent = data.think ? "Think live" : data.ollama ? "Ollama live" : "Local fallback";
    const tools = Array.isArray(data.tools) ? data.tools.length : 0;
    els.coreKv.innerHTML = `
      <dt>Name</dt><dd>${escapeHtml(data.name)}</dd>
      <dt>Model</dt><dd title="${escapeAttr(data.model)}">${escapeHtml(data.model)}</dd>
      <dt>Ollama</dt><dd>${data.ollama ? "up" : "down"}</dd>
      <dt>Memory</dt><dd>${escapeHtml(data.memory || "jsonl")}</dd>
      <dt>Voice</dt><dd>${escapeHtml(data.voice || "browser")}</dd>
      <dt>Tools</dt><dd>${tools} allowlisted</dd>
      <dt>IDE</dt><dd>${data.ide?.engine || "altron-monaco"}</dd>
      <dt>Ver</dt><dd>${escapeHtml(data.version)}</dd>`;
  } catch {
    els.statusDot.className = "dot bad";
    els.statusText.textContent = "Core down";
  }
}

async function loadIdentity() {
  try {
    const res = await fetch("/api/identity");
    const data = await res.json();
    const lines = [
      ...(data.workspace || []).map((t) => `<div class="item"><b>WS</b> ${escapeHtml(t)}</div>`),
      ...(data.human || []).map((t) => `<div class="item"><b>YOU</b> ${escapeHtml(t)}</div>`),
    ];
    els.identity.innerHTML = lines.length
      ? lines.join("")
      : `<div class="item">Empty. Say “remember that …”.</div>`;
  } catch {
    els.identity.textContent = "Identity unavailable";
  }
}

async function loadMemory() {
  try {
    const res = await fetch("/api/memory");
    const data = await res.json();
    const items = data.items || [];
    els.mem.innerHTML = items.length
      ? items
          .map((it) => `<div class="item">${escapeHtml(it.text || "")}</div>`)
          .join("")
      : `<div class="item">Empty. Say “remember that …”.</div>`;
  } catch {
    els.mem.textContent = "Memory unavailable";
  }
}

async function loadTraces() {
  try {
    const res = await fetch("/api/traces");
    const data = await res.json();
    const items = data.items || [];
    els.traces.innerHTML = items.length
      ? items
          .slice(0, 8)
          .map(
            (it) =>
              `<div class="item"><b>${escapeHtml(it.judgment || "ok")}</b> ${escapeHtml(
                it.backend || ""
              )} · ${escapeHtml((it.user || "").slice(0, 48))}</div>`
          )
          .join("")
      : `<div class="item">No traces yet.</div>`;
  } catch {
    els.traces.textContent = "Traces unavailable";
  }
}

function speakReply(text, onDone) {
  if (!window.speechSynthesis) {
    onDone?.();
    return;
  }
  window.speechSynthesis.cancel();
  const clean = String(text || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/[#*_`]/g, "")
    .slice(0, 600);
  if (!clean.trim()) {
    onDone?.();
    return;
  }
  if (micOn) pauseMic("Speaking");
  const u = new SpeechSynthesisUtterance(clean);
  u.rate = 1.02;
  u.lang = "en-IN";
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    // Brief gap so TTS echo is not captured as the next command.
    setTimeout(() => onDone?.(), 150);
  };
  u.onend = finish;
  u.onerror = finish;
  window.speechSynthesis.speak(u);
  // Some browsers skip onend; keep conversation alive.
  setTimeout(finish, Math.min(20000, 1200 + clean.length * 55));
}

async function ensureMicPermission() {
  console.info("[ALTRON voice] microphone initialization requested");
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    els.composerMeta.textContent = "This browser does not expose microphone access. Use Chrome or Edge.";
    return false;
  }

  try {
    // Echo cancellation + noise suppression cut down false wake-word triggers from TTS/speakers.
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });
    stream.getTracks().forEach((track) => track.stop());
    return true;
  } catch (err) {
    console.warn("[ALTRON voice] microphone initialization failed", { name: err?.name || "unknown" });
    els.composerMeta.textContent = "Microphone denied. Allow access in the browser and refresh the page.";
    return false;
  }
}

function startMicListen(delayMs = 0) {
  if (!rec || !micOn || micPaused || abort) return;
  clearTimeout(micKickTimer);
  const kick = () => {
    micRetryPending = false;
    if (!rec || !micOn || micPaused || abort) return;
    if (recognizing) return;
    try {
      rec.start();
      recognizing = true;
      els.micBtn.classList.add("live");
      els.composerMeta.textContent = "Starting browser speech recognition…";
    } catch (error) {
      console.warn("[ALTRON voice] recognition start failed", { name: error?.name || "unknown" });
      recognizing = false;
      queueMicRetry("Could not start browser speech recognition. Click Mic to retry; text input is still available.");
    }
  };
  if (delayMs) {
    micRetryPending = true;
    micKickTimer = setTimeout(kick, delayMs);
  }
  else kick();
}

function queueMicRetry(message) {
  if (!micOn || micPaused || abort) return;
  micFailStreak += 1;
  console.warn("[ALTRON voice] scheduling recognition retry", {
    attempt: micFailStreak,
    maxAttempts: MIC_RETRY_LIMIT - 1,
  });
  if (micFailStreak >= MIC_RETRY_LIMIT) {
    console.error("[ALTRON voice] speech service unavailable after bounded retries");
    stopMicWithMessage(message);
    return;
  }
  els.composerMeta.textContent = `Speech service unavailable. Retrying ${micFailStreak}/${MIC_RETRY_LIMIT - 1}…`;
  startMicListen(Math.min(4000, 500 * (2 ** (micFailStreak - 1))));
}

function stopMicWithMessage(message) {
  console.error("[ALTRON voice] microphone stopped after unrecoverable error", { message });
  micOn = false;
  micPaused = false;
  recognizing = false;
  wakeListeningUntil = 0;
  micRetryPending = false;
  micFinalBuf = "";
  localStorage.setItem("altron.mic", "0");
  clearTimeout(micKickTimer);
  clearTimeout(micFinalTimer);
  if (rec) {
    try {
      rec.abort();
    } catch {
      /* ignore an already-stopped recognizer */
    }
  }
  syncMicBtn();
  els.composerMeta.textContent = message;
}

function pauseMic(label) {
  micPaused = true;
  clearTimeout(micKickTimer);
  clearTimeout(micFinalTimer);
  micFinalBuf = "";
  if (rec) {
    try {
      rec.stop();
    } catch {
      /* ignore */
    }
  }
  recognizing = false;
  if (label) els.composerMeta.textContent = label;
}

function resumeMic() {
  if (!micOn) {
    micPaused = false;
    els.composerMeta.textContent = "Ready";
    return;
  }
  micPaused = false;
  syncMicBtn();
  startMicListen(400);
}

function stopMic() {
  micOn = false;
  micPaused = false;
  micFailStreak = 0;
  wakeListeningUntil = 0;
  micRetryPending = false;
  micFinalBuf = "";
  localStorage.setItem("altron.mic", "0");
  clearTimeout(micKickTimer);
  clearTimeout(micFinalTimer);
  if (rec) {
    try {
      rec.abort();
    } catch {
      try {
        rec.stop();
      } catch {
        /* ignore */
      }
    }
  }
  recognizing = false;
  syncMicBtn();
  els.composerMeta.textContent = "Ready";
}

function armMicWatch() {
  clearInterval(micWatchTimer);
  micWatchTimer = setInterval(() => {
    if (!micOn || micPaused || abort || !rec) return;
    if (document.visibilityState !== "visible") return;
    if (!recognizing) {
      els.composerMeta.textContent = "Mic reconnecting…";
      startMicListen(0);
    }
  }, 4000);
}

function syncSpeakBtn() {
  els.speakBtn.classList.toggle("on", speakOn);
}

function syncMicBtn() {
  els.micBtn.classList.toggle("live", micOn);
  els.micBtn.title = micOn ? "Mic on — click to stop" : "Speak to ALTRON (stays on until you stop)";
  els.micBtn.textContent = micOn ? "Mic · ON" : "Mic";
}

function render() {
  renderThreads();
  renderMessages();
  const thread = getActive();
  els.topTitle.textContent = thread?.title || "New thread";
}

function renderThreads() {
  els.threads.innerHTML = threads
    .map((t) => {
      const cls = t.id === activeId ? "thread active" : "thread";
      return `<button class="${cls}" data-id="${t.id}" type="button"><div class="t">${escapeHtml(
        t.title
      )}</div><div class="d">${timeAgo(t.updated)}</div></button>`;
    })
    .join("");
  els.threads.querySelectorAll(".thread").forEach((btn) => {
    btn.onclick = () => {
      activeId = btn.dataset.id;
      els.app.classList.remove("rail-open");
      render();
    };
  });
}

function renderMessages() {
  const thread = getActive();
  const msgs = thread?.messages || [];
  const has = msgs.length > 0;
  els.empty.hidden = has;
  els.log.hidden = !has;
  if (!has) return;
  els.log.innerHTML = msgs
    .map((m) => {
      const who = m.role === "assistant" ? "ALTRON" : "You";
      const whoCls = m.role === "assistant" ? "who altron" : "who";
      return `<article class="msg"><div class="${whoCls}">${who}</div><div class="body">${renderMd(
        m.content || ""
      )}</div></article>`;
    })
    .join("");
  els.log.parentElement.scrollTop = els.log.parentElement.scrollHeight;
}

function getActive() {
  return threads.find((t) => t.id === activeId);
}

function createThread() {
  const t = { id: crypto.randomUUID(), title: "New thread", updated: Date.now(), messages: [] };
  threads.unshift(t);
  save();
  return t;
}

function loadThreads() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE) || "[]");
    if (Array.isArray(raw) && raw.length) return raw;
  } catch {
    /* ignore */
  }
  return [];
}

function save() {
  localStorage.setItem(STORE, JSON.stringify(threads.slice(0, 40)));
}

function resize() {
  els.input.style.height = "auto";
  els.input.style.height = Math.min(els.input.scrollHeight, 180) + "px";
}

function timeAgo(ts) {
  const s = Math.max(1, Math.floor((Date.now() - ts) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(s) {
  return escapeHtml(s).replaceAll("\n", " ");
}

function renderMd(src) {
  const escaped = escapeHtml(src);
  const withCode = escaped.replace(/```([\s\S]*?)```/g, (_, code) => `<pre><code>${code}</code></pre>`);
  const inline = withCode
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");
  return inline
    .split(/\n{2,}/)
    .map((p) => `<p>${p.replaceAll("\n", "<br>")}</p>`)
    .join("");
}
