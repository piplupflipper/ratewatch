from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Static

from .collect import COLUMNS, build_rows, cached_states, refresh
from .config import Account
from .model import AccountState, now_utc

REFRESH_SECONDS = 300


class RatewatchApp(App):
    TITLE = "ratewatch"
    CSS = """
    DataTable { height: 1fr; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    """
    BINDINGS = [("r", "refresh", "再取得"), ("q", "quit", "終了")]

    def __init__(self, accounts: list[Account]) -> None:
        super().__init__()
        self.accounts = accounts
        self.states: list[AccountState] = cached_states(accounts)
        self.fetching = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DataTable(zebra_stripes=True, cursor_type="row")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns(*COLUMNS)
        self.redraw()
        # 残り時間は毎秒ローカルで数え直し、API は REFRESH_SECONDS ごとにだけ叩く
        self.set_interval(1, self.redraw)
        self.set_interval(REFRESH_SECONDS, self.action_refresh)
        self.action_refresh()

    def redraw(self) -> None:
        table = self.query_one(DataTable)
        row = table.cursor_row
        table.clear()
        for r in build_rows(self.states, now_utc()):
            table.add_row(*r.cells)
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))

    def action_refresh(self) -> None:
        if self.fetching:
            return
        self.fetching = True
        self.query_one("#status", Static).update("取得中…")
        self._fetch()

    @work(thread=True, exclusive=True)
    def _fetch(self) -> None:
        states = refresh(self.accounts)
        self.call_from_thread(self._done, states)

    def _done(self, states: list[AccountState]) -> None:
        self.states = states
        self.fetching = False
        failed = sum(1 for s in states if s.error)
        at = now_utc().astimezone().strftime("%H:%M:%S")
        msg = f"{at} に取得（{REFRESH_SECONDS // 60} 分ごとに自動取得）"
        if failed:
            msg += f"  失敗 {failed} 件（キャッシュの値を表示中）"
        self.query_one("#status", Static).update(msg)
        self.redraw()
