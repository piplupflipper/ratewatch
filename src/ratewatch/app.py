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
from .theme import DEFAULT_THEME, PALETTES, set_theme
from .views import TIMELINE_RANGES, VIEWS

REFRESH_SECONDS = 300
VIEW_PATH = CACHE_PATH.parent / "view"
THEME_PATH = CACHE_PATH.parent / "theme"
DEFAULT_VIEW = "cards"
# ←→ で時間軸の範囲を変えられるパターン
SPAN_VIEWS = {"timeline", "mini", "gantt", "split"}


def _load(path: Path, valid: dict, default: str) -> str:
    try:
        v = path.read_text().strip()
    except OSError:
        return default
    return v if v in valid else default


def _save(path: Path, value: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    except OSError:
        pass  # 保存できなくても表示には影響しない


def load_view(path: Path | None = None) -> str:
    return _load(path or VIEW_PATH, VIEWS, DEFAULT_VIEW)


def save_view(view: str, path: Path | None = None) -> None:
    _save(path or VIEW_PATH, view)


def load_theme(path: Path | None = None) -> str:
    return _load(path or THEME_PATH, PALETTES, DEFAULT_THEME)


def save_theme(theme: str, path: Path | None = None) -> None:
    _save(path or THEME_PATH, theme)


class RatewatchApp(App):
    TITLE = "ratewatch"
    CSS = """
    #body { height: 1fr; padding: 0 1; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    """
    BINDINGS = [
        *[
            Binding(str(i + 1), f"view('{key}')", title.split(". ")[-1])
            for i, (key, (title, _)) in enumerate(VIEWS.items())
        ],
        Binding("left", "span(-1)", "範囲", show=False),
        Binding("right", "span(1)", "範囲", show=False),
        Binding("t", "next_theme", "配色"),
        Binding("r", "refresh", "再取得"),
        Binding("q", "quit", "終了"),
    ]

    def __init__(
        self, accounts: list[Account], view: str | None = None, theme: str | None = None
    ) -> None:
        super().__init__()
        self.accounts = accounts
        self.states: list[AccountState] = cached_states(accounts)
        self.fetching = False
        self.view = view if view in VIEWS else load_view()
        self.palette_name = theme if theme in PALETTES else load_theme()
        self.span_index = 1  # 時間軸の範囲。既定は 7 日

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="body"):
            yield Static(id="view")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.apply_theme()
        # 残り時間は毎秒ローカルで数え直し、API は REFRESH_SECONDS ごとにだけ叩く
        self.set_interval(1, self.redraw)
        self.set_interval(REFRESH_SECONDS, self.action_refresh)
        self.action_refresh()

    def on_resize(self) -> None:
        self.redraw()

    def apply_theme(self) -> None:
        palette = set_theme(self.palette_name)
        self.theme = palette.textual_theme
        # 地の色を画面全体にそろえる。本文のウィジェットに Textual のテーマの背景が残ると、文字のある部分だけが帯に見える
        for node in (self.screen, self.query_one("#body"), self.query_one("#view"), self.query_one("#status")):
            node.styles.background = palette.bg
        self.redraw()

    def redraw(self) -> None:
        body = self.query_one("#body", VerticalScroll)
        # スクロールバーと左右の余白のぶんを引いた幅で描く
        width = max(40, body.size.width - 3)
        title, render = VIEWS[self.view]
        self.sub_title = f"{title} · {PALETTES[self.palette_name].label}"
        self.query_one("#view", Static).update(
            render(self.states, now_utc(), width, span_index=self.span_index)
        )

    def action_view(self, view: str) -> None:
        if view in VIEWS:
            self.view = view
            save_view(view)
            self.redraw()

    def action_span(self, delta: int) -> None:
        if self.view in SPAN_VIEWS:
            self.span_index = (self.span_index + delta) % len(TIMELINE_RANGES)
            self.redraw()

    def action_next_theme(self) -> None:
        names = list(PALETTES)
        self.palette_name = names[(names.index(self.palette_name) + 1) % len(names)]
        save_theme(self.palette_name)
        self.apply_theme()

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
