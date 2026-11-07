from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Window:
    """1 つのレートリミット枠（5 時間枠、週の枠、請求サイクルなど）。

    disabled は、上限が 0 で枠として使えない状態を表す（Codex のクレジット上限が 0 のときなど）。
    このとき used_percent と resets_at は意味を持たないので None にする。
    """

    label: str
    used_percent: float | None
    resets_at: datetime | None
    disabled: bool = False

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "used_percent": self.used_percent,
            "resets_at": self.resets_at.isoformat() if self.resets_at else None,
            "disabled": self.disabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Window:
        r = d.get("resets_at")
        return cls(
            d["label"],
            d.get("used_percent"),
            datetime.fromisoformat(r) if r else None,
            disabled=bool(d.get("disabled", False)),
        )


@dataclass
class Snapshot:
    """1 アカウントについて、ある時刻に取得できた枠の一覧。"""

    fetched_at: datetime
    windows: list[Window]
    plan: str | None = None
    note: str | None = None

    def to_dict(self) -> dict:
        return {
            "fetched_at": self.fetched_at.isoformat(),
            "windows": [w.to_dict() for w in self.windows],
            "plan": self.plan,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Snapshot:
        return cls(
            fetched_at=datetime.fromisoformat(d["fetched_at"]),
            windows=[Window.from_dict(w) for w in d.get("windows", [])],
            plan=d.get("plan"),
            note=d.get("note"),
        )


@dataclass
class AccountState:
    """画面に出す 1 アカウントの状態。最新の取得に失敗したら error に理由が入り、snapshot はキャッシュの値になる。"""

    name: str
    kind: str
    snapshot: Snapshot | None = None
    error: str | None = None
    stale: bool = False


class FetchError(Exception):
    """取得の失敗。メッセージはそのまま画面に出す。"""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(v: object) -> datetime | None:
    """ISO 8601 文字列か epoch 秒を UTC の datetime にする。"""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        # epoch ミリ秒で来る場合もあるので桁で見分ける
        if v > 1e12:
            v = v / 1000
        return datetime.fromtimestamp(v, timezone.utc)
    s = str(v).replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def window_label(seconds: int | None) -> str:
    if seconds is None:
        return "?"
    if seconds == 5 * 3600:
        return "5h"
    if seconds == 7 * 86400:
        return "週"
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    return f"{seconds // 60}m"
