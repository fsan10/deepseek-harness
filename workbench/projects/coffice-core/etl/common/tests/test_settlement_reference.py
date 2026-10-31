"""Keep export-side acceptance aligned with confirmed settlement definitions."""
from decimal import Decimal
import unittest

from etl.platform_finance.reconcile_settlement import money_values


class SettlementReferenceTests(unittest.TestCase):
    def test_pdd_refund_reference_moves_to_income_and_keeps_net(self):
        row={'收入金额（+元）':'0','支出金额（-元）':'-30','账务类型':'退款','业务描述':'0020002|订单退款'}
        self.assertEqual(money_values('pdd','ods_pdd_settlement_raw',row),
                         (Decimal(0),Decimal(30),Decimal(-30),True))
        self.assertEqual(money_values('pdd','ods_pdd_settlement_raw',row,settlement=True),
                         (Decimal(-30),Decimal(0),Decimal(-30),True))

    def test_coupon_reference_uses_code_not_refund_words(self):
        for code,expected in (('0020005',(-7,0,-7,True)),('0010005',(0,7,-7,True))):
            row={'收入金额（+元）':'0','支出金额（-元）':'-7',
                 '账务类型':'优惠券结算','业务描述':code+'|退款字样'}
            self.assertEqual(money_values('pdd','ods_pdd_settlement_raw',row,settlement=True),expected)


if __name__=='__main__':
    unittest.main()
