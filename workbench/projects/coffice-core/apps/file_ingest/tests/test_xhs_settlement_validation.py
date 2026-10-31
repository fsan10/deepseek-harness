from __future__ import annotations

from decimal import Decimal
import unittest

from etl.xhs.run_xhs_settlement_metrics_etl import (
    REQUIRED_EXPENSE_COLUMNS,
    REQUIRED_INCOME_COLUMNS,
    validate_ods,
)


class _Cursor:
    def __init__(self, income_stats, expense_stats):
        self._fetchone = iter(
            [
                ("ods.ods_xhs_settlement_income_raw",),
                ("ods.ods_xhs_settlement_expense_raw",),
                income_stats,
                expense_stats,
            ]
        )
        self._fetchall = iter(
            [
                [(column,) for column in REQUIRED_INCOME_COLUMNS],
                [(column,) for column in REQUIRED_EXPENSE_COLUMNS],
            ]
        )

    def execute(self, *_args, **_kwargs):
        return None

    def fetchone(self):
        return next(self._fetchone)

    def fetchall(self):
        return next(self._fetchall)


class XhsSettlementValidationTests(unittest.TestCase):
    def test_other_service_signed_refund_is_allowed(self):
        result = validate_ods(
            _Cursor(
                (2, 0, 2, 2, 2, 1, 0, 0, 0, 0, Decimal("100.00"), Decimal("110.00"), Decimal("-10.00"), Decimal("0.00")),
                (2, 2, 2, 1, 0, 0, 0, 0, Decimal("8.30"), 2, 0),
            )
        )

        self.assertEqual(Decimal("8.30"), result["expense_amount"])

    def test_appeal_adjustment_is_income_and_not_expense(self):
        result = validate_ods(
            _Cursor(
                (2, 1, 3, 3, 3, 2, 0, 0, 0, 0, Decimal("108.30"), Decimal("110.00"), Decimal("-10.00"), Decimal("8.30")),
                (2, 2, 2, 1, 0, 0, 0, 0, Decimal("8.30"), 3, 1),
            )
        )

        self.assertEqual(3, result["income_rows"])
        self.assertEqual(2, result["expense_rows"])
        self.assertEqual(1, result["appeal_adjustment_rows"])
        self.assertEqual(Decimal("8.30"), result["appeal_adjustment_income_amount"])
        self.assertEqual(Decimal("108.30"), result["income_amount"])

    def test_invalid_other_service_amount_remains_a_hard_failure(self):
        with self.assertRaisesRegex(RuntimeError, "支出ODS批次、日期、类型或金额校验失败"):
            validate_ods(
                _Cursor(
                    (1, 0, 1, 1, 1, 1, 0, 0, 0, 0, Decimal("10.00"), Decimal("10.00"), Decimal("0.00"), Decimal("0.00")),
                    (1, 1, 1, 1, 0, 0, 0, 1, Decimal("0.00"), 1, 0),
                )
            )


if __name__ == "__main__":
    unittest.main()
