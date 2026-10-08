"""右端ミニ軸の画面。

1 アカウントを 1 行にして、左に使用率と残り時間、右端に短い時間軸を置く。
時間軸には、各枠のリセット時刻に印と枠の名前（5h、週、月、積）を置く。

時間軸は 1 マスあたりの時間を固定する（既定は 2 時間）。
表示する範囲を軸の幅に引き伸ばすと、1 日あたりのマス数が半端になり、目盛りの位置を整数に丸めたときに間隔がそろわないため。
軸の幅からは表示する日数のほうを決めるので、端末を広げると表示する日付の範囲が広がる。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta

from rich.console import Group, RenderableType
from rich.text import Text

from .collect import fmt_duration
from .model import AccountState, Window
from .theme import C
from .views import effective_pct, is_passed, pct_style, short

AXIS_MIN = 18
# 1 日あたりのマス数。←→ で切り替える。1 マスはそれぞれ 6 時間、2 時間、1 時間
ZOOMS = [4, 12, 24]
DEFAULT_ZOOM = 1
# 日付のラベル（10/09）は 5 マスなので、間を 1 マス空けて 6 マス以上の間隔で置く
LABEL_CELLS = 6


def kind_of(w: Window) -> str:
    if w.label.startswith("5h"):
        return "5h"
    if w.label.startswith("週"):
        return "week"
    return {"請求サイクル": "month", "クレジット": "credit"}.get(w.label, "other")


SHAPES = {"5h": "●", "week": "◆", "month": "■", "credit": "▲"}


def _future(w: Window, now: datetime) -> bool:
    return w.resets_at is not None and not is_passed(w, now)


def _at(w: Window) -> datetime:
    """_future で確かめた後の枠のリセット時刻。"""
    assert w.resets_at is not None
    return w.resets_at


def _windows(st: AccountState) -> list[Window]:
    return st.snapshot.windows if st.snapshot else []


def _status_dot(st: AccountState) -> Text:
    if st.snapshot is None:
        return Text("✕", style=C.err)
    if st.error or st.stale:
        return Text("◐", style=C.warn)
    return Text("●", style=C.faint)


class MiniAxis:
    """右端の短い時間軸。位置 0 が「今」で、1 マスは 1 日 / cells_per_day。"""

    def __init__(
        self,
        now: datetime,
        width: int,
        cells_per_day: int,
        base: str = "─",
        tick: str = "┼",
    ) -> None:
        self.now, self.width, self.cpd = now, width, cells_per_day
        self.cell = timedelta(days=1) / cells_per_day
        self.base, self.tick = base, tick

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

    def line(self, marks: list[tuple[int, Text]], now_mark: str = "│") -> Text:
        """marks は（位置, 印）の一覧。印は枠の名前を含んで 2 マス以上になることがある。"""
        cells: list[Text] = [Text(self.base, style=C.faint) for _ in range(self.width)]
        for p, _ in self.tick_positions():
            cells[p] = Text(self.tick, style=C.faint)
        cells[0] = Text(now_mark, style=C.muted)
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


# ---- 色と形の決め方 ----

ColorFn = Callable[[Window, datetime], str]


def usage_color(w: Window, now: datetime) -> str:
    return pct_style(effective_pct(w, now))


def kind_color(w: Window, now: datetime) -> str:
    return C.kind(kind_of(w))


def diamond(w: Window) -> str:
    return "◆"


def shape(w: Window) -> str:
    return SHAPES.get(kind_of(w), "◆")


def labeled_marks(
    st: AccountState,
    ax: MiniAxis,
    now: datetime,
    mark_color: ColorFn,
    label_color: ColorFn,
    glyph: Callable[[Window], str] = diamond,
) -> list[tuple[int, Text]]:
    """印の右に枠の名前を書く。次の印と重なるときは名前を省いて印だけにする。"""
    raw = []
    for w in _windows(st):
        if not _future(w, now):
            continue
        p = ax.x(_at(w))
        raw.append((min(p, ax.width - 1), p >= ax.width, w))
    raw.sort(key=lambda r: r[0])
    out: list[tuple[int, Text]] = []
    for i, (p, beyond, w) in enumerate(raw):
        tag = Text(short(w.label), style=label_color(w, now))
        if beyond:
            # 範囲より先の印は右端にあるので、名前は左に置く
            start = p - tag.cell_len
            prev_end = out[-1][0] + out[-1][1].cell_len if out else 1
            if start > prev_end:
                out.append((start, tag))
            out.append((p, Text("▸", style=mark_color(w, now))))
            continue
        nxt = raw[i + 1][0] if i + 1 < len(raw) else ax.width
        mark = Text(glyph(w), style=mark_color(w, now))
        out.append((p, mark + tag if p + 1 + tag.cell_len < nxt else mark))
    return out


# ---- 左の列 ----


def _pct(p: float | None) -> Text:
    return Text(f"{p:3.0f}%" if p is not None else "  -", style=pct_style(p))


def _remain(w: Window, now: datetime) -> Text:
    if w.resets_at is None:
        return Text("", style=C.muted)
    if is_passed(w, now):
        return Text("済", style=C.ok)
    return Text(fmt_duration((w.resets_at - now).total_seconds()), style=C.muted)


def _line_gauge(p: float | None, width: int) -> Text:
    """細い線のゲージ。埋まった部分は ━、空きは ─。半マスは ╸ で描く。"""
    if p is None:
        return Text("─" * width, style=C.faint)
    halves = round(max(0.0, min(100.0, p)) / 100 * width * 2)
    full, half = divmod(halves, 2)
    t = Text("━" * full, style=pct_style(p))
    if half:
        t.append("╸", style=pct_style(p))
    t.append("─" * (width - full - half), style=C.track)
    return t


def segment(w: Window, now: datetime, label_color: ColorFn | None = None) -> Text:
    p = effective_pct(w, now)
    return Text.assemble(
        (short(w.label, 3), label_color(w, now) if label_color else C.muted),
        _line_gauge(p, 10),
        " ",
        _pct(p),
        " ",
        _remain(w, now),
    )


SEG_W = 27


def _name(st: AccountState, name_w: int) -> Text:
    return Text.assemble(
        " ", _status_dot(st), " ", (f"{st.name:<{name_w}}", C.fg), "  "
    )


def _footer(ax: MiniAxis, legend: Text | None) -> Text:
    hours = ax.cell.total_seconds() / 3600
    t = Text()
    if legend:
        t.append_text(legend)
        t.append("    ")
    t.append("1 マス ", style=C.faint)
    t.append(f"{hours:g}h", style=C.accent)
    t.append(f"  表示 {ax.span.total_seconds() / 86400:.1f} 日", style=C.faint)
    t.append("  ←→ 拡大縮小", style=C.faint)
    return t


def kind_legend(shapes: bool = False) -> Text:
    t = Text()
    for kind, label in [("5h", "5h"), ("week", "週"), ("month", "月"), ("credit", "積")]:
        t.append(f"{SHAPES[kind] if shapes else '◆'}{label}", style=C.kind(kind))
        t.append("  ")
    return t


def render_axis_view(
    states: list[AccountState],
    now: datetime,
    width: int,
    zoom: int,
    *,
    mark_color: ColorFn,
    label_color: ColorFn,
    left_label_color: ColorFn | None = None,
    glyph: Callable[[Window], str] = diamond,
    legend: Text | None = None,
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
        segs = [segment(w, now, left_label_color) for w in _windows(st)]
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
                t.append_text(
                    ax.line(labeled_marks(st, ax, now, mark_color, label_color, glyph))
                )
            out.append(t)
        if st.error:
            out.append(Text(" " * head_w + st.error, style=C.err))
    out += [Text(""), _footer(ax, legend)]
    return Group(*out)


# ---- 色分けの案 ----


def render_kind(states, now, width, span_index=DEFAULT_ZOOM, **_):
    """1. 印もラベルも種類の色。"""
    return render_axis_view(
        states,
        now,
        width,
        span_index,
        mark_color=kind_color,
        label_color=kind_color,
        legend=kind_legend(),
    )


def render_kind_split(states, now, width, span_index=DEFAULT_ZOOM, **_):
    """2. 印は使用率の色、ラベルは種類の色。"""
    return render_axis_view(
        states,
        now,
        width,
        span_index,
        mark_color=usage_color,
        label_color=kind_color,
        legend=kind_legend(),
    )


def render_kind_left(states, now, width, span_index=DEFAULT_ZOOM, **_):
    """3. 1 に加えて、左の列の枠名も種類の色にする。左の列が凡例を兼ねる。"""
    return render_axis_view(
        states,
        now,
        width,
        span_index,
        mark_color=kind_color,
        label_color=kind_color,
        left_label_color=kind_color,
    )


def render_kind_shape(states, now, width, span_index=DEFAULT_ZOOM, **_):
    """4. 3 に加えて、印の形も種類ごとに変える。"""
    return render_axis_view(
        states,
        now,
        width,
        span_index,
        mark_color=kind_color,
        label_color=kind_color,
        left_label_color=kind_color,
        glyph=shape,
        legend=kind_legend(shapes=True),
    )


def render_usage(states, now, width, span_index=DEFAULT_ZOOM, **_):
    """比較用。印もラベルも使用率の色（2026-10-07 の「軸にラベル」と同じ）。"""
    return render_axis_view(
        states, now, width, span_index, mark_color=usage_color, label_color=usage_color
    )


VARIANTS = {
    "kind": ("1. 種類の色", render_kind),
    "kind-split": ("2. 印は使用率、ラベルは種類", render_kind_split),
    "kind-left": ("3. 左の列も種類の色", render_kind_left),
    "kind-shape": ("4. 種類で形も変える", render_kind_shape),
    "usage": ("5. 使用率の色（比較用）", render_usage),
}
