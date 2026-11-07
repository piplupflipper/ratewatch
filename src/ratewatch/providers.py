"""各サービスの使用状況を取得する。

どの取得先も非公開 API であり、仕様は予告なく変わりうる。
トークンは各 CLI の認証ファイルをその場で読むだけで、更新（refresh）はしない。
更新すると CLI 側が持つ refresh token を無効にするおそれがあるため。
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path

from .model import FetchError, Snapshot, Window, now_utc, parse_ts, window_label

USER_AGENT = "ratewatch/0.1"
TIMEOUT = 15

CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
CURSOR_USAGE_URL = "https://cursor.com/api/usage-summary"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise FetchError(f"認証ファイルがない: {path}") from None
    except (OSError, ValueError) as e:
        raise FetchError(f"認証ファイルを読めない: {path}: {e}") from None


def _get(url: str, headers: dict[str, str]) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise FetchError(f"HTTP {e.code}: 要再ログイン") from None
        if e.code == 429:
            raise FetchError("HTTP 429: 取得の頻度制限") from None
        raise FetchError(f"HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise FetchError(f"接続失敗: {getattr(e, 'reason', e)}") from None
    except ValueError:
        raise FetchError("応答が JSON でない") from None


# ---- Claude ----


def fetch_claude(config_dir: Path) -> Snapshot:
    cred = _read_json(config_dir / ".credentials.json").get("claudeAiOauth") or {}
    token = cred.get("accessToken")
    if not token:
        raise FetchError("claudeAiOauth.accessToken がない")
    exp = parse_ts(cred.get("expiresAt"))
    if exp and exp <= now_utc():
        # 期限切れのトークンで叩いても 401 になるだけなので、叩かずに返す
        raise FetchError("トークン期限切れ（この設定ディレクトリで claude を起動すると更新される）")
    body = _get(CLAUDE_USAGE_URL, {"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"})
    return parse_claude(body, plan=cred.get("subscriptionType"))


_CLAUDE_WINDOWS = [
    ("five_hour", "5h"),
    ("seven_day", "週"),
    ("seven_day_opus", "週 Opus"),
    ("seven_day_sonnet", "週 Sonnet"),
]


def parse_claude(body: dict, plan: str | None = None) -> Snapshot:
    windows = []
    for key, label in _CLAUDE_WINDOWS:
        w = body.get(key)
        if isinstance(w, dict):
            windows.append(Window(label, w.get("utilization"), parse_ts(w.get("resets_at"))))
    return Snapshot(fetched_at=now_utc(), windows=windows, plan=plan)


# ---- Codex ----


def fetch_codex(codex_home: Path) -> Snapshot:
    tokens = _read_json(codex_home / "auth.json").get("tokens") or {}
    token = tokens.get("access_token")
    if not token:
        raise FetchError("tokens.access_token がない（API キー認証には未対応）")
    headers = {"Authorization": f"Bearer {token}"}
    if tokens.get("account_id"):
        headers["ChatGPT-Account-Id"] = tokens["account_id"]
    return parse_codex(_get(CODEX_USAGE_URL, headers))


def _is_zero(v: object) -> bool:
    """上限の値が 0 か。API は "0" のような文字列で返す。"""
    try:
        return v is not None and float(v) == 0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def parse_codex(body: dict) -> Snapshot:
    windows = []
    rl = body.get("rate_limit") or {}
    # 週の枠が primary に入るプランがあるので、primary/secondary の名前ではなく枠の長さで種類を決める
    for key in ("primary_window", "secondary_window"):
        w = rl.get(key)
        if isinstance(w, dict):
            windows.append(
                Window(window_label(w.get("limit_window_seconds")), w.get("used_percent"), parse_ts(w.get("reset_at")))
            )
    limit = (body.get("spend_control") or {}).get("individual_limit")
    if isinstance(limit, dict):
        if _is_zero(limit.get("limit")):
            # 上限が 0 だと、消費が 0 でも used_percent は 100 で返る。使い切ったのではなく使えない状態なので、無効として出す
            windows.append(Window("クレジット", None, None, disabled=True))
        else:
            windows.append(Window("クレジット", limit.get("used_percent"), parse_ts(limit.get("reset_at"))))
    note = None
    reached = body.get("rate_limit_reached_type")
    if isinstance(reached, dict) and reached.get("type"):
        note = reached["type"]
    return Snapshot(fetched_at=now_utc(), windows=windows, plan=body.get("plan_type"), note=note)


# ---- Cursor ----


def _jwt_sub(token: str) -> str:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))["sub"]
    except (IndexError, ValueError, KeyError):
        raise FetchError("accessToken から sub を読めない") from None


def fetch_cursor(auth_path: Path) -> Snapshot:
    token = _read_json(auth_path).get("accessToken")
    if not token:
        raise FetchError("accessToken がない（cursor-agent login が必要）")
    # cookie の値は「ユーザー ID::トークン」。ユーザー ID は sub の「|」より後ろ
    user_id = _jwt_sub(token).split("|")[-1]
    body = _get(CURSOR_USAGE_URL, {"Cookie": f"WorkosCursorSessionToken={user_id}%3A%3A{token}"})
    return parse_cursor(body)


def parse_cursor(body: dict) -> Snapshot:
    plan = ((body.get("individualUsage") or {}).get("plan")) or {}
    used = plan.get("totalPercentUsed")
    if used is None and plan.get("limit"):
        used = 100 * plan.get("used", 0) / plan["limit"]
    windows = [Window("請求サイクル", used, parse_ts(body.get("billingCycleEnd")))]
    note = None
    if plan.get("limit") is not None:
        note = f"プラン枠 {plan.get('used')}/{plan.get('limit')}"
    return Snapshot(fetched_at=now_utc(), windows=windows, plan=body.get("membershipType"), note=note)


FETCHERS = {
    "claude": fetch_claude,
    "codex": fetch_codex,
    "cursor": fetch_cursor,
}
