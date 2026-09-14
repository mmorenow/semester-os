"""Configuration from `<repo>/config.yaml` (optional, gitignored; see config.example.yaml).

Unknown keys are refused at startup. SEMESTER_OS_* env vars override the file.
Timezone and port are fixed at import; feed URLs are re-read on mtime change.
Feed URLs are bearer credentials and are never logged.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config.yaml"
EXAMPLE_PATH = REPO_ROOT / "config.example.yaml"

DEFAULT_TIMEZONE = "America/Indiana/Indianapolis"
DEFAULT_PORT = 8790

FEED_NAMES = ("outlook", "brightspace")

TOP_LEVEL_KEYS = ("timezone", "term", "school_name", "calendar_feeds", "port")

ENV_TIMEZONE = "SEMESTER_OS_TIMEZONE"
ENV_PORT = "SEMESTER_OS_PORT"
ENV_FEEDS = {
    "outlook": "SEMESTER_OS_OUTLOOK_ICS_URL",
    "brightspace": "SEMESTER_OS_BRIGHTSPACE_ICS_URL",
}

MAX_TERM = 60
MAX_SCHOOL_NAME = 120
MAX_FEED_URL = 4000

# Below 1024 needs root.
MIN_PORT = 1024
MAX_PORT = 65535


class ConfigError(Exception):
    """config.yaml, or an override, holds a value this server cannot run with."""


@dataclass(frozen=True)
class Config:
    timezone: str = DEFAULT_TIMEZONE
    term: str | None = None
    school_name: str | None = None
    calendar_feeds: dict[str, str | None] = field(
        default_factory=lambda: {name: None for name in FEED_NAMES}
    )
    port: int = DEFAULT_PORT


# --- Validation: each raises ConfigError naming the key. ---

def _clean_timezone(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}: timezone must be an IANA zone name such as {DEFAULT_TIMEZONE}.")
    name = value.strip()
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(
            f"{where}: '{name}' is not a timezone this machine knows. Use an IANA name "
            f"such as {DEFAULT_TIMEZONE} or America/New_York."
        ) from None
    return name


def _clean_text(value: Any, key: str, limit: int, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ConfigError(f"{where}: {key} must be text.")
    text = str(value).strip()
    if not text:
        return None
    if len(text) > limit:
        raise ConfigError(f"{where}: {key} is longer than {limit} characters.")
    if any(ord(char) < 32 for char in text):
        raise ConfigError(f"{where}: {key} may not contain control characters.")
    return text


def _clean_port(value: Any, where: str) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{where}: port must be a whole number.")
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError(f"{where}: port must be a whole number.") from None
    if not MIN_PORT <= port <= MAX_PORT:
        raise ConfigError(f"{where}: port must be between {MIN_PORT} and {MAX_PORT}.")
    return port


def _clean_feed_url(value: Any, name: str, where: str) -> str | None:
    """An https URL, or nothing. The URL itself never appears in a message."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{where}: calendar_feeds.{name} must be an https:// URL or empty.")
    url = value.strip()
    if not url:
        return None
    if len(url) > MAX_FEED_URL:
        raise ConfigError(f"{where}: calendar_feeds.{name} is longer than {MAX_FEED_URL} characters.")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        raise ConfigError(f"{where}: calendar_feeds.{name} must be an https:// URL.")
    return url


def _read_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} is not valid YAML: {exc}") from None
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path.name} must be a mapping of keys to values.")
    unknown = sorted(str(key) for key in loaded if key not in TOP_LEVEL_KEYS)
    if unknown:
        raise ConfigError(
            f"{path.name}: unknown key(s) {', '.join(unknown)}. "
            f"Valid keys: {', '.join(TOP_LEVEL_KEYS)}."
        )
    return loaded


def parse(raw: dict[str, Any], where: str = "config.yaml", environ: dict[str, str] | None = None) -> Config:
    """Validate a loaded mapping plus the environment overrides into a Config."""
    env = os.environ if environ is None else environ

    timezone_value = env.get(ENV_TIMEZONE) or raw.get("timezone") or DEFAULT_TIMEZONE
    timezone_where = ENV_TIMEZONE if env.get(ENV_TIMEZONE) else where
    port_value = env.get(ENV_PORT) or raw.get("port") or DEFAULT_PORT
    port_where = ENV_PORT if env.get(ENV_PORT) else where

    feeds_raw = raw.get("calendar_feeds") or {}
    if not isinstance(feeds_raw, dict):
        raise ConfigError(f"{where}: calendar_feeds must be a mapping with outlook and brightspace.")
    unknown_feeds = sorted(str(key) for key in feeds_raw if key not in FEED_NAMES)
    if unknown_feeds:
        raise ConfigError(
            f"{where}: unknown calendar feed(s) {', '.join(unknown_feeds)}. "
            f"Valid feeds: {', '.join(FEED_NAMES)}."
        )
    feeds: dict[str, str | None] = {}
    for name in FEED_NAMES:
        override = env.get(ENV_FEEDS[name])
        if override:
            feeds[name] = _clean_feed_url(override, name, ENV_FEEDS[name])
        else:
            feeds[name] = _clean_feed_url(feeds_raw.get(name), name, where)

    return Config(
        timezone=_clean_timezone(timezone_value, timezone_where),
        term=_clean_text(raw.get("term"), "term", MAX_TERM, where),
        school_name=_clean_text(raw.get("school_name"), "school_name", MAX_SCHOOL_NAME, where),
        calendar_feeds=feeds,
        port=_clean_port(port_value, port_where),
    )


def load(path: Path | None = None) -> Config:
    """Read and validate config.yaml (absent is fine) with the overrides applied."""
    target = path or CONFIG_PATH
    return parse(_read_file(target), where=target.name)


# Read once: port and timezone are baked into module constants server-wide.
CONFIG = load()

_cache_lock = threading.Lock()
_cache: tuple[float | None, Config] = (
    CONFIG_PATH.stat().st_mtime if CONFIG_PATH.is_file() else None,
    CONFIG,
)


def current() -> Config:
    """The file's current configuration, re-read only when its mtime changed.

    An invalid edit keeps the last good config; the next start reports the error.
    """
    global _cache
    mtime = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.is_file() else None
    with _cache_lock:
        if mtime == _cache[0]:
            return _cache[1]
        try:
            fresh = load()
        except ConfigError:
            return _cache[1]
        _cache = (mtime, fresh)
        return fresh


def feed_url(name: str) -> str | None:
    """The URL for one feed, or None when neither the file nor the env has one."""
    if name not in FEED_NAMES:
        raise ValueError(f"Unknown calendar feed '{name}'.")
    return current().calendar_feeds.get(name)


def feed_setting_name(name: str) -> str:
    """Where a person sets a feed, for the "not configured" message."""
    return f"calendar_feeds.{name} in config.yaml (or {ENV_FEEDS[name]})"


def public_view() -> dict[str, Any]:
    """What the interface may know: everything except the feed URLs themselves."""
    live = current()
    return {
        "timezone": CONFIG.timezone,
        "term": live.term,
        "school_name": live.school_name,
        "port": CONFIG.port,
        "calendar_feeds": {name: bool(live.calendar_feeds.get(name)) for name in FEED_NAMES},
        "config_file": CONFIG_PATH.is_file(),
    }
