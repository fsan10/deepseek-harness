import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from apps.automation_center.flow_runner import FlowRunner, FlowExecutionError
from scripts.auto_download.playwright.outcomes import NeedsHumanError, NeedsHumanTimeout


class FlowHumanOutcomeTests(unittest.TestCase):
    def test_human_wait_neither_retries_nor_continues_to_downstream(self):
        async def await_handler(coroutine, **kwargs):
            return await coroutine
        for error in (NeedsHumanError('pending verification'),NeedsHumanTimeout('pending answer')):
            with self.subTest(error=type(error).__name__):
                runner=object.__new__(FlowRunner)
                runner.step_id='fixture'; runner.component_ids={}; runner.service=Mock()
                runner._page_url=lambda: None
                runner._capture_failure=AsyncMock(return_value=None)
                runner._await_handler=await_handler
                handler=AsyncMock(side_effect=error)
                runner.handlers={'tmall.union.open':handler}
                runner.warnings=[]
                node={'id':'fixture','component_code':'tmall.union.open','retry_count':2,'on_error':'continue'}
                with self.assertRaises(FlowExecutionError) as raised:
                    asyncio.run(runner._execute_node(node))
                self.assertEqual('needs_human',raised.exception.status)
                handler.assert_awaited_once()
                self.assertEqual('needs_human',runner.service.finish_component.call_args.args[1])
