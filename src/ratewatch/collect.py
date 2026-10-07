from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from rich.text import Text

from .config import Account, load_cache, save_cache
from .model import AccountState, FetchError, Snapshot, Window
from .providers import FETCHERS


def fetch_one(account: Account) -> Snapshot:
    return FETCHERS[account.kind](account.path)


def refresh(accounts: list[Account]) -> list[AccountState]:
    """全アカウントを並列に取得し、成功した分をキャッシュへ保存する。失敗した分はキャッシュの値を返す。"""
    cache = load_cache()

    def run(a: Account) -> AccountState:
        try:
            snap = fetch_one(a)
        except FetchError as e:
            return AccountState(a.name, a.kind, cache.get(a.name), str(e), stale=True)
        except Exception as e:  # 想定外の応答の形でも、他のアカウントの表示は続ける
            return AccountState(a.name, a.kind, cache.get(a.name), f"{type(e).__name__}: {e}", stale=True)
        return AccountState(a.name, a.kind, snap)

    with ThreadPoolExecutor(max_workers=max(1, len(accounts))) as ex:
        states = list(ex.map(run, accounts))
    for s in states:
        if not s.stale and s.snapshot:
            cache[s.name] = s.snapshot
    save_cache(cache)
    return states


def cached_states(accounts: list[Account]) -> list[AccountState]:
    """起動直後、取得が終わるまでに出すキャッシュの値。"""
    cache = load_cache()
    return [AccountState(a.name, a.kind, cache.get(a.name), stale=a.name in cache) for a in accounts]


# ---- 表示用の整形 ----

COLUMNS = ["アカウント", "サービス", "枠", "使用率", "リセット", "残り", "取得", "状態"]


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d{h:02d}h"
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m{s:02d}s"


def fmt_ago(dt: datetime, now: datetime) -> str:
    sec = (now - dt).total_seconds()
    if sec < 60:
        return "たった今"
    return fmt_duration(sec) + "前"


def usage_cell(pct: float | None, reset_passed: bool) -> Text:
    if reset_passed:
        return Text("(リセット済み)", style="dim")
    if pct is None:
        return Text("-", style="dim")
    width = 6
    filled = min(width, round(pct / 100 * width))
    style = "red" if pct >= 90 else "yellow" if pct >= 70 else "green"
    t = Text("█" * filled, style=style)
    t.append("░" * (width - filled), style="dim")
    t.append(f" {pct:5.1f}%")
    return t


@dataclass
class Row:
    cells: list[Text | str]


def build_rows(states: list[AccountState], now: datetime) -> list[Row]:
    rows: list[Row] = []
    for st in states:
        snap = st.snapshot
        status = Text(st.error, style="red") if st.error else Text(snap.note or "", style="dim") if snap else Text("")
        if snap is None:
            rows.append(Row([st.name, st.kind, "-", "-", "-", "-", "-", status or Text("未取得", style="dim")]))
            continue
        ago = Text(fmt_ago(snap.fetched_at, now), style="yellow" if st.stale else "")
        windows = snap.windows or [Window("-", None, None)]
        for i, w in enumerate(windows):
            passed = w.resets_at is not None and w.resets_at <= now
            if w.resets_at is None:
                reset, remain = "-", Text("-")
            else:
                reset = w.resets_at.astimezone().strftime("%m/%d %H:%M")
                remain = Text("済", style="green") if passed else Text(fmt_duration((w.resets_at - now).total_seconds()))
            first = i == 0
            rows.append(
                Row(
                    [
                        st.name if first else "",
                        (st.kind + (f" ({snap.plan})" if snap.plan else "")) if first else "",
                        w.label,
                        usage_cell(w.used_percent, passed),
                        reset,
                        remain,
                        ago if first else "",
                        status if first else "",
                    ]
                )
            )
    return rows
