"""Small Linux Steamworks client, isolated from the CLI in a child process.

Uses the installed game's flat C ABI, not Steam's private IPC protocol.
API contracts: https://partner.steamgames.com/doc/api/ISteamUGC and ISteamUtils.
Callback layouts: Valve's public steam/isteamugc.h (Linux callback packing = 4).
No SteamworksPy/RimSort code or SDK binaries are copied into this workspace.
"""

import argparse
import ctypes as ct
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from . import core as c
from . import lifecycle

APP_ID = 294100
INVALID_UPDATE = 2**64 - 1


class SubmitResult(ct.Structure):
    _pack_ = 4
    _fields_ = [('result', ct.c_int32), ('needs_agreement', ct.c_bool),
                ('item_id', ct.c_uint64)]


class DependenciesResult(ct.Structure):
    _pack_ = 4
    _fields_ = [('result', ct.c_int32), ('item_id', ct.c_uint64),
                ('apps', ct.c_uint32 * 32), ('count', ct.c_uint32),
                ('total', ct.c_uint32)]


def item_id(value):
    text = str(value)
    if not text.isascii() or not text.isdecimal() or not 0 < int(text) < 2**64:
        raise ValueError('Workshop item ID must be a positive uint64.')
    return int(text)


def timeout_value(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Steamworks timeout must be positive and finite.')
    return value


class Client:
    def __init__(self, library):
        self.lib = ct.CDLL(str(library))
        self.initialized = False
        p, u64, u32, boolean = ct.c_void_p, ct.c_uint64, ct.c_uint32, ct.c_bool
        self.init = self.bind('SteamAPI_Init', boolean)
        self.shutdown = self.bind('SteamAPI_Shutdown', None)
        self.callbacks = self.bind('SteamAPI_RunCallbacks', None)
        # These are the versioned accessors exported by the installed RimWorld
        # library. Fail explicitly if a future bundled library drops this ABI.
        self.get_user = self.bind('SteamAPI_SteamUser_v021', p)
        self.get_utils = self.bind('SteamAPI_SteamUtils_v010', p)
        self.get_ugc = self.bind('SteamAPI_SteamUGC_v016', p)
        self.logged_on = self.bind('SteamAPI_ISteamUser_BLoggedOn', boolean, p)
        self.steam_id = self.bind('SteamAPI_ISteamUser_GetSteamID', u64, p)
        self.app_id = self.bind('SteamAPI_ISteamUtils_GetAppID', u32, p)
        self.completed = self.bind('SteamAPI_ISteamUtils_IsAPICallCompleted', boolean, p, u64, ct.POINTER(boolean))
        self.call_result = self.bind('SteamAPI_ISteamUtils_GetAPICallResult', boolean, p, u64, p, ct.c_int, ct.c_int, ct.POINTER(boolean))
        self.failure_reason = self.bind('SteamAPI_ISteamUtils_GetAPICallFailureReason', ct.c_int, p, u64)
        self.dependencies = self.bind('SteamAPI_ISteamUGC_GetAppDependencies', u64, p, u64)
        self.start = self.bind('SteamAPI_ISteamUGC_StartItemUpdate', u64, p, u32, u64)
        self.submit = self.bind('SteamAPI_ISteamUGC_SubmitItemUpdate', u64, p, u64, ct.c_char_p)
        self.setters = {name: self.bind('SteamAPI_ISteamUGC_SetItem' + name, boolean, p, u64, ct.c_char_p)
                        for name in ('Content', 'Title', 'Description', 'Preview')}

    def bind(self, name, restype, *argtypes):
        try:
            function = getattr(self.lib, name)
        except AttributeError:
            raise ValueError(f'Installed Steamworks library lacks {name}.') from None
        function.restype, function.argtypes = restype, list(argtypes)
        return function

    def __enter__(self):
        if not self.init():
            raise ValueError('Steamworks initialization failed. Run desktop Steam online as this OS user with a RimWorld license.')
        self.initialized = True
        try:
            self.user, self.utils, self.ugc = self.get_user(), self.get_utils(), self.get_ugc()
            if not all((self.user, self.utils, self.ugc)):
                raise ValueError('Steamworks did not supply the required interfaces.')
            if self.app_id(self.utils) != APP_ID:
                raise ValueError('Steamworks authenticated for a different app; expected RimWorld 294100.')
            if not self.logged_on(self.user):
                raise ValueError('Desktop Steam has no authenticated online session. Reconnect Steam and run steam-probe again.')
        except BaseException:
            self.close()
            raise
        return self

    def close(self):
        if self.initialized:
            self.shutdown()
            self.initialized = False

    def __exit__(self, *args):
        self.close()

    def identity(self):
        return {'app_id': self.app_id(self.utils), 'steam_id': str(self.steam_id(self.user)),
                'logged_on': bool(self.logged_on(self.user))}

    def wait(self, handle, structure, callback, timeout):
        if not handle:
            raise ValueError('Steamworks returned an invalid asynchronous call handle.')
        deadline = time.monotonic() + timeout_value(timeout)
        while time.monotonic() < deadline:
            self.callbacks()
            failed = ct.c_bool()
            if self.completed(self.utils, handle, ct.byref(failed)):
                if failed.value:
                    raise ValueError(f'Steamworks asynchronous call failed (reason {self.failure_reason(self.utils, handle)}).')
                result = structure()
                if not self.call_result(self.utils, handle, ct.byref(result), ct.sizeof(result), callback, ct.byref(failed)) or failed.value:
                    raise ValueError('Steamworks did not return a valid final call result.')
                return result
            time.sleep(0.05)
        raise ValueError('Steamworks timed out; result unconfirmed. Do not automatically retry a submitted upload.')

    def probe(self, item=None, timeout=30):
        result = self.identity()
        if item is not None:
            item = item_id(item)
            reply = self.wait(self.dependencies(self.ugc, item), DependenciesResult, 3416, timeout)
            if reply.result != 1 or reply.item_id != item or reply.count > 32:
                raise ValueError(f'Workshop read failed: EResult={reply.result}, item={reply.item_id}.')
            result.update(item_id=str(item), dependencies=list(reply.apps[:reply.count]),
                          total_dependencies=reply.total)
        return result

    def upload(self, run, plan, timeout):
        item = item_id(plan['item_id'])
        content = run / 'content'
        if (content / 'About/PublishedFileId.txt').read_text().strip() != str(item):
            raise ValueError('Staged content has a different Workshop item ID.')
        handle = self.start(self.ugc, APP_ID, item)
        if handle in (0, INVALID_UPDATE):
            raise ValueError('Steamworks refused to start the item update.')
        fields = {'Content': str(content), 'Title': plan['title'], 'Description': plan['description']}
        preview = content / 'About/Preview.png'
        if preview.is_file():
            fields['Preview'] = str(preview)
        for name, value in fields.items():
            if '\0' in value or not self.setters[name](self.ugc, handle, value.encode('utf-8')):
                raise ValueError(f'Steamworks rejected item {name}.')
        note = plan['change_note']
        if not note or '\0' in note:
            raise ValueError('Invalid Workshop change note.')
        # No automatic retries after this point: a timeout may still commit.
        reply = self.wait(self.submit(self.ugc, handle, note.encode('utf-8')), SubmitResult, 3404, timeout)
        result = dict(self.identity(), item_id=str(reply.item_id), result=reply.result,
                      needs_agreement=bool(reply.needs_agreement))
        verify_result(result, item)
        return result


def verify_result(result, expected):
    if (result.get('result') != 1 or result.get('item_id') != str(expected)
            or result.get('needs_agreement') is not False):
        raise ValueError(f'Workshop publication unconfirmed: {result}')


def worker(run, *, probe=False, item=None, timeout=30):
    """Launch the native client with the caller's desktop environment intact."""
    timeout = timeout_value(timeout)
    run = c.local(run).resolve()
    run.mkdir(parents=True, exist_ok=True)
    (run / 'steam_appid.txt').write_text(str(APP_ID) + '\n')
    result_path = run / c.identifier('steamworks-result-')
    args = [sys.executable, '-m', 'rwlib.steamworks', '--result', str(result_path),
            '--library', str(c.GAME / 'libsteam_api.so'), '--timeout', str(timeout)]
    if probe:
        args.append('--probe')
        if item is not None:
            args.extend(['--item', str(item_id(item))])
    env = os.environ.copy()
    env.update(SteamAppId=str(APP_ID), SteamGameId=str(APP_ID))
    env['PYTHONPATH'] = str(c.ROOT / 'tools') + os.pathsep + env.get('PYTHONPATH', '')
    # c.environment() isolates XDG paths for game tests; here we need the real
    # desktop session. Only cwd and Steam's app identity are scoped to the child.
    with (run / 'steamworks.log').open('ab') as log:
        process = subprocess.Popen(args, cwd=run, env=env, stdout=log, stderr=subprocess.STDOUT)
        lifecycle.register_process(process.pid)
        try:
            code = process.wait(timeout=timeout + 15)
        except BaseException:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    if not result_path.is_file():
        raise ValueError(f'Steamworks worker exited {code} without a result; inspect {run / "steamworks.log"}.')
    result = json.loads(result_path.read_text())
    if code != 0 or 'error' in result:
        raise ValueError(f'{result.get("error", "Steamworks worker failed")} Log: {run / "steamworks.log"}')
    return result


def probe(item=None, timeout=30):
    run = lifecycle.session_path() / c.identifier('steam-probe-')
    result = worker(run, probe=True, item=item, timeout=timeout)
    print(json.dumps(result, indent=2))
    print('Probe files:', run)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--item')
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args()
    try:
        with Client(args.library) as client:
            if args.probe:
                result = client.probe(args.item, args.timeout)
            else:
                run = Path.cwd()
                result = client.upload(run, json.loads((run / 'plan.json').read_text()), args.timeout)
    except Exception as error:
        c.write_json(args.result, {'error': str(error)})
        raise SystemExit(1)
    c.write_json(args.result, result)


if __name__ == '__main__':
    main()
