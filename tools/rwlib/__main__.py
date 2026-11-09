import argparse
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from . import core as c
from . import build as b


def setup():
    for key in ('game', 'workshop'):
        source = Path(c.CFG[key])
        if not source.is_dir():
            raise ValueError(f'Missing {key}: {source}. Copy workspace.example.json to workspace.json and configure your paths.')
    c.game_record()
    for key in ('game', 'workshop', 'rimsort', 'rimsort_data', 'player_data'):
        source = Path(c.CFG[key])
        if not source.is_dir(): continue
        link = c.ROOT / 'references' / key
        if source.absolute() == link.absolute(): continue
        if link.is_symlink() and link.resolve() == source.resolve(): continue
        if link.exists() or link.is_symlink(): raise ValueError(f'Reference path already exists: {link}')
        link.parent.mkdir(exist_ok=True)
        link.symlink_to(source, target_is_directory=True)
    for name in ('outputs/mods', 'sessions', 'state', 'investigations'):
        (c.ROOT / name).mkdir(parents=True, exist_ok=True)
    print('Workspace ready for', c.game_record()['version'])


def inventory():
    mods = []
    for key, path in c.workshop_index().items():
        xml = ET.parse(path / 'About/About.xml').getroot()
        mods.append({'workshop_id': path.name, 'package_id': key, 'name': xml.findtext('name'),
                     'url': xml.findtext('url'), 'dependencies': [e.text for e in xml.findall('modDependencies/li/packageId')],
                     'assemblies': [str(p.relative_to(path)) for p in path.rglob('*.dll')]})
    c.write_json(c.ROOT / '.cache/inventory/workshop.json', mods)
    c.write_json(c.ROOT / '.cache/inventory/game.json', c.game_record())
    print(f'{len(mods)} Workshop mods indexed; game version recorded.')


