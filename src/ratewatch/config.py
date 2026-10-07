from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .model import Snapshot


def _xdg(env: str, default: str) -> Path:
    return Path(os.environ.get(env) or Path.home() / default)


CONFIG_PATH = _xdg("XDG_CONFIG_HOME", ".config") / "ratewatch" / "config.toml"
CACHE_PATH = _xdg("XDG_CACHE_HOME", ".cache") / "ratewatch" / "snapshots.json"

# 各サービスで、アカウントの場所を指すキーと既定値
_PATH_KEYS = {
    "claude": ("dir", "~/.claude"),
    "codex": ("dir", "~/.codex"),
    "cursor": ("auth", "~/.config/cursor/auth.json"),
}


@dataclass
class Account:
    name: str
    kind: str
    path: Path


def load_accounts(path: Path = CONFIG_PATH) -> list[Account]:
    """設定ファイルからアカウントを読む。ファイルが無ければ各サービスの既定の場所を 1 つずつ使う。"""
    if not path.exists():
        return [Account(kind, kind, Path(default).expanduser()) for kind, (_, default) in _PATH_KEYS.items()]
    data = tomllib.loads(path.read_text())
    accounts = []
    for i, a in enumerate(data.get("account", [])):
        kind = a.get("kind")
        if kind not in _PATH_KEYS:
            raise ValueError(f"{path}: account[{i}] の kind が不正: {kind!r}（claude / codex / cursor）")
        key, default = _PATH_KEYS[kind]
        accounts.append(Account(a.get("name") or kind, kind, Path(a.get(key, default)).expanduser()))
    names = [a.name for a in accounts]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise ValueError(f"{path}: name が重複している: {', '.join(sorted(dup))}")
    return accounts


def load_cache(path: Path = CACHE_PATH) -> dict[str, Snapshot]:
    try:
        raw = json.loads(path.read_text())
        return {k: Snapshot.from_dict(v) for k, v in raw.items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def save_cache(cache: dict[str, Snapshot], path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: v.to_dict() for k, v in cache.items()}, ensure_ascii=False, indent=2))
    tmp.replace(path)
