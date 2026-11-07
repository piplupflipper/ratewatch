from datetime import datetime, timedelta, timezone

import pytest
from rich.console import Console

from ratewatch.model import AccountState, Snapshot, Window
from ratewatch.view import ZOOMS, MiniAxis, axis_marks, kind_of, line_gauge, render

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def h(n: float) -> datetime:
    return NOW + timedelta(hours=n)


def states():
    return [
        AccountState("claude-flt", "claude", Snapshot(NOW, [Window("5h", 0.0, h(4)), Window("週", 20.0, h(150))], plan="team")),
        AccountState("claude-private", "claude", Snapshot(NOW, [Window("5h", 7.0, h(2)), Window("週", 79.0, h(45))], plan="max")),
        AccountState("codex", "codex", Snapshot(NOW, [Window("週", 0.0, h(160)), Window("クレジット", 100.0, h(590))], plan="team")),
        AccountState(
            "cursor",
            "cursor",
            Snapshot(NOW - timedelta(hours=3), [Window("請求サイクル", 33.9, h(55))], plan="enterprise", note="プラン枠 2000/2000"),
            error="HTTP 401: 要再ログイン",
            stale=True,
        ),
        AccountState("never", "codex", None, error="認証ファイルがない: /x/auth.json", stale=True),
    ]


def text_of(renderable, width):
    c = Console(width=width, record=True, color_system=None)
    c.print(renderable)
    return c.export_text()


@pytest.mark.parametrize("zoom", range(len(ZOOMS)))
@pytest.mark.parametrize("width", [60, 100, 140, 200])
def test_render_shows_all_accounts_within_width(width, zoom):
    out = text_of(render(states(), NOW, width, zoom), width)
    for name in ["claude-flt", "claude-private", "codex", "cursor", "never", "要再ログイン"]:
        assert name in out
    assert max(len(line) for line in out.splitlines()) <= width


@pytest.mark.parametrize("zoom", range(len(ZOOMS)))
@pytest.mark.parametrize("width", range(20, 201))
def test_ticks_are_evenly_spaced_at_any_width(width, zoom):
    for hour in range(24):
        now = NOW.replace(hour=hour, minute=17)
        ax = MiniAxis(now, width, ZOOMS[zoom])
        ps = [p for p, _ in ax.tick_positions()]
        assert all(b - a == ZOOMS[zoom] for a, b in zip(ps, ps[1:]))
        assert all(0 < p < width for p in ps)
        head = ax.header()
        assert head.cell_len == width
        for p, day in ax.tick_positions():
            lab = day.strftime("%m/%d")
            if lab in head.plain:
                assert head.plain.index(lab) + 1 == p  # 「今」は 2 マスで 1 文字なので、文字列上は 1 小さい


def test_wider_terminal_shows_more_days_with_same_spacing():
    narrow = MiniAxis(NOW, 40, ZOOMS[1])
    wide = MiniAxis(NOW, 120, ZOOMS[1])
    assert wide.span > narrow.span
    assert wide.tick_positions()[:2] == narrow.tick_positions()[:2]


def test_marker_on_midnight_sits_on_tick():
    ax = MiniAxis(NOW, 100, ZOOMS[1])
    p, day = ax.tick_positions()[1]
    assert ax.x(day) == p


def test_marks_carry_window_names():
    st = states()[1]
    line = MiniAxis(NOW, 60, ZOOMS[1]).line(axis_marks(st, MiniAxis(NOW, 60, ZOOMS[1]), NOW)).plain
    assert "◆5h" in line and "◆週" in line


def test_two_resets_beyond_range_both_get_labels():
    # codex は週の枠もクレジットも 7 日より先にリセットされる
    ax = MiniAxis(NOW, 40, ZOOMS[1])
    line = ax.line(axis_marks(states()[2], ax, NOW)).plain
    assert line.endswith("週 積▸")


def test_beyond_labels_fall_back_to_arrow_when_no_room():
    ax = MiniAxis(NOW, 6, ZOOMS[1])
    marks = axis_marks(states()[2], ax, NOW)
    assert [m.plain for _, m in marks] == ["▸"]


def test_kind_of():
    assert kind_of(Window("5h", 0, None)) == "5h"
    assert kind_of(Window("週 Opus", 0, None)) == "week"
    assert kind_of(Window("請求サイクル", 0, None)) == "month"
    assert kind_of(Window("クレジット", 0, None)) == "credit"


def test_line_gauge_width_is_exact():
    for pct in [0, 2, 7, 33.9, 82, 100, None]:
        assert line_gauge(pct, 10).cell_len == 10


def test_passed_reset_counts_as_empty():
    st = [AccountState("a", "claude", Snapshot(NOW - timedelta(days=1), [Window("5h", 95.0, NOW - timedelta(hours=1))]))]
    out = text_of(render(st, NOW, 140), 140)
    assert "  0%" in out and "済" in out


def test_disabled_credit_is_annotated_without_gauge_or_mark():
    st = AccountState("codex", "codex", Snapshot(NOW, [Window("週", 36.0, h(130)), Window("クレジット", None, None, disabled=True)]))
    out = text_of(render([st], NOW, 140), 140)
    assert "クレジット無効" in out
    assert "100%" not in out
    ax = MiniAxis(NOW, 40, ZOOMS[1])
    assert all("積" not in m.plain for _, m in axis_marks(st, ax, NOW))