def execute():
    parser = argparse.ArgumentParser(description='RimWorld 1.7 workspace: independent projects, shared infrastructure.')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('setup', 'inventory', 'list', 'check'): commands.add_parser(name)
    parser.add_argument('--session', help='Reuse a named session (seven-day retention after last command)')
    p = commands.add_parser('clean'); p.add_argument('kind', choices=['sessions', 'cache'], default='sessions', nargs='?'); p.add_argument('--dry-run', action='store_true', help='Preview cleanup without deleting files')
    p.add_argument('--all', action='store_true', help='Collect inactive, unpinned sessions before their expiry too')
    p = commands.add_parser('save-report'); p.add_argument('session_id'); p.add_argument('--name', required=True)
    p = commands.add_parser('latest'); p.add_argument('project')
    p = commands.add_parser('pin'); p.add_argument('session_id'); p.add_argument('--remove', action='store_true')
    p = commands.add_parser('build'); p.add_argument('project'); p.add_argument('--worktree', type=Path); p.add_argument('--force', action='store_true')
    p = commands.add_parser('steam-probe', help='Check desktop Steam authentication without uploading')
    p.add_argument('--item', help='Also make a read-only Workshop dependency query for this item ID')
    p.add_argument('--timeout', type=float, default=30)
    p = commands.add_parser('publish', help='Update an existing Workshop item')
    p.add_argument('project'); p.add_argument('--worktree', type=Path)
    p.add_argument('--dry-run', action='store_true', help='Prepare and review the upload without contacting Steam')
    p.add_argument('--account', help='SteamCMD backend only: owning Steam account; first login may require Steam Guard')
    p.add_argument('--notes', type=Path, help='Change-note file; defaults to this version in CHANGELOG.md')
    p.add_argument('--steamcmd', help='SteamCMD backend only: executable; defaults to steamcmd or steamcmd.sh on PATH')
    p.add_argument('--backend', choices=['desktop', 'steamcmd'], default='desktop', help='default: desktop, using the running Steam session; steamcmd requires explicit selection')
    p.add_argument('--timeout', type=float, default=600, help='Desktop upload timeout in seconds (default: 600)')
    p = commands.add_parser('test'); p.add_argument('project'); p.add_argument('--worktree', type=Path); p.add_argument('--suite', default='runtime'); p.add_argument('--with', dest='additional', action='append', default=[]); p.add_argument('--timeout', type=int, default=240)
    p = commands.add_parser('probe', help='Run an investigation fixture against a copied save and active mod set')
    p.add_argument('fixture', type=Path); p.add_argument('--save', type=Path, required=True)
    p.add_argument('--config', type=Path, default=Path(c.CFG['player_data']) / 'Config/ModsConfig.xml')
    p.add_argument('--package', type=Path, action='append', default=[], help='Use a built package for an already active mod in the isolated host')
    p.add_argument('--timeout', type=int, default=240)
    p = commands.add_parser('trace', help='Sample a running process through its .NET diagnostics socket')
    p.add_argument('--pid', type=int, required=True); p.add_argument('--seconds', type=int, default=30)
    p.add_argument('--native', action='store_true', help='Use Linux perf to include native runtime stacks')
    p.add_argument('--dump', action='store_true', help='Collect a small runtime snapshot instead of a sampling trace')
    p = commands.add_parser('trace-report', help='Decode runtime GC and contention events from a trace')
    p.add_argument('input', type=Path)
    p = commands.add_parser('code', help='Read a bounded executable-code range from RimWorld for disassembly')
    p.add_argument('--pid', type=int, required=True); p.add_argument('--start', type=lambda s: int(s, 0), required=True)
    p.add_argument('--size', type=int, default=8192)
    p = commands.add_parser('live-state', help='Read shared component-list state from running RimWorld')
    p.add_argument('--pid', type=int, required=True)
    for name in ('install', 'rollback'):
        p = commands.add_parser(name); p.add_argument('project'); p.add_argument('--worktree', type=Path); p.add_argument('--instance')
        if name == 'install':
            p.add_argument('--dry-run', action='store_true'); p.add_argument('--settings', type=Path)
        else: p.add_argument('--apply', action='store_true')
    p = commands.add_parser('sync', help='Show installation status and build/update out-of-date mods')
    p.add_argument('project', nargs='?'); p.add_argument('--instance'); p.add_argument('--settings', type=Path)
    p.add_argument('--json', action='store_true'); p.add_argument('--check', action='store_true', help='Exit 1 if any mod is out of sync')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--no', action='store_true', help='Show status without building or installing')
    mode.add_argument('--all', action='store_true', help='Build/update every out-of-date mod without prompting')
    mode.add_argument('--answer', help='Build/update numbered out-of-date mods, e.g. --answer=1,2,4')
    p = commands.add_parser('decompile'); p.add_argument('assembly'); p.add_argument('output', nargs='?'); p.add_argument('--type')
    commands.add_parser('inspect', help='Inspect mod metadata and assembly relations; see --help', add_help=False)
    args, extra = parser.parse_known_args()
    if args.command != 'inspect' and extra: parser.error('unrecognized arguments: ' + ' '.join(extra))
    args.extra = extra
    if args.command == 'sync' and (args.all or args.answer is not None) and (args.json or args.check):
        parser.error('--all/--answer cannot be combined with --json/--check')
    try:
        if args.command == 'clean':
            if args.kind == 'cache':
                if args.all: parser.error('--all applies only to session cleanup')
                from .lifecycle import clean_cache
                clean_cache(not args.dry_run)
                return
            from .lifecycle import collect
            for path in collect(not args.dry_run, all_sessions=args.all): print(('Eligible: ' if args.dry_run else 'Removed: ') + str(path))
            if args.dry_run: print('Preview only. Omit --dry-run to collect eligible, unpinned sessions.')
            return
        if args.command == 'save-report':
            from .lifecycle import promote
            promote(args.session_id, args.name)
            return
        if args.command == 'sync':
            from .sync import run
            report = run(args)
            if args.check and not report['in_sync']: raise SystemExit(1)
            return
        if args.command == 'latest':
            path = b.latest(c.project(args.project))
            if path is None: raise ValueError('No package has been built.')
            print(path)
            return
        if args.command == 'list':
            dispatch(args)
            return
        if args.command == 'pin':
            from .lifecycle import pin
            pin(args.session_id, not args.remove)
            return
        from .lifecycle import session
        with session(args.command, args.session):
            dispatch(args)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')


