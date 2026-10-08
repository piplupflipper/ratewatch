from datetime import datetime, timedelta, timezone

import pytest
from rich.console import Console

from ratewatch.model import AccountState, Snapshot, Window
from ratewatch.theme import PALETTES, set_theme
from ratewatch.views import VIEWS as BASE_VIEWS
from ratewatch.views import bar
from ratewatch.views_mini import VARIANTS, ZOOMS, MiniAxis, kind_of

VIEWS = {**BASE_VIEWS, **VARIANTS}

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


@pytest.mark.parametrize("theme", list(PALETTES))
@pytest.mark.parametrize("view", list(VIEWS))
@pytest.mark.parametrize("width", [60, 100, 160])
def test_every_view_renders_all_accounts_without_overflow(view, width, theme):
    set_theme(theme)
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


@pytest.mark.parametrize("view", ["timeline", "mini", "gantt", "split"])
@pytest.mark.parametrize("span_index", [0, 1, 2])
def test_axis_views_render_every_span(view, span_index):
    out = text_of(VIEWS[view][1](states(), NOW, 120, span_index=span_index), 120)
    assert "今" in out
    assert max(len(line) for line in out.splitlines()) <= 120


def test_gantt_draws_exhausted_window_as_thick_line():
    out = text_of(VIEWS["gantt"][1](states(), NOW, 120, span_index=2), 120)
    credit = next(line for line in out.splitlines() if "積" in line)
    assert "━" in credit


def test_split_initials_are_unique():
    from ratewatch.views import _initials

    ini = _initials(states())
    assert len(set(ini.values())) == len(ini)
    assert ini["claude-private"] == "P"


@pytest.mark.parametrize("view", list(VARIANTS))
def test_variants_put_labels_on_axis_without_breaking_width(view):
    set_theme("iceberg")
    out = text_of(VARIANTS[view][1](states(), NOW, 140, span_index=1), 140)
    assert max(len(line) for line in out.splitlines()) <= 140
    # 週の枠の印に名前が付く（形を変える案でも、週の印は ◆）
    assert "◆週" in out


@pytest.mark.parametrize("zoom", range(len(ZOOMS)))
@pytest.mark.parametrize("width", range(20, 201))
def test_ticks_are_evenly_spaced_at_any_width(width, zoom):
    for hour in range(24):
        now = NOW.replace(hour=hour, minute=17)
        ax = MiniAxis(now, width, ZOOMS[zoom])
        ps = [p for p, _ in ax.tick_positions()]
        assert all(b - a == ZOOMS[zoom] for a, b in zip(ps, ps[1:]))
        assert all(0 < p < width for p in ps)
        # ヘッダーの日付は目盛りの位置から始まり、幅を超えない
        head = ax.header()
        assert head.cell_len == width
        for p, day in ax.tick_positions():
            lab = day.strftime("%m/%d")
            if head.plain.find(lab) != -1:
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


def test_kind_colors_differ_between_5h_and_week():
    set_theme("iceberg")
    from ratewatch.theme import C

    assert C.kind("5h") != C.kind("week")
    assert kind_of(Window("5h", 0, None)) == "5h"
    assert kind_of(Window("週 Opus", 0, None)) == "week"
    assert kind_of(Window("請求サイクル", 0, None)) == "month"
