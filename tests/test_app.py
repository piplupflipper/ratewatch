import asyncio

from ratewatch import app as app_mod
from ratewatch.app import RatewatchApp
from ratewatch.config import Account
from ratewatch.model import AccountState, Snapshot, Window, now_utc


def test_app_shows_rows_after_refresh(monkeypatch, tmp_path):
    states = [AccountState("work", "claude", Snapshot(now_utc(), [Window("5h", 10.0, None), Window("週", 5.0, None)]))]
    monkeypatch.setattr(app_mod, "cached_states", lambda accounts: [])
    monkeypatch.setattr(app_mod, "refresh", lambda accounts: states)

    async def run():
        app = RatewatchApp([Account("work", "claude", tmp_path)])
        async with app.run_test() as pilot:
            await pilot.pause(0.5)
            table = app.query_one(app_mod.DataTable)
            assert table.row_count == 2
            await pilot.press("r")
            await pilot.pause(0.2)
            assert table.row_count == 2

    asyncio.run(run())
