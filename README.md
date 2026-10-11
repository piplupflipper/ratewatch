# ratewatch

Claude / Codex / Cursor の複数アカウントについて、レートリミットの使用率とリセット時刻を 1 画面に並べる TUI。

## 入れ方

```sh
uv tool install git+ssh://git@github.com/piplupflipper/ratewatch.git
ratewatch          # TUI
ratewatch --once   # 1 回取得して表を出力して終わる
```

## 画面

1 アカウントを 1 行にして、左に枠ごとの使用率と残り時間、右端に短い時間軸を置く。
時間軸には各枠のリセット時刻に印と枠の名前を置き、枠の種類で色を分ける（5h は水色、週は紫、月は緑、積は白）。
表示範囲より先にリセットされる枠は、右端に名前を並べて ▸ を付ける。

時間軸は 1 マスあたりの時間が一定で、目盛りの間隔は端末の幅によらずそろう。
端末を広げると、表示する日数が広がる。

| キー | 動作 |
|---|---|
| `←` `→` | 1 マスあたりの時間を 6 時間、2 時間、1 時間で切り替える |
| `r` | 再取得 |
| `q` | 終了 |

配色は Iceberg（cocopon/iceberg.vim）のダーク版で、背景は塗らずに端末の背景色を使う。

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
