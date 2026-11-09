"""Compare development with RimSort copies and synchronize selected mods."""
import json
import subprocess
import xml.etree.ElementTree as ET
from . import core as c
from . import build as b
from .install import instance, package_id


def files(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob('*')
            if p.is_file() and p.relative_to(folder).as_posix() != 'build.json'}


def difference(expected, actual):
    return {'missing': sorted(expected.keys() - actual.keys()),
            'extra': sorted(actual.keys() - expected.keys()),
            'changed': sorted(k for k in expected.keys() & actual.keys() if expected[k] != actual[k])}


def copy_status(path, expected):
    result = {'path': str(path), 'linked': path.is_symlink(), 'build_id': None}
    actual = files(path)
    manifest = path / 'build.json'
    if manifest.is_file():
        try:
            record = b.validate(path)
            result['build_id'] = record['build_id']
        except (ValueError, OSError, KeyError, TypeError, ET.ParseError, subprocess.SubprocessError) as error:
            result.update(status='modified', detail=str(error))
            if expected is not None: result['difference'] = difference(expected, actual)
            return result
    if expected is None:
        result['status'] = 'uncompared' if manifest.is_file() else 'legacy'
    elif actual == expected:
        result['status'] = 'in-sync' if manifest.is_file() else 'in-sync (unrecorded)'
    else:
        result['status'] = 'older/different' if manifest.is_file() else 'different (legacy)'
        result['difference'] = difference(expected, actual)
    if path.is_symlink(): result['status'] = 'linked'
    return result


def project_status(project, folder, candidates):
    row = {'project': project['key'], 'package_id': project['package_id'],
           'build': 'missing', 'development': 'unbuilt', 'installation': 'missing',
           'package': None, 'copies': [], 'issues': [], 'in_sync': False}
    expected = None
    try:
        package = b.latest(project)
        if package is not None:
            row['package'] = str(package)
            record = b.validate(package)
            expected = files(package)
            row['build'] = 'valid'
            row['development'] = 'current' if record['inputs'] == b.inputs(project) else 'changed since build'
    except (ValueError, OSError, KeyError, TypeError, ET.ParseError, subprocess.SubprocessError) as error:
        row['build'] = 'invalid/error'
        row['development'] = 'unknown'
        row['issues'].append(str(error))
    destination = folder / project['key']
    if destination.is_symlink(): row['issues'].append(f'Canonical destination is a symlink: {destination}')
    elif destination.exists() and package_id(destination) != project['package_id'].lower():
        row['issues'].append(f'Canonical destination belongs to another mod or has invalid metadata: {destination}')
    for path in candidates.get(project['package_id'].lower(), []):
        try: row['copies'].append(copy_status(path, expected))
        except (OSError, ValueError, KeyError, TypeError) as error:
            row['copies'].append({'path': str(path), 'status': 'unreadable', 'detail': str(error)})
    if len(row['copies']) > 1: row['installation'] = 'duplicates'
    elif row['copies']: row['installation'] = row['copies'][0]['status']
    if row['issues']: row['installation'] += ' / blocked' if destination.exists() or destination.is_symlink() else ''
    row['in_sync'] = (row['build'] == 'valid' and row['development'] == 'current'
                      and row['installation'] in ('in-sync', 'in-sync (unrecorded)') and not row['issues'])
    return row


def status(project_key=None, instance_name=None, settings=None):
    name, folder = instance(instance_name, settings)
    selected = [c.project(project_key)] if project_key else [p for p in c.projects().values() if p.get('status', 'active') == 'active']
    candidates = {}
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            key = package_id(path)
            if key: candidates.setdefault(key, []).append(path)
    rows = [project_status(project, folder, candidates) for project in selected]
    return {'instance': name, 'local_folder': str(folder), 'mods': rows,
            'in_sync': all(row['in_sync'] for row in rows)}


def show(report, as_json=False):
    if as_json:
        print(json.dumps(report, indent=2))
        return
    print(f"RimSort instance: {report['instance']}\nLocal mods: {report['local_folder']}")
    columns = ('Project', 'Build', 'Development', 'Installation')
    rows = [(r['project'], r['build'], r['development'], r['installation']) for r in report['mods']]
    widths = [max(len(columns[i]), *(len(row[i]) for row in rows)) if rows else len(columns[i]) for i in range(4)]
    print('  '.join(value.ljust(width) for value, width in zip(columns, widths)))
    for row in rows: print('  '.join(value.ljust(width) for value, width in zip(row, widths)))
    for row in report['mods']:
        for issue in row['issues']: print(f"  {row['project']}: {issue}")
        for copy in row['copies']:
            diff = copy.get('difference', {})
            counts = ', '.join(f'{len(names)} {kind}' for kind, names in diff.items() if names)
            print(f"  {row['project']}: {copy['path']} [{copy['status']}]" + (f' — {counts}' if counts else ''))
    print('All installations match development.' if report['in_sync'] else 'Differences found. No files changed; no builds or game launches performed.')


def selection(answer, pending):
    """Resolve one answer completely before any build or installation starts."""
    answer = answer.strip().lower()
    if answer in ('', 'y', 'yes', 'all'): return pending
    if answer in ('n', 'no'): return []
    parts = [part.strip() for part in answer.split(',')]
    if not all(part.isascii() and part.isdecimal() for part in parts):
        raise ValueError('Enter all, no, or comma-separated mod numbers (e.g. 1,2,4).')
    numbers = {int(part) for part in parts}
    if not numbers or min(numbers) < 1 or max(numbers) > len(pending):
        raise ValueError(f'Mod numbers must be between 1 and {len(pending)}.')
    return [row for number, row in enumerate(pending, 1) if number in numbers]


def run(args):
    report = status(args.project, args.instance, args.settings)
    show(report, args.json)
    if args.no or args.json or args.check: return report
    pending = [row for row in report['mods'] if not row['in_sync']]
    if not pending: return report
    print('\nMods to build/update:')
    for number, row in enumerate(pending, 1): print(f"  {number}) {row['project']}")
    if args.all:
        selected = pending
    elif args.answer is not None:
        selected = selection(args.answer, pending)
    else:
        while True:
            try:
                answer = input('Build/update mods? [Enter=all, no, or numbers such as 1,2,4] ')
            except (EOFError, KeyboardInterrupt):
                print('\nCancelled. No mods updated.')
                return report
            try:
                selected = selection(answer, pending)
                break
            except ValueError as error:
                print(error)
    if not selected:
        print('No mods updated.')
        return report
    from pathlib import Path
    from .install import install, previous_copies
    from .lifecycle import session
    projects = [(row, c.project(row['project'])) for row in selected]
    # Check existing installation safeguards before spending time compiling.
    folder = Path(report['local_folder'])
    for row, project in projects:
        previous_copies(folder, folder / project['key'], project['package_id'])
    with session('sync', args.session):
        for row, project in projects:
            print(f"\nUpdating {project['key']}...")
            if row['build'] != 'valid' or row['development'] != 'current':
                b.build(project, force=row['build'] == 'invalid/error')
            install(project, instance_name=report['instance'], settings=args.settings)
    report = status(args.project, report['instance'], args.settings)
    print()
    show(report)
    return report
