from __future__ import annotations

import logging
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.auto_download.run_all_platform_downloads import (
    ControllerRunLock,
    ControllerError,
    DEFAULT_CONFIG,
    DownloadController,
    ResumeCheckpoint,
    load_config,
    validate_profile_companies,
    main,
)


class ProfileCompanyConsistencyTests(unittest.TestCase):
    @staticmethod
    def plans():
        return [{'profile_name':name, '_metadata':{'platform':'抖音','company':company,'shop':'MOCK宁盏冲饮专卖店'}}
                for name, company in (('DY-抖音-宁盏','南京南京宁盏食品科技有限公司'),
                                      ('DY-千川-宁盏','南京宁盏食品科技有限公司'))]

    def test_conflicting_profiles_are_rejected_during_inventory_before_browser_start(self):
        controller = object.__new__(DownloadController)
        controller.config = {'profile_rules':[{'name':'抖音','platform':'抖音','profile_name_prefixes':['DY-'],
                                              'steps':[{'name':'订单','module':'douyin_order_download'}]}]}
        controller.summary = {'profiles':[], 'warnings':[]}
        controller.logger = logging.getLogger('test_profile_companies')
        controller.client = Mock()
        plans = self.plans()
        profiles = [{'id':str(index),'name':p['profile_name'],
                     'note':f"platform=抖音;company={p['_metadata']['company']};shop=MOCK宁盏冲饮专卖店"}
                    for index,p in enumerate(plans)]
        controller.client.call.side_effect = [profiles[0], profiles[1]]
        with self.assertRaisesRegex(ControllerError, '公司名不一致'):
            controller._materialize_profile_plans(profiles)
        self.assertTrue(all(call.args[0] == 'get_profile' for call in controller.client.call.call_args_list))

    def test_corrected_notes_and_equivalent_parentheses_are_accepted(self):
        plans = self.plans()
        plans[0]['_metadata']['company'] = '南京宁盏食品科技有限公司'
        validate_profile_companies(plans)
        plans[0]['_metadata']['company'] = '公司（南京）'
        plans[1]['_metadata']['company'] = '公司(南京)'
        validate_profile_companies(plans)

    def test_same_named_shop_on_another_platform_is_not_a_conflict(self):
        plans = self.plans()
        plans[1]['_metadata']['platform'] = '天猫'
        validate_profile_companies(plans)


