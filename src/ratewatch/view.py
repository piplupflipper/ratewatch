"""TUI の画面。

1 アカウントを 1 行にして、左に使用率と残り時間、右端に短い時間軸を置く。
時間軸には、各枠のリセット時刻に印と枠の名前（5h、週、月、積）を置き、枠の種類で色を分ける。

縦幅は「軸の日付 1 行 + アカウント数 + 凡例 1 行」に抑える。
tmux で btop などと上下に並べて常時表示する使い方を想定し、ヘッダ、空行、
ステータス行、フッタは置かず、キー操作の案内と取得時刻も凡例の行に入れる。

時間軸は 1 マスあたりの時間を固定する（既定は 2 時間）。
表示する範囲を軸の幅に引き伸ばすと、1 日あたりのマス数が半端になり、目盛りの位置を整数に丸めたときに間隔がそろわないため。
軸の幅からは表示する日数のほうを決めるので、端末を広げると表示する日付の範囲が広がる。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.text import Text

from .collect import fmt_duration
from .model import AccountState, Window
from .theme import C, pct_color

AXIS_MIN = 18
# 1 日あたりのマス数。←→ で切り替える。1 マスはそれぞれ 6 時間、2 時間、1 時間
ZOOMS = [4, 12, 24]
DEFAULT_ZOOM = 1
# 日付のラベル（10/09）は 5 マスなので、間を 1 マス空けて 6 マス以上の間隔で置く
LABEL_CELLS = 6
SEG_W = 27

SHORT_LABEL = {
    "クレジット": "積",
    "請求サイクル": "月",
    "週 Opus": "週O",
    "週 Sonnet": "週S",
}


def short(label: str, width: int = 0) -> str:
    """枠の短い名前。width を渡すと、全角を 2 マスとして数えて右を空白で埋める。"""
    s = SHORT_LABEL.get(label, label)
    return s + " " * max(0, width - cell_len(s))


def kind_of(w: Window) -> str:
    if w.label.startswith("5h"):
        return "5h"
    if w.label.startswith("週"):
        return "week"
    return {"請求サイクル": "month", "クレジット": "credit"}.get(w.label, "other")


def is_passed(w: Window, now: datetime) -> bool:
    return w.resets_at is not None and w.resets_at <= now


def effective_pct(w: Window, now: datetime) -> float | None:
    """リセット時刻を過ぎた枠は 0% として扱う（使っていない間に保存した値でも、リセット後は空いている）。"""
    return 0.0 if is_passed(w, now) else w.used_percent


def _future(w: Window, now: datetime) -> bool:
    return w.resets_at is not None and not is_passed(w, now)


def _at(w: Window) -> datetime:
    """_future で確かめた後の枠のリセット時刻。"""
    assert w.resets_at is not None
    return w.resets_at


def _windows(st: AccountState) -> list[Window]:
    return st.snapshot.windows if st.snapshot else []


class MiniAxis:
    """右端の短い時間軸。位置 0 が「今」で、1 マスは 1 日 / cells_per_day。"""

    def __init__(self, now: datetime, width: int, cells_per_day: int) -> None:
        self.now, self.width, self.cpd = now, width, cells_per_day
        self.cell = timedelta(days=1) / cells_per_day

    @property
    def span(self) -> timedelta:
        return self.cell * self.width

    def x(self, dt: datetime) -> int:
        """dt の位置。範囲より先は width を返す。位置 0 は「今」の印なので、直近のリセットも 1 以上にする。"""
        p = round((dt - self.now) / self.cell)
        return self.width if p >= self.width else max(1, p)

    def tick_positions(self) -> list[tuple[int, datetime]]:
        """日付が変わる位置。最初の位置から cells_per_day ずつ足すので、間隔は必ず一定になる。"""
        local = self.now.astimezone()
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            days=1
        )
        first = round((midnight - local) / self.cell)
        out = []
        k = 0
        while first + k * self.cpd < self.width:
            # 日付が変わる直前は最初の目盛りが位置 0（「今」の印）に丸められるので外す
            if first + k * self.cpd > 0:
                out.append((first + k * self.cpd, midnight + timedelta(days=k)))
            k += 1
        return out

    def header(self) -> Text:
        cells = [" "] * self.width
        cells[0], cells[1] = "今", ""  # 「今」は全角で 2 マスを使う
        # 1 日のマス数がラベルより狭いときは、何日かおきにラベルを置く
        every = max(1, math.ceil(LABEL_CELLS / self.cpd))
        for i, (p, day) in enumerate(self.tick_positions()):
            lab = day.strftime("%m/%d")
            if i % every or p < 3 or p + len(lab) > self.width:
                continue
            cells[p : p + len(lab)] = list(lab)
        return Text("".join(cells), style=C.muted)

    def line(self, marks: list[tuple[int, Text]]) -> Text:
        """marks は（位置, 印）の一覧。印は枠の名前を含んで 2 マス以上になることがある。"""
        cells: list[Text] = [Text("─", style=C.faint) for _ in range(self.width)]
        for p, _ in self.tick_positions():
            cells[p] = Text("┼", style=C.faint)
        cells[0] = Text("│", style=C.muted)
        for p, mark in marks:
            i = p
            for j in range(len(mark.plain)):
                ch = mark[j : j + 1]
                wide = ch.cell_len == 2
                if i + (2 if wide else 1) > self.width:
                    break
                cells[i] = ch
                if wide:
                    cells[i + 1] = Text("")  # 全角の 2 マス目
                i += 2 if wide else 1
        return Text("").join(cells)


def axis_marks(st: AccountState, ax: MiniAxis, now: datetime) -> list[tuple[int, Text]]:
    """各枠のリセット位置に「◆ + 枠の名前」を置く。色は枠の種類で決める。

    次の印と重なるときは名前を省いて印だけにする。
    範囲より先の枠は、右端に名前を並べてから ▸ を 1 つ置く（「週 積▸」）。
    """
    inside, beyond = [], []
    for w in _windows(st):
        if not _future(w, now):
            continue
        p = ax.x(_at(w))
        (beyond if p >= ax.width else inside).append((p, w))
    inside.sort(key=lambda r: r[0])
    beyond.sort(key=lambda r: _at(r[1]))

    tail = Text()
    if beyond:
        for i, (_, w) in enumerate(beyond):
            if i:
                tail.append(" ")
            tail.append(short(w.label), style=C.kind(kind_of(w)))
        tail.append("▸", style=C.kind(kind_of(beyond[-1][1])))
    # 右端の名前が入りきらないときは ▸ だけにする
    tail_start = ax.width - tail.cell_len
    if beyond and tail_start <= (inside[-1][0] + 1 if inside else 1):
        tail = Text("▸", style=C.kind(kind_of(beyond[-1][1])))
        tail_start = ax.width - 1

    out: list[tuple[int, Text]] = []
    for i, (p, w) in enumerate(inside):
        color = C.kind(kind_of(w))
        tag = Text(short(w.label), style=color)
        nxt = (
            inside[i + 1][0]
            if i + 1 < len(inside)
            else (tail_start if beyond else ax.width)
        )
        mark = Text("◆", style=color)
        out.append((p, mark + tag if p + 1 + tag.cell_len < nxt else mark))
    if beyond:
        out.append((tail_start, tail))
    return out


# ---- 左の列 ----


def _status_dot(st: AccountState) -> Text:
    if st.snapshot is None:
        return Text("✕", style=C.err)
    if st.error or st.stale:
        return Text("◐", style=C.warn)
    return Text("●", style=C.faint)


def _pct(p: float | None) -> Text:
    return Text(f"{p:3.0f}%" if p is not None else "  -", style=pct_color(p))


def _remain(w: Window, now: datetime) -> Text:
    if w.resets_at is None:
        return Text("", style=C.muted)
    if is_passed(w, now):
        return Text("済", style=C.ok)
    return Text(fmt_duration((w.resets_at - now).total_seconds()), style=C.muted)


def line_gauge(p: float | None, width: int) -> Text:
    """細い線のゲージ。埋まった部分は ━、空きは ─。半マスは ╸ で描く。"""
    if p is None:
        return Text("─" * width, style=C.faint)
    halves = round(max(0.0, min(100.0, p)) / 100 * width * 2)
    full, half = divmod(halves, 2)
    t = Text("━" * full, style=pct_color(p))
    if half:
        t.append("╸", style=pct_color(p))
    t.append("─" * (width - full - half), style=C.track)
    return t


def segment(w: Window, now: datetime) -> Text:
    """左の列の 1 枠ぶん。「週 ━━━━━━━━──  82% 1d04h」。"""
    p = effective_pct(w, now)
    return Text.assemble(
        (short(w.label, 3), C.muted),
        line_gauge(p, 10),
        " ",
        _pct(p),
        " ",
        _remain(w, now),
    )


def _name(st: AccountState, name_w: int) -> Text:
    return Text.assemble(
        " ", _status_dot(st), " ", (f"{st.name:<{name_w}}", C.fg), "  "
    )


def _footer(ax: MiniAxis, width: int, status: str = "") -> Text:
    """凡例、ズームの状態、キー操作の案内、取得時刻を 1 行にまとめる。幅を超える分は右を落とす。"""
    t = Text(no_wrap=True, overflow="ellipsis")
    for kind, label in [
        ("5h", "5h"),
        ("week", "週"),
        ("month", "月"),
        ("credit", "積"),
    ]:
        t.append(f"◆{label}", style=C.kind(kind))
        t.append("  ")
    t.append("  1 マス ", style=C.faint)
    t.append(f"{ax.cell.total_seconds() / 3600:g}h", style=C.accent)
    t.append(f"  表示 {ax.span.total_seconds() / 86400:.1f} 日", style=C.faint)
    t.append("  ←→ 拡大縮小  r 再取得  q 終了", style=C.faint)
    if status:
        t.append("  " + status, style=C.muted)
    t.truncate(width, overflow="ellipsis")
    return t


def render(
    states: list[AccountState],
    now: datetime,
    width: int,
    zoom: int = DEFAULT_ZOOM,
    status: str = "",
) -> RenderableType:
    name_w = max([len(s.name) for s in states] + [6])
    head_w = 3 + name_w + 2
    left_w = head_w + 2 * SEG_W
    axis_w = width - left_w - 2
    ax = MiniAxis(now, max(axis_w, AXIS_MIN), ZOOMS[zoom % len(ZOOMS)])
    show_axis = axis_w >= AXIS_MIN
    out: list[RenderableType] = []
    if show_axis:
        out.append(Text(" " * (left_w + 2)) + ax.header())
    for st in states:
        segs = [segment(w, now) for w in _windows(st)]
        if st.kind == "cursor" and st.snapshot and st.snapshot.note:
            segs.append(Text(st.snapshot.note.replace("プラン枠 ", ""), style=C.faint))
        chunks = [segs[i : i + 2] for i in range(0, len(segs), 2)] or [[]]
        for i, chunk in enumerate(chunks):
            t = _name(st, name_w) if i == 0 else Text(" " * head_w)
            for sg in chunk:
                sg = sg.copy()
                sg.truncate(SEG_W, pad=True)
                t.append_text(sg)
            t.pad_right(left_w - t.cell_len)
            if show_axis and i == 0:
                t.append("  ")
                t.append_text(ax.line(axis_marks(st, ax, now)))
            out.append(t)
        if st.error:
            out.append(Text(" " * head_w + st.error, style=C.err))
    out.append(_footer(ax, width, status))
    return Group(*out)
