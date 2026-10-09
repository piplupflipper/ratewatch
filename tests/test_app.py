import asyncio
import io

from rich.console import Console
from textual.widgets import Static

from ratewatch import app as app_mod
from ratewatch.app import RatewatchApp
from ratewatch.config import Account
from ratewatch.model import AccountState, Snapshot, Window, now_utc
from ratewatch.view import render


def _states(n: int) -> list[AccountState]:
    return [
        AccountState(f"acct{i}", "claude", Snapshot(now_utc(), [Window("5h", 10.0, None), Window("週", 5.0, None)]))
        for i in range(n)
    ]


def _lines(renderable, width: int = 140) -> list[str]:
    buf = io.StringIO()
    Console(file=buf, width=width, force_terminal=False, color_system=None).print(renderable)
    return buf.getvalue().rstrip("\n").split("\n")


def test_render_uses_axis_header_plus_rows_plus_one_footer_line():
    # 軸の日付 1 行 + アカウント数 + 凡例 1 行。空行やステータス行を挟まない
    for n in (1, 4):
        lines = _lines(render(_states(n), now_utc(), 140, status="12:00:00 取得"))
        assert len(lines) == n + 2
        assert "r 再取得" in lines[-1] and "q 終了" in lines[-1]
        assert "12:00:00 取得" in lines[-1]


def test_footer_never_wraps_when_width_is_narrow():
    # 幅 80 では軸が消えて「行 + 凡例」だけになる。凡例は幅を超えても折り返さず右を落とす
    status = "12:00:00 取得（5 分ごと）  失敗 1 件は保存値"
    lines = _lines(render(_states(1), now_utc(), 80, status=status), width=80)
    assert len(lines) == 1 + 1
    assert lines[-1].endswith("…")


def test_app_has_no_header_footer_or_status_widgets(monkeypatch, tmp_path):
    states = _states(1)
    monkeypatch.setattr(app_mod, "cached_states", lambda accounts: [])
    monkeypatch.setattr(app_mod, "refresh", lambda accounts: states)

    async def run():
        app = RatewatchApp([Account("acct0", "claude", tmp_path)])
        async with app.run_test(size=(120, 20)) as pilot:
            await pilot.pause(0.5)
            assert [w.id for w in app.query(Static)] == ["view"]
            assert app.states == states
            assert "取得" in app.status
            await pilot.press("r")
            await pilot.pause(0.2)
            assert app.states == states

    asyncio.run(run())
