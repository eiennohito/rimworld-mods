import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from rwlib import core, build, install, runner, lifecycle


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        (self.source / 'About').mkdir(parents=True)
        (self.source / 'About/About.xml').write_text('<ModMetaData><packageId>test.mod</packageId></ModMetaData>')
        (self.source / 'payload').write_bytes(b'new-build')
        self.folder = self.root / 'Mods'
        self.destination = self.folder / 'test-mod'
    def tearDown(self): self.temp.cleanup()
    def previous(self): return install.previous_copies(self.folder, self.destination, 'test.mod')
    def test_runtime_dependencies_accept_installed_dlc_but_reject_missing_dlc(self):
        game = self.root / 'game'
        royalty = game / 'Data/Royalty/About/About.xml'
        royalty.parent.mkdir(parents=True)
        royalty.write_text('<ModMetaData><packageId>Ludeon.RimWorld.Royalty</packageId></ModMetaData>')
        (self.source / 'About/About.xml').write_text('''<ModMetaData><packageId>test.mod</packageId>
<modDependencies><li><packageId>Ludeon.RimWorld.Royalty</packageId></li></modDependencies></ModMetaData>''')
        project = {'package_id': 'local.patch', 'dependencies': ['test.mod']}
        with patch.object(core, 'GAME', game), patch.object(core, 'workshop_index', return_value={'test.mod': self.source}):
            self.assertEqual(runner.dependencies(project, []), {'test.mod': self.source})
            royalty.unlink()
            with self.assertRaisesRegex(ValueError, 'Missing Workshop dependency: ludeon.rimworld.royalty'):
                runner.dependencies(project, [])
    def test_runtime_dependencies_build_and_validate_local_companions(self):
        game = self.root / 'game'
        (game / 'Data').mkdir(parents=True)
        companion = {'package_id': 'test.mod', 'key': 'companion'}
        with patch.object(core, 'GAME', game), patch.object(core, 'workshop_index', return_value={}), \
             patch.object(core, 'projects', return_value={'companion': companion}), \
             patch.object(build, 'build', return_value=self.source) as compile_mod, \
             patch.object(build, 'validate') as validate:
            self.assertEqual(runner.dependencies({'package_id': 'local.patch'}, ['test.mod']), {'test.mod': self.source})
            compile_mod.assert_called_once_with(companion)
            validate.assert_called_once_with(self.source)

    def test_runtime_dependencies_accept_local_test_copies_without_installation(self):
        other = self.root / 'other'
        shutil.copytree(self.source, other)
        with patch.object(core, 'ROOT', self.root), patch.object(core, 'GAME', self.root / 'game'), \
             patch.object(core, 'workshop_index', return_value={'test.mod': other}):
            self.assertEqual(runner.dependencies({'package_id': 'local.patch'}, [], [self.source]),
                             {'test.mod': self.source})
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                runner.dependencies({'package_id': 'local.patch'}, [], [self.source, other])
    def test_install_and_duplicate_replacement_keep_backups(self):
        install.transaction(self.source, self.destination, [], self.root / 'unused')
        (self.destination / 'payload').write_bytes(b'old-build')
        duplicate = self.folder / 'old-name'
        shutil.copytree(self.destination, duplicate)
        before = self.previous()
        self.assertEqual(len(before), 2)
        backup = install.transaction(self.source, self.destination, before, self.root / 'backup')
        self.assertEqual((backup / 'test-mod/payload').read_bytes(), b'old-build')
        self.assertEqual((self.destination / 'payload').read_bytes(), b'new-build')
        self.assertFalse(duplicate.exists())
    def test_final_rename_failure_restores_previous_files(self):
        install.transaction(self.source, self.destination, [], self.root / 'unused')
        (self.destination / 'payload').write_bytes(b'keep-me')
        rename = Path.rename
        def failing(path, target):
            if path.name == 'incoming': raise OSError('injected commit failure')
            return rename(path, target)
        with patch.object(Path, 'rename', failing), self.assertRaises(OSError):
            install.transaction(self.source, self.destination, self.previous(), self.root / 'backup')
        self.assertEqual((self.destination / 'payload').read_bytes(), b'keep-me')
    def test_receipt_failure_also_rolls_back_files(self):
        install.transaction(self.source, self.destination, [], self.root / 'unused')
        (self.destination / 'payload').write_bytes(b'keep-me')
        def fail(): raise OSError('injected receipt failure')
        with self.assertRaises(OSError):
            install.transaction(self.source, self.destination, self.previous(), self.root / 'backup', fail)
        self.assertEqual((self.destination / 'payload').read_bytes(), b'keep-me')
    def test_unrelated_destination_is_never_replaced(self):
        shutil.copytree(self.source, self.destination)
        (self.destination / 'About/About.xml').write_text('<ModMetaData><packageId>other.mod</packageId></ModMetaData>')
        with self.assertRaises(ValueError): self.previous()
    def test_linked_copy_is_never_replaced(self):
        self.folder.mkdir()
        self.destination.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError): self.previous()
    def test_clean_packages_do_not_keep_removed_assets(self):
        project = {'root': self.source, 'key': 'test-mod', 'package_id': 'test.mod', 'project': 'Source/Test.csproj',
                   'assembly': 'Test', 'content': ['About', 'assets']}
        (self.source / 'assets').mkdir()
        obsolete = self.source / 'assets/removed.txt'
        obsolete.write_text('old asset')
        state = {'revision': 1}
        def compile_stub(project, output, cache_key, capture=False):
            output.mkdir(parents=True)
            (output / 'Test.dll').write_bytes(b'test assembly')
        with patch.object(core, 'ROOT', self.root), patch.object(build, 'inputs', lambda p: dict(state)), patch.object(build, 'compile_project', compile_stub), lifecycle.session('build-test'):
            first = build.build(project)
            obsolete.unlink(); state['revision'] = 2
            second = build.build(project)
            self.assertNotEqual(first, second)
            self.assertTrue((first / 'assets/removed.txt').exists())
            self.assertFalse((second / 'assets/removed.txt').exists())
            self.assertEqual(build.build(project), second)
            (second / 'unexpected-file').write_text('stale')
            self.assertEqual(build.validate(second)['package_id'], 'test.mod')
    def test_run_preferences_mute_every_audio_channel(self):
        import xml.etree.ElementTree as ET
        runner.preferences(self.root / 'data')
        prefs = ET.parse(self.root / 'data/Config/Prefs.xml').getroot()
        for key in ('volumeMaster', 'volumeGame', 'volumeMusic', 'volumeAmbient', 'volumeUI'):
            self.assertEqual(prefs.findtext(key), '0')
        self.assertEqual(prefs.findtext('fullscreen'), 'False')

    def test_runtime_runner_stages_independent_mods_and_records_packages(self):
        dependency = self.root / 'dependency'
        (dependency / '.git').mkdir(parents=True)
        (dependency / '.git/config').write_text('not runtime content')
        (dependency / 'payload').write_bytes(b'dependency')
        project = {'key': 'test-mod', 'package_id': 'test.mod', 'tests': {'runtime': {}}}

        def make_game(run_dir):
            game = run_dir / 'game'
            (game / 'Mods').mkdir(parents=True)
            core.write_json(run_dir / 'quiet-audio.json', {'noAudio': True})
            return game

        test = self
        class Process:
            pid = 99999999
            returncode = 0
            def __init__(self, command, **kwargs):
                run_dir = kwargs['cwd']
                staged = run_dir / 'game/Mods/test-mod/payload'
                test.assertEqual(staged.read_bytes(), b'new-build')
                staged.write_bytes(b'isolated edit')
                test.assertEqual((test.source / 'payload').read_bytes(), b'new-build')
                test.assertEqual((run_dir / 'game/Mods/dependency/payload').read_bytes(), b'dependency')
                test.assertFalse((run_dir / 'game/Mods/dependency/.git').exists())
                test.assertIn('-Headless', command)
                core.write_json(run_dir / 'data/report.json', {
                    'steam': {'active': False, 'initialized': False, 'nativeLibraryMapped': False},
                    'audio': {'masterVolume': 0},
                    'mods': [{'packageId': key} for key in ('test.mod', 'dep.mod', 'local.fixture')],
                    'tests': [{'pass': True}],
                })
            def wait(self, timeout=None): return self.returncode

        with patch.object(core, 'ROOT', self.root), \
             patch.object(build, 'build', return_value=self.source), \
             patch.object(build, 'validate', return_value={'build_id': 'example-build'}), \
             patch.object(core, 'game_record', return_value={'version': '1.7.test'}), \
             patch.object(runner, 'make_game', side_effect=make_game), \
             patch.object(runner, 'dependencies', return_value={'dep.mod': dependency}), \
             patch.object(runner, 'harness', return_value='local.fixture'), \
             patch.object(runner.subprocess, 'Popen', Process), lifecycle.session('runner-staging'):
            run = runner.test(project, 'runtime')
        inputs = json.loads((run / 'inputs.json').read_text())
        self.assertEqual(set(inputs['packages']), {'test.mod', 'dep.mod'})
        self.assertEqual(inputs['packages']['test.mod']['build_id'], 'example-build')
        self.assertTrue(json.loads((run / 'result.json').read_text())['pass'])
    def test_build_records_legacy_dependency_assemblies(self):
        dependency = self.root / 'workshop/1541460369'
        for relative in ('Assemblies/BPC.dll', 'v1.6/Assemblies/BPC.dll'):
            path = dependency / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'legacy-compatible-mod')
        (self.source / 'Source').mkdir()
        (self.source / 'mod.toml').write_text('schema = 1')
        props = self.root / 'tools/dotnet/RimWorld17.props'
        props.parent.mkdir(parents=True); props.write_text('<Project/>')
        project = {'root': self.source, 'content': ['About'], 'dependencies': ['voult.betterpawncontrol']}
        game = self.root / 'game'
        game.mkdir()
        for name in ('Assembly-CSharp.dll', 'UnityStubs.dll', 'Waylith.dll', 'RimWorld.dll'):
            (game / name).write_bytes(b'game-reference')
        with patch.object(core, 'ROOT', self.root), patch.object(core, 'WORKSHOP', dependency.parent), \
             patch.object(core, 'GAME', game), \
             patch.object(core, 'workshop_index', return_value={'voult.betterpawncontrol': dependency}), \
             patch.object(core, 'game_record', return_value={}), patch.object(core, 'git_record', return_value={}):
            first = build.inputs(project)
            self.assertIn(str(dependency / 'Assemblies/BPC.dll'), first['dependencies'])
            self.assertIn(str(dependency / 'v1.6/Assemblies/BPC.dll'), first['dependencies'])
            (dependency / 'Assemblies/BPC.dll').write_bytes(b'updated-legacy-mod')
            self.assertNotEqual(first, build.inputs(project))
    def test_bundled_assemblies_stay_inside_the_project(self):
        (self.source / 'Libraries').mkdir(parents=True)
        (self.source / 'Libraries/0Stub.dll').write_bytes(b'stub')
        project = {'root': self.source, 'content': [], 'bundled_assemblies': ['Libraries/0Stub.dll']}
        self.assertEqual(list(build.bundled_assemblies(project)), ['Libraries/0Stub.dll'])
        for bad in ('../outside.dll', 'Libraries/missing.dll', 'mod.toml'):
            with self.assertRaises(ValueError): build.bundled_assemblies({**project, 'bundled_assemblies': [bad]})
    def test_runs_have_independent_xdg_paths_without_changing_parent(self):
        before = dict(os.environ)
        with patch.object(core, 'ROOT', self.root):
            first = core.environment(self.root / 'run-a')
            second = core.environment(self.root / 'run-b')
        for name in ('XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME', 'XDG_RUNTIME_DIR'):
            self.assertNotEqual(first[name], second[name])
        self.assertEqual(before, dict(os.environ))

    def test_cleanup_only_collects_expired_unpinned_dead_sessions(self):
        from datetime import timedelta
        with patch.object(core, 'ROOT', self.root):
            with lifecycle.session('test') as folder:
                data = json.loads((folder / 'session.json').read_text())
                data['expires'] = lifecycle.stamp(lifecycle.now() - timedelta(days=1))
                core.write_json(folder / 'session.json', data)
                self.assertEqual(lifecycle.collect(apply=True), [])
            data = json.loads((folder / 'session.json').read_text())
            data.update(expires=lifecycle.stamp(lifecycle.now() - timedelta(days=1)), processes=[], pinned=True)
            core.write_json(folder / 'session.json', data)
            self.assertEqual(lifecycle.collect(apply=True), [])
            data['pinned'] = False
            core.write_json(folder / 'session.json', data)
            output = self.root / 'outputs/mods/user-mod/keep.txt'
            output.parent.mkdir(parents=True); output.write_text('user output')
            self.assertEqual(lifecycle.collect(), [folder]); self.assertTrue(folder.exists())
            lifecycle.collect(apply=True)
            self.assertFalse(folder.exists()); self.assertTrue(output.exists())

    def test_named_session_reuse_refreshes_retention(self):
        with patch.object(core, 'ROOT', self.root):
            with lifecycle.session('test', 'repeatable') as folder: pass
            first = json.loads((folder / 'session.json').read_text())
            with lifecycle.session('test-again', 'repeatable'): pass
            second = json.loads((folder / 'session.json').read_text())
            self.assertEqual(first['created'], second['created'])
            self.assertGreaterEqual(second['expires'], first['expires'])
            self.assertEqual(second['status'], 'finished')

    def test_explicit_all_cleanup_preserves_live_pinned_and_persistent_files(self):
        with patch.object(core, 'ROOT', self.root):
            with lifecycle.session('test', 'recent') as recent:
                self.assertEqual(lifecycle.collect(apply=True, all_sessions=True), [])
            with lifecycle.session('test', 'pinned') as pinned: pass
            lifecycle.pin('pinned')
            with lifecycle.session('test', 'child') as child: pass
            data = json.loads((child / 'session.json').read_text())
            data['processes'] = [lifecycle.process_record(os.getpid())]
            core.write_json(child / 'session.json', data)
            output = self.root / 'outputs/mods/keep'
            output.mkdir(parents=True)
            self.assertEqual(lifecycle.collect(), [])
            self.assertEqual(lifecycle.collect(all_sessions=True), [recent])
            self.assertTrue(recent.exists())
            self.assertEqual(lifecycle.collect(apply=True, all_sessions=True), [recent])
            self.assertFalse(recent.exists())
            self.assertTrue(pinned.exists())
            self.assertTrue(child.exists())
            self.assertTrue(output.exists())

    def test_cleanup_cli_applies_by_default_and_dry_run_preserves_files(self):
        from datetime import timedelta
        from rwlib import __main__ as cli
        for kind in ('sessions', 'cache'):
            for dry_run in (True, False):
                with self.subTest(kind=kind, dry_run=dry_run), patch.object(core, 'ROOT', self.root):
                    if kind == 'sessions':
                        with lifecycle.session('test', 'cleanup-cli') as target: pass
                        data = json.loads((target / 'session.json').read_text())
                        data['expires'] = lifecycle.stamp(lifecycle.now() - timedelta(days=1))
                        core.write_json(target / 'session.json', data)
                    else:
                        target = self.root / '.cache/hosts'
                        target.mkdir(parents=True)
                        (target / 'payload').write_text('rebuildable')
                    args = ['rw', 'clean', kind] + (['--dry-run'] if dry_run else [])
                    with patch('sys.argv', args): cli.main()
                    self.assertEqual(target.exists(), dry_run)
                    if dry_run: shutil.rmtree(target)

    def test_abandoned_session_receives_retention_from_detection(self):
        from datetime import timedelta
        with patch.object(core, 'ROOT', self.root):
            folder = self.root / 'sessions/crashed'
            old = lifecycle.stamp(lifecycle.now() - timedelta(days=30))
            core.write_json(folder / 'session.json', {'created': old, 'updated': old, 'status': 'active',
                'expires': None, 'pinned': False, 'processes': [{'pid': 99999999, 'start': 'missing'}]})
            lifecycle.collect(apply=True)
            data = json.loads((folder / 'session.json').read_text())
            self.assertEqual(data['status'], 'abandoned')
            self.assertGreater(data['expires'], lifecycle.stamp(lifecycle.now()))

    def test_reference_changes_during_build_do_not_block_packaging(self):
        project = {'root': self.source, 'key': 'test-mod', 'package_id': 'test.mod',
                   'project': 'Source/Test.csproj', 'assembly': 'Test', 'content': ['About']}
        calls = 0
        def changing_inputs(project):
            nonlocal calls
            calls += 1
            return {'revision': calls}
        def compile_stub(project, output, cache_key, capture=False):
            output.mkdir(parents=True)
            (output / 'Test.dll').write_bytes(b'test assembly')
        with patch.object(core, 'ROOT', self.root), patch.object(build, 'inputs', changing_inputs), patch.object(build, 'compile_project', compile_stub), lifecycle.session('stage-failure'):
            package = build.build(project)
            self.assertTrue((package / '1.7/Assemblies/Test.dll').is_file())


if __name__ == '__main__': unittest.main()
