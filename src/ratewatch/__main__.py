from __future__ import annotations

import argparse
import sys

from .config import CONFIG_PATH, load_accounts
from .theme import PALETTES


def main() -> None:
    p = argparse.ArgumentParser(prog="ratewatch", description="Claude / Codex / Cursor のレートリミットのリセット時刻を並べる")
    p.add_argument("--once", action="store_true", help="TUI を開かず、1 回取得して表を出力して終わる")
    p.add_argument("--config", default=str(CONFIG_PATH), help=f"設定ファイル（既定: {CONFIG_PATH}）")
    from .app import VIEWS

    p.add_argument("--view", choices=list(VIEWS), help="起動時の描画パターン（既定: 前回選んだもの）")
    p.add_argument("--theme", choices=list(PALETTES), help="配色（既定: 前回選んだもの）")
    args = p.parse_args()

    from pathlib import Path

    try:
        accounts = load_accounts(Path(args.config))
    except ValueError as e:
        sys.exit(f"ratewatch: {e}")

    if args.once:
        from rich import box
        from rich.console import Console
        from rich.table import Table

        from .collect import COLUMNS, build_rows, refresh
        from .model import now_utc

        table = Table(box=box.SIMPLE_HEAD)
        for c in COLUMNS:
            table.add_column(c, overflow="fold")
        for r in build_rows(refresh(accounts), now_utc()):
            table.add_row(*r.cells)
        Console().print(table)
        return

    from .app import RatewatchApp

    RatewatchApp(accounts, view=args.view, theme=args.theme).run()


if __name__ == "__main__":
    main()
