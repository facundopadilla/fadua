"""CLI entry point.

SAFETY DEFAULT: without --live, the run is ALWAYS a dry-run against
the real forms, even if --dry-run was not explicitly passed. --live
is the only gate to submitting to the real FADUA forms.
"""

from __future__ import annotations

import argparse
import logging
import time

from app import config as config_module
from app import runner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("fadua.main")


def _positive_int(value: str) -> int:
    """argparse type for --watch: must be a positive integer (>= 1).

    `--watch 0` (or a negative value) is not a valid polling interval
    and must never be silently accepted as "watch disabled" -- that
    behavior belongs exclusively to omitting --watch entirely.
    """
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(
            f"--watch must be a positive integer (got {value!r})"
        )
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fadua-form-filler",
        description="Autonomous agent that fills Google Forms from Google Sheets records.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the form-filling agent.")
    run_parser.add_argument(
        "--watch",
        type=_positive_int,
        default=None,
        metavar="SECONDS",
        help="Poll the sheet every N seconds, processing only the delta.",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fill the forms but do NOT submit (this is also the default without --live).",
    )
    run_parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser window instead of running headless.",
    )
    run_parser.add_argument(
        "--slow-mo",
        type=int,
        default=0,
        metavar="MS",
        help="Slow down each Playwright action by MS milliseconds.",
    )
    run_parser.add_argument(
        "--only",
        type=str,
        default=None,
        metavar="ID_CLIENTE",
        help="Process only the record with this ID_Cliente.",
    )
    run_parser.add_argument(
        "--form",
        type=str,
        choices=["ventas", "mora"],
        default=None,
        help="Process only this form (default: both).",
    )
    run_parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "DANGER: submit to the REAL FADUA forms. Without this flag, "
            "every run is a dry-run regardless of --dry-run."
        ),
    )

    return parser


def run_once(args, cfg) -> list[dict]:
    is_dry_run = not args.live
    if not args.live:
        print(
            "NOTICE: running in DRY-RUN mode (no --live flag). "
            "Forms will be filled but NOT submitted."
        )

    forms_to_run = [args.form] if args.form else list(cfg.form_urls.keys())

    all_outcomes: list[dict] = []
    for form_key in forms_to_run:
        outcomes = runner.run_form(
            form_key,
            cfg=cfg,
            dry_run=is_dry_run,
            headed=args.headed,
            slow_mo=args.slow_mo,
            only_id=args.only,
        )
        all_outcomes.extend(outcomes)

    return all_outcomes


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = config_module.load_config()

    if args.command == "run":
        if args.watch is not None:
            print(f"Watch mode: polling every {args.watch}s (Ctrl+C to stop).")
            try:
                while True:
                    outcomes = run_once(args, cfg)
                    for outcome in outcomes:
                        logger.info("%s: %s", outcome["id_cliente"], outcome["status"])
                    time.sleep(args.watch)
            except KeyboardInterrupt:
                print("Stopped.")
                return 0
        else:
            outcomes = run_once(args, cfg)
            for outcome in outcomes:
                logger.info("%s: %s", outcome["id_cliente"], outcome["status"])
            return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