class DownloadControllerProfileLifecycleTests(unittest.TestCase):
    def test_backfill_refuses_changed_profile_or_shop_before_opening_browser(self):
        profile={'id':'profile-1','name':self.plan()['profile_name']}
        for field, value, pattern in (
            ('expected_profile_id','another-profile','标识已改变'),
            ('expected_metadata',{'platform':'快手','company':'测试公司','shop':'旧店铺'},'业务归属已改变'),
        ):
            controller=self.make_controller();plan=self.plan();plan[field]=value
            controller._ensure_profile_running=Mock()
            with self.assertRaisesRegex(ControllerError,pattern):
                controller._run_profile_plan(1,plan,[profile])
            controller._ensure_profile_running.assert_not_called()

    def make_controller(self) -> DownloadController:
        controller = object.__new__(DownloadController)
        controller.client = Mock()
        controller.checkpoint = Mock()
        controller.checkpoint.successful_step.return_value = None
        controller.logger = logging.getLogger("test_all_platform_downloads")
        controller.summary = {"profiles": [], "warnings": [], "cleanup_errors": []}
        controller.started_profile_ids = []
        controller.profiles_ready_to_close = []
        controller.execution_lane = "all"
        return controller

    @staticmethod
    def plan() -> dict[str, object]:
        return {
            "profile_name": "KS-快手-MOCK测试专卖店",
            "required": True,
            "platform": "快手",
            "_profile_id": "profile-1",
            "_metadata": {
                "platform": "快手",
                "company": "测试公司",
                "shop": "测试店铺",
            },
            "steps": [{"name": "订单", "module": "kuaishou_order_download", "args": []}],
        }

    def test_completed_preexisting_profile_is_closed(self):
        controller = self.make_controller()
        controller._ensure_profile_running = Mock(return_value=("ws://cdp", False))
        controller._run_step = Mock(return_value={"return_code": 0})
        controller.client.call.return_value = {}

        controller._run_profile_plan(1, self.plan(), [{"id": "profile-1", "name": self.plan()["profile_name"]}])

        controller.client.call.assert_called_once_with(
            "stop_profile", {"id": "profile-1"}
        )
        self.assertEqual("success", controller.summary["profiles"][0]["status"])
        self.assertEqual([], controller.profiles_ready_to_close)

    def test_incomplete_profile_is_preserved_when_outer_cleanup_runs(self):
        controller = self.make_controller()
        controller._ensure_profile_running = Mock(return_value=("ws://cdp", True))
        controller._run_step = Mock(side_effect=ControllerError("step failed"))
        controller.checkpoint.record_failure.return_value = None

        with self.assertRaises(ControllerError):
            controller._run_profile_plan(
                1,
                self.plan(),
                [{"id": "profile-1", "name": self.plan()["profile_name"]}],
            )

        controller._cleanup_completed_profiles()

        controller.client.call.assert_not_called()
        self.assertEqual([], controller.started_profile_ids)
        self.assertEqual([], controller.profiles_ready_to_close)
        self.assertEqual("failed", controller.summary["profiles"][0]["status"])

    def test_manual_interrupt_preserves_incomplete_profile(self):
        controller = self.make_controller()
        controller._ensure_profile_running = Mock(return_value=("ws://cdp", True))
        controller._run_step = Mock(side_effect=KeyboardInterrupt)

        with self.assertRaises(KeyboardInterrupt):
            controller._run_profile_plan(
                1,
                self.plan(),
                [{"id": "profile-1", "name": self.plan()["profile_name"]}],
            )

        controller._cleanup_completed_profiles()

        controller.client.call.assert_not_called()
        self.assertEqual([], controller.started_profile_ids)
        self.assertEqual([], controller.profiles_ready_to_close)
        self.assertEqual("running", controller.summary["profiles"][0]["status"])

    def test_outer_cleanup_retries_only_completed_profile_close(self):
        controller = self.make_controller()
        controller.started_profile_ids = [("profile-1", "完成店铺")]
        controller._queue_profile_for_close("profile-1", "完成店铺")
        controller.client.call.side_effect = [RuntimeError("temporary stop error"), {}]

        controller._stop_profile("profile-1", "完成店铺")
        self.assertEqual([("profile-1", "完成店铺")], controller.profiles_ready_to_close)

        controller._cleanup_completed_profiles()

        self.assertEqual(2, controller.client.call.call_count)
        self.assertEqual([], controller.profiles_ready_to_close)
        self.assertEqual([], controller.started_profile_ids)

    def test_checkpoint_complete_profile_is_not_started_again(self):
        controller = self.make_controller()
        controller.execution_lane = "interactive"
        controller.checkpoint.successful_step.return_value = {
            "status": "success",
            "recorded_at": "2026-09-09T05:10:00+08:00",
            "execution_lane": "overnight",
        }
        controller.client.call.return_value = []
        controller._ensure_profile_running = Mock(
            side_effect=AssertionError("completed profile must not be started")
        )

        controller._run_profile_plan(
            1,
            self.plan(),
            [{"id": "profile-1", "name": self.plan()["profile_name"]}],
        )

        controller._ensure_profile_running.assert_not_called()
        self.assertEqual("success", controller.summary["profiles"][0]["status"])
        self.assertTrue(controller.summary["profiles"][0]["checkpoint_only"])
        self.assertEqual(
            "overnight",
            controller.summary["profiles"][0]["steps"][0]["completed_in_lane"],
        )

    def test_checkpoint_complete_active_profile_is_only_closed(self):
        controller = self.make_controller()
        controller.execution_lane = "interactive"
        controller.checkpoint.successful_step.return_value = {"status": "success"}
        controller.client.call.side_effect = [
            [{"id": "profile-1", "name": self.plan()["profile_name"]}],
            {},
        ]
        controller._ensure_profile_running = Mock(
            side_effect=AssertionError("completed profile must not be started")
        )

        controller._run_profile_plan(
            1,
            self.plan(),
            [{"id": "profile-1", "name": self.plan()["profile_name"]}],
        )

        controller._ensure_profile_running.assert_not_called()
        controller.client.call.assert_any_call("stop_profile", {"id": "profile-1"})


