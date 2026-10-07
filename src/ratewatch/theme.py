"""配色。

色はすべて truecolor で指定し、端末のテーマに左右されないようにする。
描画パターンは色名ではなく役割（low、muted など）で色を指定し、`C` を通して今の配色から引く。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    label: str
    textual_theme: str  # ヘッダーとフッターに当てる Textual のテーマ
    fg: str  # 本文
    muted: str  # 補助の文字（時刻、単位）
    faint: str  # 目盛りや区切り線
    track: str  # ゲージの空き部分、時間軸の地
    low: str  # 70% 未満
    mid: str  # 90% 未満
    high: str  # 100% 未満
    full: str  # 使い切り
    accent: str  # 強調（次のリセットなど）
    bg: str

    @property
    def ok(self) -> str:
        return self.low

    @property
    def warn(self) -> str:
        return self.mid

    @property
    def err(self) -> str:
        return self.full


PALETTES: dict[str, Palette] = {
    "mono": Palette(
        label="単色アクセント",
        textual_theme="atom-one-dark",
        fg="#c8ccd4",
        muted="#7f848e",
        faint="#4b5263",
        track="#353b45",
        low="#3d6487",
        mid="#4f8cc2",
        high="#61afef",
        full="#e06c75",
        accent="#61afef",
        bg="#282c34",
    ),
    "tokyo-night": Palette(
        label="Tokyo Night",
        textual_theme="tokyo-night",
        fg="#c0caf5",
        muted="#565f89",
        faint="#3b4261",
        track="#292e42",
        low="#7aa2f7",
        mid="#e0af68",
        high="#ff9e64",
        full="#f7768e",
        accent="#7dcfff",
        bg="#1a1b26",
    ),
    "catppuccin": Palette(
        label="Catppuccin Mocha",
        textual_theme="catppuccin-mocha",
        fg="#cdd6f4",
        muted="#6c7086",
        faint="#45475a",
        track="#313244",
        low="#a6e3a1",
        mid="#f9e2af",
        high="#fab387",
        full="#f38ba8",
        accent="#89b4fa",
        bg="#1e1e2e",
    ),
    "nord": Palette(
        label="Nord",
        textual_theme="nord",
        fg="#d8dee9",
        muted="#616e88",
        faint="#4c566a",
        track="#3b4252",
        low="#88c0d0",
        mid="#ebcb8b",
        high="#d08770",
        full="#bf616a",
        accent="#81a1c1",
        bg="#2e3440",
    ),
}
DEFAULT_THEME = "tokyo-night"

_active: Palette = PALETTES[DEFAULT_THEME]


def set_theme(name: str) -> Palette:
    global _active
    _active = PALETTES.get(name, PALETTES[DEFAULT_THEME])
    return _active


class _Current:
    """`C.low` のように書くと、その時点の配色の色を返す。"""

    def __getattr__(self, name: str) -> str:
        return getattr(_active, name)


C = _Current()


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
