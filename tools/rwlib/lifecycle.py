"""Leased command sessions. Outputs and installation state are never collected."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
from . import core as c

RETENTION = timedelta(days=7)
ACTIVE = None


def now(): return datetime.now(timezone.utc)
def stamp(value): return value.isoformat()


def process_record(pid):
    try:
        # Start time disambiguates a reused PID. Linux is the workspace platform.
        rest = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return {'pid': pid, 'start': None if rest[0] in ('Z', 'X') else rest[19]}
    except (OSError, IndexError): return {'pid': pid, 'start': None}


def alive(process):
    current = process_record(process['pid'])
    return current['start'] is not None and current == process


def session_path():
    if ACTIVE is None: raise ValueError('Scratch work requires an active workspace session.')
    return ACTIVE


def register_process(pid):
    if ACTIVE is None: return
    path = ACTIVE / 'session.json'
    data = json.loads(path.read_text())
    data['processes'].append(process_record(pid))
    c.write_json(path, data)


@contextmanager
def session(command, ident=None):
    global ACTIVE
    ident = ident or c.identifier(command + '-')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', ident) or ident in ('.', '..'): raise ValueError('Invalid session ID.')
    root = c.ROOT / 'sessions' / ident
    with c.lock('session-' + ident):
        root.mkdir(parents=True, exist_ok=True)
        path = root / 'session.json'
        data = json.loads(path.read_text()) if path.exists() else {'created': stamp(now()), 'pinned': False}
        if any(alive(p) for p in data.get('processes', [])): raise ValueError('This session is still in use.')
        data.update(command=command, status='active', updated=stamp(now()), expires=None, processes=[process_record(os.getpid())])
        c.write_json(path, data)
        previous = ACTIVE
        ACTIVE = root
        try:
            yield root
        finally:
            data = json.loads(path.read_text())
            data['processes'] = [p for p in data['processes'] if p['pid'] != os.getpid() and alive(p)]
            data.update(status='finished', updated=stamp(now()), expires=stamp(now() + RETENTION))
            c.write_json(path, data)
            ACTIVE = previous


def collect(apply=False, all_sessions=False):
    eligible = []
    for path in sorted((c.ROOT / 'sessions').glob('*/session.json')):
        data = json.loads(path.read_text())
        if data.get('pinned') or any(alive(p) for p in data.get('processes', [])): continue
        expires = data.get('expires')
        if expires is None and not all_sessions:
            # Start retention when an abandoned lease is first detected, rather
            # than deleting a long-running crashed session immediately.
            if apply:
                data.update(status='abandoned', updated=stamp(now()), expires=stamp(now() + RETENTION))
                c.write_json(path, data)
            continue
        if not all_sessions and datetime.fromisoformat(expires) > now(): continue
        if apply:
            # No process may start/reuse this named session during collection.
            with c.lock('session-' + path.parent.name):
                latest = json.loads(path.read_text())
                if latest.get('pinned') or any(alive(p) for p in latest.get('processes', [])): continue
                if not all_sessions and (not latest.get('expires') or datetime.fromisoformat(latest['expires']) > now()): continue
                shutil.rmtree(path.parent)
        eligible.append(path.parent)
    return eligible


def pin(ident, value=True):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', ident) or ident in ('.', '..'): raise ValueError('Invalid session ID.')
    with c.lock('session-' + ident):
        path = c.ROOT / 'sessions' / ident / 'session.json'
        data = json.loads(path.read_text())
        data['pinned'] = value
        c.write_json(path, data)
    print(('Pinned: ' if value else 'Unpinned: ') + ident)


def clean_cache(apply=False):
    # Keep downloaded SDK/NuGet/renderer packages unless the user removes them
    # explicitly. This operation clears rebuildable outputs, never source.
    names = ('obj', 'tools', 'hosts', 'tmp', 'xdg', 'legacy-project-output', 'inventory')
    for name in names:
        path = c.ROOT / '.cache' / name
        if not path.exists(): continue
        print(('Remove cache: ' if apply else 'Cache candidate: ') + str(path))
        if apply: shutil.rmtree(path)


def promote(ident, name):
    for value in (ident, name):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value) or value in ('.', '..'): raise ValueError('Invalid session/report name.')
    with c.lock('session-' + ident):
        source = c.ROOT / 'sessions' / ident
        data = json.loads((source / 'session.json').read_text())
        if any(alive(p) for p in data.get('processes', [])): raise ValueError('Finish the session before saving its reports.')
        destination = c.ROOT / 'outputs/reports' / name
        if destination.exists(): raise ValueError('Report name already exists; use another name.')
        destination.mkdir(parents=True)
        for run in (source / 'runs').iterdir() if (source / 'runs').is_dir() else []:
            target = destination / run.name
            target.mkdir()
            for file in ('inputs.json', 'result.json', 'report.json', 'run.log', 'steamless-host.json', 'quiet-audio.json'):
                if (run / file).is_file(): shutil.copy2(run / file, target / file)
            if (run / 'screenshots').is_dir(): shutil.copytree(run / 'screenshots', target / 'screenshots')
        c.write_json(destination / 'origin.json', {'session': ident, 'saved': stamp(now())})
        print('Saved persistent report:', destination)
