"""配色。

cocopon/iceberg.vim の colors/iceberg.vim（23835d5ed696436f716cbfdb56a93a7850fe3b18）のダーク版から取った。
背景は塗らず、端末の背景色をそのまま使う。
"""

from __future__ import annotations

from types import SimpleNamespace

from textual.theme import Theme

C = SimpleNamespace(
    fg="#c6c8d1",  # Normal
    muted="#6b7089",  # Comment
    faint="#444b71",  # LineNr の文字色
    track="#272c42",  # Visual の背景色
    low="#84a0c6",  # Function。使用率 70% 未満
    mid="#e2a478",  # Title。90% 未満
    high="#e98989",  # terminal_color_9。100% 未満
    full="#e27878",  # ErrorMsg。使い切り
    accent="#89b8c2",  # Identifier
)
C.ok, C.warn, C.err = C.low, C.mid, C.full

# 枠の種類の色。軸の印とラベルに使う
KIND_COLORS = {
    "5h": "#89b8c2",  # Identifier
    "week": "#a093c7",  # Constant
    "month": "#b4be82",  # PreProc
    "credit": "#c6c8d1",  # Normal
}
C.kind = lambda kind: KIND_COLORS.get(kind, C.muted)


def pct_color(pct: float | None) -> str:
    if pct is None:
        return C.muted
    if pct >= 100:
        return C.full
    if pct >= 90:
        return C.high
    if pct >= 70:
        return C.mid
    return C.low


# ヘッダーとフッターに当てる Textual のテーマ。背景は ansi_default にして端末の背景色を使う
ICEBERG = Theme(
    name="iceberg",
    primary="#84a0c6",
    secondary="#89b8c2",
    accent="#89b8c2",
    warning="#e2a478",
    error="#e27878",
    success="#b4be82",
    foreground="#c6c8d1",
    background="ansi_default",
    surface="ansi_default",
    panel="ansi_default",
    boost="ansi_default",
    dark=True,
    ansi=True,
    # ansi=True のテーマでは Textual の組み込みの CSS がこれらの変数を参照する（textual/theme.py の ansi-dark と同じ組）
    variables={
        "ansi-background": "#1e2132",  # terminal_color_0
        "ansi-foreground": "#c6c8d1",
        "border-blurred": "#1e2132",
        "block-cursor-foreground": "#161821",
        "block-cursor-background": "#c6c8d1",
        "input-cursor-background": "#c6c8d1",
        "input-cursor-foreground": "#161821",
        "input-cursor-text-style": "none",
        "input-selection-background": "#272c42",
        "input-selection-foreground": "#c6c8d1",
        "screen-selection-background": "#272c42",
        "screen-selection-foreground": "#c6c8d1",
    },
)
