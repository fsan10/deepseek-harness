import asyncio
import contextlib
import io
import sys
import unittest
from unittest.mock import AsyncMock, patch

from scripts.auto_download.playwright import automation_challenge as challenge
from scripts.auto_download.playwright.component_runtime import classify_error
from scripts.auto_download.playwright.outcomes import NeedsHumanError


class HumanOutcomeTests(unittest.TestCase):
    def test_expired_challenge_is_a_human_outcome(self):
        with patch.object(challenge,'relay_settings',return_value=('http://test','fixture')), \
                patch.object(challenge,'json_request',return_value={'status':'expired'}):
            with self.assertRaises(NeedsHumanError) as result:
                asyncio.run(challenge.wait_answer(challenge_id='existing'))
        self.assertEqual('NEEDS_HUMAN',classify_error(result.exception))

    def test_order_entrypoints_return_two_and_keep_other_failures_as_one(self):
        from scripts.auto_download.playwright import (jd_order_download, kuaishou_order_download, douyin_order_download,
            tmall_taobao_union_promotion_download, tmall_wanxiangtai_promotion_download)
        for module in (jd_order_download,kuaishou_order_download,douyin_order_download,
                       tmall_taobao_union_promotion_download,tmall_wanxiangtai_promotion_download):
            argv=['download','--cdp','ws://test','--company','fixture','--shop','fixture']
            if 'tmall_' in module.__name__: argv+=['--platform','天猫','--mode','day']
            for error,expected in ((NeedsHumanError('verification pending'),2),(RuntimeError('broken report'),1)):
                with self.subTest(module=module.__name__,expected=expected), \
                        patch.object(sys,'argv',argv), \
                        patch.object(module,'run',new=AsyncMock(side_effect=error)), \
                        contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(expected,module.main())
