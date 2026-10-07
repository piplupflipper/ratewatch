"""TUI の描画パターン。

どのパターンも、アカウントの状態の一覧と現在時刻と描画幅を受け取り、rich の renderable を返す純粋な関数である。
Textual 側はこれを毎秒呼び直して、残り時間を数え直す。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .collect import fmt_ago, fmt_duration
from .model import AccountState, Window
from .theme import C, pct_color

# ---- 共通の部品 ----

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


def pct_style(pct: float | None) -> str:
    return pct_color(pct)


def is_passed(w: Window, now: datetime) -> bool:
    return w.resets_at is not None and w.resets_at <= now


def effective_pct(w: Window, now: datetime) -> float | None:
    """リセット時刻を過ぎた枠は 0% として扱う（使っていない間に保存した値でも、リセット後は空いている）。"""
    return 0.0 if is_passed(w, now) else w.used_percent


def bar(pct: float | None, width: int) -> Text:
    """1/8 刻みのブロック文字で描くゲージ。"""
    width = max(1, width)
    if pct is None:
        return Text("·" * width, style=C.muted)
    cells = max(0.0, min(100.0, pct)) / 100 * width
    full = int(cells)
    part = int((cells - full) * 8)
    t = Text("█" * full, style=pct_style(pct))
    if full < width:
        # 途中のマスは残りの部分に空き部分と同じ色を敷き、ゲージに切れ目ができないようにする
        t.append(" ▏▎▍▌▋▊▉"[part] if part else "", style=f"{pct_style(pct)} on {C.track}")
        rest = width - full - (1 if part else 0)
        t.append("█" * rest, style=C.track)
    return t


def fmt_reset(dt: datetime, now: datetime) -> str:
    local = dt.astimezone()
    if local.date() == now.astimezone().date():
        return local.strftime("%H:%M")
    return local.strftime("%m/%d %H:%M")


def remaining(w: Window, now: datetime) -> Text:
    if w.resets_at is None:
        return Text("-", style=C.muted)
    if is_passed(w, now):
        return Text("リセット済", style=C.ok)
    return Text(fmt_duration((w.resets_at - now).total_seconds()))


def glyph(st: AccountState) -> Text:
    if st.snapshot is None:
        return Text("✕", style=f"bold {C.err}")
    if st.error or st.stale:
        return Text("◐", style=C.warn)
    return Text("●", style=C.ok)


def plan_of(st: AccountState) -> str:
    return st.snapshot.plan if st.snapshot and st.snapshot.plan else st.kind


def freshness(st: AccountState, now: datetime) -> Text:
    if st.snapshot is None:
        return Text("未取得", style=C.err)
    return Text(
        fmt_ago(st.snapshot.fetched_at, now), style=C.warn if st.stale else C.muted
    )




# ---- 1. カード型 ----


def card(st: AccountState, now: datetime, width: int) -> Panel:
    lines: list[RenderableType] = []
    bar_w = max(6, width - 15)
    snap = st.snapshot
    if snap:
        for w in snap.windows:
            p = effective_pct(w, now)
            line = Text.assemble((short(w.label, 4), "bold"), bar(p, bar_w))
            line.append(f" {p:3.0f}%" if p is not None else "    -", style=pct_style(p))
            lines.append(line)
            sub = Text("    ")
            if w.resets_at:
                sub.append(f"↻ {fmt_reset(w.resets_at, now)}  ", style=C.muted)
                sub.append_text(remaining(w, now))
            lines.append(sub)
        if snap.note:
            lines.append(
                Text(f"    {snap.note}", style=C.muted, overflow="ellipsis", no_wrap=True)
            )
    if st.error:
        lines.append(Text(st.error, style=C.err))
    title = Text.assemble(
        glyph(st), " ", (st.name, "bold"), (f" · {plan_of(st)}", C.muted)
    )
    return Panel(
        Group(*lines) if lines else Text("-", style=C.muted),
        title=title,
        title_align="left",
        subtitle=freshness(st, now),
        subtitle_align="right",
        border_style=C.warn if st.error else C.faint,
        width=width,
        padding=(0, 1),
    )


def render_cards(
    states: list[AccountState], now: datetime, width: int, **_
) -> RenderableType:
    cols = max(1, min(len(states) or 1, width // 42))
    card_w = width // cols
    grid = Table.grid(padding=0)
    for _ in range(cols):
        grid.add_column(width=card_w)
    for i in range(0, len(states), cols):
        row = [card(st, now, card_w) for st in states[i : i + cols]]
        grid.add_row(*row)
    return grid


# ---- 2. タイムライン型 ----

TIMELINE_RANGES = [timedelta(hours=24), timedelta(days=7), timedelta(days=30)]


def _range_name(r: timedelta) -> str:
    return f"{r.days}d" if r.days else f"{int(r.total_seconds() // 3600)}h"


def _ticks(now: datetime, span: timedelta) -> list[tuple[datetime, str]]:
    local = now.astimezone()
    if span <= timedelta(hours=24):
        start = local.replace(minute=0, second=0, microsecond=0)
        step, fmt = timedelta(hours=3), "%H:%M"
        t = start + timedelta(hours=3 - start.hour % 3)
    else:
        step = timedelta(days=1 if span <= timedelta(days=7) else 5)
        fmt = "%m/%d"
        t = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    out = []
    while t - local < span:
        out.append((t, t.strftime(fmt)))
        t += step
    return out


def render_timeline(
    states: list[AccountState], now: datetime, width: int, span_index: int = 1, **_
) -> RenderableType:
    span = TIMELINE_RANGES[span_index % len(TIMELINE_RANGES)]
    name_w = min(24, max([len(s.name) for s in states] + [8]) + 3)
    axis_w = max(20, width - name_w - 2)

    def pos(dt: datetime) -> int:
        return int((dt - now) / span * (axis_w - 1))

    # 目盛りの行と、日時のラベルの行
    tick_line = [" "] * axis_w
    label_line = [" "] * axis_w
    tick_line[0] = "│"
    # 「今」は全角で 2 マスを使うので、2 マス目を空文字にしておく
    label_line[0], label_line[1] = "今", ""
    for t, lab in _ticks(now, span):
        p = pos(t)
        if 2 < p < axis_w:
            tick_line[p] = "│"
            if p + len(lab) <= axis_w and all(
                c == " " for c in label_line[max(0, p - 1) : p + len(lab)]
            ):
                label_line[p : p + len(lab)] = list(lab)
    out: list[RenderableType] = [
        Text(" " * name_w + "".join(label_line), style=C.muted),
        Text(" " * name_w + "".join(tick_line), style=C.faint),
    ]

    for st in states:
        line = Text()
        line.append_text(glyph(st))
        line.append(f" {st.name[: name_w - 3]:<{name_w - 3}} ")
        axis = Text("·" * axis_w, style=C.track)
        axis.stylize("bold", 0, 1)
        detail = Text(" " * name_w)
        windows = st.snapshot.windows if st.snapshot else []
        for w in windows:
            p_eff = effective_pct(w, now)
            style = pct_style(p_eff)
            if w.resets_at is None or is_passed(w, now):
                continue
            # 位置 0 は「今」の印なので、直近のリセットも 1 マス目に置く
            p = max(1, pos(w.resets_at))
            mark = "◆" if p < axis_w else "▶"
            p = min(p, axis_w - 1)
            axis = axis[:p] + Text(mark, style=style) + axis[p + 1 :]
        line.append_text(Text("●", style="bold") + axis[1:])
        for w in windows:
            p_eff = effective_pct(w, now)
            detail.append("◆ ", style=pct_style(p_eff))
            detail.append(f"{short(w.label)} ")
            detail.append(
                f"{p_eff:.0f}% " if p_eff is not None else "- ", style=pct_style(p_eff)
            )
            if w.resets_at:
                detail.append(f"↻{fmt_reset(w.resets_at, now)}", style=C.muted)
            detail.append("   ")
        if st.error:
            detail.append(st.error, style=C.err)
        out += [line, detail]

    out.append(Text(""))
    out.append(
        Text.assemble(
            ("◆ リセット  ▶ 範囲より先  ", C.muted),
            ("■ ", C.low),
            ("<70%  ", C.muted),
            ("■ ", C.mid),
            ("<90%  ", C.muted),
            ("■ ", C.high),
            ("<100%  ", C.muted),
            ("■ ", C.full),
            ("100%", C.muted),
            (f"     範囲 {_range_name(span)} (←→)", "bold"),
        )
    )
    return Group(*out)


# ---- 3. コンパクト一覧型 ----


def render_compact(
    states: list[AccountState], now: datetime, width: int, **_
) -> RenderableType:
    name_w = max(len(s.name) for s in states) if states else 8
    seg_w = 26
    per_line = max(1, (width - name_w - 4) // seg_w)
    rule = Text("─" * width, style=C.track)
    out: list[RenderableType] = [rule]
    for st in states:
        head = Text.assemble(
            " ", glyph(st), " ", (f"{st.name:<{name_w}}", "bold"), "  "
        )
        segs: list[Text] = []
        for w in st.snapshot.windows if st.snapshot else []:
            p = effective_pct(w, now)
            s = Text.assemble((short(w.label, 4), "bold"), bar(p, 8))
            s.append(f" {p:3.0f}% " if p is not None else "    - ", style=pct_style(p))
            s.append_text(remaining(w, now) if w.resets_at else Text("-", style=C.muted))
            s.pad_right(seg_w - s.cell_len)
            segs.append(s)
        if st.snapshot and st.snapshot.note and st.kind == "cursor":
            segs.append(Text(st.snapshot.note.replace("プラン枠 ", ""), style=C.muted))
        lines = [segs[i : i + per_line] for i in range(0, len(segs), per_line)] or [[]]
        for i, chunk in enumerate(lines):
            t = head.copy() if i == 0 else Text(" " * head.cell_len)
            for s in chunk:
                t.append_text(s)
            out.append(t)
        if st.error:
            out.append(Text(" " * head.cell_len + st.error, style=C.err))
    out.append(rule)
    return Group(*out)


# ---- 4. 「次に空く」優先型 ----


@dataclass
class _Slot:
    st: AccountState
    w: Window
    at: datetime


def render_next(
    states: list[AccountState], now: datetime, width: int, **_
) -> RenderableType:
    usable: list[Text] = []
    blocked: list[Text] = []
    unknown: list[Text] = []
    slots: list[_Slot] = []
    for st in states:
        if st.snapshot is None:
            unknown.append(
                Text.assemble((st.name, "bold"), (f"  {st.error or '未取得'}", C.err))
            )
            continue
        ws = st.snapshot.windows
        slots += [_Slot(st, w, w.resets_at) for w in ws if w.resets_at and not is_passed(w, now)]
        full = [w for w in ws if (effective_pct(w, now) or 0) >= 100]
        if full:
            # 使い切った枠のうち、最後にリセットされるものが空く時刻
            free_at = max((w.resets_at for w in full if w.resets_at), default=None)
            t = Text.assemble((st.name, "bold"), "  ")
            t.append(", ".join(f"{short(w.label)} 100%" for w in full), style=C.err)
            if free_at:
                t.append(
                    f"  → {fmt_reset(free_at, now)} ({fmt_duration((free_at - now).total_seconds())})",
                    style=C.muted,
                )
            blocked.append(t)
        else:
            t = Text.assemble((st.name, "bold"), "  ")
            for w in ws:
                p = effective_pct(w, now)
                t.append(f"{short(w.label)} ", style=C.muted)
                t.append(f"{p:.0f}%  " if p is not None else "-  ", style=pct_style(p))
            usable.append(t)
        if st.stale:
            (blocked if full else usable)[-1].append("  ◐ 古い値", style=C.warn)

    head = Table.grid(padding=(0, 2))
    head.add_column(style="bold", width=12)
    head.add_column()

    def section(label: str, items: list[Text], style: str) -> None:
        for i, it in enumerate(items):
            head.add_row(Text(label if i == 0 else "", style=style), it)

    section("今使える", usable, C.ok)
    section("使えない", blocked, C.err)
    section("不明", unknown, C.warn)
    slots.sort(key=lambda s: s.at)
    if slots:
        n = slots[0]
        head.add_row(Text(""), Text(""))
        head.add_row(
            Text("次のリセット", style=f"bold {C.accent}"),
            Text.assemble(
                (f"{n.st.name} {short(n.w.label)}", "bold"),
                f"   ↻ {fmt_reset(n.at, now)}   ",
                (fmt_duration((n.at - now).total_seconds()), f"bold {C.accent}"),
            ),
        )

    table = Table(
        box=None, padding=(0, 2), show_header=True, header_style=C.muted, expand=False
    )
    for c, j in [
        ("残り", "right"),
        ("リセット", "left"),
        ("アカウント", "left"),
        ("枠", "left"),
        ("使用率", "left"),
    ]:
        table.add_column(c, justify=j)
    for s in slots:
        p = effective_pct(s.w, now)
        table.add_row(
            remaining(s.w, now),
            fmt_reset(s.at, now),
            s.st.name,
            short(s.w.label),
            Text.assemble(
                bar(p, 8), (f" {p:3.0f}%" if p is not None else "   -", pct_style(p))
            ),
        )
    rule = Text("── リセットが近い順 " + "─" * max(0, width - 22), style=C.faint)
    return Group(head, Text(""), rule, table)



# ---- 組み合わせ型で共有する時間軸 ----


@dataclass
class _Axis:
    now: datetime
    span: timedelta
    width: int

    def pos(self, dt: datetime) -> int:
        """dt の位置。範囲より先は width を返す。位置 0 は「今」なので、直近のリセットも 1 以上にする。"""
        p = int((dt - self.now) / self.span * (self.width - 1))
        return self.width if p >= self.width else max(1, p)

    def header(self) -> tuple[Text, Text]:
        """日時のラベルの行と、目盛りの行。"""
        labels = [" "] * self.width
        ticks = [" "] * self.width
        labels[0], labels[1] = "今", ""  # 「今」は全角で 2 マスを使う
        ticks[0] = "│"
        for t, lab in _ticks(self.now, self.span):
            p = int((t - self.now) / self.span * (self.width - 1))
            if 2 < p < self.width:
                ticks[p] = "┆"
                if p + len(lab) <= self.width and all(c == " " for c in labels[p - 1 : p + len(lab)]):
                    labels[p : p + len(lab)] = list(lab)
        return Text("".join(labels), style=C.muted), Text("".join(ticks), style=C.faint)

    def grid(self) -> list[str]:
        """目盛りの位置にだけ点線を置いた、空の行の地。"""
        g = [" "] * self.width
        for t, _ in _ticks(self.now, self.span):
            p = int((t - self.now) / self.span * (self.width - 1))
            if 2 < p < self.width:
                g[p] = "┆"
        return g


def _span(span_index: int) -> timedelta:
    return TIMELINE_RANGES[span_index % len(TIMELINE_RANGES)]


def _span_hint(span: timedelta) -> Text:
    return Text.assemble(("←→ 範囲 ", C.muted), (_range_name(span), f"bold {C.accent}"))


def _windows(st: AccountState) -> list[Window]:
    return st.snapshot.windows if st.snapshot else []


def _segment(w: Window, now: datetime, bar_w: int = 6) -> Text:
    """コンパクト一覧の 1 枠ぶん。「週 ████▊█  79% 1d20h」（後ろの █ は空き部分の色）。"""
    p = effective_pct(w, now)
    s = Text.assemble((short(w.label, 3), C.muted), bar(p, bar_w))
    s.append(f" {p:3.0f}%" if p is not None else "    -", style=pct_style(p))
    s.append(" ")
    rem = remaining(w, now)
    rem.stylize(C.muted)
    s.append_text(rem)
    return s


def _name_cell(st: AccountState, name_w: int) -> Text:
    return Text.assemble(" ", glyph(st), " ", (f"{st.name:<{name_w}}", f"bold {C.fg}"), " ")


# ---- A. 右端ミニ軸 ----


def render_mini(states: list[AccountState], now: datetime, width: int, span_index: int = 1, **_) -> RenderableType:
    span = _span(span_index)
    name_w = max([len(s.name) for s in states] + [6])
    seg_w = 24
    left_w = 3 + name_w + 1 + 2 * seg_w
    axis_w = width - left_w - 1
    show_axis = axis_w >= 16
    ax = _Axis(now, span, max(axis_w, 16))
    out: list[RenderableType] = []
    if show_axis:
        lab, tick = ax.header()
        out += [Text(" " * left_w) + lab, Text(" " * left_w) + tick]
    for st in states:
        ws = _windows(st)
        segs = [_segment(w, now) for w in ws]
        if st.snapshot and st.snapshot.note and st.kind == "cursor":
            segs.append(Text(st.snapshot.note.replace("プラン枠 ", ""), style=C.muted))
        rows = [segs[i : i + 2] for i in range(0, len(segs), 2)] or [[]]
        for i, chunk in enumerate(rows):
            t = _name_cell(st, name_w) if i == 0 else Text(" " * (3 + name_w + 1))
            for sg in chunk:
                sg = sg.copy()
                sg.truncate(seg_w, pad=True)
                t.append_text(sg)
            t.pad_right(left_w - t.cell_len)
            if show_axis and i == 0:
                line = Text("".join(ax.grid()), style=C.faint)
                line = Text("·", style=C.faint) + line[1:]
                for w in ws:
                    if w.resets_at is None or is_passed(w, now):
                        continue
                    p = ax.pos(w.resets_at)
                    mark, p = ("▶", ax.width - 1) if p >= ax.width else ("◆", p)
                    line = line[:p] + Text(mark, style=pct_style(effective_pct(w, now))) + line[p + 1 :]
                t.append(" ")
                t.append_text(line)
            out.append(t)
        if st.error:
            out.append(Text(" " * (3 + name_w + 1) + st.error, style=C.err))
    out += [Text(""), Text.assemble(("◆ リセット  ▶ 範囲より先    ", C.muted), _span_hint(span))]
    return Group(*out)


# ---- B. ガント型 ----


def render_gantt(states: list[AccountState], now: datetime, width: int, span_index: int = 1, **_) -> RenderableType:
    span = _span(span_index)
    name_w = max([len(s.name) for s in states] + [6])
    left_w = 3 + name_w + 1 + 9
    ax = _Axis(now, span, max(20, width - left_w))
    lab, tick = ax.header()
    out: list[RenderableType] = [Text(" " * left_w) + lab, Text(" " * left_w) + tick]
    for st in states:
        ws = _windows(st) or [Window("-", None, None)]
        for i, w in enumerate(ws):
            p_eff = effective_pct(w, now)
            color = pct_style(p_eff)
            t = _name_cell(st, name_w) if i == 0 else Text(" " * (3 + name_w + 1))
            t.append(short(w.label, 3), style=C.muted)
            t.append(f"{p_eff:4.0f}% " if p_eff is not None else "    - ", style=color)
            line = Text("".join(ax.grid()), style=C.faint)
            if w.resets_at and not is_passed(w, now):
                end = ax.pos(w.resets_at)
                beyond = end >= ax.width
                end = ax.width - 1 if beyond else end
                stroke = "━" if (p_eff or 0) >= 100 else "─"
                # 低い使用率の線は地に近い色にして、使用率の高い枠だけが目に入るようにする
                line_color = C.faint if (p_eff or 0) < 70 else color
                line = Text(stroke * end, style=line_color) + Text("▶" if beyond else "◆", style=color) + line[end + 1 :]
                tag = fmt_reset(w.resets_at, now)
                if not beyond and end + 2 + len(tag) <= ax.width:
                    line = line[: end + 1] + Text(f" {tag}", style=C.muted) + line[end + 2 + len(tag) :]
                elif end - len(tag) - 1 > 0:
                    # 右に入りきらないときは、印の左の線の上に重ねて置く
                    line = line[: end - len(tag) - 1] + Text(f"{tag} ", style=C.muted) + line[end:]
            elif w.resets_at:
                done = Text("◇ リセット済", style=C.ok)
                line = done + line[done.cell_len :]
            t.append_text(line)
            out.append(t)
        if st.error:
            out.append(Text(" " * left_w + st.error, style=C.err))
    out += [
        Text(""),
        Text.assemble(
            ("─ リセットまで  ", C.muted),
            ("━ 使い切り（使えない期間）  ", C.full),
            ("◆ リセット  ▶ 範囲より先    ", C.muted),
            _span_hint(span),
        ),
    ]
    return Group(*out)


# ---- C. 上下 2 段 ----


def _initials(states: list[AccountState]) -> dict[str, str]:
    """アカウントごとに重ならない 1 文字を決める。名前の中で、まだ使われていない最初の英数字を選ぶ。"""
    used: set[str] = set()
    out: dict[str, str] = {}
    for st in states:
        # 「claude-private」なら区切りの後ろ（p）を優先する
        parts = st.name.replace("_", "-").split("-")
        cands = [c for c in (parts[-1] + st.name) if c.isalnum()]
        ch = next((c.upper() for c in cands if c.upper() not in used), "?")
        used.add(ch)
        out[st.name] = ch
    return out


def render_split(states: list[AccountState], now: datetime, width: int, span_index: int = 1, **_) -> RenderableType:
    span = _span(span_index)
    name_w = max([len(s.name) for s in states] + [6])
    initials = _initials(states)
    out: list[RenderableType] = []
    for st in states:
        segs = [_segment(w, now, bar_w=8) for w in _windows(st)]
        if st.snapshot and st.snapshot.note and st.kind == "cursor":
            segs.append(Text(st.snapshot.note.replace("プラン枠 ", ""), style=C.muted))
        t = _name_cell(st, name_w)
        for sg in segs:
            sg = sg.copy()
            sg.truncate(28, pad=True)
            t.append_text(sg)
        t.truncate(width)
        out.append(t)
        if st.error:
            out.append(Text(" " * (3 + name_w + 1) + st.error, style=C.err))
    out.append(Text(""))

    ax = _Axis(now, span, max(20, width - 2))
    lab, tick = ax.header()
    line = Text("●", style=f"bold {C.fg}") + Text("".join(ax.grid())[1:], style=C.faint)
    # 印の下に「頭文字 + 枠」のラベルを置く。重なるときは下の段へずらす
    label_rows: list[list[tuple[int, Text]]] = []
    occupied: list[set[int]] = []
    marks = []
    for st in states:
        for w in _windows(st):
            if w.resets_at is None or is_passed(w, now):
                continue
            p = ax.pos(w.resets_at)
            marks.append((min(p, ax.width - 1), p >= ax.width, st, w))
    marks.sort(key=lambda m: m[0])
    for p, beyond, st, w in marks:
        color = pct_style(effective_pct(w, now))
        line = line[:p] + Text("▶" if beyond else "◆", style=color) + line[p + 1 :]
        tag = Text.assemble((initials[st.name], f"bold {color}"), (short(w.label), C.muted))
        start = min(p, ax.width - tag.cell_len)
        cells = set(range(start, start + tag.cell_len + 1))
        for r, occ in enumerate(occupied):
            if not occ & cells:
                break
        else:
            r = len(occupied)
            occupied.append(set())
            label_rows.append([])
        occupied[r] |= cells
        label_rows[r].append((start, tag))
    rows: list[RenderableType] = [Text(" ") + lab, Text(" ") + tick, Text(" ") + line]
    for items in label_rows:
        t = Text(" ")
        for start, tag in sorted(items, key=lambda x: x[0]):
            t.pad_right(1 + start - t.cell_len)
            t.append_text(tag)
        rows.append(t)
    out += rows
    legend = Text(" ")
    for st in states:
        legend.append(initials[st.name], style=f"bold {C.fg}")
        legend.append(f" {st.name}   ", style=C.muted)
    out += [Text(""), legend, Text.assemble(" ", _span_hint(span))]
    return Group(*out)

VIEWS = {
    "cards": ("カード", render_cards),
    "timeline": ("タイムライン", render_timeline),
    "compact": ("コンパクト", render_compact),
    "next": ("次に空く", render_next),
    "mini": ("A. 右端ミニ軸", render_mini),
    "gantt": ("B. ガント", render_gantt),
    "split": ("C. 上下 2 段", render_split),
}
