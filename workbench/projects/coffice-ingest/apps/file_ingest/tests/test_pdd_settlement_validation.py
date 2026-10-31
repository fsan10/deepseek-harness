from __future__ import annotations

import contextlib
import io
import unittest

from etl.pdd.run_pdd_settlement_metrics_etl import REQUIRED_ODS_COLUMNS, validate_ods


class _Cursor:
    def __init__(self, stats: tuple[int, int, int, int, int]):
        self._one = iter(
            [
                ("ods_pdd_settlement_raw",),
                stats,
                (0,),
                (0,),
                (0, 0, 0, 0, 0),
                (0,),
            ]
        )
        self._many = iter(
            [[(column,) for column in REQUIRED_ODS_COLUMNS]]
        )

    def execute(self, *_args, **_kwargs):
        return None

    def fetchone(self):
        return next(self._one)

    def fetchall(self):
        return next(self._many)


class PddSettlementValidationTests(unittest.TestCase):
    def test_business_key_collision_is_warning_and_source_rows_are_kept(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = validate_ods(_Cursor((2, 2, 2, 1, 1)))

        self.assertEqual((2, 1, 1), result)
        self.assertIn("业务字段组合键存在重复", output.getvalue())
        self.assertIn("按source_id/source_row_no保留并累计", output.getvalue())

    def test_source_id_or_hash_collision_remains_hard_failure(self):
        with self.assertRaisesRegex(RuntimeError, "ODS源行粒度重复"):
            validate_ods(_Cursor((2, 1, 2, 1, 1)))


if __name__ == "__main__":
    unittest.main()