def dispatch(args):
    if args.command == 'check':
        for key, project in c.projects().items():
            for relative in ('PURPOSE.md', '.git', project['project']):
                if not (project['root'] / relative).exists(): raise ValueError(f'{key}: missing {relative}')
        subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=c.ROOT / 'tools', check=True, env=c.environment())
    elif args.command == 'setup': setup()
    elif args.command == 'inventory': inventory()
    elif args.command == 'list':
        for key, project in c.projects().items(): print(f'{key:24} {project.get("status", "active"):8} {project["name"]}')
    elif args.command == 'build': b.build(c.project(args.project, args.worktree), args.force)
    elif args.command == 'publish':
        from .publish import publish
        publish(c.project(args.project, args.worktree), args.dry_run, args.account, args.notes, args.steamcmd, args.backend, args.timeout)
    elif args.command == 'steam-probe':
        from .steamworks import probe
        probe(args.item, args.timeout)
    elif args.command == 'test':
        from .runner import test
        test(c.project(args.project, args.worktree), args.suite, args.additional, args.timeout)
    elif args.command == 'probe':
        from .probe import probe
        probe(args.fixture, args.save, args.config, args.timeout, args.package)
    elif args.command == 'trace':
        from .trace import collect
        collect(args.pid, args.seconds, args.native, args.dump)
    elif args.command == 'trace-report':
        from .trace import report
        report(args.input)
    elif args.command == 'code':
        from .trace import read_code
        read_code(args.pid, args.start, args.size)
    elif args.command == 'live-state':
        from .trace import live_state
        live_state(args.pid)
    elif args.command == 'install':
        from .install import install
        install(c.project(args.project, args.worktree), args.dry_run, args.instance, args.settings)
    elif args.command == 'rollback':
        from .install import rollback
        rollback(c.project(args.project, args.worktree), args.apply, args.instance)
    elif args.command == 'decompile':
        from .lifecycle import session_path
        output = c.local(c.ROOT / args.output) if args.output else session_path() / 'decompiled' / Path(args.assembly).stem
        if not output.is_relative_to(session_path()): raise ValueError('Decompilation is session scratch; omit OUTPUT or choose a path under the current session.')
        if not args.type and output.exists() and any(output.iterdir()): raise ValueError('Choose an empty decompilation output directory.')
        output.mkdir(parents=True, exist_ok=True)
        command = [c.CFG['ilspy'], '--disable-updatecheck', '-r', c.GAME, '-r', c.WORKSHOP / '2009463077/1.7/Assemblies']
        if args.type:
            target = output / (args.type + '.cs')
            if target.exists(): raise ValueError('This type is already decompiled in the session.')
            result = c.run(command + ['-t', args.type, (c.ROOT / args.assembly).absolute()], capture_output=True, text=True)
            target.write_text(result.stdout)
        else: c.run(command + ['-p', '-o', output, (c.ROOT / args.assembly).absolute()])
        print('Session decompilation:', output)
    elif args.command == 'inspect':
        from .relations import inspect
        inspect(args.extra)

def main():
    from .lifecycle import collect
    # Expired scratch is collected on every command, never persistent outputs.
    if not any(word in ('clean', 'pin', 'save-report', 'sync') for word in sys.argv[1:]): collect(apply=True)
    cache_cleanup = any(sys.argv[i:i+2] == ['clean', 'cache'] for i in range(1, len(sys.argv)))
    with c.lock('cache-use', shared=not cache_cleanup):
        execute()


if __name__ == '__main__': main()
