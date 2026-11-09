"""Installation transactions shared by every project; activation is separate."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET
from . import core as c
from . import build as b


def package_id(path):
    try: return (ET.parse(Path(path) / 'About/About.xml').findtext('packageId') or '').lower()
    except (ET.ParseError, OSError): return None


def previous_copies(folder, destination, expected):
    folder, destination = Path(folder), Path(destination)
    if destination.is_symlink(): raise ValueError(f'Refusing to replace a linked mod: {destination}')
    if destination.exists() and package_id(destination) != expected.lower():
        raise ValueError(f'Destination belongs to another mod: {destination}')
    copies = []
    if folder.exists():
        for path in folder.iterdir():
            if package_id(path) == expected.lower():
                if path.is_symlink(): raise ValueError(f'Refusing to replace a linked mod: {path}')
                copies.append(path)
    return sorted(copies)


def transaction(source, destination, previous, backup_root, on_commit=None):
    """Copy verified content, retain backups, and roll back any failed replacement."""
    source, destination, backup_root = map(Path, (source, destination, backup_root))
    destination.parent.mkdir(parents=True, exist_ok=True)
    if previous:
        backup_root.mkdir(parents=True, exist_ok=False)
        for path in previous: shutil.copytree(path, backup_root / path.name, symlinks=True)
    with tempfile.TemporaryDirectory(prefix='.rw-install-', dir=destination.parent) as temporary:
        temporary = Path(temporary)
        incoming = temporary / 'incoming'
        shutil.copytree(source, incoming)
        moved = []
        installed = False
        try:
            for index, path in enumerate(previous):
                retired = temporary / f'previous-{index}'
                path.rename(retired)
                moved.append((path, retired))
            incoming.rename(destination)
            installed = True
            if on_commit: on_commit()
        except Exception:
            if installed: destination.rename(incoming)
            for original, retired in reversed(moved): retired.rename(original)
            raise
    return backup_root if previous else None


def instance(name=None, settings_file=None):
    path = c.ROOT / settings_file if settings_file else Path(c.CFG['rimsort_data']) / 'settings.json'
    settings = json.loads(path.read_text())
    name = name or settings['current_instance']
    if name not in settings['instances']: raise ValueError(f'Unknown RimSort instance: {name}')
    if Path(name).name != name or name in ('.', '..'): raise ValueError('Instance name is not a safe directory name.')
    folder = Path(settings['instances'][name]['local_folder']).expanduser()
    if not folder.is_absolute(): raise ValueError('RimSort local_folder must be absolute.')
    if folder.resolve().is_relative_to(c.WORKSHOP.resolve()): raise ValueError('Refusing to install into Workshop downloads.')
    return name, folder


def install(project, dry_run=False, instance_name=None, settings=None):
    source = b.latest(project)
    if source is None: raise ValueError('No built package. Run tools/rw build ' + project['key'])
    record = b.validate(source)
    name, folder = instance(instance_name, settings)
    destination = folder / project['key']
    with c.lock('install-' + hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:20]):
        previous = previous_copies(folder, destination, project['package_id'])
        print(f'Instance: {name}\nSource: {source}\nDestination: {destination}')
        for path in previous: print('Back up and replace:', path)
        if dry_run:
            print('Dry run only. Omit --dry-run to install. The active mod list is never changed.')
            return
        receipt = c.ROOT / 'state/installs' / name / project['key'] / c.identifier()
        receipt.mkdir(parents=True)
        data = {'schema': 1, 'instance': name, 'package_id': project['package_id'],
                'source': str(source), 'destination': str(destination), 'build_id': record['build_id'],
                'previous': [p.name for p in previous], 'applied': False}
        c.write_json(receipt / 'receipt.json', data)
        def commit_receipt():
            data['applied'] = True
            c.write_json(receipt / 'receipt.json', data)
        transaction(source, destination, previous, receipt / 'backups', commit_receipt)
        print('Installed. Refresh RimSort. Receipt:', receipt)


def rollback(project, apply=False, instance_name=None):
    name, folder = instance(instance_name)
    receipts = sorted((c.ROOT / 'state/installs' / name / project['key']).glob('*/receipt.json'), reverse=True)
    found = [(p, json.loads(p.read_text())) for p in receipts]
    found = [(p, data) for p, data in found if data.get('applied') and not data.get('rolled_back')]
    if not found: raise ValueError('No applied installation to roll back.')
    path, data = found[0]
    destination = folder / project['key']
    with c.lock('install-' + hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:20]):
        if Path(data['destination']) != destination: raise ValueError('RimSort destination changed since installation.')
        current = b.validate(destination)
        if current['build_id'] != data['build_id']: raise ValueError('A different build is installed; refusing to overwrite it.')
        for original in data['previous']:
            if (folder / original).exists() and folder / original != destination:
                raise ValueError(f'Previous location is occupied: {folder / original}')
        print('Restore installation receipt:', path)
        if not apply:
            print('Preview only. Add --apply to restore backups.')
            return
        with tempfile.TemporaryDirectory(prefix='.rw-rollback-', dir=folder) as temp:
            retired = Path(temp) / 'current'
            destination.rename(retired)
            restored = []
            try:
                for original in data['previous']:
                    target = folder / original
                    restored.append(target)
                    shutil.copytree(path.parent / 'backups' / original, target, symlinks=True)
                data['rolled_back'] = True
                c.write_json(path, data)
            except Exception:
                for target in restored:
                    if target.exists(): shutil.rmtree(target)
                retired.rename(destination)
                raise
        print('Restored previous local files; active mod list unchanged.')
