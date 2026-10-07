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
    if pct is None:
        return "dim"
    return "red" if pct >= 90 else "yellow" if pct >= 70 else "green"


def is_passed(w: Window, now: datetime) -> bool:
    return w.resets_at is not None and w.resets_at <= now


def effective_pct(w: Window, now: datetime) -> float | None:
    """リセット時刻を過ぎた枠は 0% として扱う（使っていない間に保存した値でも、リセット後は空いている）。"""
    return 0.0 if is_passed(w, now) else w.used_percent


def bar(pct: float | None, width: int) -> Text:
    """1/8 刻みのブロック文字で描くゲージ。"""
    width = max(1, width)
    if pct is None:
        return Text("·" * width, style="dim")
    cells = max(0.0, min(100.0, pct)) / 100 * width
    full = int(cells)
    part = int((cells - full) * 8)
    t = Text("█" * full, style=pct_style(pct))
    if full < width:
        t.append(" ▏▎▍▌▋▊▉"[part] if part else "", style=pct_style(pct))
        rest = width - full - (1 if part else 0)
        t.append("░" * rest, style="grey30")
    return t


def fmt_reset(dt: datetime, now: datetime) -> str:
    local = dt.astimezone()
    if local.date() == now.astimezone().date():
        return local.strftime("%H:%M")
    return local.strftime("%m/%d %H:%M")


def remaining(w: Window, now: datetime) -> Text:
    if w.resets_at is None:
        return Text("-", style="dim")
    if is_passed(w, now):
        return Text("リセット済", style="green")
    return Text(fmt_duration((w.resets_at - now).total_seconds()))


def glyph(st: AccountState) -> Text:
    if st.snapshot is None:
        return Text("✕", style="bold red")
    if st.error or st.stale:
        return Text("◐", style="yellow")
    return Text("●", style="green")


def plan_of(st: AccountState) -> str:
    return st.snapshot.plan if st.snapshot and st.snapshot.plan else st.kind


def freshness(st: AccountState, now: datetime) -> Text:
    if st.snapshot is None:
        return Text("未取得", style="red")
    return Text(
        fmt_ago(st.snapshot.fetched_at, now), style="yellow" if st.stale else "dim"
    )


LEGEND = Text.assemble(
    ("● ", "green"),
    "取得済  ",
    ("◐ ", "yellow"),
    "古い値  ",
    ("✕ ", "red"),
    "失敗",
    style="dim",
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
                sub.append(f"↻ {fmt_reset(w.resets_at, now)}  ", style="dim")
                sub.append_text(remaining(w, now))
            lines.append(sub)
        if snap.note:
            lines.append(
                Text(f"    {snap.note}", style="dim", overflow="ellipsis", no_wrap=True)
            )
    if st.error:
        lines.append(Text(st.error, style="red"))
    title = Text.assemble(
        glyph(st), " ", (st.name, "bold"), (f" · {plan_of(st)}", "dim")
    )
    return Panel(
        Group(*lines) if lines else Text("-", style="dim"),
        title=title,
        title_align="left",
        subtitle=freshness(st, now),
        subtitle_align="right",
        border_style="yellow" if st.error else "grey50",
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
        Text(" " * name_w + "".join(label_line), style="dim"),
        Text(" " * name_w + "".join(tick_line), style="grey50"),
    ]

    for st in states:
        line = Text()
        line.append_text(glyph(st))
        line.append(f" {st.name[: name_w - 3]:<{name_w - 3}} ")
        axis = Text("·" * axis_w, style="grey30")
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
                detail.append(f"↻{fmt_reset(w.resets_at, now)}", style="dim")
            detail.append("   ")
        if st.error:
            detail.append(st.error, style="red")
        out += [line, detail]

    out.append(Text(""))
    out.append(
        Text.assemble(
            ("◆ リセット  ▶ 範囲より先  ", "dim"),
            ("緑 ", "green"),
            ("<70%  ", "dim"),
            ("黄 ", "yellow"),
            ("70-90%  ", "dim"),
            ("赤 ", "red"),
            ("≥90%", "dim"),
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
    rule = Text("─" * width, style="grey30")
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
            s.append_text(remaining(w, now) if w.resets_at else Text("-", style="dim"))
            s.pad_right(seg_w - s.cell_len)
            segs.append(s)
        if st.snapshot and st.snapshot.note and st.kind == "cursor":
            segs.append(Text(st.snapshot.note.replace("プラン枠 ", ""), style="dim"))
        lines = [segs[i : i + per_line] for i in range(0, len(segs), per_line)] or [[]]
        for i, chunk in enumerate(lines):
            t = head.copy() if i == 0 else Text(" " * head.cell_len)
            for s in chunk:
                t.append_text(s)
            out.append(t)
        if st.error:
            out.append(Text(" " * head.cell_len + st.error, style="red"))
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
                Text.assemble((st.name, "bold"), (f"  {st.error or '未取得'}", "red"))
            )
            continue
        ws = st.snapshot.windows
        slots += [_Slot(st, w, w.resets_at) for w in ws if w.resets_at and not is_passed(w, now)]
        full = [w for w in ws if (effective_pct(w, now) or 0) >= 100]
        if full:
            # 使い切った枠のうち、最後にリセットされるものが空く時刻
            free_at = max((w.resets_at for w in full if w.resets_at), default=None)
            t = Text.assemble((st.name, "bold"), "  ")
            t.append(", ".join(f"{short(w.label)} 100%" for w in full), style="red")
            if free_at:
                t.append(
                    f"  → {fmt_reset(free_at, now)} ({fmt_duration((free_at - now).total_seconds())})",
                    style="dim",
                )
            blocked.append(t)
        else:
            t = Text.assemble((st.name, "bold"), "  ")
            for w in ws:
                p = effective_pct(w, now)
                t.append(f"{short(w.label)} ", style="dim")
                t.append(f"{p:.0f}%  " if p is not None else "-  ", style=pct_style(p))
            usable.append(t)
        if st.stale:
            (blocked if full else usable)[-1].append("  ◐ 古い値", style="yellow")

    head = Table.grid(padding=(0, 2))
    head.add_column(style="bold", width=12)
    head.add_column()

    def section(label: str, items: list[Text], style: str) -> None:
        for i, it in enumerate(items):
            head.add_row(Text(label if i == 0 else "", style=style), it)

    section("今使える", usable, "green")
    section("使えない", blocked, "red")
    section("不明", unknown, "yellow")
    slots.sort(key=lambda s: s.at)
    if slots:
        n = slots[0]
        head.add_row(Text(""), Text(""))
        head.add_row(
            Text("次のリセット", style="bold cyan"),
            Text.assemble(
                (f"{n.st.name} {short(n.w.label)}", "bold"),
                f"   ↻ {fmt_reset(n.at, now)}   ",
                (fmt_duration((n.at - now).total_seconds()), "bold cyan"),
            ),
        )

    table = Table(
        box=None, padding=(0, 2), show_header=True, header_style="dim", expand=False
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
    rule = Text("── リセットが近い順 " + "─" * max(0, width - 22), style="grey50")
    return Group(head, Text(""), rule, table)


VIEWS = {
    "cards": ("カード", render_cards),
    "timeline": ("タイムライン", render_timeline),
    "compact": ("コンパクト", render_compact),
    "next": ("次に空く", render_next),
}
