from datetime import datetime, timezone

from ratewatch.collect import build_rows
from ratewatch.model import AccountState, Snapshot, Window, parse_ts, window_label
from ratewatch.providers import parse_claude, parse_codex, parse_cursor


def test_parse_claude_reads_five_hour_and_weekly():
    body = {
        "five_hour": {"utilization": 60.0, "resets_at": "2026-10-07T02:49:59.657679+00:00"},
        "seven_day": {"utilization": 16.0, "resets_at": "2026-10-13T13:59:59.657697+00:00"},
        "seven_day_opus": None,
    }
    snap = parse_claude(body, plan="team")
    assert [(w.label, w.used_percent) for w in snap.windows] == [("5h", 60.0), ("週", 16.0)]
    assert snap.windows[0].resets_at == datetime(2026, 10, 7, 2, 49, 59, 657679, timezone.utc)
    assert snap.plan == "team"


def test_parse_codex_labels_windows_by_length_not_by_slot():
    # 週の枠が primary に入り、secondary が null のプラン
    body = {
        "plan_type": "team",
        "rate_limit": {
            "primary_window": {"used_percent": 100, "limit_window_seconds": 604800, "reset_at": 1791445515},
            "secondary_window": None,
        },
        "spend_control": {"individual_limit": {"used_percent": 100, "reset_at": 1793491201}},
        "rate_limit_reached_type": {"type": "workspace_member_credits_depleted"},
    }
    snap = parse_codex(body)
    assert [w.label for w in snap.windows] == ["週", "クレジット"]
    assert snap.windows[0].resets_at == datetime.fromtimestamp(1791445515, timezone.utc)
    assert snap.note == "workspace_member_credits_depleted"


def test_parse_codex_five_hour_and_weekly():
    body = {
        "rate_limit": {
            "primary_window": {"used_percent": 12, "limit_window_seconds": 18000, "reset_at": 1791445515},
            "secondary_window": {"used_percent": 40, "limit_window_seconds": 604800, "reset_at": 1791845515},
        }
    }
    assert [w.label for w in parse_codex(body).windows] == ["5h", "週"]


def test_parse_codex_zero_credit_limit_is_disabled_not_full():
    # 上限が 0 だと、消費 0 でも used_percent は 100 で返る（2026-11-07 の Team プランの応答）
    body = {
        "rate_limit": {
            "primary_window": {"used_percent": 36, "limit_window_seconds": 604800, "reset_at": 1794556956},
            "secondary_window": None,
        },
        "spend_control": {
            "reached": True,
            "individual_limit": {"limit": "0", "used": "0.0", "used_percent": 100, "reset_at": 1796083200},
        },
    }
    credit = parse_codex(body).windows[1]
    assert credit.label == "クレジット"
    assert credit.disabled
    assert credit.used_percent is None and credit.resets_at is None


def test_parse_codex_nonzero_credit_limit_keeps_percent():
    body = {"spend_control": {"individual_limit": {"limit": "50", "used_percent": 20, "reset_at": 1796083200}}}
    credit = parse_codex(body).windows[0]
    assert not credit.disabled
    assert credit.used_percent == 20


def test_disabled_window_survives_cache_round_trip():
    w = Window("クレジット", None, None, disabled=True)
    assert Window.from_dict(w.to_dict()) == w
    # disabled を持たない古いキャッシュも読める
    assert Window.from_dict({"label": "週", "used_percent": 3.0, "resets_at": None}).disabled is False


def test_parse_cursor_billing_cycle():
    body = {
        "billingCycleEnd": "2026-10-09T16:07:23.000Z",
        "membershipType": "enterprise",
        "individualUsage": {"plan": {"used": 2000, "limit": 2000, "totalPercentUsed": 33.908}},
    }
    snap = parse_cursor(body)
    (w,) = snap.windows
    assert w.label == "請求サイクル"
    assert w.used_percent == 33.908
    assert w.resets_at == datetime(2026, 10, 9, 16, 7, 23, tzinfo=timezone.utc)
    assert snap.note == "プラン枠 2000/2000"


def test_parse_ts_accepts_epoch_ms_and_iso():
    assert parse_ts(1791445515000) == parse_ts(1791445515)
    assert parse_ts("2026-10-09T16:07:23Z").tzinfo is not None
    assert parse_ts(None) is None


def test_window_label():
    assert window_label(18000) == "5h"
    assert window_label(604800) == "週"
    assert window_label(86400 * 30) == "30d"


def test_passed_reset_is_shown_as_done_in_stale_snapshot():
    now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    snap = Snapshot(
        fetched_at=datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc),
        windows=[Window("5h", 90.0, datetime(2026, 10, 7, 5, 0, tzinfo=timezone.utc))],
    )
    (row,) = build_rows([AccountState("a", "claude", snap, error="HTTP 401: 要再ログイン", stale=True)], now)
    cells = [str(c) for c in row.cells]
    assert cells[3] == "(リセット済み)"
    assert cells[5] == "済"
    assert cells[6] == "12h00m前"
    assert "要再ログイン" in cells[7]
