from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header, Static

from .collect import cached_states, refresh
from .config import CACHE_PATH, Account
from .model import AccountState, now_utc
from .views import TIMELINE_RANGES, VIEWS

REFRESH_SECONDS = 300
VIEW_PATH = CACHE_PATH.parent / "view"
DEFAULT_VIEW = "cards"


def load_view(path: Path | None = None) -> str:
    path = path or VIEW_PATH
    try:
        v = path.read_text().strip()
    except OSError:
        return DEFAULT_VIEW
    return v if v in VIEWS else DEFAULT_VIEW


def save_view(view: str, path: Path | None = None) -> None:
    path = path or VIEW_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(view)
    except OSError:
        pass  # 保存できなくても表示には影響しない


class RatewatchApp(App):
    TITLE = "ratewatch"
    CSS = """
    #body { height: 1fr; padding: 0 1; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    """
    BINDINGS = [
        Binding("1", "view('cards')", "カード"),
        Binding("2", "view('timeline')", "タイムライン"),
        Binding("3", "view('compact')", "コンパクト"),
        Binding("4", "view('next')", "次に空く"),
        Binding("left", "span(-1)", "範囲", show=False),
        Binding("right", "span(1)", "範囲", show=False),
        Binding("r", "refresh", "再取得"),
        Binding("q", "quit", "終了"),
    ]

    def __init__(self, accounts: list[Account], view: str | None = None) -> None:
        super().__init__()
        self.accounts = accounts
        self.states: list[AccountState] = cached_states(accounts)
        self.fetching = False
        self.view = view if view in VIEWS else load_view()
        self.span_index = 1  # タイムラインの範囲。既定は 7 日

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="body"):
            yield Static(id="view")
        yield Static("", id="status")
        yield Footer()

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
        title, render = VIEWS[self.view]
        self.sub_title = title
        self.query_one("#view", Static).update(
            render(self.states, now_utc(), width, span_index=self.span_index)
        )

    def action_view(self, view: str) -> None:
        if view in VIEWS:
            self.view = view
            save_view(view)
            self.redraw()

    def action_span(self, delta: int) -> None:
        if self.view == "timeline":
            self.span_index = (self.span_index + delta) % len(TIMELINE_RANGES)
            self.redraw()

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
            msg += f"  失敗 {failed} 件（保存しておいた値を表示中）"
        self.query_one("#status", Static).update(msg)
        self.redraw()
