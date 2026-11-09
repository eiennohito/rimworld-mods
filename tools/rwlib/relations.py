#!/usr/bin/env python3
"""Inspect active mod dependencies and storage/hauling metadata without executing mods."""
import argparse
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from . import core as rw
from . import build as builder
from .lifecycle import session_path
ROOT = rw.ROOT


def version(text):
    try:
        return tuple(int(s) for s in text.removeprefix('v').split('.'))
    except ValueError:
        return ()


def folders(root, current, active):
    load_file = root / 'LoadFolders.xml'
    if load_file.exists():
        options = {e.tag.lower().removeprefix('v'): e for e in ET.parse(load_file).getroot()}
        selected = options.get(current)
        if selected is None:
            older = [v for v in options if version(v) and version(v) <= version(current)]
            selected = options[max(older)] if older else options.get('default')
        if selected is not None and len(selected):
            result = []
            for entry in selected:
                attrs = {k: {s.strip().lower() for s in v.split(',')} for k, v in entry.attrib.items()}
                if attrs.get('IfModActive') and not attrs['IfModActive'] & active:
                    continue
                if attrs.get('IfModActiveAll') and not attrs['IfModActiveAll'] <= active:
                    continue
                if attrs.get('IfModNotActive', set()) & active:
                    continue
                result.append(root / (entry.text or '').strip().strip('/\\'))
            return list(reversed(result))
    available = [p for p in root.iterdir() if p.is_dir() and version(p.name)]
    compatible = [p for p in available if version(p.name) <= version(current)]
    chosen = max(compatible, key=lambda p: version(p.name)) if compatible else (
        min(available, key=lambda p: version(p.name)) if available else None)
    return ([chosen] if chosen else []) + ([root / 'Common'] if (root / 'Common').is_dir() else []) + [root]


def inspect(argv):
    parser = argparse.ArgumentParser(prog="tools/rw inspect", description=__doc__)
    parser.add_argument('--config', default=str(ROOT / 'references/player_data/Config/ModsConfig.xml'))
    parser.add_argument('--runtime', type=Path, help='Optional ModDiagnostics patch-report.json')
    parser.add_argument('--output', default=str(session_path() / 'relations.json'))
    args = parser.parse_args(argv)
    output = rw.local(ROOT / args.output)
    config = ET.parse(ROOT / args.config).getroot()
    active_order = [e.text.lower().removesuffix('_steam') for e in config.findall('activeMods/li')]
    active = set(active_order)
    current = '.'.join((rw.GAME / 'Version.txt').read_text().split()[0].split('.')[:2])
    mods = {}
    candidates = []
    for base in [rw.WORKSHOP, rw.GAME / 'Mods', rw.GAME / 'Data']:
        if base.is_dir(): candidates.extend(sorted(base.iterdir()))
    candidates.extend(package for project in rw.projects().values() if (package := builder.latest(project)) is not None)
    for path in candidates:
        metadata = path / 'About/About.xml'
        if not metadata.is_file():
            continue
        xml = ET.parse(metadata).getroot()
        package = (xml.findtext('packageId') or '').lower()
        if package not in active:
            continue
        record = dict(packageId=package, name=xml.findtext('name'), root=str(path),
                      order=active_order.index(package),
                      dependencies=[e.text.lower() for e in xml.findall('modDependencies/li/packageId')],
                      loadAfter=[e.text.lower() for e in xml.findall('loadAfter/li')],
                      declaredIncompatible=[e.text.lower() for e in xml.findall('incompatibleWith/li')])
        # Prefer the live Workshop copy; staged copies are inputs only when no live mod matched.
        if package in mods:
            mods[package].setdefault('otherCopies', []).append(str(path))
            continue
        dlls = {}
        selected = folders(path, current, active)
        for folder in reversed(selected):
            for dll in sorted((folder / 'Assemblies').rglob('*.dll')):
                dlls[str(dll.relative_to(folder))] = str(dll)
        record.update(loadFolders=[str(p) for p in selected], assemblies=list(dlls.values()))
        mods[package] = record

    tool_output = ROOT / '.cache/tools/AssemblyRelations'
    with rw.lock('assembly-inspection-tool'):
        builder.compile_project(ROOT / 'tools/dotnet/inspect/AssemblyRelations.csproj', tool_output, 'tools/inspect', capture=True)
    paths = [path for mod in mods.values() for path in mod['assemblies']]
    scan = rw.run(['dotnet', tool_output / 'AssemblyRelations.dll', *paths],
                  capture_output=True, text=True)
    assembly_reports = json.loads(scan.stdout)
    by_path = {r['path']: r for r in assembly_reports}
    for mod in mods.values():
        mod['assemblyEvidence'] = [by_path[p] for p in mod['assemblies'] if p in by_path]
        mod['missingDependencies'] = [p for p in mod['dependencies'] if p not in active]
    runtime = json.loads((ROOT / args.runtime).read_text()) if args.runtime else None
    rw.write_json(output, dict(game=current, activeCount=len(active_order),
        note='Static metadata references and Harmony attribute mentions identify investigation candidates, not confirmed conflicts. Dynamic patch targets and actual execution require runtime evidence. Folder selection approximates the installed loader; duplicate package selection must be checked in runtime reports.',
        mods=sorted(mods.values(), key=lambda m: m['order']), runtime=runtime))
    print(f'{len(active_order)} active mods; {len(mods)} resolved mod packages; {len(paths)} assemblies scanned.')
    for mod in sorted(mods.values(), key=lambda m: m['order']):
        matches = sorted({member for a in mod['assemblyEvidence'] for member in a.get('memberReferences', [])
                          if any(s in member for s in ['NoStorageBlockersIn', 'HaulToStorageJob',
                                                       'GetItemStackSpaceLeftFor', 'HaulToCellStorageJob'])})
        attrs = [a for assembly in mod['assemblyEvidence'] for a in assembly.get('harmonyAttributeMentions', [])
                 if any(m in a['mentions'] for m in ['NoStorageBlockersIn', 'HaulToStorageJob', 'TryAbsorbStack'])]
        if matches or attrs:
            print(f"  {mod['order']:3} {mod['name']} ({mod['packageId']})")
            for match in matches:
                print('      references ' + match)
            for attr in attrs:
                print('      Harmony attribute: ' + attr['patchClass'] + ': ' + ', '.join(attr['mentions']))
    print(output)
    if runtime:
        print('Shared runtime targets (overlap alone does not establish a conflict):')
        for target in runtime['patches']:
            owners = sorted({p['owner'] for kind in ['prefixes', 'postfixes', 'transpilers', 'finalizers']
                             for p in target[kind]})
            if len(owners) > 1:
                print('  ' + target['targetType'] + '.' + target['targetMethod'] + ': ' + ', '.join(owners))
