"""Read-only sampling of a running .NET process, with leased trace artifacts."""
import subprocess
import os
from pathlib import Path
from . import core as c
from . import lifecycle


def live_state(pid):
    from . import build
    if lifecycle.process_record(pid)['start'] is None or Path(f'/proc/{pid}/exe').resolve().name != 'RimWorld':
        raise ValueError('A running RimWorld process is required.')
    if Path(f'/proc/{pid}/exe').resolve().parent != c.GAME:
        raise ValueError('The live metadata reader requires the matching installed runtime and DAC.')
    libraries = list((c.ROOT / '.cache/tools/dotnet-dump/.store').rglob('Microsoft.Diagnostics.Runtime.dll'))
    if len(libraries) != 1:
        raise ValueError('Expected one installed ClrMD library in the dump tool.')
    root = lifecycle.session_path()
    c.write_json(root / 'metadata-inputs.json', {'target': lifecycle.process_record(pid),
        'runtime': str(c.GAME / 'libcoreclr.so'), 'dac': str(c.GAME / 'libmscordaccore.so')})
    project = c.ROOT / 'tools/dotnet/live/LiveState.csproj'
    wrapper = root / 'LiveState.csproj'
    wrapper.write_text(project.read_text().replace('$(DiagnosticsToolPath)', str(libraries[0].parent)).replace(
        '<ItemGroup>', '<ItemGroup><Compile Include="' + str(project.parent / 'Program.cs') + '" />', 1).replace(
        '<OutputType>Exe</OutputType>', '<OutputType>Exe</OutputType><EnableDefaultCompileItems>false</EnableDefaultCompileItems>'))
    build.compile_project(wrapper, root / 'live-state-build', 'tools/live-state', capture=True)
    result = subprocess.run(['dotnet', str(root / 'live-state-build/LiveState.dll'), str(pid), str(c.GAME / 'libmscordaccore.so')],
                            env=c.environment(), capture_output=True, text=True)
    (root / 'live-state.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError('Live metadata inspection failed: ' + result.stderr[-3000:])
    (root / 'live-state.json').write_text(result.stdout)
    print(result.stdout)


def read_code(pid, start, size=8192):
    if not 1 <= size <= 65536:
        raise ValueError('Code reads must be between 1 and 65536 bytes.')
    process = lifecycle.process_record(pid)
    if process['start'] is None or Path(f'/proc/{pid}/exe').resolve().name != 'RimWorld':
        raise ValueError('A running RimWorld process is required.')
    mappings = Path(f'/proc/{pid}/maps').read_text().splitlines()
    match = None
    for line in mappings:
        parts = line.split()
        low, high = (int(value, 16) for value in parts[0].split('-'))
        if low <= start and start + size <= high and 'x' in parts[1] and 'r' in parts[1]:
            match = line
            break
    if match is None:
        raise ValueError('The requested range must be inside one readable executable mapping.')
    fd = os.open(f'/proc/{pid}/mem', os.O_RDONLY)
    try:
        data = os.pread(fd, size, start)
    finally:
        os.close(fd)
    if len(data) != size or lifecycle.process_record(pid) != process:
        raise ValueError('Incomplete code read or target process changed.')
    root = lifecycle.session_path()
    code = root / f'code-{start:x}.bin'
    code.write_bytes(data)
    c.write_json(root / f'code-{start:x}.json', {'target': process, 'start': hex(start), 'size': size,
        'mapping': match})
    with code.with_suffix('.asm').open('w') as output:
        subprocess.run(['objdump', '-D', '-b', 'binary', '-m', 'i386:x86-64', f'--adjust-vma={start}', code],
                       stdout=output, check=True)
    print('Executable code disassembly:', code.with_suffix('.asm'))


def report(trace):
    from . import build
    trace = c.local(c.ROOT / trace)
    libraries = list((c.ROOT / '.cache/tools/dotnet-trace/.store').rglob('Microsoft.Diagnostics.Tracing.TraceEvent.dll'))
    if len(libraries) != 1:
        raise ValueError('Expected exactly one installed TraceEvent library.')
    output = lifecycle.session_path() / 'trace-summary-build'
    # Use the normal compiler wrapper; the helper has no game or mod dependencies.
    project = c.ROOT / 'tools/dotnet/trace/TraceSummary.csproj'
    wrapper = lifecycle.session_path() / 'TraceSummary.csproj'
    wrapper.write_text(project.read_text().replace('$(TraceToolPath)', str(libraries[0].parent)).replace(
        '<ItemGroup>', '<ItemGroup><Compile Include="' + str(project.parent / 'Program.cs') + '" />', 1).replace(
        '<OutputType>Exe</OutputType>', '<OutputType>Exe</OutputType><EnableDefaultCompileItems>false</EnableDefaultCompileItems>'))
    build.compile_project(wrapper, output, 'tools/trace-summary', capture=True)
    target = lifecycle.session_path() / 'runtime-events.json'
    c.run(['dotnet', output / 'TraceSummary.dll', trace, target])
    print('Runtime events:', target)


def collect(pid, seconds=30, native=False, dump=False):
    if not 1 <= seconds <= 60:
        raise ValueError('Trace duration must be between 1 and 60 seconds.')
    tool = c.ROOT / '.cache/tools/dotnet-trace/dotnet-trace'
    if native and dump:
        raise ValueError('Select either a native trace or a runtime snapshot.')
    if dump:
        tool = c.ROOT / '.cache/tools/dotnet-dump/dotnet-dump'
    if not native and not tool.is_file():
        raise ValueError('Microsoft dotnet-trace is required in .cache/tools/dotnet-trace.')
    process = lifecycle.process_record(pid)
    if process['start'] is None:
        raise ValueError('Target process is not running in this process namespace.')
    target = Path(f'/proc/{pid}/exe').resolve()
    if target.name != 'RimWorld':
        raise ValueError('Live traces in this workspace must target RimWorld.')
    root = lifecycle.session_path()
    output = root / 'runs' / c.identifier('trace-')
    output.mkdir(parents=True)
    command = [str(tool), 'collect', '--process-id', str(pid), '--duration', f'00:00:{seconds // 60:02}:{seconds % 60:02}',
               '--profile', 'dotnet-sampled-thread-time', '--providers', 'Microsoft-Windows-DotNETRuntime:0x1:4',
               '--format', 'Speedscope', '--output', str(output / 'live.nettrace'), '--buffersize', '64']
    if native:
        command = ['perf', 'record', '-e', 'cycles:u', '-F', '199', '--call-graph', 'dwarf,16384',
                   '-p', str(pid), '-o', str(output / 'native.data'), '--', 'sleep', str(seconds)]
    if dump:
        command = [str(tool), 'collect', '--process-id', str(pid), '--type', 'Mini', '--output', str(output / 'runtime.core')]
    env = c.environment(output)
    # The target was started by the desktop in /tmp, not by the isolated launcher.
    env['TMPDIR'] = '/tmp'
    c.write_json(output / 'inputs.json', {'target': process, 'executable': str(target),
        'game': c.game_record(), 'command': command})
    result = {'pass': False, 'target': process}
    try:
        with (output / 'run.log').open('w') as log:
            sampler = subprocess.Popen(command, cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT)
            lifecycle.register_process(sampler.pid)
            try:
                sampler.wait(timeout=seconds + 60)
            except subprocess.TimeoutExpired:
                sampler.kill(); sampler.wait()
                raise ValueError('Sampler timed out; target process was left running.')
        result['sampler_exit'] = sampler.returncode
        if sampler.returncode:
            raise ValueError('Sampling failed; inspect ' + str(output / 'run.log'))
        result['pass'] = True
        print('Live sampling trace:', output)
        return output
    finally:
        c.write_json(output / 'result.json', result)
