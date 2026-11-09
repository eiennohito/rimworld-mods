from contextlib import contextmanager
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from . import core as c
from . import build as b
from .host import make_game
from . import lifecycle
from . import snapshot


def preferences(data):
    (data / 'Config').mkdir(parents=True)
    (data / 'Config/Prefs.xml').write_text('''<PrefsData>
<screenWidth>1280</screenWidth><screenHeight>800</screenHeight><fullscreen>False</fullscreen>
<runInBackground>True</runInBackground><uiScale>1</uiScale>
<volumeMaster>0</volumeMaster><volumeGame>0</volumeGame><volumeMusic>0</volumeMusic>
<volumeAmbient>0</volumeAmbient><volumeUI>0</volumeUI>
</PrefsData>''')


@contextmanager
def private_display(env, run_dir, log, enabled):
    if not enabled:
        yield
        return
    xvfb = c.ROOT / '.cache/virtual-display/usr/bin/Xvfb'
    software = c.ROOT / '.cache/software-vulkan/usr/lib/libvulkan_lvp.so'
    if not xvfb.is_file() or not software.is_file():
        raise ValueError('Private Xvfb and software Vulkan caches are required. See docs/running-rimworld.md.')
    driver = json.loads((software.parents[1] / 'share/vulkan/icd.d/lvp_icd.json').read_text())
    driver['ICD']['library_path'] = str(software)
    icd = run_dir / 'vulkan-icd.json'
    c.write_json(icd, driver)
    read_fd, write_fd = os.pipe()
    server = subprocess.Popen([str(xvfb), '-displayfd', str(write_fd), '-screen', '0', '1280x800x24',
                               '-nolisten', 'tcp', '-ac', '-extension', 'GLX'],
                              pass_fds=(write_fd,), env=env, stdout=log, stderr=subprocess.STDOUT)
    lifecycle.register_process(server.pid)
    os.close(write_fd)
    try:
        if not select.select([read_fd], [], [], 8)[0]: raise ValueError('Private Xvfb display did not become ready.')
        number = os.read(read_fd, 32).decode().strip()
        if not number.isdecimal(): raise ValueError('Private Xvfb failed to start; inspect run.log.')
        env.update(DISPLAY=':' + number, XDG_SESSION_TYPE='x11', SDL_VIDEODRIVER='x11',
                   VK_DRIVER_FILES=str(icd), VK_ICD_FILENAMES=str(icd))
        for key in ('WAYLAND_DISPLAY', 'WAYLAND_SOCKET', 'XDG_ACTIVATION_TOKEN', 'DESKTOP_STARTUP_ID'):
            env.pop(key, None)
        yield
    finally:
        os.close(read_fd)
        if server.poll() is None:
            server.terminate()
            try: server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill(); server.wait()


def dependencies(project, additional):
    index = c.workshop_index()
    # The isolated host already includes official game content. Required DLC
    # must be present, but is not a Workshop download to stage under Mods.
    official = {ET.parse(path).getroot().findtext('packageId', '').lower()
                for path in (c.GAME / 'Data').glob('*/About/About.xml')}
    own = project['package_id'].lower()
    pending = list(project.get('dependencies', [])) + list(additional)
    result = {}
    while pending:
        key = pending.pop(0).lower()
        if key == own or key in result or key in official: continue
        if key in index:
            root = index[key]
        else:
            local = next((p for p in c.projects().values() if p['package_id'].lower() == key), None)
            if local is None: raise ValueError(f'Missing Workshop dependency: {key}')
            root = b.build(local)
            b.validate(root)
        result[key] = root
        xml = ET.parse(root / 'About/About.xml').getroot()
        pending.extend(e.text for e in xml.findall('modDependencies/li/packageId') if e.text)
    return result


def harness(project, suite, run_dir):
    spec = project['tests'][suite]
    output = run_dir / 'harness-build'
    if 'project' in spec:
        csproj = project['root'] / spec['project']
        assembly = spec['assembly']
        package_id = spec['package_id']
    else:
        assembly = 'WorkspaceChecks'
        package_id = 'local.workspacechecks'
        csproj = run_dir / 'WorkspaceChecks.csproj'
        shared = escape(str(c.ROOT / 'tools/dotnet/RimWorld17.props'), {'"': '&quot;'})
        common = escape(str(c.ROOT / 'tools/dotnet/testing/Diagnostics.cs'), {'"': '&quot;'})
        fixtures = escape(str(project['root'] / 'tests/runtime/**/*.cs'), {'"': '&quot;'})
        csproj.write_text(f'''<Project Sdk="Microsoft.NET.Sdk">
<Import Project="{shared}" />
<PropertyGroup><EnableDefaultCompileItems>false</EnableDefaultCompileItems><AssemblyName>{assembly}</AssemblyName></PropertyGroup>
<ItemGroup><Compile Include="{common}" /><Compile Include="{fixtures}" /></ItemGroup></Project>''')
    b.compile_project(csproj, output, 'tests/' + run_dir.name)
    root = run_dir / 'game/Mods/WorkspaceChecks'
    (root / 'About').mkdir(parents=True)
    (root / 'Assemblies').mkdir()
    (root / 'About/About.xml').write_text(f'''<ModMetaData><name>Workspace test harness</name>
<author>Local development</author><packageId>{package_id}</packageId>
<supportedVersions><li>1.7</li></supportedVersions><loadAfter><li>{project['package_id']}</li><li>brrainz.harmony</li></loadAfter>
</ModMetaData>''')
    shutil.copy2(output / (assembly + '.dll'), root / 'Assemblies')
    return package_id


