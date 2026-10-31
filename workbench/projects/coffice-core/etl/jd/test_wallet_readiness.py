import contextlib
import io
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from etl.common.errors import SourceNotReady
from etl.jd.wallet_reconciliation import validate


class WalletReadinessTests(unittest.TestCase):
    def cursor(self, *, covered=False, amount=None):
        cursor=MagicMock()
        cursor.connection=SimpleNamespace()
        cursor.fetchall.side_effect=[
            [('jd|one','20261025000001',date(2026,10,24),date(2026,10,24),Decimal('604.77'))],
            [('jd|one',1,date(2026,10,24),date(2026,10,24))],
            [] if amount is None else [('jd|one','20261025000001',amount)],
            [('jd|one',date(2026,10,1),date(2026,10,24))],
        ]
        context={'mode':'incremental','trigger_type':'ingest_complete','as_of_date':'2026-10-26',
            'months':{'jd':['2026-10-01']},'shops':{'jd':['one']},
            'fund_coverage':{'jd|one':{'verified_days':['2026-10-25'] if covered else ['2026-10-24']}}}
        return cursor,context

    def test_unarrived_fund_waits_without_publishing(self):
        cursor,context=self.cursor()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SourceNotReady):
            validate(cursor,context)

    def test_true_missing_wallet_and_amount_mismatch_still_fail(self):
        for kwargs in ({'covered':True},{'amount':Decimal('1.00')}):
            with self.subTest(kwargs=kwargs):
                cursor,context=self.cursor(**kwargs)
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError) as result:
                    validate(cursor,context)
                self.assertNotIsInstance(result.exception,SourceNotReady)
