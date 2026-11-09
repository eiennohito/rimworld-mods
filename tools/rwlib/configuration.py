"""Create local path configuration and read-only reference links."""
import json
from pathlib import Path

from . import core as c


DIRECTORIES = ('game', 'workshop', 'rimsort', 'rimsort_data', 'player_data')


def setup(overrides=None):
    overrides = {key: value for key, value in (overrides or {}).items() if value is not None}
    with c.lock('setup'):
        config = dict(c.CFG)
        for key, value in overrides.items():
            value = str(value)
            if not value.strip(): raise ValueError(f'{key} must be a nonempty path')
            if key != 'ilspy' or '/' in value:
                value = str((c.ROOT / Path(value).expanduser()).absolute())
            config[key] = value
        for key in DIRECTORIES:
            source = Path(config[key])
            if not source.is_dir() and (key in ('game', 'workshop') or key in overrides):
                raise ValueError(
                    f'Missing {key}: {source}. Configure paths with tools/rw setup '
                    '--game PATH --workshop PATH (see workspace.example.json).')
        version = (Path(config['game']) / 'Version.txt').read_text().strip()
        if not version.startswith('1.7.'):
            raise ValueError(f'Only RimWorld 1.7 is supported; found {version}')

        # Validate all destinations before saving config or creating any links.
        links = []
        for key in DIRECTORIES:
            source = Path(config[key])
            if not source.is_dir(): continue
            link = c.ROOT / 'references' / key
            if source.absolute() == link.absolute(): continue
            if link.is_symlink() and link.resolve() == source.resolve(): continue
            if link.exists() or link.is_symlink():
                raise ValueError(f'Reference path already exists: {link}; it has not been replaced.')
            links.append((link, source))
        path = c.local(c.ROOT / 'workspace.json')
        if overrides or not path.is_file():
            stored = json.loads(path.read_text()) if path.is_file() else {
                key: config[key] for key in ('game', 'workshop')}
            stored.update({key: config[key] for key in overrides})
            c.write_json(path, stored)
            print('Saved local configuration:', path)
        for link, source in links:
            link.parent.mkdir(exist_ok=True)
            link.symlink_to(source, target_is_directory=True)
        for name in ('projects', 'outputs/mods', 'sessions', 'state', 'investigations'):
            (c.ROOT / name).mkdir(parents=True, exist_ok=True)
        print('Workspace ready for', version)
