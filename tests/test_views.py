from datetime import datetime, timedelta, timezone

import pytest
from rich.console import Console

from ratewatch.model import AccountState, Snapshot, Window
from ratewatch.views import VIEWS, bar

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def states():
    h = lambda n: NOW + timedelta(hours=n)  # noqa: E731
    return [
        AccountState("claude-flt", "claude", Snapshot(NOW, [Window("5h", 0.0, h(4)), Window("週", 20.0, h(150))], plan="team")),
        AccountState("claude-private", "claude", Snapshot(NOW, [Window("5h", 7.0, h(2)), Window("週", 79.0, h(45))], plan="max")),
        AccountState(
            "codex", "codex", Snapshot(NOW, [Window("週", 0.0, h(160)), Window("クレジット", 100.0, h(590))], plan="team")
        ),
        AccountState(
            "cursor",
            "cursor",
            Snapshot(NOW - timedelta(hours=3), [Window("請求サイクル", 33.9, h(55))], plan="enterprise", note="プラン枠 2000/2000"),
            error="HTTP 401: 要再ログイン",
            stale=True,
        ),
        AccountState("never", "codex", None, error="認証ファイルがない: /x/auth.json", stale=True),
    ]


def text_of(renderable, width=100):
    c = Console(width=width, record=True, color_system=None)
    c.print(renderable)
    return c.export_text()


@pytest.mark.parametrize("view", list(VIEWS))
@pytest.mark.parametrize("width", [60, 100, 160])
def test_every_view_renders_all_accounts_without_overflow(view, width):
    _, render = VIEWS[view]
    out = text_of(render(states(), NOW, width, span_index=1), width)
    for name in ["claude-flt", "claude-private", "codex", "cursor", "never"]:
        assert name in out
    assert "要再ログイン" in out or view in ("next",)
    assert max(len(line) for line in out.splitlines()) <= width


def test_next_view_lists_blocked_account_with_free_time():
    out = text_of(VIEWS["next"][1](states(), NOW, 100))
    blocked = next(line for line in out.splitlines() if "使えない" in line)
    assert "codex" in blocked and "積 100%" in blocked


def test_passed_reset_counts_as_empty():
    st = [AccountState("a", "claude", Snapshot(NOW - timedelta(days=1), [Window("5h", 95.0, NOW - timedelta(hours=1))]))]
    out = text_of(VIEWS["compact"][1](st, NOW, 100))
    assert "0%" in out and "リセット済" in out


def test_bar_width_is_exact():
    for pct in [0, 7, 33.9, 79, 100, None]:
        assert bar(pct, 10).cell_len == 10
