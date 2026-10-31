"""Interrupted ETL regression tests; DB tests use a disposable database only."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
import unittest
import uuid
from unittest.mock import Mock, patch

import psycopg2
from psycopg2 import sql

from apps.file_ingest.service import FileIngestService, FileIngestWorker, PROJECT_ROOT


class RecoveryLoopTests(unittest.TestCase):
    def make_worker(self):
        worker = object.__new__(FileIngestWorker)
        worker._stop = threading.Event()
        worker._idle = threading.Event()
        worker._idle.set()
        worker._last_recovery_scan = float('-inf')
        worker._heartbeat = Mock()
        worker._process_ingest_run = Mock(return_value=False)
        worker._process_etl_run = Mock(return_value=False)
        worker.recover_interrupted_etl = Mock()
        return worker

    def test_existing_loop_throttles_scans_to_30_seconds(self):
        worker = self.make_worker()
        with patch('apps.file_ingest.service.time.monotonic', return_value=100):
            worker.run_once()
        with patch('apps.file_ingest.service.time.monotonic', return_value=129):
            worker.run_once()
        self.assertEqual(1, worker.recover_interrupted_etl.call_count)
        with patch('apps.file_ingest.service.time.monotonic', return_value=130):
            worker.run_once()
        self.assertEqual(2, worker.recover_interrupted_etl.call_count)

    def test_stopping_worker_does_not_claim_another_run(self):
        worker = self.make_worker()
        worker.stop()
        self.assertFalse(worker.run_once())
        worker._process_etl_run.assert_not_called()

    def test_running_child_pulses_without_another_polling_thread(self):
        worker = self.make_worker()
        worker._pulse_etl = Mock()
        worker._terminate_etl_process = Mock()
        child = Mock(returncode=0)
        child.communicate.side_effect = [subprocess.TimeoutExpired('test', 1), ('done', ''), ('done', '')]
        with patch('apps.file_ingest.service.subprocess.Popen', return_value=child), \
             patch('apps.file_ingest.service.time.monotonic', side_effect=[0, 0, 11]):
            result = worker._execute_etl_process(['test'], {}, 'run')
        self.assertEqual('done', result.stdout)
        self.assertEqual(2, worker._pulse_etl.call_count)

    def test_shutdown_terminates_and_reaps_current_child(self):
        worker = self.make_worker()
        worker._stop.set()
        worker._terminate_etl_process = Mock()
        child = Mock()
        child.communicate.return_value = ('', '')
        with patch('apps.file_ingest.service.subprocess.Popen', return_value=child):
            with self.assertRaisesRegex(RuntimeError, '后端停止'):
                worker._execute_etl_process(['test'], {}, 'run')
        worker._terminate_etl_process.assert_called_once_with(child, owns_group=True)
        child.communicate.assert_called_once()


@unittest.skipUnless(os.getenv('RUN_ETL_RECOVERY_DB_TESTS') == '1', 'disposable PostgreSQL database required')
class RecoveryDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from apps.fund_split_adjust.server import load_project_env
        load_project_env()
        cls.database_name = 'etl_recovery_test_' + uuid.uuid4().hex
        cls.kwargs = dict(host=os.getenv('PGHOST', '192.168.77.111'),
                          port=int(os.getenv('PGPORT', '5432')), user=os.getenv('PGUSER', 'postgres'),
                          password=os.getenv('PGPASSWORD'), connect_timeout=10)
        maintenance = psycopg2.connect(dbname=os.getenv('PGDATABASE', 'mock_coffice'), **cls.kwargs)
        maintenance.autocommit = True
        try:
            with maintenance.cursor() as cur:
                cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.database_name)))
        finally:
            maintenance.close()
        cls.service = FileIngestService(argparse.Namespace(
            host=cls.kwargs['host'], pg_port=cls.kwargs['port'], dbname=cls.database_name,
            user=cls.kwargs['user'], password=cls.kwargs['password'],
        ))
        try:
            with cls.service.transaction() as cur:
                cur.execute('CREATE SCHEMA ops')
                source = (PROJECT_ROOT / 'sql/common/368_file_ingest_automation_postgres.sql').read_text(encoding='utf-8')
                for table in ('ingest_run', 'etl_run', 'etl_task', 'worker_heartbeat', 'refresh_watermark', 'operation_log'):
                    ddl = re.search(r'CREATE TABLE IF NOT EXISTS ops\.' + table + r' \(.*?\n\);', source, re.S)
                    cur.execute(ddl.group())
                cur.execute((PROJECT_ROOT / 'sql/common/466_etl_execution_ownership_postgres.sql').read_text(encoding='utf-8'))
                cur.execute('CREATE TABLE ops.executor_probe(value TEXT)')
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        maintenance = psycopg2.connect(dbname=os.getenv('PGDATABASE', 'mock_coffice'), **cls.kwargs)
        maintenance.autocommit = True
        try:
            with maintenance.cursor() as cur:
                cur.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(cls.database_name)))
        finally:
            maintenance.close()

    def setUp(self):
        with self.service.transaction() as cur:
            cur.execute('TRUNCATE ops.etl_task,ops.etl_run,ops.worker_heartbeat,ops.executor_probe,ops.refresh_watermark,ops.operation_log')
        self.worker = FileIngestWorker(self.service, worker_name='recovery-test')

    def tearDown(self):
        self.worker.stop()

    def make_run(self, *, owner=True, stale=False, stopped=False, legacy=False):
        run_id = str(uuid.uuid4())
        owner_id = str(uuid.uuid4())
        with self.service.transaction() as cur:
            if owner:
                cur.execute("""INSERT INTO ops.worker_heartbeat(worker_id,worker_name,status,last_seen_at)
                    VALUES(%s,'old-worker',%s,NOW()-(%s*INTERVAL '1 second'))""",
                    (owner_id, 'stopped' if stopped else 'busy', 180 if stale else 0))
            cur.execute("""INSERT INTO ops.etl_run(etl_run_id,trigger_type,scope,status,requested_etls,operator,
                worker_id,heartbeat_at,updated_at) VALUES(%s,'manual','affected','running','[]','test',%s,
                NOW()-(%s*INTERVAL '1 second'),NOW()-(%s*INTERVAL '1 minute'))""",
                (run_id, None if legacy else owner_id, 180 if stale else 0, 20 if stale else 0))
            for index, status in enumerate(('success', 'running', 'queued'), 1):
                cur.execute("""INSERT INTO ops.etl_task(etl_task_id,etl_run_id,etl_key,etl_label,
                    sequence_no,status,dependencies,command_args) VALUES(%s,%s,%s,'test',%s,%s,'[]','[]')""",
                    (str(uuid.uuid4()), run_id, 'test_' + str(index), index, status))
        return run_id, owner_id

    def state(self, run_id):
        with self.service.transaction() as cur:
            cur.execute('SELECT status,completed_at,error_message FROM ops.etl_run WHERE etl_run_id=%s', (run_id,))
            run = dict(cur.fetchone())
            cur.execute('SELECT status FROM ops.etl_task WHERE etl_run_id=%s ORDER BY sequence_no', (run_id,))
            return run, [r['status'] for r in cur.fetchall()]

    def test_restart_before_15_minutes_closes_stopped_owner_and_is_idempotent(self):
        run_id, _ = self.make_run(stopped=True)
        result = self.worker.recover_interrupted_etl()
        self.assertEqual({'etl_runs': 1, 'etl_tasks': 2}, result)
        run, states = self.state(run_id)
        self.assertEqual('partial_failed', run['status'])
        self.assertIsNotNone(run['completed_at'])
        self.assertEqual(['success', 'failed', 'skipped'], states)
        self.assertEqual(0, self.worker.recover_interrupted_etl()['etl_runs'])

    def test_first_task_interruption_closes_entire_run_failed(self):
        run_id, _ = self.make_run(stopped=True)
        with self.service.transaction() as cur:
            cur.execute("DELETE FROM ops.etl_task WHERE etl_run_id=%s AND status='success'", (run_id,))
        self.worker.recover_interrupted_etl()
        run, states = self.state(run_id)
        self.assertEqual('failed', run['status'])
        self.assertEqual(['failed', 'skipped'], states)

    def test_late_cleanup_cannot_change_finished_or_retried_run(self):
        run_id, _ = self.make_run()
        with self.service.transaction() as cur:
            cur.execute("UPDATE ops.etl_run SET status='queued' WHERE etl_run_id=%s", (run_id,))
            self.assertEqual(0, self.worker._close_interrupted_etl(cur, run_id, 'late callback'))
        self.assertEqual(['success', 'running', 'queued'], self.state(run_id)[1])

    def test_periodic_scan_recovers_legacy_record_missed_at_startup(self):
        run_id, _ = self.make_run(legacy=True)
        self.assertEqual(0, self.worker.recover_interrupted_etl()['etl_runs'])
        with self.service.transaction() as cur:
            cur.execute("UPDATE ops.etl_run SET updated_at=NOW()-INTERVAL '16 minutes' WHERE etl_run_id=%s", (run_id,))
        self.assertEqual(1, self.worker.recover_interrupted_etl()['etl_runs'])

    def test_long_task_with_live_owner_or_fresh_heartbeat_is_preserved(self):
        run_id, owner_id = self.make_run(stale=True)
        with self.service.transaction() as cur:
            cur.execute('UPDATE ops.worker_heartbeat SET last_seen_at=NOW(),current_task=%s WHERE worker_id=%s',
                        ('etl:' + run_id, owner_id))
        self.assertEqual(0, self.worker.recover_interrupted_etl()['etl_runs'])
        self.assertEqual('running', self.state(run_id)[0]['status'])

    def test_live_worker_no_longer_executing_abandoned_run_does_not_hide_it(self):
        run_id, owner_id = self.make_run(stale=True)
        with self.service.transaction() as cur:
            cur.execute("UPDATE ops.worker_heartbeat SET last_seen_at=NOW(),status='idle' WHERE worker_id=%s", (owner_id,))
        self.assertEqual(1, self.worker.recover_interrupted_etl()['etl_runs'])

    def test_crashed_owner_recovers_only_after_heartbeat_expires(self):
        run_id, _ = self.make_run(owner=False)
        self.assertEqual(0, self.worker.recover_interrupted_etl()['etl_runs'])
        with self.service.transaction() as cur:
            cur.execute("UPDATE ops.etl_run SET heartbeat_at=NOW()-INTERVAL '2 minutes' WHERE etl_run_id=%s", (run_id,))
        self.assertEqual(1, self.worker.recover_interrupted_etl()['etl_runs'])

    def test_surviving_executor_lock_blocks_recovery_and_new_dispatch(self):
        run_id, _ = self.make_run(stale=True)
        guard = self.service.connect()
        guard.autocommit = True
        try:
            with guard.cursor() as cur:
                cur.execute("SELECT pg_advisory_lock(hashtext('mock_coffice_global_etl'))")
            self.assertEqual(0, self.worker.recover_interrupted_etl()['etl_runs'])
            self.assertFalse(self.worker._process_etl_run())
            self.assertEqual('running', self.state(run_id)[0]['status'])
        finally:
            guard.close()
        self.assertEqual(1, self.worker.recover_interrupted_etl()['etl_runs'])

    def test_another_dispatcher_blocks_recovery(self):
        self.make_run(stale=True)
        guard = self.service.connect()
        guard.autocommit = True
        try:
            with guard.cursor() as cur:
                cur.execute("SELECT pg_advisory_lock(hashtext('mock_coffice_file_ingest_dispatch'))")
            self.assertEqual(0, self.worker.recover_interrupted_etl()['etl_runs'])
        finally:
            guard.close()

    def test_heartbeat_renews_running_attempt(self):
        run_id, _ = self.make_run(stale=True)
        with self.service.transaction() as cur:
            cur.execute('UPDATE ops.etl_run SET worker_id=%s WHERE etl_run_id=%s', (str(self.worker.worker_id), run_id))
        self.worker._pulse_etl(run_id)
        self.assertEqual(0, self.worker.recover_interrupted_etl()['etl_runs'])
        with self.service.transaction() as cur:
            cur.execute('SELECT current_task FROM ops.worker_heartbeat WHERE worker_id=%s', (str(self.worker.worker_id),))
            self.assertEqual('etl:' + run_id, cur.fetchone()['current_task'])

    def test_migration_is_repeatable_and_new_columns_have_comments(self):
        with self.service.transaction() as cur:
            cur.execute((PROJECT_ROOT / 'sql/common/466_etl_execution_ownership_postgres.sql').read_text(encoding='utf-8'))
            cur.execute("""SELECT col_description('ops.etl_run'::regclass,attnum) comment FROM pg_attribute
                WHERE attrelid='ops.etl_run'::regclass AND attname IN ('worker_id','heartbeat_at')""")
            comments = cur.fetchall()
        self.assertEqual(2, len(comments))
        self.assertTrue(all(r['comment'] for r in comments))

    def probe_command(self, run_id, owner_id):
        environment = self.worker._subprocess_environment()
        environment.update(ETL_PROBE_RUN=run_id, ETL_PROBE_OWNER=owner_id)
        return [sys.executable, '-m', 'apps.file_ingest.tests.test_etl_recovery', '--executor-probe'], environment

    def wait_for_probe(self, thread=None):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with self.service.transaction() as cur:
                cur.execute("SELECT value FROM ops.executor_probe WHERE value='started'")
                if cur.fetchone():
                    return
            if thread is not None and not thread.is_alive():
                break
            time.sleep(0.05)
        self.fail('executor probe did not start')

    def test_actual_executor_survives_owner_loss_until_cancelled_and_rolls_back(self):
        run_id, _ = self.make_run()
        owner_id = str(self.worker.worker_id)
        with self.service.transaction() as cur:
            cur.execute('UPDATE ops.etl_run SET worker_id=%s WHERE etl_run_id=%s', (owner_id, run_id))
        command, environment = self.probe_command(run_id, owner_id)
        errors = []

        def execute():
            try:
                self.worker._execute_etl_process(command, environment, run_id)
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=execute)
        thread.start()
        try:
            self.wait_for_probe(thread)
            # Reproduce loss of the owner while the actual executor is alive.
            with self.service.transaction() as cur:
                cur.execute("UPDATE ops.worker_heartbeat SET status='stopped' WHERE worker_id=%s", (owner_id,))
            self.assertEqual(0, self.worker.recover_interrupted_etl()['etl_runs'])
            self.assertFalse(self.worker._process_etl_run())
        finally:
            self.worker._stop.set()
            thread.join(timeout=12)
        self.assertFalse(thread.is_alive(), 'executor process was not reaped')
        self.assertEqual(1, len(errors))
        self.assertIn('后端停止', str(errors[0]))
        self.assertEqual(1, self.worker.recover_interrupted_etl()['etl_runs'])
        with self.service.transaction() as cur:
            cur.execute('SELECT value FROM ops.executor_probe ORDER BY value')
            self.assertEqual(['started'], [r['value'] for r in cur.fetchall()])

    def test_actual_executor_rejects_finished_attempt_before_touching_metrics(self):
        run_id, owner_id = self.make_run()
        with self.service.transaction() as cur:
            cur.execute("UPDATE ops.etl_run SET status='failed' WHERE etl_run_id=%s", (run_id,))
        command, environment = self.probe_command(run_id, owner_id)
        result = subprocess.run(command, env=environment, cwd=PROJECT_ROOT, text=True,
                                capture_output=True, encoding='utf-8', timeout=10)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('执行归属已失效', result.stderr)
        with self.service.transaction() as cur:
            cur.execute('SELECT count(*) count FROM ops.executor_probe')
            self.assertEqual(0, cur.fetchone()['count'])

    def test_registered_run_completes_with_real_executor_and_preserves_retry(self):
        run = self.service.create_etl_run({'douyin_settlement'}, trigger_type='manual',
                                          scope='affected', operator='test')
        run_id = str(run['etl_run_id'])
        real_popen = subprocess.Popen

        def safe_probe(command, **kwargs):
            self.assertIn('apps.file_ingest.etl_executor', command)
            environment = kwargs['env']
            environment.update(ETL_PROBE_RUN=run_id, ETL_PROBE_OWNER=str(self.worker.worker_id), ETL_PROBE_MODE='complete')
            return real_popen([sys.executable, '-m', 'apps.file_ingest.tests.test_etl_recovery', '--executor-probe'], **kwargs)

        with patch('apps.file_ingest.service.subprocess.Popen', side_effect=safe_probe):
            self.assertTrue(self.worker._process_etl_run())
        run, states = self.state(run_id)
        self.assertEqual('success', run['status'])
        self.assertTrue(states and all(status == 'success' for status in states))
        with self.service.transaction() as cur:
            cur.execute('SELECT etl_run_id FROM ops.refresh_watermark WHERE watermark_key=%s', ('affected',))
            self.assertEqual(run_id, str(cur.fetchone()['etl_run_id']))
        # Closing a stopped attempt leaves it eligible for the existing retry API.
        interrupted_id, _ = self.make_run(stopped=True)
        self.worker.recover_interrupted_etl()
        with self.service.transaction() as cur:
            cur.execute("SELECT etl_task_id FROM ops.etl_task WHERE etl_run_id=%s AND status='failed'", (interrupted_id,))
            task_id = str(cur.fetchone()['etl_task_id'])
        self.service.retry_etl_task(task_id, 'test', None)
        self.assertEqual('queued', self.state(interrupted_id)[0]['status'])

    def test_backend_stop_closes_current_task_and_all_pending_nodes(self):
        run = self.service.create_etl_run({'douyin_settlement'}, trigger_type='manual',
                                          scope='affected', operator='test')
        run_id = str(run['etl_run_id'])
        real_popen = subprocess.Popen

        def safe_probe(command, **kwargs):
            if 'apps.file_ingest.etl_executor' not in command:
                return real_popen(command, **kwargs)
            kwargs['env'].update(ETL_PROBE_RUN=run_id, ETL_PROBE_OWNER=str(self.worker.worker_id))
            return real_popen([sys.executable, '-m', 'apps.file_ingest.tests.test_etl_recovery', '--executor-probe'], **kwargs)

        with patch('apps.file_ingest.service.subprocess.Popen', side_effect=safe_probe), \
             patch.object(self.worker, '_process_ingest_run', return_value=False):
            thread = threading.Thread(target=self.worker.run_once)
            thread.start()
            try:
                self.wait_for_probe(thread)
            finally:
                self.worker.stop()
                thread.join(timeout=12)
        self.assertFalse(thread.is_alive())
        run, states = self.state(run_id)
        self.assertEqual('failed', run['status'])
        self.assertIsNotNone(run['completed_at'])
        self.assertEqual('failed', states[0])
        self.assertTrue(all(s == 'skipped' for s in states[1:]))
        with self.service.transaction() as cur:
            cur.execute('SELECT value FROM ops.executor_probe ORDER BY value')
            self.assertEqual(['started'], [r['value'] for r in cur.fetchall()])


def executor_probe():
    """Exercise the real lock-owning entrypoint without running a business ETL."""
    if not os.environ.get('PGDATABASE', '').startswith('etl_recovery_test_'):
        raise RuntimeError('executor probe requires a disposable database')
    from apps.file_ingest.etl_executor import main

    def metric_transaction(worker, task):
        with worker.service.transaction() as cur:
            cur.execute("UPDATE ops.etl_task SET status='running',started_at=NOW() WHERE etl_task_id=%s",
                        (str(task['etl_task_id']),))
        connection = psycopg2.connect(host=os.environ['PGHOST'], port=os.environ['PGPORT'],
            dbname=os.environ['PGDATABASE'], user=os.environ['PGUSER'], password=os.getenv('PGPASSWORD'))
        try:
            with connection.cursor() as cur:
                cur.execute("INSERT INTO ops.executor_probe VALUES('started')")
                connection.commit()
                cur.execute("INSERT INTO ops.executor_probe VALUES('uncommitted')")
                if os.getenv('ETL_PROBE_MODE') == 'complete':
                    connection.commit()
                    print('汇总：probe完成')
                else:
                    time.sleep(60)
        finally:
            connection.rollback()
            connection.close()
        with worker.service.transaction() as cur:
            cur.execute("""UPDATE ops.etl_task SET status='success',exit_code=0,
                started_at=NOW(),finished_at=NOW() WHERE etl_task_id=%s""", (str(task['etl_task_id']),))
        return 'success'

    sys.argv = ['probe', '--run-id', os.environ['ETL_PROBE_RUN'],
                '--worker-id', os.environ['ETL_PROBE_OWNER']]
    with patch.object(FileIngestWorker, '_run_etl_task', metric_transaction):
        return main()


if __name__ == '__main__':
    if sys.argv[1:] == ['--executor-probe']:
        raise SystemExit(executor_probe())
    unittest.main()
