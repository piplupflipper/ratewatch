import asyncio

from ratewatch import app as app_mod
from ratewatch.app import RatewatchApp
from ratewatch.config import Account
from ratewatch.model import AccountState, Snapshot, Window, now_utc


def test_app_draws_and_zooms(monkeypatch, tmp_path):
    states = [AccountState("work", "claude", Snapshot(now_utc(), [Window("5h", 10.0, None), Window("週", 5.0, None)]))]
    monkeypatch.setattr(app_mod, "cached_states", lambda accounts: [])
    monkeypatch.setattr(app_mod, "refresh", lambda accounts: states)

    async def run():
        app = RatewatchApp([Account("work", "claude", tmp_path)])
        async with app.run_test(size=(140, 20)) as pilot:
            await pilot.pause(0.3)
            assert app.theme == "iceberg"
            assert app.zoom == 1
            await pilot.press("right", "right")
            assert app.zoom == 2  # 端で止まる
            await pilot.press("left", "left", "left")
            assert app.zoom == 0
            await pilot.press("r")
            await pilot.pause(0.2)
            assert app.states == states

    asyncio.run(run())
