import fnmatch
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
from . import core as c
from . import lifecycle


def compile_project(project, output, cache_key, capture=False):
    output = c.local(output)
    output.mkdir(parents=True, exist_ok=True)
    obj = c.ROOT / '.cache/obj' / cache_key if output.is_relative_to(c.ROOT / '.cache') else output / 'obj'
    # A generated fixture may sit beside copied mods containing older DLLs.
    # Resolve explicit references instead of scanning those trees for candidates.
    command = ['dotnet', 'build', project, '--configuration', 'Release', '--configfile',
               c.ROOT / 'tools/offline.nuget.config', '-p:NuGetAudit=false', '-p:UseSharedCompilation=false',
               '-p:AssemblySearchPath_UseCandidateAssemblyFiles=false',
               '-p:WorkspaceRoot=' + str(c.ROOT), '-p:RimWorldDir=' + str(c.GAME),
               '-p:HarmonyDir=' + str(c.WORKSHOP / '2009463077/1.7/Assemblies'),
               '-p:BaseIntermediateOutputPath=' + str(obj) + '/', '-o', output]
    result = subprocess.run([str(x) for x in command], cwd=c.ROOT, env=c.environment(),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (output / 'build.log').write_text(result.stdout)
    if not capture or result.returncode:
        print(result.stdout, end='', flush=True)
    if result.returncode: raise ValueError(f'Compilation failed; inspect {output / "build.log"}')
    return result


def content_files(project):
    root = project['root']
    result = {}
    for relative in project['content']:
        path = root / relative
        if not path.exists(): continue
        paths = path.rglob('*') if path.is_dir() else [path]
        for file in paths:
            if not file.is_file(): continue
            name = file.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(name, pattern) for pattern in project.get('exclude', [])): continue
            if any(part in ('.git', 'bin', 'obj', '__pycache__') for part in file.parts): continue
            result[name] = file
    return result


def bundled_assemblies(project):
    """Project-owned helper DLLs shipped beside the mod assembly, e.g. an API stub."""
    root = project['root']
    result = {}
    for relative in project.get('bundled_assemblies', []):
        path = root / relative
        if path.suffix != '.dll' or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f'Bundled assembly must be a DLL inside the project: {relative}')
        result[path.relative_to(root).as_posix()] = path
    return result


def inputs(project):
    root = project['root']
    files = dict(content_files(project))
    files.update(bundled_assemblies(project))
    for path in (root / 'Source').rglob('*'):
        if path.is_file() and path.suffix in ('.cs', '.csproj', '.props', '.targets') and not any(x in ('bin', 'obj') for x in path.parts):
            files[path.relative_to(root).as_posix()] = path
    files['mod.toml'] = root / 'mod.toml'
    references = {}
    index = c.workshop_index()
    for dependency in project.get('dependencies', []):
        path = index.get(dependency.lower())
        if path is None: raise ValueError(f'Missing Workshop dependency: {dependency}')
        # Refresh the build cache when installed references are updated.
        for dll in sorted(path.rglob('*.dll')):
            references[str(dll)] = c.file_stamp(dll)
    for name in ('Assembly-CSharp.dll', 'UnityStubs.dll', 'Waylith.dll', 'RimWorld.dll'):
        references[str(c.GAME / name)] = c.file_stamp(c.GAME / name)
    return {'files': {k: c.file_stamp(v) for k, v in sorted(files.items())},
            'shared_props': c.file_stamp(c.ROOT / 'tools/dotnet/RimWorld17.props'),
            'game': c.game_record(), 'dependencies': references,
            'git': c.git_record(root)}


def latest(project):
    path = c.ROOT / 'state/builds' / (project['key'] + '.json')
    if not path.is_file(): return None
    data = json.loads(path.read_text())
    package = c.local(c.ROOT / data['package'])
    if not package.is_dir(): return None
    return package


def validate(package):
    package = Path(package)
    record = json.loads((package / 'build.json').read_text())
    if (ET.parse(package / 'About/About.xml').findtext('packageId') or '').lower() != record['package_id'].lower():
        raise ValueError('Package ID differs from its build record.')
    return record


def build(project, force=False):
    if project.get('status', 'active') != 'active': raise ValueError('This project is retained as historical work, not an active build.')
    with c.lock('build-' + project['key']):
        current = inputs(project)
        prior = latest(project)
        if prior and not force:
            record = validate(prior)
            if record['inputs'] == current:
                print('Unchanged package:', prior)
                return prior
        ident = c.identifier()
        output = lifecycle.session_path() / 'build' / project['key'] / ident
        compile_project(project['root'] / project['project'], output, project['key'] + '/' + ident, capture=True)
        package = lifecycle.session_path() / 'staging' / project['key'] / ident
        package.mkdir(parents=True)
        for relative, path in content_files(project).items():
            destination = package / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        assemblies = package / '1.7/Assemblies'
        assemblies.mkdir(parents=True)
        for suffix in ('.dll', '.pdb'):
            file = output / (project['assembly'] + suffix)
            if file.exists(): shutil.copy2(file, assemblies / file.name)
        for path in bundled_assemblies(project).values():
            if (assemblies / path.name).exists(): raise ValueError(f'Bundled assembly name collides: {path.name}')
            shutil.copy2(path, assemblies / path.name)
        (package / 'LoadFolders.xml').write_text('<loadFolders><v1.7><li>/</li><li>1.7</li></v1.7></loadFolders>\n')
        record = {'schema': 2, 'key': project['key'], 'build_id': ident,
                  'package_id': project['package_id'], 'inputs': current,
                  'files': [p.relative_to(package).as_posix() for p in sorted(package.rglob('*')) if p.is_file()]}
        c.write_json(package / 'build.json', record)
        validate(package)
        final = c.ROOT / 'outputs/mods' / project['key'] / ident
        final.parent.mkdir(parents=True, exist_ok=True)
        package.rename(final)
        package = final
        c.write_json(c.ROOT / 'state/builds' / (project['key'] + '.json'), {'package': str(package.relative_to(c.ROOT))})
        print('Package:', package)
        return package
