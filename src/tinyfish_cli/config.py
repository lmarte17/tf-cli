from __future__ import annotations

import json
import os
from getpass import getpass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import webbrowser

from tinyfish_cli.errors import CliError

DEFAULT_CONFIG_PATH = Path.home() / ".tinyfish" / "config.json"
API_KEYS_URL = "https://agent.tinyfish.ai/api-keys"


def expand_config_path(path: Optional[str]) -> Path:
    if path:
        return Path(path).expanduser()
    return DEFAULT_CONFIG_PATH


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CliError(
            f"Invalid TinyFish config JSON at {path}",
            code="INVALID_CONFIG",
            details={"path": str(path), "error": str(exc)},
        ) from exc


def save_config(path: Path, config: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def save_api_key(path: Path, api_key: str) -> None:
    config = load_config(path)
    config["api_key"] = api_key.strip()
    save_config(path, config)


def clear_api_key(path: Path) -> None:
    config = load_config(path)
    config.pop("api_key", None)
    save_config(path, config)


def resolve_api_key(explicit_api_key: Optional[str], config_path: Path) -> Tuple[Optional[str], str]:
    if explicit_api_key:
        return explicit_api_key.strip(), "arg"
    env_key = os.getenv("TINYFISH_API_KEY", "").strip()
    if env_key:
        return env_key, "env"
    config_key = str(load_config(config_path).get("api_key", "")).strip()
    if config_key:
        return config_key, "config"
    return None, "none"


def preview_api_key(api_key: Optional[str]) -> Optional[str]:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


def prompt_for_api_key(provided_api_key: Optional[str]) -> str:
    if provided_api_key:
        return provided_api_key.strip()
    stdin = os.fdopen(os.dup(0))
    try:
        if not stdin.isatty():
            value = stdin.read().strip()
            if value:
                return value
    finally:
        stdin.close()
    return getpass("Paste your TinyFish API key: ").strip()


def open_api_keys_page() -> bool:
    try:
        return bool(webbrowser.open(API_KEYS_URL))
    except Exception:
        return False
