import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rwlib import core
from rwlib import __main__ as cli


class ConfigTests(unittest.TestCase):
    def test_fresh_tooling_checkout_starts_without_config_or_mods(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tools = root / 'tools'
            shutil.copytree(core.ROOT / 'tools/rwlib', tools / 'rwlib',
                            ignore=shutil.ignore_patterns('__pycache__'))
            for args in (['--help'], ['list']):
                result = subprocess.run([sys.executable, '-m', 'rwlib', *args], cwd=tools,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / 'workspace.json').exists())

    def test_independent_mods_are_discovered_without_registration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for key in ('one-mod', 'another-mod'):
                mod = root / 'projects' / key
                mod.mkdir(parents=True)
                (mod / 'mod.toml').write_text(f'key = "{key}"\n')
            (root / 'projects/not-a-mod').mkdir()
            with patch.object(core, 'ROOT', root):
                self.assertEqual(set(core.projects()), {'one-mod', 'another-mod'})
                shutil.rmtree(root / 'projects/one-mod')
                self.assertEqual(set(core.projects()), {'another-mod'})

    def test_missing_config_uses_reference_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = core.load_config(root)
            self.assertEqual(config['game'], str(root / 'references/game'))
            self.assertEqual(config['player_data'], str(root / 'references/player_data'))
            self.assertEqual(config['ilspy'], 'ilspycmd')

    def test_relative_paths_resolve_from_workspace_not_current_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'workspace.json').write_text(json.dumps({'game': 'owned-game', 'ilspy': 'ilspycmd'}))
            config = core.load_config(root)
            self.assertEqual(config['game'], str(root / 'owned-game'))
            self.assertEqual(config['ilspy'], 'ilspycmd')

    def test_setup_needs_no_rimsort_or_player_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game = root / 'owned-game'
            game.mkdir()
            (game / 'Version.txt').write_text('1.7.1234 rev1')
            workshop = root / 'owned-workshop'
            workshop.mkdir()
            config = {**core.load_config(root), 'game': str(game), 'workshop': str(workshop)}
            with patch.object(core, 'ROOT', root), patch.object(core, 'CFG', config), patch.object(core, 'GAME', game):
                cli.setup()
                cli.setup()
            self.assertEqual((root / 'references/game').resolve(), game)
            self.assertFalse((root / 'references/rimsort').exists())

    def test_setup_does_not_create_links_to_themselves(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = core.load_config(root)
            game = Path(config['game'])
            game.mkdir(parents=True)
            (game / 'Version.txt').write_text('1.7.1234 rev1')
            Path(config['workshop']).mkdir()
            with patch.object(core, 'ROOT', root), patch.object(core, 'CFG', config), patch.object(core, 'GAME', game):
                cli.setup()
            self.assertFalse(game.is_symlink())

    def test_setup_explains_missing_required_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(core, 'CFG', core.load_config(Path(folder))):
                with self.assertRaisesRegex(ValueError, 'workspace.example.json'):
                    cli.setup()
