"""Entry point: `python -m survivor` runs one cycle (or sleeps, or stays dead)."""

import logging
import sys

from .agent import Survivor
from .config import load_config
from .external import GitHub, Stripe


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    survivor = Survivor(load_config(), github=GitHub.from_env(), stripe=Stripe.from_env())
    result = survivor.run_cycle()
    d = survivor.ledger.data
    print(f"outcome={result.outcome} spent={result.spent_eur:.4f}EUR "
          f"balance={d['balance_eur']:.4f}EUR cycles={d['cycles']} sleep_until={d['sleep_until']}")
    if result.summary:
        print(result.summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
