# ratewatch

Claude / Codex / Cursor の複数アカウントについて、レートリミットの使用率とリセット時刻を 1 画面に並べる TUI。

## 入れ方

```sh
uv tool install git+ssh://git@github.com/ngmtine/ratewatch.git
ratewatch          # TUI（r で再取得、q で終了）
ratewatch --once   # 1 回取得して表を出力して終わる
```

## アカウントの設定

Claude Code と Codex は、アカウントごとに設定ディレクトリを分けて使う。
分けたディレクトリでそれぞれログインしておく。

```sh
CLAUDE_CONFIG_DIR=~/.claude-sub claude   # 起動して /login
CODEX_HOME=~/.codex-sub codex login
```

`~/.config/ratewatch/config.toml` にアカウントを並べる。
ファイルが無いときは `~/.claude`、`~/.codex`、`~/.config/cursor/auth.json` を 1 つずつ読む。

```toml
[[account]]
name = "claude-main"
kind = "claude"
dir = "~/.claude"

[[account]]
name = "claude-sub"
kind = "claude"
dir = "~/.claude-sub"

[[account]]
name = "codex-main"
kind = "codex"
dir = "~/.codex"

[[account]]
name = "cursor"
kind = "cursor"
auth = "~/.config/cursor/auth.json"   # cursor-agent login の認証ファイル
```

## 取得先と注意

どれも非公開 API で、仕様は予告なく変わりうる。

| kind | 認証ファイル | 取得先 | 出す枠 |
|---|---|---|---|
| claude | `<dir>/.credentials.json` | `api.anthropic.com/api/oauth/usage` | 5 時間枠、週の枠 |
| codex | `<dir>/auth.json` | `chatgpt.com/backend-api/wham/usage` | 5 時間枠と週の枠（プランによる）、ワークスペースのクレジット上限 |
| cursor | `~/.config/cursor/auth.json` | `cursor.com/api/usage-summary` | 月の請求サイクル |

- トークンは読むだけで更新しない。更新すると CLI 側の refresh token を無効にするおそれがあるため。
- Claude のアクセストークンは数時間で切れる。しばらく使っていないアカウントは取得に失敗し、最後に取得できた値（`~/.cache/ratewatch/snapshots.json`）を取得時刻と一緒に出す。使っていない間は使用量が増えないので、保存したリセット時刻は有効なままである。リセット時刻を過ぎた枠は「リセット済み」と出す。
- API は TUI を開いている間だけ 5 分ごとに叩く。