def test(project, suite, additional=(), timeout=240):
    if suite not in project.get('tests', {}): raise ValueError(f'No {suite} suite declared for {project["key"]}')
    package = b.build(project)
    record = b.validate(package)
    spec = project['tests'][suite]
    run_dir = lifecycle.session_path() / 'runs' / c.identifier(project['key'] + '-' + suite + '-')
    run_dir.mkdir(parents=True)
    result = {'run': str(run_dir), 'project': project['key'], 'suite': suite, 'pass': False}
    try:
        data = run_dir / 'data'
        preferences(data)
        game = make_game(run_dir)
        dep_paths = dependencies(project, additional)
        package_ids = []
        snapshot = {project['package_id']: {'package': str(package), 'build_id': record['build_id']}}
        snapshot.copy_tree(package, game / 'Mods' / project['key'])
        for package_id, path in dep_paths.items():
            destination = game / 'Mods' / path.name
            snapshot.copy_tree(path, destination, ignore=shutil.ignore_patterns('.git', 'bin', 'obj'))
            package_ids.append(package_id)
            snapshot[package_id] = {'source': str(path)}
        helper = harness(project, suite, run_dir)
        package_ids += [project['package_id'], helper]
        c.write_json(run_dir / 'inputs.json', {'project': project['key'], 'suite': suite,
                     'packages': snapshot, 'game': c.game_record()})
        ui = spec.get('ui', False)
        command = [str(game / 'RimWorld'), '-savedatafolder=' + str(data), '-mod=' + ','.join(package_ids),
                   *([] if ui else ['-Headless']), '-WorkspaceDiagnosticsExit', '-NoCrashDialog', *spec.get('args', [])]
        result['command'] = command
        env = c.environment(run_dir)
        report_path = data / spec.get('report', 'report.json')
        with (run_dir / 'run.log').open('w') as log, private_display(env, run_dir, log, ui):
            process = subprocess.Popen(command, cwd=run_dir, env=env, stdout=log, stderr=subprocess.STDOUT)
            lifecycle.register_process(process.pid)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
                raise ValueError(f'Test timed out after {timeout}s; no successful exit.')
        result['host_exit'] = process.returncode
        if process.returncode != 0: raise ValueError(f'Test host exited with {process.returncode}')
        if not report_path.is_file(): raise ValueError('Host exited without a completion report.')
        report = json.loads(report_path.read_text())
        c.write_json(run_dir / 'report.json', report)
        steam = report.get('steam', {k: report.get(k) for k in ('steamActive', 'steamInitialized', 'steamNativeLibraryMapped')})
        if any(value is not False for value in steam.values()): raise ValueError('Steam-disabled status was not verified.')
        quiet = json.loads((run_dir / 'quiet-audio.json').read_text())
        if quiet.get('noAudio') is not True:
            raise ValueError('No-device audio host was not verified.')
        master = report.get('audio', {}).get('masterVolume', report.get('audioMasterVolume'))
        if master != 0: raise ValueError('Muted audio preferences were not verified.')
        loaded = {m['packageId'].lower() for m in report.get('mods', [])}
        if 'mods' in report and set(map(str.lower, package_ids)) - loaded: raise ValueError('Requested mods did not all load.')
        checks = report.get('tests', [])
        if any('error' in t or t.get('pass') is False for t in checks): raise ValueError('One or more runtime checks failed.')
        shots = data / 'Screenshots'
        if 'files' in report: shots = report_path.parent
        if shots.is_dir():
            (run_dir / 'screenshots').mkdir()
            for image in shots.glob('*.png'): shutil.copy2(image, run_dir / 'screenshots' / image.name)
        if 'files' in report and any(not (run_dir / 'screenshots' / name).is_file() for name in report['files']):
            raise ValueError('The capture report names missing screenshots.')
        result.update({'pass': True, 'checks_passed': sum(t.get('pass') is True for t in checks), 'steam': steam, 'audio_no_device': True})
    except Exception as error:
        result['error'] = str(error)
        raise
    finally:
        c.write_json(run_dir / 'result.json', result)
        print('Run evidence:', run_dir, flush=True)
    print(f'{result["checks_passed"]} checks passed; normal exit; Steam disabled; sound muted.')
    return run_dir
