import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import call, patch
from rwlib import build, core, install, sync
from rwlib import __main__ as cli


class InstallationSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.package = self.root / 'package'
        (self.package / 'About').mkdir(parents=True)
        (self.package / 'About/About.xml').write_text('<ModMetaData><packageId>local.example</packageId></ModMetaData>')
        (self.package / 'payload').write_bytes(b'current')
        self.fingerprint = {'revision': 1}
        self.record = {'schema': 1, 'key': 'example', 'package_id': 'local.example', 'build_id': 'current',
                       'inputs': self.fingerprint, 'files': list(sync.files(self.package))}
        (self.package / 'build.json').write_text(json.dumps(self.record))
        self.project = {'key': 'example', 'package_id': 'local.example'}
        self.folder = self.root / 'Mods'
        self.destination = self.folder / 'example'
        self.settings = self.root / 'settings.json'
        self.settings.write_text(json.dumps({'current_instance': 'Test', 'instances': {'Test': {'local_folder': str(self.folder)}}}))
    def tearDown(self): self.temp.cleanup()
    def installed(self): shutil.copytree(self.package, self.destination)
    def row(self, fingerprint=None):
        candidates = {'local.example': sorted(self.folder.iterdir())} if self.folder.is_dir() else {}
        with patch.object(build, 'latest', return_value=self.package), patch.object(build, 'inputs', return_value=fingerprint or self.fingerprint):
            return sync.project_status(self.project, self.folder, candidates)
    def test_current_install_is_in_sync(self):
        self.installed()
        self.assertTrue(self.row()['in_sync'])
    def test_missing_install_is_reported_without_installing(self):
        row = self.row()
        self.assertEqual(row['installation'], 'missing')
        self.assertFalse(self.folder.exists())
    def test_development_changes_are_separate_from_installed_content(self):
        self.installed()
        row = self.row({'revision': 2})
        self.assertEqual(row['installation'], 'in-sync')
        self.assertEqual(row['development'], 'changed since build')
        self.assertFalse(row['in_sync'])
    def test_changed_installation_is_compared_to_current_package(self):
        self.installed()
        (self.destination / 'payload').write_bytes(b'old')
        old = dict(self.record, build_id='old', files=list(sync.files(self.destination)))
        (self.destination / 'build.json').write_text(json.dumps(old))
        self.assertEqual(self.row()['installation'], 'older/different')
        (self.destination / 'payload').write_bytes(b'locally edited')
        row = self.row()
        self.assertEqual(row['installation'], 'older/different')
        self.assertEqual(row['copies'][0]['difference']['changed'], ['payload'])
    def test_legacy_install_is_reported_by_actual_bytes(self):
        self.installed()
        (self.destination / 'build.json').unlink()
        self.assertTrue(self.row()['in_sync'])
        (self.destination / 'payload').write_bytes(b'legacy')
        self.assertEqual(self.row()['installation'], 'different (legacy)')
    def test_duplicates_are_not_treated_as_synced(self):
        self.installed()
        shutil.copytree(self.package, self.folder / 'old-folder-name')
        row = self.row()
        self.assertEqual(row['installation'], 'duplicates')
        self.assertFalse(row['in_sync'])
    def test_all_projects_include_unbuilt_mods_and_do_not_rebuild(self):
        self.installed()
        other = {'key': 'unbuilt', 'package_id': 'local.unbuilt'}
        with patch.object(core, 'projects', return_value={'example': self.project, 'unbuilt': other}), patch.object(sync, 'instance', return_value=('Test', self.folder)), patch.object(build, 'latest', side_effect=lambda p: self.package if p['key'] == 'example' else None), patch.object(build, 'inputs', return_value=self.fingerprint), patch.object(build, 'build') as compile_mod:
            report = sync.status()
        self.assertEqual(len(report['mods']), 2)
        self.assertEqual(report['mods'][1]['development'], 'unbuilt')
        self.assertFalse(report['in_sync'])
        compile_mod.assert_not_called()
    def test_damaged_build_does_not_hide_other_status(self):
        (self.package / 'build.json').write_text('invalid json')
        self.assertEqual(self.row()['build'], 'invalid/error')
    def test_install_applies_without_an_extra_flag(self):
        with patch.object(core, 'ROOT', self.root), patch.object(build, 'latest', return_value=self.package), patch.object(build, 'inputs', side_effect=AssertionError('must not gate installation on inputs')):
            install.install(self.project, settings=self.settings)
        self.assertEqual((self.destination / 'payload').read_bytes(), b'current')
        receipts = list((self.root / 'state/installs/Test/example').glob('*/receipt.json'))
        self.assertEqual(len(receipts), 1)
    def test_explicit_dry_run_does_not_install(self):
        with patch.object(core, 'ROOT', self.root), patch.object(build, 'latest', return_value=self.package), patch.object(build, 'inputs', return_value=self.fingerprint):
            install.install(self.project, dry_run=True, settings=self.settings)
        self.assertFalse(self.folder.exists())
        self.assertFalse((self.root / 'state/installs').exists())
    def test_cli_install_defaults_and_dry_run(self):
        for flags, dry_run in (([], False), (['--dry-run'], True)):
            with self.subTest(flags=flags), patch.object(sys, 'argv', ['rw', 'install', 'example', *flags]), patch.object(cli, 'dispatch') as dispatch, patch('rwlib.lifecycle.session'):
                cli.execute()
                args = dispatch.call_args.args[0]
                self.assertEqual(args.command, 'install')
                self.assertEqual(args.dry_run, dry_run)
    def test_cli_sync_check_reports_drift_without_starting_session(self):
        with patch.object(sys, 'argv', ['rw', 'sync', '--check']), patch.object(sync, 'status', return_value={'in_sync': False}), patch.object(sync, 'show'), patch('rwlib.lifecycle.session') as session:
            with self.assertRaises(SystemExit) as error: cli.execute()
            self.assertEqual(error.exception.code, 1)
            session.assert_not_called()
    def test_cli_sync_check_accepts_current_installations(self):
        with patch.object(sys, 'argv', ['rw', 'sync', '--check']), patch.object(sync, 'status', return_value={'in_sync': True}), patch.object(sync, 'show'):
            cli.execute()


class SyncCommandTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {'project': 'current', 'in_sync': True, 'build': 'valid', 'development': 'current'},
            {'project': 'stale', 'in_sync': False, 'build': 'valid', 'development': 'changed since build'},
            {'project': 'missing', 'in_sync': False, 'build': 'missing', 'development': 'unbuilt'},
            {'project': 'install-only', 'in_sync': False, 'build': 'valid', 'development': 'current'},
            {'project': 'damaged', 'in_sync': False, 'build': 'invalid/error', 'development': 'unknown'},
        ]
        self.report = {'in_sync': False, 'instance': 'Test', 'local_folder': '/unused', 'mods': self.rows}
        self.projects = {r['project']: {'key': r['project'], 'package_id': 'local.' + r['project']} for r in self.rows}
        self.status = self.start(patch.object(sync, 'status', return_value=self.report))
        self.start(patch.object(sync, 'show'))
        self.start(patch.object(core, 'project', side_effect=self.projects.__getitem__))
        self.compile = self.start(patch.object(build, 'build'))
        self.install = self.start(patch.object(install, 'install'))
        self.preflight = self.start(patch.object(install, 'previous_copies'))
        self.session = self.start(patch('rwlib.lifecycle.session'))
        self.input = self.start(patch('builtins.input', return_value=''))
    def start(self, patcher):
        self.addCleanup(patcher.stop)
        return patcher.start()
    def execute(self, *flags):
        with patch.object(sys, 'argv', ['rw', 'sync', *flags]): cli.execute()
    def test_enter_updates_all_pending_and_reuses_current_build(self):
        self.execute()
        self.assertEqual(self.compile.call_args_list, [
            call(self.projects['stale'], force=False), call(self.projects['missing'], force=False),
            call(self.projects['damaged'], force=True)])
        self.assertEqual([c.args[0]['key'] for c in self.install.call_args_list],
                         ['stale', 'missing', 'install-only', 'damaged'])
        self.session.assert_called_once_with('sync', None)
    def test_all_does_not_prompt(self):
        self.execute('--all')
        self.input.assert_not_called()
        self.assertEqual(self.install.call_count, 4)
    def test_answer_selects_pending_numbers_deduplicates_and_preserves_order(self):
        self.execute('--answer=3,1,3')
        self.input.assert_not_called()
        self.assertEqual([c.args[0]['key'] for c in self.install.call_args_list], ['stale', 'install-only'])
    def test_interactive_partial_selection(self):
        self.input.return_value = '2,4'
        self.execute()
        self.assertEqual([c.args[0]['key'] for c in self.install.call_args_list], ['missing', 'damaged'])
    def test_status_modes_and_decline_do_not_mutate(self):
        for flags in [('--no',), ('--json',), ('--answer=no',), ()]:
            with self.subTest(flags=flags):
                self.input.return_value = 'no'
                self.execute(*flags)
        self.session.assert_not_called()
        self.compile.assert_not_called()
        self.install.assert_not_called()
    def test_invalid_answers_do_not_partially_update(self):
        for answer in ('0', '1,5', '-1', 'one', '1,,2', '1,'):
            with self.subTest(answer=answer), self.assertRaises(SystemExit) as error:
                self.execute('--answer=' + answer)
            self.assertEqual(error.exception.code, 1)
        self.compile.assert_not_called()
        self.install.assert_not_called()
        self.session.assert_not_called()
    def test_bad_interactive_answer_reprompts(self):
        self.input.side_effect = ['99', '3']
        self.execute()
        self.install.assert_called_once_with(self.projects['install-only'], instance_name='Test', settings=None)
    def test_eof_and_interrupt_cancel(self):
        for error in (EOFError, KeyboardInterrupt):
            self.input.side_effect = error
            self.execute()
        self.install.assert_not_called()
        self.session.assert_not_called()
    def test_current_report_does_not_prompt_or_start_session(self):
        self.report.update(in_sync=True, mods=[self.rows[0]])
        self.execute()
        self.input.assert_not_called()
        self.session.assert_not_called()
    def test_conflicting_flags_rejected(self):
        for flags in [('--all', '--no'), ('--all', '--answer=1'), ('--all', '--json'), ('--answer=1', '--check')]:
            with self.subTest(flags=flags), self.assertRaises(SystemExit) as error:
                self.execute(*flags)
            self.assertEqual(error.exception.code, 2)
        self.status.assert_not_called()
    def test_install_preflight_failure_prevents_builds(self):
        self.preflight.side_effect = ValueError('Refusing to replace a linked mod')
        with self.assertRaises(SystemExit): self.execute('--all')
        self.compile.assert_not_called()
        self.install.assert_not_called()
    def test_failed_build_stops_before_installing_that_mod(self):
        self.compile.side_effect = ValueError('Compilation failed')
        with self.assertRaises(SystemExit): self.execute('--all')
        self.install.assert_not_called()
    def test_instance_settings_and_session_are_forwarded(self):
        self.execute('--answer=3', '--instance', 'Test', '--settings', '/tmp/settings.json')
        self.status.assert_any_call(None, 'Test', Path('/tmp/settings.json'))
        self.install.assert_called_once_with(self.projects['install-only'], instance_name='Test', settings=Path('/tmp/settings.json'))


if __name__ == '__main__': unittest.main()