class DownloadControllerLaneTests(unittest.TestCase):
    def make_controller(self, lane: str) -> DownloadController:
        controller = object.__new__(DownloadController)
        controller.execution_lane = lane
        controller.logger = logging.getLogger("test_all_platform_download_lanes")
        return controller

    @staticmethod
    def plan() -> dict[str, object]:
        return {
            "profile_name": "JD-测试店",
            "steps": [
                {
                    "name": "订单",
                    "module": "jd_order_download",
                    "args": [],
                    "lanes": ["interactive"],
                },
                {
                    "name": "资金",
                    "module": "jd_fund_download",
                    "args": [],
                    "lanes": ["overnight", "interactive"],
                },
            ],
        }

    def test_overnight_lane_filters_only_eligible_steps(self):
        selected = self.make_controller("overnight")._select_plan_for_lane(
            1, self.plan()
        )

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(["资金"], [step["name"] for step in selected["steps"]])
        self.assertEqual(2, selected["steps"][0]["_source_step_index"])

    def test_all_lane_preserves_every_step(self):
        selected = self.make_controller("all")._select_plan_for_lane(1, self.plan())

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(
            ["订单", "资金"], [step["name"] for step in selected["steps"]]
        )

    def test_checkpoint_key_is_shared_between_lanes(self):
        overnight = {
            "name": "资金",
            "module": "jd_fund_download",
            "args": [],
            "lanes": ["overnight"],
        }
        interactive = dict(overnight, lanes=["interactive"])

        self.assertEqual(
            ResumeCheckpoint.step_key(overnight),
            ResumeCheckpoint.step_key(interactive),
        )

    def test_tmall_and_pinduoduo_are_in_overnight_and_fallback_lanes(self):
        config = load_config(DEFAULT_CONFIG)
        platform_rules = {
            platform: [
                step
                for rule in config["profile_rules"]
                if rule["platform"] == platform
                for step in rule["steps"]
            ]
            for platform in ("天猫", "拼多多")
        }

        for steps in platform_rules.values():
            self.assertTrue(steps)
            for step in steps:
                self.assertIn("overnight", step["lanes"])
                self.assertIn("interactive", step["lanes"])

    def test_tmall_is_excluded_overnight_and_complete_in_morning_run(self):
        config = load_config(DEFAULT_CONFIG)
        expected_tmall = {
            "tmall_order_download", "tmall_aggregate_fund_download",
            "tmall_alipay_fund_download", "tmall_taobao_union_promotion_download",
            "tmall_wanxiangtai_promotion_download",
        }
        for lane, exclude in (
            ("overnight", "天猫"),
            ("interactive", None),
        ):
            with self.subTest(lane=lane, exclude=exclude):
                controller = self.make_controller(lane)
                controller.exclude_platform = exclude
                modules = set()
                for index, rule in enumerate(config["profile_rules"], 1):
                    plan = dict(rule, profile_name=rule["name"], _metadata={"platform": rule["platform"]})
                    selected = controller._select_plan_for_lane(index, plan)
                    if selected:
                        modules.update(step["module"] for step in selected["steps"])
                self.assertTrue(modules)
                if exclude:
                    self.assertFalse(expected_tmall & modules)
                else:
                    self.assertTrue(expected_tmall <= modules)
                expected = {
                    step["module"] for rule in config["profile_rules"]
                    if rule["platform"] != exclude for step in rule["steps"]
                    if lane in step["lanes"]
                }
                self.assertEqual(expected, modules)


