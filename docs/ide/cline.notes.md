# Cline → ALTRON brain

In VS Code / code-server / Cursor:

1. Install extension: Cline
2. API Provider: **OpenAI Compatible**
3. Base URL: `http://127.0.0.1:8088/v1`
4. API Key: `altron` (any non-empty)
5. Model ID: `altron`

SDK shape:

```ts
{
  providerId: "openai-compatible",
  modelId: "altron",
  apiKey: "altron",
  baseUrl: "http://127.0.0.1:8088/v1"
}
```

ALTRON must be running: `python -m altron serve`

Voice/type sticky (no extension needed):
- `open ide` → list / open / edit / run / close ide
