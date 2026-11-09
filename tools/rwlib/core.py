from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tomllib
import uuid

ROOT = Path(__file__).resolve().parents[2]


def load_config(root):
    """Local paths are optional until a command needs the corresponding input."""
    root = Path(root)
    config = {key: str(root / 'references' / key) for key in
              ('game', 'workshop', 'rimsort', 'rimsort_data', 'player_data')}
    config['ilspy'] = 'ilspycmd'
    path = root / 'workspace.json'
    if path.is_file():
        overrides = json.loads(path.read_text())
        for key, value in overrides.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'{path}: {key} must be a nonempty path string')
            config[key] = value if key == 'ilspy' else str((root / Path(value).expanduser()).absolute())
    return config


CFG = load_config(ROOT)
GAME = Path(CFG['game'])
WORKSHOP = Path(CFG['workshop'])


def local(path):
    path = Path(path).absolute()
    if not path.resolve().is_relative_to(ROOT):
        raise ValueError(f'Output must stay inside workspace: {path}')
    return path


def identifier(prefix=''):
    return prefix + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]


def file_stamp(path):
    """Cheap cache invalidation for local builds; not a reproducibility record."""
    stat = Path(path).stat()
    return [stat.st_size, stat.st_mtime_ns]


def write_json(path, data):
    path = local(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def environment(run_dir=None):
    env = os.environ.copy()
    for key, relative in {'DOTNET_CLI_HOME': 'dotnet', 'NUGET_PACKAGES': 'nuget',
                          'TMPDIR': 'tmp', 'UV_CACHE_DIR': 'uv'}.items():
        path = ROOT / '.cache' / relative
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    xdg = Path(run_dir) / 'xdg' if run_dir else ROOT / '.cache/xdg'
    for kind in ('config', 'cache', 'data', 'runtime'):
        path = xdg / kind
        path.mkdir(parents=True, exist_ok=True)
        env['XDG_' + kind.upper() + ('_HOME' if kind != 'runtime' else '_DIR')] = str(path)
        if kind == 'runtime': path.chmod(0o700)
    env.update(DOTNET_NOLOGO='1', DOTNET_CLI_TELEMETRY_OPTOUT='1',
               DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1', DOTNET_ROLL_FORWARD='Major')
    return env


def run(command, **kwargs):
    return subprocess.run([str(x) for x in command], cwd=ROOT, env=environment(), check=True, **kwargs)


@contextmanager
def lock(name, shared=False):
    folder = ROOT / 'state/locks'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / (name + '.lock')).open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        yield


def projects():
    result = {}
    for file in sorted((ROOT / 'projects').glob('*/mod.toml')):
        data = tomllib.loads(file.read_text())
        data['root'] = file.parent
        key = data['key']
        if key != file.parent.name or key in result: raise ValueError(f'Invalid project key: {file}')
        result[key] = data
    return result


def project(key, worktree=None):
    if worktree is not None:
        root = local(ROOT / worktree)
        data = tomllib.loads((root / 'mod.toml').read_text())
        if data['key'] != key or not (root / '.git').exists(): raise ValueError('Worktree key or Git checkout does not match.')
        data['root'] = root
        return data
    try: return projects()[key]
    except KeyError: raise ValueError(f'Unknown project: {key}') from None


def game_record():
    version = (GAME / 'Version.txt').read_text().strip()
    if not version.startswith('1.7.'): raise ValueError(f'Only RimWorld 1.7 is supported; found {version}')
    return {'version': version}


def workshop_index():
    import xml.etree.ElementTree as ET
    result = {}
    for path in sorted(WORKSHOP.iterdir()):
        about = path / 'About/About.xml'
        if not about.is_file(): continue
        try:
            xml = ET.parse(about).getroot()
            result[(xml.findtext('packageId') or '').lower()] = path
        except ET.ParseError: continue
    return result


def git_record(folder):
    def git(*args):
        return subprocess.check_output(['git', '--no-optional-locks', '-C', str(folder), *args], text=True).strip()
    return {'commit': git('rev-parse', 'HEAD'), 'dirty': bool(git('status', '--porcelain'))}
