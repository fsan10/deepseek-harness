from decimal import Decimal
from pathlib import Path
import unittest

from apps.fund_split_adjust.domain import allocate_adjustment_diffs, allocate_split_amounts, parse_workbook, pending_amount


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_FILE = PROJECT_ROOT / "data" / "银行" / "看板数据.xlsx"


class DomainTests(unittest.TestCase):
    def test_sample_workbook_reconciles_ods_and_dwd(self):
        parsed = parse_workbook(SAMPLE_FILE)
        self.assertEqual(len(parsed.source_rows), 58)
        self.assertEqual(len(parsed.split_specs), 63)
        self.assertEqual(len(parsed.expense_types), 8)
        self.assertEqual(len({name for name, _ in parsed.account_pairs}), 25)
        self.assertEqual(parsed.adjustment_balance, Decimal("0.00"))
        by_source = {}
        for split in parsed.split_specs:
            by_source.setdefault(split.source_row_order, Decimal("0.00"))
            by_source[split.source_row_order] += split.split_amount
        for source in parsed.source_rows:
            self.assertEqual(by_source[source.row_order], source.source_amount)

    def test_even_allocation_places_rounding_remainder_last(self):
        self.assertEqual(
            allocate_split_amounts(Decimal("100.00"), [Decimal("30"), None, None]),
            [Decimal("30.00"), Decimal("35.00"), Decimal("35.00")],
        )
        self.assertEqual(
            allocate_split_amounts(Decimal("10.00"), [None, None, None]),
            [Decimal("3.33"), Decimal("3.33"), Decimal("3.34")],
        )

    def test_pending_is_signed_imbalance_not_adjusted_volume(self):
        self.assertEqual(pending_amount(["-346.60", "346.60"]), Decimal("0.00"))
        self.assertEqual(pending_amount(["-346.60"]), Decimal("346.60"))
        self.assertEqual(pending_amount(["0.93"]), Decimal("-0.93"))

    def test_adjustment_diff_is_evenly_preserved_when_splitting(self):
        self.assertEqual(
            allocate_adjustment_diffs("300.00", 2),
            [Decimal("150.00"), Decimal("150.00")],
        )
        self.assertEqual(
            allocate_adjustment_diffs("-300.00", 2),
            [Decimal("-150.00"), Decimal("-150.00")],
        )
        positive = allocate_adjustment_diffs("100.00", 3)
        negative = allocate_adjustment_diffs("-100.00", 3)
        self.assertEqual(positive, [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")])
        self.assertEqual(negative, [Decimal("-33.33"), Decimal("-33.33"), Decimal("-33.34")])
        self.assertEqual(sum(positive), Decimal("100.00"))
        self.assertEqual(sum(negative), Decimal("-100.00"))


if __name__ == "__main__":
    unittest.main()
