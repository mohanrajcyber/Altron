# Reference harvest map

ALTRON is original code. Donor Git trees stay outside this folder.
We harvest features, scripts, options, and properties only.

| Layer | Donor (local path under Desktop/AGI) | What we took | Where it landed |
|---|---|---|---|
| Think | CUSOR RECOMMEND PROJETS/litellm-litellm_internal_staging | NVIDIA NIM is OpenAI-compatible; NVIDIA_NIM_API_KEY; api_base integrate.api.nvidia.com/v1 | altron/adapters/think.py, harvest/options.yaml |
| Think failover | MY OLD & MY FAV PROJECTS ZIP & UNZIP/quantum-free-router-main | Key rotation, timeout 90s, nvidia-nim model catalog, fallback yaml | harvest/fallbacks.yaml, altron/settings.py |
| Brain | CUSOR RECOMMEND PROJETS/langgraph-main | StateGraph: START -> nodes -> END, typed state, durable loop | altron/graph.py |
| Brain loop | MY OLD & MY FAV PROJECTS ZIP & UNZIP/AutoGPT-master | Goal -> plan -> execute -> report | altron/graph.py plan/think/act |
| Types | CUSOR RECOMMEND PROJETS/pydantic-ai-main | Pydantic models for settings, tools, chat payload | altron/settings.py, altron/state.py |
| Memory | CUSOR RECOMMEND PROJETS/letta-code-main | Memory blocks, identity that survives sessions | altron/identity.py, adapters/memory.py |
| Memory vectors | CUSOR RECOMMEND PROJETS/mem0-main + qdrant | Mem0-shaped add/search + optional Qdrant HTTP | adapters/vector_memory.py |
| Act browser | CUSOR RECOMMEND PROJETS/browser-use-main | Playwright click/type + public URL allowlist | adapters/browser_agent.py |
| Act sandbox | CUSOR RECOMMEND PROJETS/E2B-main | Cloud sandbox when E2B_API_KEY set | adapters/e2b_cloud.py |
| Act jobs | CUSOR RECOMMEND PROJETS/n8n-master | Webhook enqueue + local queue | adapters/n8n_live.py |
| Graph | CUSOR RECOMMEND PROJETS/graphiti-main | Entity/relation JSON graph | adapters/graphiti_local.py |
| Generate | CUSOR RECOMMEND PROJETS/ComfyUI* (if present) | Local ComfyUI probe/prompt | adapters/comfy.py |
| Compile | CUSOR RECOMMEND PROJETS/dspy-main | Failures → prompt constraints | adapters/dspy_compile.py |
| Face | CUSOR RECOMMEND PROJETS/open-webui-main | OpenAI /v1/chat/completions + /v1/models | altron/server.py |
| Voice | CUSOR RECOMMEND PROJETS/agents-main | LiveKit agent LLM points at same /v1 | altron/voice.py + web mic |
| Judge | MY OLD & MY FAV PROJECTS ZIP & UNZIP/future-agi-main | Trace JSONL per turn | altron/adapters/traces.py, judge.py |
| Judge compile | CUSOR RECOMMEND PROJETS/dspy-main | Failures become prompt constraints | traces.compile_hints |
| Local Think | CUSOR RECOMMEND PROJETS/pydantic-ai-main + ollama | OLLAMA_BASE_URL http://127.0.0.1:11434/v1 | altron/adapters/ollama.py, think.py |
| Act | CUSOR RECOMMEND PROJETS/servers-main | filesystem allowlist, git status/log, fetch http(s) | altron/adapters/workspace.py, mcp_fs.py, mcp_git.py, mcp_fetch.py |
| Act | CUSOR RECOMMEND PROJETS/browser-use-main | public URL / no localhost / no private IP | altron/adapters/mcp_fetch.py |
| Act | CUSOR RECOMMEND PROJETS/E2B-main | isolated cwd, timeout, stdout cap | altron/adapters/sandbox.py |
| Act | CUSOR RECOMMEND PROJETS/OpenHands-main | write then run in a workspace | fs_write/code_write + code_run |
| Act | CUSOR RECOMMEND PROJETS/n8n-master | enqueue / list long jobs + webhook | altron/adapters/jobs.py, /api/jobs |
| Ignore | letta-main (landing page), SuperAGI (duplicates AutoGPT) | — | — |
