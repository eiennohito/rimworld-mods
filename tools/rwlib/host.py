from pathlib import Path
import json
import shutil
import hashlib
from . import core as c
from .build import compile_project
from . import snapshot


def prepare_host():
    c.game_record()
    paths = [c.GAME / 'Assembly-CSharp.dll', c.GAME / 'Waylith.dll',
             *sorted((c.ROOT / 'tools/dotnet/host').glob('*.cs')),
             c.ROOT / 'tools/dotnet/host/PrepareTestHost.csproj']
    key = hashlib.sha256(json.dumps({str(p): c.file_stamp(p) for p in paths}, sort_keys=True).encode()).hexdigest()[:20]
    folder = c.ROOT / '.cache/hosts' / key
    assembly = folder / 'Assembly-CSharp.dll'
    manifest = folder / 'steamless-host.json'
    with c.lock('host'):
        if assembly.is_file() and manifest.is_file() and (folder / 'quiet-audio.json').is_file():
            audio = json.loads((folder / 'quiet-audio.json').read_text())
            if audio.get('noAudio') and (folder / 'Waylith.dll').is_file(): return folder
        tool = c.ROOT / '.cache/tools/PrepareTestHost'
        compile_project(c.ROOT / 'tools/dotnet/host/PrepareTestHost.csproj', tool, 'tools/host', capture=True)
        folder.mkdir(parents=True, exist_ok=True)
        c.run(['dotnet', tool / 'PrepareTestHost.dll', c.GAME / 'Assembly-CSharp.dll', assembly, manifest])
        c.run(['dotnet', tool / 'PrepareTestHost.dll', '--no-audio', c.GAME / 'Waylith.dll', folder / 'Waylith.dll', folder / 'quiet-audio.json'])
    return folder


def make_game(run_dir):
    template = prepare_host()
    game = run_dir / 'game'
    game.mkdir()
    for item in c.GAME.iterdir():
        target = game / item.name
        if item.name == 'Mods': continue
        if item.name == 'Assembly-CSharp.dll': snapshot.copy_file(template / item.name, target)
        elif item.name == 'Waylith.dll': snapshot.copy_file(template / item.name, target)
        elif item.name in ('RimWorld', 'RimWorld.dll', 'RimWorld.deps.json', 'RimWorld.runtimeconfig.json'):
            snapshot.copy_file(item, target)
        else: target.symlink_to(item, target_is_directory=item.is_dir())
    shutil.copy2(template / 'steamless-host.json', run_dir / 'steamless-host.json')
    shutil.copy2(template / 'quiet-audio.json', run_dir / 'quiet-audio.json')
    (game / 'Mods').mkdir()
    return game
