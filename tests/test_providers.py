import json
from datetime import datetime, timezone

import pytest

from ratewatch import providers
from ratewatch.collect import build_rows
from ratewatch.model import AccountState, FetchError, Snapshot, Window, parse_ts, window_label
from ratewatch.providers import fetch_grok, parse_claude, parse_codex, parse_cursor, parse_grok
from ratewatch.view import kind_of


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


# 2026-11-22 の応答（Team のアカウント）
GROK_BODY = {
    "config": {
        "currentPeriod": {
            "type": "USAGE_PERIOD_TYPE_WEEKLY",
            "start": "2026-11-16T06:51:18.410+00:00",
            "end": "2026-11-23T06:51:18.410+00:00",
        },
        "creditUsagePercent": 100.0,
        "productUsage": [{"product": "GrokBuild", "usagePercent": 99.0}, {"product": "GrokBot", "usagePercent": 1.0}],
        "isUnifiedBillingUser": True,
        "prepaidBalance": {"val": 0},
        "billingPeriodStart": "2026-11-16T06:51:18.410+00:00",
        "billingPeriodEnd": "2026-11-23T06:51:18.410+00:00",
    }
}


def test_parse_grok_weekly_credit_period():
    snap = parse_grok(GROK_BODY, plan="team")
    (w,) = snap.windows
    assert (w.label, w.used_percent) == ("週", 100.0)
    assert w.resets_at == datetime(2026, 11, 23, 6, 51, 18, 410000, timezone.utc)
    assert snap.note == "内訳 GrokBuild 99% / GrokBot 1%"
    assert snap.plan == "team"


def test_parse_grok_unknown_period_type_is_named_by_length():
    body = {
        "config": {
            "currentPeriod": {"type": "X", "start": "2026-11-01T00:00:00+00:00", "end": "2026-12-01T00:00:00+00:00"},
            "creditUsagePercent": 12.5,
        }
    }
    (w,) = parse_grok(body).windows
    assert w.label == "月"
    assert kind_of(w) == "month"


def test_parse_grok_empty_config_has_no_windows():
    assert parse_grok({"config": {}}).windows == []


def _write_grok_auth(tmp_path, **login):
    (tmp_path / "auth.json").write_text(json.dumps({"https://auth.x.ai::client": login}))


def test_fetch_grok_skips_request_when_token_expired(tmp_path, monkeypatch):
    _write_grok_auth(tmp_path, key="a.b.c", expires_at="2026-11-22T02:16:42.046162602Z")
    monkeypatch.setattr(providers, "now_utc", lambda: datetime(2026, 11, 22, 3, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(providers, "_get", lambda *a: pytest.fail("期限切れのトークンで叩いた"))
    with pytest.raises(FetchError, match="期限切れ"):
        fetch_grok(tmp_path)


def test_fetch_grok_sends_bearer_token(tmp_path, monkeypatch):
    _write_grok_auth(tmp_path, key="a.b.c", expires_at="2026-11-22T02:16:42Z", principal_type="Team")
    monkeypatch.setattr(providers, "now_utc", lambda: datetime(2026, 11, 22, 0, 0, tzinfo=timezone.utc))
    seen = {}

    def fake_get(url, headers):
        seen.update(url=url, headers=headers)
        return GROK_BODY

    monkeypatch.setattr(providers, "_get", fake_get)
    snap = fetch_grok(tmp_path)
    assert seen["url"] == providers.GROK_USAGE_URL
    assert seen["headers"]["Authorization"] == "Bearer a.b.c"
    assert snap.plan == "team"


def test_fetch_grok_without_login(tmp_path):
    (tmp_path / "auth.json").write_text("{}")
    with pytest.raises(FetchError, match="grok login"):
        fetch_grok(tmp_path)
