from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx

MAX_BYTES = 200_000
MAX_TEXT = 4_000
USER_AGENT = "ALTRON/0.3 (workspace-fetch)"


def http_get(url: str, timeout: float = 12.0) -> tuple[int, str, bytes]:
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        response = client.get(url, headers={"User-Agent": USER_AGENT})
        return response.status_code, response.headers.get("content-type") or "", response.content


def web_fetch(url: str, getter=None) -> str:
    fetch = getter or http_get
    if not is_public_http_url(url):
        return "Blocked: only public http(s) URLs. No localhost, file, or private IPs."
    try:
        status, content_type, body = fetch(url)
    except Exception as exc:  # noqa: BLE001 — surface fetch failures to the core
        return f"Fetch failed: {exc}"
    if status >= 400:
        return f"HTTP {status} from {url}"
    if len(body) > MAX_BYTES:
        return f"Response too large ({len(body)} bytes)."
    text = body.decode("utf-8", errors="replace")
    if "html" in content_type.lower() or text.lstrip().lower().startswith("<!doctype") or "<html" in text[:400].lower():
        text = _strip_html(text)
    text = text.strip()[:MAX_TEXT]
    return f"{url} [{status}]\n{text or '(empty)'}"


def is_public_http_url(url: str) -> bool:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        return False
    if _is_private_host(host):
        return False
    return True


def _is_private_host(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        # DNS failed — do not treat public hostnames as private; let fetch/browser try.
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except (ValueError, TypeError):
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    return False


def _strip_html(html: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()
