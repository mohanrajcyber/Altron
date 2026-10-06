from __future__ import annotations

"""Safe expression evaluator for ALTRON FLOWS — no arbitrary eval()."""

import ast
import operator
import re
from typing import Any


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}
_CMPOPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}
_UNARY = {
    ast.Not: operator.not_,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _lookup(ctx: dict, path: str) -> Any:
    parts = [p for p in path.replace("$", "").split(".") if p]
    cur: Any = ctx
    for p in parts:
        if isinstance(cur, dict):
            lower = {str(k).lower(): k for k in cur.keys()}
            if p in cur:
                cur = cur[p]
            elif p.lower() in lower:
                cur = cur[lower[p.lower()]]
            else:
                return None
        elif isinstance(cur, list) and p.isdigit():
            i = int(p)
            cur = cur[i] if 0 <= i < len(cur) else None
        else:
            return None
    return cur


def _resolve_templates(expr: str, ctx: dict) -> str:
    def repl(m: re.Match) -> str:
        val = _lookup(ctx, m.group(1).strip())
        if val is None:
            return "None"
        if isinstance(val, bool):
            return "True" if val else "False"
        if isinstance(val, (int, float)):
            return str(val)
        if isinstance(val, str):
            return repr(val)
        if isinstance(val, list):
            return f"__LEN_{len(val)}__"
        return repr(str(val))

    return re.sub(r"\{\{([^}]+)\}\}", repl, expr)


def _len_rewrite(expr: str, ctx: dict) -> str:
    # files.length / {{nodes.x.output.files}}.length style already handled via templates;
    # also support bare: count, filter.count via ctx variables
    expr = re.sub(r"\bfiles\.length\b", str(len(ctx.get("last_listing") or [])), expr, flags=re.I)
    expr = re.sub(r"\bfile\.extension\b", repr(str((ctx.get("file") or {}).get("extension") or "")), expr, flags=re.I)
    expr = re.sub(r"\bfile\.name\b", repr(str((ctx.get("file") or {}).get("name") or "")), expr, flags=re.I)
    vals = ctx.get("variables") or {}
    # pdf_count alias → prefer filter.file_count then list.file_count
    if re.search(r"\bpdf[_\s]?count\b", expr, re.I):
        pdf_n = int(vals.get("filter.file_count", vals.get("list.file_count", vals.get("filter.count", 0))) or 0)
        expr = re.sub(r"\bpdf[_\s]?count\b", str(pdf_n), expr, flags=re.I)
    for key in ("filter.count", "filter.file_count", "list.count", "list.file_count", "count"):
        if key in expr:
            expr = expr.replace(key, str(int(vals.get(key, vals.get("list.count", 0)) or 0)))
    expr = re.sub(r"__LEN_(\d+)__", r"\1", expr)
    return expr


class _SafeEval(ast.NodeVisitor):
    def __init__(self, ctx: dict):
        self.ctx = ctx

    def visit(self, node):  # type: ignore[override]
        if isinstance(node, ast.Expression):
            return self.visit(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in {"True", "False", "None"}:
                return {"True": True, "False": False, "None": None}[node.id]
            # allow simple names from variables
            vals = self.ctx.get("variables") or {}
            if node.id in vals:
                return vals[node.id]
            if node.id == "count":
                return int(vals.get("filter.count", vals.get("list.count", 0)) or 0)
            raise ValueError(f"Unknown name: {node.id}")
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](self.visit(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](self.visit(node.left), self.visit(node.right))
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(self.visit(v) for v in node.values)
            if isinstance(node.op, ast.Or):
                return any(self.visit(v) for v in node.values)
        if isinstance(node, ast.Compare):
            left = self.visit(node.left)
            for op, comp in zip(node.ops, node.comparators):
                right = self.visit(comp)
                fn = _CMPOPS.get(type(op))
                if fn is None:
                    raise ValueError("Unsupported comparison")
                if not fn(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.List):
            return [self.visit(e) for e in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self.visit(e) for e in node.elts)
        raise ValueError(f"Unsafe or unsupported expression node: {type(node).__name__}")


def evaluate(expr: str, ctx: dict | None = None) -> Any:
    """Evaluate a controlled expression. Returns Python value (often bool)."""
    ctx = ctx or {}
    text = (expr or "").strip()
    if not text:
        return False
    # shorthand truthy
    low = text.lower()
    if low in {"true", "yes", "1"}:
        return True
    if low in {"false", "no", "0"}:
        return False

    text = _resolve_templates(text, ctx)
    text = _len_rewrite(text, ctx)

    # normalize common ALTRON sugar
    text = text.replace("&&", " and ").replace("||", " or ")

    # inject AI fields as bare names for conditions
    vals = ctx.get("variables") or {}
    ai = vals.get("ai.result")
    if isinstance(ai, dict):
        for k in ("category", "confidence", "classification", "summary", "suggested_name"):
            if k in ai and k not in text.split():
                pass
        # replace bare identifiers carefully via rewrite helpers below

    # startsWith / endsWith / contains as function-like sugar
    def _str_side(s: str) -> str:
        return s.strip().strip("'\"")

    m = re.match(r"^(.+?)\s+startswith\s+(.+)$", text, re.I)
    if m:
        left = _lookup_str(ctx, m.group(1).strip())
        return left.lower().startswith(_str_side(m.group(2)).lower())
    m = re.match(r"^(.+?)\s+endswith\s+(.+)$", text, re.I)
    if m:
        left = _lookup_str(ctx, m.group(1).strip())
        return left.lower().endswith(_str_side(m.group(2)).lower())
    m = re.match(r"^startswith\s*\(\s*(.+?)\s*,\s*(.+?)\s*\)$", text, re.I)
    if m:
        return _lookup_str(ctx, m.group(1)).lower().startswith(_str_side(m.group(2)).lower())
    m = re.match(r"^endswith\s*\(\s*(.+?)\s*,\s*(.+?)\s*\)$", text, re.I)
    if m:
        return _lookup_str(ctx, m.group(1)).lower().endswith(_str_side(m.group(2)).lower())

    # "contains .pdf" against listing
    m = re.match(r"^contains\s+(.+)$", text.strip(), re.I)
    if m:
        needle = m.group(1).strip().strip("'\"").lower()
        # also search AI summary/category
        ai = vals.get("ai.result") if isinstance(vals.get("ai.result"), dict) else {}
        blob = " ".join(str(ai.get(k) or "") for k in ("category", "classification", "summary")).lower()
        if needle in blob:
            return True
        return any(needle in str(e.get("name", "")).lower() for e in (ctx.get("last_listing") or []))

    # Rewrite AI fields into literals for AST
    text = _ai_rewrite(text, ctx)

    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        # fallback: == / != string compare without quotes
        if "==" in text:
            a, b = text.split("==", 1)
            return a.strip().strip("'\"").lower() == b.strip().strip("'\"").lower()
        if "!=" in text:
            a, b = text.split("!=", 1)
            return a.strip().strip("'\"").lower() != b.strip().strip("'\"").lower()
        raise ValueError(f"Invalid expression: {exc}") from exc

    return _SafeEval(ctx).visit(tree)


def _lookup_str(ctx: dict, token: str) -> str:
    token = token.strip().strip("'\"")
    vals = ctx.get("variables") or {}
    if token in vals:
        return str(vals[token] or "")
    ai = vals.get("ai.result")
    if isinstance(ai, dict) and token in ai:
        return str(ai.get(token) or "")
    if token.startswith("file."):
        return str((ctx.get("file") or {}).get(token.split(".", 1)[1]) or "")
    if token in {"name", "file.name"}:
        return str((ctx.get("file") or {}).get("name") or (ctx.get("item") or {}).get("name") or "")
    looked = _lookup(ctx, token)
    return "" if looked is None else str(looked)


def _ai_rewrite(expr: str, ctx: dict) -> str:
    vals = ctx.get("variables") or {}
    ai = vals.get("ai.result") if isinstance(vals.get("ai.result"), dict) else {}
    # prefer nested ai.result fields + flat aliases
    mapping = {
        "confidence": ai.get("confidence", vals.get("ai.confidence", vals.get("confidence"))),
        "category": ai.get("category", vals.get("ai.classification", vals.get("category"))),
        "classification": ai.get("classification", ai.get("category", vals.get("ai.classification"))),
        "summary": ai.get("summary", ""),
        "suggested_name": ai.get("suggested_name", ""),
    }
    for key, val in mapping.items():
        if val is None:
            continue
        if isinstance(val, (int, float)):
            expr = re.sub(rf"\b{key}\b", str(val), expr)
        else:
            expr = re.sub(rf"\b{key}\b", repr(str(val)), expr)
    return expr


def evaluate_bool(expr: str, ctx: dict | None = None) -> bool:
    try:
        return bool(evaluate(expr, ctx))
    except Exception:
        return False
