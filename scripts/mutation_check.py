"""Check that the engine correctness tests actually catch the bugs they target.

For each mutation below, the repository's ``src/`` and ``tests/`` are copied
to a temporary directory, one deliberate bug is injected, and the engine test
suite is run. A mutation is "caught" if at least one test fails; the script
also reports whether the specific test written for that property failed.
The unmodified copy is run first and must pass.

Usage:  python scripts/mutation_check.py [--markdown]
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE_TESTS = [
    "tests/test_matching_engine.py",
    "tests/test_matching_priority.py",
    "tests/test_matching_partial_fills.py",
    "tests/test_matching_volume_conservation.py",
    "tests/test_order_book_consistency.py",
    "tests/test_order_book.py",
]


@dataclass(frozen=True)
class Mutation:
    name: str
    file: str
    old: str
    new: str
    target: str  # the test written specifically for this property


MUTATIONS = [
    Mutation(
        "Price priority: best bid taken as the LOWEST bid",
        "src/order_book.py",
        "return prices[-1] if side is Side.BUY else prices[0]",
        "return prices[0] if side is Side.BUY else prices[0]",
        "test_matching_engine.py::test_price_priority",
    ),
    Mutation(
        "Price priority: best ask taken as the HIGHEST ask",
        "src/order_book.py",
        "return prices[-1] if side is Side.BUY else prices[0]",
        "return prices[-1] if side is Side.BUY else prices[-1]",
        "test_matching_engine.py::test_price_priority",
    ),
    Mutation(
        "Time priority: LIFO within a level (newest order trades first)",
        "src/order_book.py",
        "return next(iter(self._levels[side][price].orders.values()))",
        "return next(reversed(self._levels[side][price].orders.values()))",
        "test_matching_engine.py::test_time_priority_within_level",
    ),
    Mutation(
        "Partial fill sends the remainder to the back of the queue",
        "src/order_book.py",
        "        if order.qty == 0:\n            self.remove(order_id)\n        return order",
        "        if order.qty == 0:\n            self.remove(order_id)\n"
        "        else:\n            level.orders.move_to_end(order_id)\n        return order",
        "test_matching_engine.py::test_partial_fill_preserves_queue_position",
    ),
    Mutation(
        "Cancel also bumps the new front-of-queue order to the back",
        "src/order_book.py",
        "        if not level.orders:\n            self._drop_level(order.side, order.price)\n"
        "        return order\n\n    def reduce",
        "        if not level.orders:\n            self._drop_level(order.side, order.price)\n"
        "        else:\n            level.orders.move_to_end(next(iter(level.orders)))\n"
        "        return order\n\n    def reduce",
        "test_matching_engine.py::test_cancellation_correctness",
    ),
    Mutation(
        "Cancel leaves the order's quantity counted in the level total",
        "src/order_book.py",
        "        del level.orders[order_id]\n        level.total_qty -= order.qty",
        "        del level.orders[order_id]",
        "test_matching_engine.py::test_cancellation_correctness",
    ),
    Mutation(
        "Cancel of a non-resting order is accepted (double cancel)",
        "src/matching_engine.py",
        '            return EventResult(False, reason=f"order not resting ({rec.status.value})")',
        "            rec.cancelled += 0\n            return EventResult(True)",
        "test_matching_engine.py::test_cancellation_correctness",
    ),
    Mutation(
        "No out-of-order guard (engine accepts events from the past)",
        "src/matching_engine.py",
        "        if event.ts < self.last_ts:",
        "        if False:",
        "test_matching_engine.py::test_no_lookahead",
    ),
    Mutation(
        "Volume: maker credited with double the traded quantity",
        "src/matching_engine.py",
        "            maker_rec.filled += qty\n",
        "            maker_rec.filled += 2 * qty\n",
        "test_matching_volume_conservation.py::test_volume_conserved_after_every_event",
    ),
    Mutation(
        "Volume: taker overfilled by one share on multi-order sweeps",
        "src/matching_engine.py",
        "            taker.filled += qty\n",
        "            taker.filled += qty + (1 if fills else 0)\n",
        "test_matching_volume_conservation.py::test_volume_conserved_after_every_event",
    ),
    Mutation(
        "Volume: partial fill does not reduce the level total",
        "src/order_book.py",
        "        order.qty -= qty\n        level.total_qty -= qty",
        "        order.qty -= qty",
        "test_matching_volume_conservation.py::test_volume_conserved_after_every_event",
    ),
    Mutation(
        "Trade executes at the aggressor's limit, not the resting price",
        "src/matching_engine.py",
        "            price = maker.price\n",
        "            price = limit_price if limit_price is not None else maker.price\n",
        "test_matching_priority.py::test_trade_price_is_resting_price_not_aggressor_limit",
    ),
    Mutation(
        "Marketable limit stops matching one level early (strict inequality)",
        "src/matching_engine.py",
        "if taker.side is Side.BUY and maker.price > limit_price:",
        "if taker.side is Side.BUY and maker.price >= limit_price:",
        "test_matching_engine.py::test_price_priority",
    ),
    Mutation(
        "Size reduction (partial cancel) sends the order to the back",
        "src/matching_engine.py",
        "        self.book.reduce(ev.order_id, ev.qty)  # keeps queue position",
        "        self.book.reduce(ev.order_id, ev.qty)\n"
        "        self.book._levels[resting.side][resting.price].orders.move_to_end(ev.order_id)",
        "test_matching_engine.py::test_partial_fill_preserves_queue_position",
    ),
    Mutation(
        "Market order remainder silently counted as filled",
        "src/matching_engine.py",
        "            rec.expired = remaining\n",
        "            rec.filled += remaining\n",
        "test_matching_partial_fills.py::test_market_order_larger_than_book_expires_remainder",
    ),
]


def run_suite(workdir: Path) -> tuple[int, set[str]]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", *ENGINE_TESTS],
        cwd=workdir,
        capture_output=True,
        text=True,
    )
    failed = set()
    for line in proc.stdout.splitlines():
        if line.startswith("FAILED tests/"):
            test_id = line.split()[1].removeprefix("tests/")
            failed.add(re.sub(r"\[.*$", "", test_id))
    return proc.returncode, failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--markdown", action="store_true", help="print a markdown table")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "repo"
        base.mkdir()
        for sub in ("src", "tests"):
            shutil.copytree(ROOT / sub, base / sub, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(ROOT / "pyproject.toml", base / "pyproject.toml")

        code, failed = run_suite(base)
        if code != 0:
            print(f"Unmutated suite does not pass ({sorted(failed)}); aborting.")
            return 2

        rows = []
        for mut in MUTATIONS:
            path = base / mut.file
            original = path.read_text()
            if original.count(mut.old) != 1:
                print(f"Mutation anchor not found exactly once: {mut.name}")
                return 2
            path.write_text(original.replace(mut.old, mut.new))
            code, failed = run_suite(base)
            path.write_text(original)
            rows.append((mut, code != 0, mut.target in failed, len(failed)))

    all_caught = all(caught and target for _, caught, target, _ in rows)
    if args.markdown:
        print("| Injected bug | Suite fails | Targeted test fails | Failing tests |")
        print("|---|---|---|---|")
        for mut, caught, target, n in rows:
            print(
                f"| {mut.name} | {'yes' if caught else '**NO**'} | "
                f"{'yes' if target else '**NO**'} (`{mut.target}`) | {n} |"
            )
    else:
        for mut, caught, target, n in rows:
            status = "CAUGHT" if caught and target else "MISSED"
            print(f"[{status}] {mut.name}  (targeted test failed: {target}; {n} failing tests)")
    print(f"\n{sum(c and t for _, c, t, _ in rows)}/{len(rows)} mutations caught by their "
          "targeted test.")
    return 0 if all_caught else 1


if __name__ == "__main__":
    raise SystemExit(main())
