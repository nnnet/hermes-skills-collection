"""
Domain routing config — maps domains to fetch backends.

Read before any fetch() call to skip low tiers for known difficult sites.
Supports auto-learning: record_failure() escalates a domain to the next tier.

Usage:
    from domain_config import get_backend, add_domain, record_failure

    backend = get_backend("https://cian.ru/...")  # returns "playwright"
    add_domain("site.ru", "playwright", "bot protection")
    record_failure("https://site.ru/page", "curl")  # auto-escalates domain
"""

import json
import os
from datetime import date
from urllib.parse import urlparse

DOMAINS_FILE = os.path.join(os.path.dirname(__file__), "..", "references", "domains.json")

TIER_ORDER = ["web_extract", "curl", "playwright", "skip"]

_TIER_KEY = {
    "playwright": "playwright_required",
    "curl": "curl_bypass",
    "skip": "skip",
    "web_extract": "web_extract_ok",
}

_DEFAULT = {
    "playwright_required": [],
    "curl_bypass": [],
    "skip": [],
    "web_extract_ok": [],
}


def load_config() -> dict:
    if not os.path.exists(DOMAINS_FILE):
        return {k: list(v) for k, v in _DEFAULT.items()}
    with open(DOMAINS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_config(config: dict) -> None:
    with open(DOMAINS_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return url.lower()


def _root_domain(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def get_backend(url: str) -> str:
    """
    Return the recommended fetch backend for this URL.
    Returns: 'web_extract' | 'curl' | 'playwright' | 'skip'
    """
    host = _host(url)
    config = load_config()

    for entry in config.get("skip", []):
        if entry["domain"] in host:
            return "skip"

    for entry in config.get("playwright_required", []):
        if entry["domain"] in host:
            return "playwright"

    for entry in config.get("curl_bypass", []):
        if entry["domain"] in host:
            return "curl"

    return "web_extract"


def add_domain(domain: str, backend: str, reason: str = "") -> None:
    """
    Register or update a domain's required backend.
    Call this when you discover a site needs a specific fetch backend.
    """
    tier = _TIER_KEY.get(backend, "curl_bypass")
    config = load_config()

    for key in _TIER_KEY.values():
        config.setdefault(key, [])
        config[key] = [e for e in config[key] if domain not in e.get("domain", "")]

    config.setdefault(tier, []).append(
        {"domain": domain, "reason": reason, "added": str(date.today())}
    )
    _save_config(config)


def record_failure(url: str, failed_backend: str) -> None:
    """
    Auto-learn: if a backend failed, escalate domain to the next stronger tier.
    web_extract → curl | curl → playwright
    Does nothing if domain is already at the correct tier or higher.
    """
    escalation = {"web_extract": "curl", "curl": "playwright"}
    next_backend = escalation.get(failed_backend)
    if not next_backend:
        return

    host = _host(url)
    domain = _root_domain(host)
    current = get_backend(url)

    if TIER_ORDER.index(next_backend) > TIER_ORDER.index(current):
        add_domain(
            domain,
            next_backend,
            reason=f"auto-learned: {failed_backend} failed on {str(date.today())}",
        )
