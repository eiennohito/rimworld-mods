"""Save investigations use the same isolated host and fixture lifecycle as tests."""
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from . import core as c
from . import lifecycle
from .runner import preferences, harness
from .host import make_game
from .install import package_id
from . import build as b
from . import snapshot


def probe(fixture, save, config, timeout=240, packages=()):
    fixture = c.local(c.ROOT / fixture)
    save, config = c.ROOT / save, c.ROOT / config
    if not fixture.is_file() or fixture.suffix != '.csproj':
        raise ValueError('Probe fixture must be an existing workspace .csproj file.')
    active = [e.text.lower().removesuffix('_steam') for e in ET.parse(config).findall('activeMods/li')]
    sources = {}
    for base in (c.GAME / 'Mods', c.WORKSHOP, c.GAME / 'Data'):
        if base.is_dir():
            for path in sorted(base.iterdir()):
                key = package_id(path)
                if key in active and key not in sources:
                    sources[key] = path
    missing = set(active) - sources.keys()
    if missing:
        raise ValueError('Unresolved active mods: ' + ', '.join(sorted(missing)))
    overrides = {}
    for package in packages:
        path = c.local(c.ROOT / package)
        record = b.validate(path)
        key = package_id(path)
        if key not in active:
            raise ValueError('Probe package is not active: ' + key)
        if key in overrides:
            raise ValueError('Duplicate probe package override: ' + key)
        sources[key] = path
        overrides[key] = {'package': str(path), 'build_id': record['build_id']}
    run = lifecycle.session_path() / 'runs' / c.identifier('probe-')
    run.mkdir(parents=True)
    result = {'run': str(run), 'pass': False}
    try:
        data = run / 'data'
        preferences(data)
        (data / 'Saves').mkdir()
        snapshot.copy_file(save, data / 'Saves/Probe.rws')
        # Copy settings so mod behavior matches the player's configuration.
        for path in config.parent.glob('*.xml'):
            if path.name not in ('Prefs.xml', 'ModsConfig.xml', 'Profiler.xml'):
                shutil.copy2(path, data / 'Config' / path.name)
        game = make_game(run)
        snapshots = {}
        for i, key in enumerate(active):
            source = sources[key]
            if source.parent == c.GAME / 'Data':
                continue
            destination = game / 'Mods' / f'probe-{i}'
            snapshot.copy_tree(source, destination, ignore=shutil.ignore_patterns('.git', 'bin', 'obj'))
            snapshots[key] = {'source': str(source)}
        project = {'root': fixture.parent, 'package_id': 'ludeon.rimworld', 'tests': {
            'probe': {'project': fixture.name, 'assembly': 'SaveProbe', 'package_id': 'local.saveprobe'}}}
        helper = harness(project, 'probe', run)
        mods_config = ET.parse(config)
        for entry, key in zip(mods_config.getroot().findall('activeMods/li'), active):
            entry.text = key
        ET.SubElement(mods_config.getroot().find('activeMods'), 'li').text = helper
        mods_config.write(data / 'Config/ModsConfig.xml', encoding='utf-8', xml_declaration=True)
        command = [str(game / 'RimWorld'), '-savedatafolder=' + str(data),
                   '-Headless', '-WorkspaceDiagnosticsExit', '-NoCrashDialog']
        result['command'] = command
        c.write_json(run / 'inputs.json', {'save': str(save), 'config': str(config),
            'game': c.game_record(), 'packages': snapshots,
            'package_overrides': overrides,
            'fixture': str(fixture)})
        print('Running isolated save probe:', run, flush=True)
        with (run / 'run.log').open('w') as log:
            process = subprocess.Popen(command, cwd=run, env=c.environment(run), stdout=log, stderr=subprocess.STDOUT)
            lifecycle.register_process(process.pid)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
                raise ValueError('Save probe timed out; no successful verification.')
        result['host_exit'] = process.returncode
        if process.returncode != 0:
            raise ValueError(f'Save probe exited with {process.returncode}')
        report = json.loads((data / 'report.json').read_text())
        c.write_json(run / 'report.json', report)
        if any(value is not False for value in report['steam'].values()):
            raise ValueError('Steam isolation failed.')
        quiet = json.loads((run / 'quiet-audio.json').read_text())
        if not quiet.get('noAudio'):
            raise ValueError('No-device audio isolation failed.')
        if report['audio']['masterVolume'] != 0:
            raise ValueError('Audio mute verification failed.')
        loaded = {m['packageId'].lower() for m in report['mods']}
        if set(active + [helper]) - loaded:
            raise ValueError('Some requested mods did not load.')
        if not report['tests'] or any(t.get('error') or t.get('pass') is False for t in report['tests']):
            raise ValueError('Save probe fixture failed; inspect report.json.')
        result['pass'] = True
        print('Save probe finished normally:', run, flush=True)
        return run
    finally:
        c.write_json(run / 'result.json', result)
