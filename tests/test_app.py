import asyncio

import pytest

from ratewatch import app as app_mod
from ratewatch.app import RatewatchApp
from ratewatch.config import Account
from ratewatch.model import AccountState, Snapshot, Window, now_utc


@pytest.fixture
def app(monkeypatch, tmp_path):
    states = [AccountState("work", "claude", Snapshot(now_utc(), [Window("5h", 10.0, None), Window("週", 5.0, None)]))]
    monkeypatch.setattr(app_mod, "cached_states", lambda accounts: [])
    monkeypatch.setattr(app_mod, "refresh", lambda accounts: states)
    monkeypatch.setattr(app_mod, "VIEW_PATH", tmp_path / "view")
    monkeypatch.setattr(app_mod, "THEME_PATH", tmp_path / "theme")
    return RatewatchApp([Account("work", "claude", tmp_path)])


def test_keys_switch_views_and_remember_the_choice(app, tmp_path):
    async def run():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            assert app.view == "line"
            assert app.palette_name == "iceberg"
            assert app.theme == "iceberg"
            for key, view in [("1", "lean"), ("3", "labeled"), ("4", "focus"), ("5", "mini"), ("2", "line")]:
                await pilot.press(key)
                assert app.view == view
            await pilot.press("t")
            assert app.palette_name == "mono"
            await pilot.press("right")
            assert app.span_index == 2
            await pilot.press("r")
            await pilot.pause(0.2)

    asyncio.run(run())
    assert app_mod.load_view(tmp_path / "view") == "line"
    assert (tmp_path / "theme").read_text() == "mono"
