from __future__ import annotations

"""ALTRON Flows node catalog — categorized, versioned definitions.

implemented=True  → real executor exists and is usable in Run
implemented=False → NOT IMPLEMENTED (config may be stored; Run fails clearly)
"""

NODE_CATALOG: list[dict] = [
    # TRIGGERS
    {
        "type": "trigger.manual",
        "category": "TRIGGERS",
        "kind": "trigger",
        "label": "Manual Trigger",
        "desc": "Start flow from Run button",
        "icon": "▶",
        "implemented": True,
        "fields": [{"key": "note", "label": "Note", "placeholder": "Optional note"}],
        "outputs": ["trigger.source", "trigger.at"],
    },
    {
        "type": "trigger.schedule",
        "category": "TRIGGERS",
        "kind": "trigger",
        "label": "Schedule",
        "desc": "Cron schedule (5-field) — fired by ALTRON flows runtime",
        "icon": "⏱",
        "implemented": True,
        "fields": [{"key": "cron", "label": "Cron", "placeholder": "*/5 * * * *"}],
    },
    {
        "type": "trigger.file_created",
        "category": "TRIGGERS",
        "kind": "trigger",
        "label": "File Created",
        "desc": "Watch a Trusted Root folder for new files",
        "icon": "📄",
        "implemented": True,
        "fields": [{"key": "path", "label": "Folder (trusted)"}],
    },
    {
        "type": "trigger.webhook",
        "category": "TRIGGERS",
        "kind": "trigger",
        "label": "Webhook",
        "desc": "HTTP POST /api/flows/hooks/{slug} starts this flow",
        "icon": "🔗",
        "implemented": True,
        "fields": [{"key": "path", "label": "Webhook path", "placeholder": "my-flow"}],
    },
    {
        "type": "trigger.app_started",
        "category": "TRIGGERS",
        "kind": "trigger",
        "label": "App Started",
        "desc": "Runs once when ALTRON server starts",
        "icon": "⚡",
        "implemented": True,
        "fields": [],
    },
    # AI
    {
        "type": "ai.agent",
        "category": "AI",
        "kind": "ai",
        "label": "AI Agent",
        "desc": "ALTRON Think — analyze / extract / reason",
        "icon": "🤖",
        "accent": "ai",
        "implemented": True,
        "fields": [
            {"key": "prompt", "label": "Prompt", "type": "textarea", "placeholder": "Analyze the input and return key facts."},
            {"key": "input_var", "label": "Input (template or text)", "placeholder": "{{nodes.n2.message}} or leave blank for previous output"},
            {"key": "output_var", "label": "Output variable", "placeholder": "ai.result"},
        ],
        "outputs": ["ai.result", "text"],
    },
    {
        "type": "ai.summarize",
        "category": "AI",
        "kind": "ai",
        "label": "Summarize",
        "desc": "Short summary via ALTRON Think",
        "icon": "📝",
        "accent": "ai",
        "implemented": True,
        "fields": [
            {"key": "input_var", "label": "Input (template)", "placeholder": "leave blank = previous output"},
            {"key": "output_var", "label": "Output var", "placeholder": "ai.summary"},
        ],
        "outputs": ["ai.summary", "text"],
    },
    {
        "type": "ai.classify",
        "category": "AI",
        "kind": "ai",
        "label": "Classify",
        "desc": "Classify into labels via ALTRON Think",
        "icon": "🏷",
        "accent": "ai",
        "implemented": True,
        "fields": [
            {"key": "input_var", "label": "Input (template)", "placeholder": "leave blank = previous output"},
            {"key": "labels", "label": "Labels (comma)", "placeholder": "pdf,image,other"},
            {"key": "output_var", "label": "Output var", "placeholder": "ai.label"},
        ],
        "outputs": ["ai.label", "text"],
    },
    # LOGIC
    {
        "type": "logic.if",
        "category": "LOGIC",
        "kind": "logic",
        "label": "If / Else",
        "desc": "Branch YES/NO on condition",
        "icon": "⑂",
        "implemented": True,
        "fields": [
            {
                "key": "condition",
                "label": "Condition",
                "placeholder": "count > 0  |  {{variables.filter.count}} > 0  |  contains .pdf",
            }
        ],
        "outputs": ["branch", "result"],
    },
    {
        "type": "logic.filter",
        "category": "LOGIC",
        "kind": "logic",
        "label": "Filter",
        "desc": "Filter previous file list by name pattern",
        "icon": "▾",
        "implemented": True,
        "fields": [{"key": "pattern", "label": "Pattern", "placeholder": ".pdf or report"}],
        "outputs": ["files", "count"],
    },
    {
        "type": "logic.delay",
        "category": "LOGIC",
        "kind": "logic",
        "label": "Delay",
        "desc": "Wait N seconds (max 30)",
        "icon": "⏳",
        "implemented": True,
        "fields": [{"key": "seconds", "label": "Seconds", "placeholder": "1"}],
        "outputs": ["seconds"],
    },
    {
        "type": "logic.foreach",
        "category": "LOGIC",
        "kind": "logic",
        "label": "For Each",
        "desc": "Iterate files from previous List/Filter",
        "icon": "↻",
        "implemented": True,
        "fields": [
            {"key": "source", "label": "Source", "placeholder": "files (default = last listing)"},
            {"key": "max", "label": "Max items", "placeholder": "20"},
        ],
        "outputs": ["item", "index", "total", "results"],
    },
    {
        "type": "logic.log",
        "category": "LOGIC",
        "kind": "logic",
        "label": "Log",
        "desc": "Write message / previous output to execution log",
        "icon": "📜",
        "implemented": True,
        "fields": [
            {
                "key": "message",
                "label": "Message (blank = previous output)",
                "type": "textarea",
                "placeholder": "{{nodes.n2.message}}",
            }
        ],
        "outputs": ["logged"],
    },
    # FILES
    {
        "type": "files.list",
        "category": "FILES",
        "kind": "files",
        "label": "List Folder",
        "desc": "List trusted-root folder",
        "icon": "📁",
        "implemented": True,
        "fields": [
            {"key": "path", "label": "Folder path"},
            {"key": "recursive", "label": "Recursive (true/false)", "placeholder": "false"},
            {"key": "pattern", "label": "Name filter", "placeholder": "*.pdf"},
        ],
        "outputs": ["folder", "files", "entries", "count", "file_count"],
    },
    {
        "type": "files.read",
        "category": "FILES",
        "kind": "files",
        "label": "Read File",
        "desc": "Read text or PDF (safe extract) inside trusted root",
        "icon": "📖",
        "implemented": True,
        "fields": [{"key": "path", "label": "File path"}],
        "outputs": ["path", "name", "text", "extension", "pages"],
    },
    {
        "type": "files.write",
        "category": "FILES",
        "kind": "files",
        "label": "Write File",
        "desc": "Write text inside trusted root",
        "icon": "✎",
        "implemented": True,
        "fields": [
            {"key": "path", "label": "File path"},
            {"key": "content", "label": "Content", "type": "textarea"},
        ],
        "outputs": ["path", "bytes"],
    },
    {
        "type": "files.copy",
        "category": "FILES",
        "kind": "files",
        "label": "Copy File",
        "desc": "Copy within trusted roots",
        "icon": "⧉",
        "implemented": True,
        "fields": [{"key": "src", "label": "Source file"}, {"key": "dst_dir", "label": "Destination folder"}],
        "outputs": ["path", "file"],
    },
    {
        "type": "files.move",
        "category": "FILES",
        "kind": "files",
        "label": "Move File",
        "desc": "Move within trusted roots",
        "icon": "⇢",
        "implemented": True,
        "fields": [{"key": "src", "label": "Source file"}, {"key": "dst_dir", "label": "Destination folder"}],
        "outputs": ["path", "file"],
    },
    {
        "type": "files.rename",
        "category": "FILES",
        "kind": "files",
        "label": "Rename File",
        "desc": "Rename a file inside trusted roots (no path escape)",
        "icon": "Aa",
        "implemented": True,
        "fields": [
            {"key": "src", "label": "Source file", "placeholder": "{{item.path}}"},
            {"key": "new_name", "label": "New filename", "placeholder": "{{variables.ai.result.suggested_name}}"},
        ],
        "outputs": ["path", "file", "name"],
    },
    # Secondary usable nodes (already wired)
    {
        "type": "apps.open_app",
        "category": "APPS",
        "kind": "apps",
        "label": "Open App",
        "desc": "Open allowlisted app",
        "icon": "▣",
        "implemented": True,
        "fields": [{"key": "app", "label": "App name", "placeholder": "notepad"}],
    },
    {
        "type": "apps.open_path",
        "category": "APPS",
        "kind": "apps",
        "label": "Open Path",
        "desc": "Open trusted path in Explorer",
        "icon": "📂",
        "implemented": True,
        "fields": [{"key": "path", "label": "Path"}],
    },
    {
        "type": "browser.open_url",
        "category": "BROWSER",
        "kind": "browser",
        "label": "Open URL",
        "desc": "Open URL in browser",
        "icon": "🌐",
        "implemented": True,
        "fields": [{"key": "url", "label": "URL"}],
    },
    {
        "type": "data.transform",
        "category": "DATA",
        "kind": "data",
        "label": "Transform",
        "desc": "Set variable from template",
        "icon": "⚙",
        "implemented": True,
        "fields": [{"key": "name", "label": "Variable name"}, {"key": "template", "label": "Template"}],
    },
    {
        "type": "notify.log",
        "category": "NOTIFICATIONS",
        "kind": "notify",
        "label": "Log Message",
        "desc": "Alias of Log node",
        "icon": "💬",
        "implemented": True,
        "fields": [{"key": "message", "label": "Message", "type": "textarea"}],
    },
    # SERVICES
    {
        "type": "service.http_request",
        "category": "SERVICES",
        "kind": "service",
        "label": "HTTP Request",
        "desc": "Call a public HTTP(s) API (GET/POST/PUT/DELETE)",
        "icon": "🌐",
        "implemented": True,
        "fields": [
            {"key": "method", "label": "Method", "placeholder": "GET"},
            {"key": "url", "label": "URL", "placeholder": "https://api.example.com/x"},
            {"key": "headers", "label": "Headers (JSON)", "type": "textarea", "placeholder": '{"Authorization": "Bearer ..."}'},
            {"key": "body", "label": "Body (JSON or text)", "type": "textarea"},
        ],
        "outputs": ["status", "json", "text"],
    },
    {
        "type": "service.email_send",
        "category": "SERVICES",
        "kind": "service",
        "label": "Send Email (SMTP)",
        "desc": "Send email via configured SMTP server",
        "icon": "✉",
        "implemented": True,
        "fields": [
            {"key": "to", "label": "To", "placeholder": "someone@example.com"},
            {"key": "subject", "label": "Subject"},
            {"key": "body", "label": "Body", "type": "textarea"},
        ],
        "outputs": ["sent", "to"],
    },
    {
        "type": "service.slack_message",
        "category": "SERVICES",
        "kind": "service",
        "label": "Slack Message",
        "desc": "Post a message via a Slack Incoming Webhook URL",
        "icon": "💬",
        "implemented": True,
        "fields": [
            {"key": "webhook_url", "label": "Webhook URL", "placeholder": "https://hooks.slack.com/services/..."},
            {"key": "message", "label": "Message", "type": "textarea"},
        ],
        "outputs": ["sent", "status"],
    },
    {
        "type": "data.database_query",
        "category": "DATA",
        "kind": "data",
        "label": "Database Query",
        "desc": "Run a read/write SQL statement against a local SQLite file (trusted root)",
        "icon": "🗄",
        "implemented": True,
        "fields": [
            {"key": "db_path", "label": "SQLite file path (trusted root)"},
            {"key": "sql", "label": "SQL", "type": "textarea", "placeholder": "SELECT * FROM table LIMIT 20"},
            {"key": "params", "label": "Params (JSON array, optional)", "placeholder": '["a", 1]'},
        ],
        "outputs": ["rows", "row_count", "rowcount"],
    },
]

TYPE_ALIASES = {
    "action.list_folder": "files.list",
    "action.copy_file": "files.copy",
    "action.move_file": "files.move",
    "action.open_path": "apps.open_path",
    "action.open_url": "browser.open_url",
    "action.open_app": "apps.open_app",
    "action.log": "logic.log",
}

NOT_IMPLEMENTED: set[str] = set()  # Phase-1 triggers are live via flows_runtime


def catalog() -> list[dict]:
    return NODE_CATALOG


def catalog_by_category() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for n in NODE_CATALOG:
        cat = n.get("category") or "OTHER"
        out.setdefault(cat, []).append(n)
    return out


def meta_for(ntype: str) -> dict | None:
    ntype = TYPE_ALIASES.get(ntype, ntype)
    for n in NODE_CATALOG:
        if n["type"] == ntype:
            return n
    return None


def is_implemented(ntype: str) -> bool:
    ntype = TYPE_ALIASES.get(ntype, ntype)
    if ntype in NOT_IMPLEMENTED:
        return False
    meta = meta_for(ntype)
    if meta is None:
        return False
    return bool(meta.get("implemented", True))
