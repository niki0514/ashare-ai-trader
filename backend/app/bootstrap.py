from __future__ import annotations

import argparse

from .config import settings
from .db import db_runtime, session_scope
from .seed_data import SEED_CLOSE_PRICES
from .services import PnlService, SeedService


def bootstrap_database(*, seed_demo: bool | None = None) -> None:
    db_runtime.init_schema()

    if seed_demo is None:
        seed_demo = settings.bootstrap_demo_data
    if not seed_demo:
        return

    with session_scope() as session:
        seed = SeedService(session)
        seed.ensure_seed_data(settings.default_user_id)

        pnl_service = PnlService(session)
        for day in sorted(SEED_CLOSE_PRICES.keys()):
            pnl_service.recompute_daily_pnl(
                settings.default_user_id,
                day,
                use_realtime=False,
                is_final=True,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize the A-share AI Trader database.")
    parser.add_argument(
        "--seed-demo",
        action=argparse.BooleanOptionalAction,
        default=settings.bootstrap_demo_data,
        help="Seed the default demo user and baseline PnL snapshots.",
    )
    args = parser.parse_args()
    bootstrap_database(seed_demo=args.seed_demo)


if __name__ == "__main__":
    main()