class ControllerStateFileTests(unittest.TestCase):
    def test_scheduled_sunday_uses_daily_checkpoint_and_records_schedule_source(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            controller = DownloadController(
                config={}, config_path=root / "config.json", destination=root,
                logger=logging.getLogger("test_daily_schedule"), run_id="sunday-run",
                summary_path=root / "summary.json", mcp_url="http://127.0.0.1:1/mcp",
                business_date=date(2026, 10, 18), require_daily_checkpoint=True,
                execution_lane="interactive", trigger_type="schedule",
            )
            self.assertEqual("2026-10-18", controller.checkpoint_scope)
            self.assertEqual("schedule", controller.journal.data["trigger_type"])
            with self.assertRaisesRegex(ControllerError, "检查点日期与业务日期不一致"):
                DownloadController(
                    config={}, config_path=root / "config.json", destination=root,
                    logger=controller.logger, run_id="stale-run", summary_path=root / "stale.json",
                    mcp_url="http://127.0.0.1:1/mcp", business_date=date(2026, 10, 18),
                    require_daily_checkpoint=True, checkpoint_scope="2026-10-17",
                    trigger_type="schedule",
                )

    def test_schedule_cli_keeps_daily_checkpoint_guard_without_a_wrapper(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with patch("apps.fund_split_adjust.server.load_project_env"), \
                 patch("scripts.auto_download.run_all_platform_downloads.load_config", return_value={}), \
                 patch("scripts.auto_download.run_all_platform_downloads.configure_logger", return_value=Mock()), \
                 patch("scripts.auto_download.run_all_platform_downloads.ControllerRunLock"), \
                 patch("scripts.auto_download.run_all_platform_downloads.DownloadController") as factory:
                factory.return_value.run.return_value = 0
                self.assertEqual(0, main(["--config", str(root / "config.json"), "--dest", str(root),
                                          "--log-dir", str(root), "--trigger-type", "schedule"]))
                self.assertTrue(factory.call_args.kwargs["require_daily_checkpoint"])
                self.assertEqual("schedule", factory.call_args.kwargs["trigger_type"])

    def test_overnight_cli_passes_platform_exclusion_without_changing_daily_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with patch("apps.fund_split_adjust.server.load_project_env"), \
                 patch("scripts.auto_download.run_all_platform_downloads.load_config", return_value={}), \
                 patch("scripts.auto_download.run_all_platform_downloads.configure_logger", return_value=Mock()), \
                 patch("scripts.auto_download.run_all_platform_downloads.ControllerRunLock"), \
                 patch("scripts.auto_download.run_all_platform_downloads.DownloadController") as factory:
                factory.return_value.run.return_value = 0
                self.assertEqual(0, main(["--config", str(root / "config.json"), "--dest", str(root),
                    "--log-dir", str(root), "--lane", "overnight", "--exclude-platform", "天猫",
                    "--lock-wait-seconds", "0", "--trigger-type", "schedule"]))
                self.assertEqual("天猫", factory.call_args.kwargs["exclude_platform"])
                self.assertTrue(factory.call_args.kwargs["require_daily_checkpoint"])
                self.assertIsNone(factory.call_args.kwargs["checkpoint_scope"])

    def test_disabled_profile_is_not_started_or_emitted_as_a_step(self):
        controller = object.__new__(DownloadController)
        controller.config = {
            "profiles": [
                {
                    "profile_name": "disabled-profile",
                    "enabled": False,
                    "steps": [
                        {
                            "name": "订单",
                            "module": "unused_download",
                            "args": [],
                        }
                    ],
                }
            ]
        }
        controller.config_path = Path("test-config.json")
        controller.destination = Path("test-destination")
        controller.logger = logging.getLogger("test_disabled_profile")
        controller.run_id = "test-run"
        controller.execution_lane = "all"
        controller.python_executable = Path(__file__).parents[3] / ".venv" / "Scripts" / "python.exe"
        controller.client = Mock()
        controller.client.call.return_value = []
        controller.started_profile_ids = []
        controller.profiles_ready_to_close = []
        controller.summary = {
            "profiles": [],
            "warnings": [],
            "cleanup_errors": [],
        }
        events = []
        controller.event_sink = lambda event, payload: events.append((event, payload))

        self.assertEqual(0, controller.run())

        controller.client.initialize.assert_called_once_with()
        controller.client.load_tools.assert_called_once_with()
        controller.client.call.assert_called_once_with("list_profiles", {})
        self.assertEqual([], controller.summary["profiles"])
        self.assertEqual(["run_started", "plan", "run_finished"], [event for event, _ in events])
        self.assertEqual([], next(payload["targets"] for event, payload in events if event == "plan"))

    def test_event_sink_is_optional_and_does_not_scan_destination(self):
        controller = object.__new__(DownloadController)
        controller.event_sink = None
        controller.destination = Path("does-not-need-to-exist")
        self.assertEqual({}, controller._artifact_snapshot())

    def test_artifact_collector_reports_new_files_without_log_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            events = []
            controller = object.__new__(DownloadController)
            controller.event_sink = lambda event, payload: events.append((event, payload))
            controller.destination = root
            before = controller._artifact_snapshot()
            (root / "2026-09-20_京东_测试公司_测试店铺_订单.xlsx").write_bytes(b"report")
            logs = root / ".automation_logs"
            logs.mkdir()
            (logs / "run.log").write_text("secret-free", encoding="utf-8")
            artifacts = controller._collect_artifacts(before)
        self.assertEqual(1, len(artifacts))
        self.assertEqual("report_file", artifacts[0]["artifact_type"])
        self.assertEqual(64, len(artifacts[0]["file_hash"]))

    def test_resume_checkpoint_constructs_on_fresh_path(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            checkpoint = ResumeCheckpoint(
                path=Path(temporary_directory) / "checkpoint.json",
                scope="2026-09-09",
                config_fingerprint="fingerprint",
                logger=logging.getLogger("test_resume_checkpoint"),
            )

        self.assertEqual("2026-09-09", checkpoint.data["scope"])

    def test_controller_lock_blocks_second_instance_and_releases(self):
        logger = logging.getLogger("test_controller_lock")
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock_path = Path(temporary_directory) / "controller.lock"
            first = ControllerRunLock(
                path=lock_path,
                wait_seconds=0,
                run_id="first",
                execution_lane="overnight",
                logger=logger,
            )
            second = ControllerRunLock(
                path=lock_path,
                wait_seconds=0,
                run_id="second",
                execution_lane="interactive",
                logger=logger,
            )
            first.acquire()
            try:
                with self.assertRaises(ControllerError):
                    second.acquire()
            finally:
                first.release()

            second.acquire()
            second.release()

    def test_config_change_preserves_step_state_in_same_execution_context(self):
        logger = logging.getLogger("test_checkpoint_config_change")
        with tempfile.TemporaryDirectory() as temporary_directory:
            checkpoint_path = Path(temporary_directory) / "checkpoint.json"
            first = ResumeCheckpoint(
                path=checkpoint_path,
                scope="2026-09-09",
                config_fingerprint="config-v2",
                execution_context_fingerprint="same-destination",
                logger=logger,
            )
            first.data["profiles"] = {"店铺": {"steps": {"订单": {"status": "success"}}}}
            first._persist()

            resumed = ResumeCheckpoint(
                path=checkpoint_path,
                scope="2026-09-09",
                config_fingerprint="config-v3",
                execution_context_fingerprint="same-destination",
                logger=logger,
            )

        self.assertIn("店铺", resumed.data["profiles"])
        self.assertEqual("config-v3", resumed.data["config_fingerprint"])
        self.assertEqual(
            "config-v2", resumed.data["previous_config_fingerprint"]
        )

    def test_destination_change_starts_fresh_checkpoint_state(self):
        logger = logging.getLogger("test_checkpoint_context_change")
        with tempfile.TemporaryDirectory() as temporary_directory:
            checkpoint_path = Path(temporary_directory) / "checkpoint.json"
            first = ResumeCheckpoint(
                path=checkpoint_path,
                scope="2026-09-09",
                config_fingerprint="config",
                execution_context_fingerprint="destination-a",
                logger=logger,
            )
            first.data["profiles"] = {"店铺": {"steps": {"订单": {"status": "success"}}}}
            first._persist()

            fresh = ResumeCheckpoint(
                path=checkpoint_path,
                scope="2026-09-09",
                config_fingerprint="config",
                execution_context_fingerprint="destination-b",
                logger=logger,
            )

        self.assertEqual({}, fresh.data["profiles"])


if __name__ == "__main__":
    unittest.main()
