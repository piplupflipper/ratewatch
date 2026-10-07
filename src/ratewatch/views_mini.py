"""右端ミニ軸（views.render_mini）の改良案。

どの案も、1 アカウントを 1 行にして左に使用率と残り時間、右端に短い時間軸を置く。
違うのは、使用率の見せ方と、時間軸の印の読ませ方である。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from rich.console import Group, RenderableType
from rich.text import Text

from .collect import fmt_duration
from .model import AccountState, Window
from .theme import C
from .views import (
    _range_name,
    _span,
    _ticks,
    effective_pct,
    fmt_reset,
    is_passed,
    pct_style,
    short,
)

AXIS_MIN = 18


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


def _is_blocked(st: AccountState, now: datetime) -> bool:
    return any((effective_pct(w, now) or 0) >= 100 for w in _windows(st))


class MiniAxis:
    """右端の短い時間軸。位置 0 が「今」。"""

    def __init__(
        self,
        now: datetime,
        span: timedelta,
        width: int,
        base: str = "·",
        tick: str = "┊",
    ) -> None:
        self.now, self.span, self.width = now, span, width
        self.base, self.tick = base, tick

    def x(self, dt: datetime) -> int:
        p = int((dt - self.now) / self.span * (self.width - 1))
        return min(max(1, p), self.width)  # width は範囲より先

    def _tick_positions(self) -> list[tuple[int, str]]:
        out = []
        for t, lab in _ticks(self.now, self.span):
            p = int((t - self.now) / self.span * (self.width - 1))
            if 2 < p < self.width:
                out.append((p, lab))
        return out

    def header(self) -> Text:
        cells = [" "] * self.width
        cells[0], cells[1] = "今", ""
        for p, lab in self._tick_positions():
            if p + len(lab) <= self.width and all(
                c == " " for c in cells[p - 1 : p + len(lab)]
            ):
                cells[p : p + len(lab)] = list(lab)
        return Text("".join(cells), style=C.muted)

    def line(self, marks: list[tuple[int, Text]], now_mark: str = "│") -> Text:
        """marks は（位置, 印）の一覧。印は枠の名前を含んで 2 マス以上になることがある。"""
        cells: list[Text] = [Text(self.base, style=C.faint) for _ in range(self.width)]
        for p, _ in self._tick_positions():
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


def _marks(
    st: AccountState, ax: MiniAxis, now: datetime, glyph: str = "◆"
) -> list[tuple[int, Text]]:
    out = []
    for w in _windows(st):
        if not _future(w, now):
            continue
        p = ax.x(_at(w))
        color = pct_style(effective_pct(w, now))
        out.append(
            (ax.width - 1, Text("▸", style=color))
            if p >= ax.width
            else (p, Text(glyph, style=color))
        )
    return out


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


def _layout(
    width: int,
    left_w: int,
    span_index: int,
    now: datetime,
    **axis_kw,
) -> tuple[int, MiniAxis]:
    span = _span(span_index)
    axis_w = width - left_w - 2
    return axis_w, MiniAxis(now, span, max(axis_w, AXIS_MIN), **axis_kw)


def _footer(span: timedelta, extra: list[tuple[str, str]] | None = None) -> Text:
    t = Text.assemble(*(extra or []))
    t.append("←→ ", style=C.faint)
    t.append(_range_name(span), style=C.accent)
    return t


def _name(st: AccountState, name_w: int, style: str | None = None) -> Text:
    return Text.assemble(
        " ", _status_dot(st), " ", (f"{st.name:<{name_w}}", style or C.fg), "  "
    )


def _errors(st: AccountState, indent: int) -> list[Text]:
    return [Text(" " * indent + st.error, style=C.err)] if st.error else []


def _assemble(
    states: list[AccountState],
    now: datetime,
    width: int,
    span_index: int,
    seg_fn,
    seg_w: int,
    *,
    marks_fn=_marks,
    axis_kw: dict | None = None,
    row_style=None,
    top: list[RenderableType] | None = None,
    legend: list[tuple[str, str]] | None = None,
) -> RenderableType:
    name_w = max([len(s.name) for s in states] + [6])
    head_w = 3 + name_w + 2
    left_w = head_w + 2 * seg_w
    axis_w, ax = _layout(width, left_w, span_index, now, **(axis_kw or {}))
    show_axis = axis_w >= AXIS_MIN
    out: list[RenderableType] = list(top or [])
    if show_axis:
        out.append(Text(" " * (left_w + 2)) + ax.header())
    for st in states:
        ws = _windows(st)
        segs = [seg_fn(w, now) for w in ws]
        if st.kind == "cursor" and st.snapshot and st.snapshot.note:
            segs.append(Text(st.snapshot.note.replace("プラン枠 ", ""), style=C.faint))
        chunks = [segs[i : i + 2] for i in range(0, len(segs), 2)] or [[]]
        for i, chunk in enumerate(chunks):
            t = (
                _name(st, name_w, row_style(st) if row_style else None)
                if i == 0
                else Text(" " * head_w)
            )
            for sg in chunk:
                sg = sg.copy()
                sg.truncate(seg_w, pad=True)
                t.append_text(sg)
            t.pad_right(left_w - t.cell_len)
            if show_axis and i == 0:
                t.append("  ")
                t.append_text(ax.line(marks_fn(st, ax, now)))
            if row_style and row_style(st) == C.muted:
                t.stylize(C.muted, 0, head_w)
            out.append(t)
        out += _errors(st, head_w)
    out += [Text(""), _footer(ax.span, legend)]
    return Group(*out)


# ---- 1. 文字だけ ----


def _seg_text(w: Window, now: datetime) -> Text:
    p = effective_pct(w, now)
    return Text.assemble((short(w.label, 3), C.muted), _pct(p), "  ", _remain(w, now))


def render_lean(
    states: list[AccountState], now: datetime, width: int, span_index: int = 1, **_
) -> RenderableType:
    return _assemble(states, now, width, span_index, _seg_text, 18)


# ---- 2. 線のゲージ ----


def _seg_line(w: Window, now: datetime) -> Text:
    p = effective_pct(w, now)
    return Text.assemble(
        (short(w.label, 3), C.muted),
        _line_gauge(p, 10),
        " ",
        _pct(p),
        " ",
        _remain(w, now),
    )


def render_line(
    states: list[AccountState], now: datetime, width: int, span_index: int = 1, **_
) -> RenderableType:
    return _assemble(
        states,
        now,
        width,
        span_index,
        _seg_line,
        27,
        axis_kw={"base": "─", "tick": "┼"},
        marks_fn=lambda st, ax, now: _marks(st, ax, now, glyph="●"),
    )


# ---- 3. 軸にラベル ----


def _labeled_marks(st: AccountState, ax: MiniAxis, now: datetime) -> list[tuple[int, Text]]:
    """印の右に枠の名前を書く。次の印と重なるときは名前を省いて印だけにする。"""
    raw = []
    for w in _windows(st):
        if not _future(w, now):
            continue
        p = ax.x(_at(w))
        beyond = p >= ax.width
        raw.append((min(p, ax.width - 1), beyond, short(w.label), pct_style(effective_pct(w, now))))
    raw.sort()
    out: list[tuple[int, Text]] = []
    for i, (p, beyond, label, color) in enumerate(raw):
        tag = Text(label, style=color)
        if beyond:
            # 範囲より先の印は右端にあるので、名前は左に置く
            start = p - tag.cell_len
            prev_end = out[-1][0] + out[-1][1].cell_len if out else 1
            if start > prev_end:
                out.append((start, tag))
            out.append((p, Text("▸", style=color)))
            continue
        nxt = raw[i + 1][0] if i + 1 < len(raw) else ax.width
        mark = Text("◆", style=color)
        out.append((p, mark + tag if p + 1 + tag.cell_len < nxt else mark))
    return out


def render_labeled(
    states: list[AccountState], now: datetime, width: int, span_index: int = 1, **_
) -> RenderableType:
    return _assemble(
        states,
        now,
        width,
        span_index,
        _seg_line,
        27,
        axis_kw={"base": "─", "tick": "┼"},
        marks_fn=_labeled_marks,
    )


# ---- 4. 次のリセットを強調 ----


def _next_reset(
    states: list[AccountState], now: datetime
) -> tuple[AccountState, Window] | None:
    cands = [
        (_at(w), st, w) for st in states for w in _windows(st) if _future(w, now)
    ]
    if not cands:
        return None
    _, st, w = min(cands, key=lambda c: c[0])
    return st, w


def render_focus(
    states: list[AccountState], now: datetime, width: int, span_index: int = 1, **_
) -> RenderableType:
    top: list[RenderableType] = []
    nxt = _next_reset(states, now)
    if nxt:
        st, w = nxt
        top.append(
            Text.assemble(
                (" 次のリセット  ", C.muted),
                (fmt_duration((_at(w) - now).total_seconds()), f"bold {C.accent}"),
                ("  ", ""),
                (f"{st.name} {short(w.label)}", C.fg),
                (f"  {fmt_reset(_at(w), now)}", C.muted),
            )
        )
    blocked = [s.name for s in states if _is_blocked(s, now)]
    if blocked:
        top.append(
            Text.assemble((" 使えない      ", C.muted), (", ".join(blocked), C.err))
        )
    top.append(Text(""))

    def row_style(st: AccountState) -> str:
        return C.muted if _is_blocked(st, now) else C.fg

    def marks(st: AccountState, ax: MiniAxis, now: datetime) -> list[tuple[int, Text]]:
        ms = _labeled_marks(st, ax, now)
        if nxt and st is nxt[0]:
            # 次にリセットされる枠の印だけを強調色にする
            p = ax.x(_at(nxt[1]))
            ms = [
                (q, Text(m.plain[:1], style=f"bold {C.accent}") + m[1:])
                if q == p
                else (q, m)
                for q, m in ms
            ]
        return ms

    return _assemble(
        states,
        now,
        width,
        span_index,
        _seg_line,
        27,
        axis_kw={"base": "─", "tick": "┼"},
        marks_fn=marks,
        row_style=row_style,
        top=top,
    )


VARIANTS = {
    "lean": ("1. 文字だけ", render_lean),
    "line": ("2. 線のゲージ", render_line),
    "labeled": ("3. 軸にラベル", render_labeled),
    "focus": ("4. 次のリセットを強調", render_focus),
}
