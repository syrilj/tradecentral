"""Small command shell; pipeline construction is injected by integration code."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Protocol, Sequence

from .clock import RunContext
from .config import DailyPlaysConfig, load_config, load_project_environment
from .contracts import RunMode, canonical_json
from .pipeline import run_pipeline
from .render import render_report
from .realize import realize_due_decisions
from .shadow_lifecycle import mark_open_option_positions
from .monitoring import render_shadow_report, shadow_report


class TodayRunner(Protocol):
    def __call__(self, *, context: RunContext, account: float, config: DailyPlaysConfig) -> MappingResult: ...


MappingResult = dict[str, Any]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m edge.daily_plays", description="Daily decision-support plays")
    sub = parser.add_subparsers(dest="command", required=True)
    today = sub.add_parser("today", help="Produce today's ranked plays (no order placement)")
    today.add_argument("--account", required=True, type=float, help="Account value in dollars")
    today.add_argument("--json", action="store_true", dest="as_json", help="Emit canonical JSON")
    today.add_argument("--config", type=Path, default=None, help="Policy JSON path")
    today.add_argument("--replay", action="store_true", help="Use an injected/offline replay runner")
    today.add_argument("--output-root", type=Path, default=None, help="Audit output root (testing/operations)")
    realize = sub.add_parser("realize", help="Realize due shadow decisions; never places orders")
    realize.add_argument("--output-root", type=Path, default=None)
    realize.add_argument("--outcomes-json", type=Path, required=True, help="Offline outcome mapping for controlled realization")
    realize.add_argument("--json", action="store_true", dest="as_json")
    marks = sub.add_parser("mark-options", help="Record offline NBBO marks for open shadow options; never places orders")
    marks.add_argument("--output-root", type=Path, default=None)
    marks.add_argument("--quotes-json", type=Path, required=True, help="Offline mapping of position_id to listed NBBO/Greek quote")
    marks.add_argument("--json", action="store_true", dest="as_json")
    report = sub.add_parser("report", help="Report shadow reliability and readiness")
    report.add_argument("--output-root", type=Path, default=None)
    report.add_argument("--spread-bps", type=float, default=0.0)
    report.add_argument("--slippage-bps", type=float, default=0.0)
    report.add_argument("--json", action="store_true", dest="as_json")
    return parser


def run(argv: Sequence[str] | None = None, *, runner: TodayRunner | None = None,
        now: datetime | None = None) -> tuple[int, MappingResult, bool]:
    args = build_parser().parse_args(argv)
    if args.command == "report":
        result = shadow_report(output_root=args.output_root, spread_bps=args.spread_bps, slippage_bps=args.slippage_bps)
        return 0, result, args.as_json
    if args.command == "realize":
        raw = json.loads(args.outcomes_json.read_text(encoding="utf-8"))
        if not isinstance(raw, dict): raise ValueError("--outcomes-json must be a JSON object keyed by play_id")
        def provider(*, play: MappingResult, due_utc: datetime) -> MappingResult | None:
            value = raw.get(play.get("play_id"))
            return value if isinstance(value, dict) else None
        result = realize_due_decisions(output_root=args.output_root, provider=provider, asof_utc=now or datetime.now(timezone.utc))
        return 0, result, args.as_json
    if args.command == "mark-options":
        raw = json.loads(args.quotes_json.read_text(encoding="utf-8"))
        if not isinstance(raw, dict): raise ValueError("--quotes-json must be a JSON object keyed by position_id")
        def quote_provider(*, position: MappingResult, asof_utc: datetime) -> MappingResult | None:
            value = raw.get(position.get("position_id"))
            return value if isinstance(value, dict) else None
        result = mark_open_option_positions(output_root=args.output_root, provider=quote_provider,
                                            asof_utc=now or datetime.now(timezone.utc))
        return 0, result, args.as_json
    if args.account <= 0:
        raise ValueError("--account must be a positive number")
    load_project_environment()
    config = load_config(args.config)
    context = RunContext.create(asof_utc=now or datetime.now(timezone.utc), mode=RunMode.REPLAY if args.replay else RunMode.LIVE)
    result = (runner or run_pipeline)(context=context, account=args.account, config=config,
                                      **({"output_root": str(args.output_root)} if args.output_root else {}))
    return 0, result, args.as_json


def main(argv: Sequence[str] | None = None, *, runner: TodayRunner | None = None,
         now: datetime | None = None) -> int:
    try:
        status, result, as_json = run(argv, runner=runner, now=now)
    except (ValueError, OSError) as exc:
        print(f"daily-plays: {exc}")
        return 2
    if as_json:
        print(canonical_json(result))
    else:
        print(render_shadow_report(result) if "readiness_checklist" in result else render_report(result))
    return status
