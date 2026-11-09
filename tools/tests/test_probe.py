import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from rwlib import core, lifecycle, probe


class SaveProbeTests(unittest.TestCase):
    def test_probe_uses_copies_and_preserves_order_without_live_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = root / 'installed'
            local = game / 'Mods/Example'
            (local / 'About').mkdir(parents=True)
            (local / 'About/About.xml').write_text('<ModMetaData><packageId>example.mod</packageId></ModMetaData>')
            (local / 'payload').write_text('installed payload')
            config = root / 'player/Config/ModsConfig.xml'
            config.parent.mkdir(parents=True)
            config.write_text('<ModsConfigData><activeMods><li>example.mod</li></activeMods></ModsConfigData>')
            (config.parent / 'Example.xml').write_text('<Settings/>')
            (config.parent / 'Profiler.xml').write_text('<Profiler/>')
            save = root / 'player/Original.rws'
            save.write_text('original save')
            fixture = root / 'investigation/Probe.csproj'
            fixture.parent.mkdir()
            fixture.write_text('<Project/>')
            (fixture.parent / 'CargoPlan.json').write_text('{"cargo": []}')
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}

            def host(run):
                private = run / 'game'
                (private / 'Mods').mkdir(parents=True)
                (private / 'Waylith.dll').write_bytes(b'quiet host')
                core.write_json(run / 'quiet-audio.json', {
                    'noAudio': True})
                return private

            class Process:
                pid = 999999999
                returncode = 0
                def __init__(self, command, **kwargs):
                    self.command = command
                def wait(self, timeout):
                    data = Path(next(a.split('=', 1)[1] for a in self.command if a.startswith('-savedatafolder=')))
                    entries = ET.parse(data / 'Config/ModsConfig.xml').findall('activeMods/li')
                    assert [e.text for e in entries] == ['example.mod', 'local.saveprobe']
                    assert not any(a.startswith('-mod=') for a in self.command)
                    assert (data / 'Config/Example.xml').is_file()
                    assert not (data / 'Config/Profiler.xml').exists()
                    (data / 'Saves/Probe.rws').write_text('sandbox changed save')
                    core.write_json(data / 'report.json', {
                        'steam': {'active': False, 'initialized': False, 'nativeLibraryMapped': False},
                        'audio': {'masterVolume': 0}, 'tests': [{'pass': True}],
                        'mods': [{'packageId': e.text} for e in entries]})

            with patch.object(core, 'ROOT', root), patch.object(core, 'GAME', game), \
                 patch.object(core, 'WORKSHOP', root / 'workshop'), \
                 patch.object(core, 'game_record', return_value={'version': '1.7.test'}), \
                 patch.object(probe, 'make_game', host), \
                 patch.object(probe, 'harness', return_value='local.saveprobe'), \
                 patch.object(probe.subprocess, 'Popen', Process), lifecycle.session('probe-test'):
                run = probe.probe(fixture, save, config)
                self.assertTrue(json.loads((run / 'result.json').read_text())['pass'])
                self.assertEqual((run / 'game/Mods/probe-0/payload').read_text(), 'installed payload')
                self.assertEqual(json.loads((run / 'inputs.json').read_text())['fixture'], str(fixture))
                package = root / 'outputs/mods/example/build'
                (package / 'About').mkdir(parents=True)
                (package / 'About/About.xml').write_bytes((local / 'About/About.xml').read_bytes())
                (package / 'payload').write_text('new build')
                record = {'inputs': {'game': core.game_record()}, 'build_id': 'build'}
                with patch.object(probe.b, 'validate', return_value=record) as validate:
                    run = probe.probe(fixture, save, config, packages=[package])
                    validate.assert_called_once_with(package)
                    self.assertEqual((run / 'game/Mods/probe-0/payload').read_text(), 'new build')
                    self.assertEqual(json.loads((run / 'inputs.json').read_text())['package_overrides'], {
                        'example.mod': {'package': str(package), 'build_id': 'build'}})
                    with self.assertRaisesRegex(ValueError, 'Duplicate probe package'):
                        probe.probe(fixture, save, config, packages=[package, package])
                    record['inputs']['game'] = {'version': 'stale'}
                    run = probe.probe(fixture, save, config, packages=[package])
                    self.assertTrue(json.loads((run / 'result.json').read_text())['pass'])
                    record['inputs']['game'] = core.game_record()
                    (package / 'About/About.xml').write_text('<ModMetaData><packageId>inactive.mod</packageId></ModMetaData>')
                    with self.assertRaisesRegex(ValueError, 'not active'):
                        probe.probe(fixture, save, config, packages=[package])
            for path, content in before.items():
                self.assertEqual(path.read_bytes(), content, str(path))
