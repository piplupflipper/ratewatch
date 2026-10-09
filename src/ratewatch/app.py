from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static

from .collect import cached_states, refresh
from .config import Account
from .model import AccountState, now_utc
from .theme import ICEBERG
from .view import DEFAULT_ZOOM, ZOOMS, render

REFRESH_SECONDS = 300


class RatewatchApp(App):
    TITLE = "ratewatch"
    CSS = """
    Screen, #body, #view { background: ansi_default; }
    #body { height: 1fr; padding: 0 1; }
    """
    BINDINGS = [
        Binding("left", "zoom(-1)", "縮小"),
        Binding("right", "zoom(1)", "拡大"),
        Binding("r", "refresh", "再取得"),
        Binding("q", "quit", "終了"),
    ]

    def __init__(self, accounts: list[Account]) -> None:
        super().__init__()
        self.accounts = accounts
        self.states: list[AccountState] = cached_states(accounts)
        self.fetching = False
        self.status = ""
        self.zoom = DEFAULT_ZOOM
        self.register_theme(ICEBERG)
        self.theme = ICEBERG.name

    def compose(self) -> ComposeResult:
        # ヘッダもフッタも置かない。キー操作の案内と取得時刻は凡例の行に入れる
        with VerticalScroll(id="body"):
            yield Static(id="view")

    def on_mount(self) -> None:
        self.redraw()
        # 残り時間は毎秒ローカルで数え直し、API は REFRESH_SECONDS ごとにだけ叩く
        self.set_interval(1, self.redraw)
        self.set_interval(REFRESH_SECONDS, self.action_refresh)
        self.action_refresh()

    def on_resize(self) -> None:
        self.redraw()

    def redraw(self) -> None:
        body = self.query_one("#body", VerticalScroll)
        # スクロールバーと左右の余白のぶんを引いた幅で描く
        width = max(40, body.size.width - 3)
        self.query_one("#view", Static).update(
            render(self.states, now_utc(), width, self.zoom, self.status)
        )

    def action_zoom(self, delta: int) -> None:
        self.zoom = max(0, min(len(ZOOMS) - 1, self.zoom + delta))
        self.redraw()

    def action_refresh(self) -> None:
        if self.fetching:
            return
        self.fetching = True
        self.status = "取得中…"
        self.redraw()
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
        msg = f"{at} 取得（{REFRESH_SECONDS // 60} 分ごと）"
        if failed:
            msg += f"  失敗 {failed} 件は保存値"
        self.status = msg
        self.redraw()
