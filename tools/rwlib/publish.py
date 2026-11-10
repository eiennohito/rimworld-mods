"""Prepare and submit updates to existing RimWorld Workshop items."""

import codecs
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from . import build as b
from . import core as c
from . import lifecycle


def quote(value):
    """Encode a quoted Valve KeyValues string, retaining actual multiline text."""
    value = str(value)
    if '\0' in value or any(ord(ch) < 32 and ch not in '\n\r\t' for ch in value):
        raise ValueError('Workshop text contains unsupported control characters.')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def vdf(fields):
    return '"workshopitem"\n{\n' + ''.join(
        f'    {quote(key)} {quote(value)}\n' for key, value in fields.items()) + '}\n'


def release_note(project, version, notes=None):
    if notes:
        text = (c.ROOT / notes).read_text(encoding='utf-8').strip()
    else:
        path = project['root'] / 'CHANGELOG.md'
        if not path.is_file():
            raise ValueError('No CHANGELOG.md; provide the release note with --notes FILE.')
        text = None
        sections = re.split(r'(?m)^##\s+', path.read_text(encoding='utf-8'))[1:]
        for section in sections:
            heading, _, body = section.partition('\n')
            match = re.match(r'v?(\d+(?:\.\d+)+)(?:\s|$)', heading)
            if match and tuple(map(int, match[1].split('.'))) == tuple(map(int, version.split('.'))):
                # Stop at a parent heading, e.g. the separate upstream history.
                body = re.split(r'(?m)^#\s+', body)[0].strip()
                if body:
                    text = f'Version {version}\n\n{body}'
                break
        if not text:
            raise ValueError(f'No release notes for version {version}; provide --notes FILE.')
    if not text:
        raise ValueError('The Workshop change note must not be empty.')
    quote(text)
    return text


def prepare(project, notes=None):
    # Refuse an absent/invalid ID before building. This command only updates
    # existing items; SteamCMD must never turn a missing ID into a new upload.
    id_path = project['root'] / 'About/PublishedFileId.txt'
    item = id_path.read_text().strip() if id_path.is_file() else ''
    if not re.fullmatch(r'[1-9][0-9]{0,19}', item) or int(item) > 2**64 - 1:
        raise ValueError('Publishing requires an existing item ID in About/PublishedFileId.txt.')
    workshop = project['root'] / 'About/Workshop.txt'
    if not workshop.is_file():
        raise ValueError('Publishing requires About/Workshop.txt for the Workshop description.')
    description = workshop.read_text(encoding='utf-8').strip()
    if not description:
        raise ValueError('The Workshop description must not be empty.')
    package = b.build(project)
    record = b.validate(package)
    about = ET.parse(package / 'About/About.xml').getroot()
    if (about.findtext('packageId') or '').lower() != project['package_id'].lower():
        raise ValueError('Workshop package belongs to a different project.')
    if (package / 'About/PublishedFileId.txt').read_text().strip() != item:
        raise ValueError('Workshop item ID changed during preparation.')
    version = (about.findtext('modVersion') or '').strip()
    if not re.fullmatch(r'\d+(?:\.\d+)+', version):
        raise ValueError('About/About.xml needs a numeric modVersion for this release.')
    change_note = release_note(project, version, notes)
    title = (about.findtext('name') or '').strip()
    if not title:
        raise ValueError('The Workshop title must not be empty.')

    run = lifecycle.session_path() / 'publishing' / c.identifier(project['key'] + '-')
    content = run / 'content'
    run.mkdir(parents=True)
    shutil.copytree(package, content)
    b.validate(content)
    fields = {'appid': '294100', 'publishedfileid': item,
              'contentfolder': str(content), 'title': title,
              'description': description, 'changenote': change_note}
    preview = content / 'About/Preview.png'
    if preview.is_file():
        fields['previewfile'] = str(preview)
    # Visibility, tags and extra carousel images are deliberately not set:
    # Steam retains fields omitted from an update VDF.
    upload = run / 'upload.vdf'
    upload.write_text(vdf(fields), encoding='utf-8')
    (run / 'description.txt').write_text(description + '\n', encoding='utf-8')
    (run / 'change-note.txt').write_text(change_note + '\n', encoding='utf-8')
    plan = {'project': project['key'], 'package': str(package),
            'build_id': record['build_id'], 'version': version, 'item_id': item,
            'source': record['inputs']['git'],
            'title': title, 'description': description, 'change_note': change_note,
            'run': str(run)}
    c.write_json(run / 'plan.json', plan)
    return run, plan


def command(executable, account, upload):
    if not re.fullmatch(r'[A-Za-z0-9_@.\-]+', account) or account.startswith('-'):
        raise ValueError('Supply a Steam account name, without spaces or command syntax.')
    return [str(executable), '+@ShutdownOnFailedCommand', '1',
            '+login', account, '+workshop_build_item', str(upload), '+quit']


def successful(output, item):
    output = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', output)
    explicit = re.search(r'(?im)^\s*Success\.\s+Published\s+(?:item|File\s+ID)\s*:?\s*'
                         + re.escape(item) + r'\b', output)
    # Current SteamCMD prints only "Committing update...Success.". In that
    # format the expected item ID is verified separately against its VDF.
    committed = re.search(r'(?i)Committing update\.\.\.\s*Success\.', output)
    return bool(explicit or committed)


def verify_upload(run, plan, code, output):
    if code != 0 or not successful(output, plan['item_id']):
        raise ValueError(f'SteamCMD did not confirm publication of item {plan["item_id"]}; inspect {run / "steamcmd.log"}')
    text = (run / 'upload.vdf').read_text(encoding='utf-8')
    ids = re.findall(r'"publishedfileid"\s+"([0-9]+)"', text, re.IGNORECASE)
    if ids != [plan['item_id']]:
        raise ValueError('SteamCMD changed the item ID; inspect the upload before retrying.')


def reconcile(run):
    """Verify an already completed attempt from its receipt and log, without retrying."""
    run = c.local(run)
    plan = json.loads((run / 'plan.json').read_text())
    receipt = c.ROOT / 'state/publications' / plan['project'] / (run.name + '.json')
    result = json.loads(receipt.read_text())
    if result['run'] != str(run) or result['item_id'] != plan['item_id']:
        raise ValueError('The publication receipt does not match this upload.')
    b.validate(run / 'content')
    if result.get('backend') == 'desktop':
        from .steamworks import verify_result
        verify_result(result.get('steamworks', {}), plan['item_id'])
    else:
        verify_upload(run, plan, result.get('exit_code'), (run / 'steamcmd.log').read_text(errors='replace'))
    if 'error' in result:
        result['previous_error'] = result.pop('error')
    result.update(status='published', verified_at=lifecycle.stamp(lifecycle.now()))
    c.write_json(receipt, result)
    print('Confirmed completed publication:', plan['item_id'])
    print('Publication receipt:', receipt)
    return result


def submit(args, run, plan):
    """Stream login/upload prompts while retaining session logs and a receipt."""
    receipt = c.ROOT / 'state/publications' / plan['project'] / (run.name + '.json')
    result = dict(plan, status='started')
    c.write_json(receipt, result)
    tail = ''
    try:
        # Inherit stdin for Steam Guard and first-login prompts. Passwords are
        # never command arguments or fields in the prepared files/receipt.
        with (run / 'steamcmd.log').open('wb') as log:
            process = subprocess.Popen(args, cwd=run, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT)
            lifecycle.register_process(process.pid)
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            try:
                while chunk := process.stdout.read1(4096):
                    log.write(chunk)
                    text = decoder.decode(chunk)
                    sys.stdout.write(text)
                    sys.stdout.flush()
                    tail = (tail + text)[-65536:]
                tail += decoder.decode(b'', final=True)
                code = process.wait()
            except BaseException:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise
            finally:
                process.stdout.close()
        result['exit_code'] = code
        verify_upload(run, plan, code, tail)
        result['status'] = 'published'
    except BaseException as error:
        result.update(status='failed/unconfirmed', error=str(error))
        raise
    finally:
        c.write_json(receipt, result)
    print(f'Published version {plan["version"]}: https://steamcommunity.com/sharedfiles/filedetails/?id={plan["item_id"]}')
    print('Publication receipt:', receipt)


def submit_desktop(run, plan, timeout):
    from . import steamworks
    receipt = c.ROOT / 'state/publications' / plan['project'] / (run.name + '.json')
    result = dict(plan, backend='desktop', status='started')
    c.write_json(receipt, result)
    try:
        b.validate(run / 'content')
        reply = steamworks.worker(run, timeout=timeout)
        result['steamworks'] = reply
        steamworks.verify_result(reply, plan['item_id'])
        result['status'] = 'published'
    except BaseException as error:
        result.update(status='failed/unconfirmed', error=str(error))
        raise
    finally:
        c.write_json(receipt, result)
    print(f'Published version {plan["version"]}: https://steamcommunity.com/sharedfiles/filedetails/?id={plan["item_id"]}')
    print('Publication receipt:', receipt)


def publish(project, dry_run=False, account=None, notes=None, steamcmd=None, backend='desktop', timeout=600):
    if backend not in ('steamcmd', 'desktop'):
        raise ValueError('Unknown publication backend.')
    if backend == 'desktop':
        from .steamworks import timeout_value
        timeout_value(timeout)
        if account or steamcmd:
            raise ValueError('--account and --steamcmd apply only to --backend steamcmd.')
        with c.lock('publish-' + project['key']), c.lock('steamcmd-publish'):
            run, plan = prepare(project, notes)
            print(f'Workshop item: {plan["item_id"]}; version: {plan["version"]}')
            print('Upload files:', run)
            print('Change note:\n' + plan['change_note'])
            print('Backend: desktop Steam session')
            if dry_run:
                print('Dry run: no Steam connection or publication attempted.')
            else:
                submit_desktop(run, plan, timeout)
            return run
    if steamcmd and '/' in str(steamcmd):
        executable = str((c.ROOT / steamcmd).resolve())
    else:
        executable = shutil.which(steamcmd or 'steamcmd') or (None if steamcmd else shutil.which('steamcmd.sh'))
        if executable:
            executable = str(Path(executable).resolve())
    if not dry_run:
        if not account:
            raise ValueError('Publishing requires --account STEAM_ACCOUNT.')
        if executable is None or not shutil.which(str(executable)):
            raise ValueError('SteamCMD is not installed; install it or pass --steamcmd PATH.')
        # Validate account syntax before preparing an upload or starting login.
        command(executable, account, 'upload.vdf')
    with c.lock('publish-' + project['key']), c.lock('steamcmd-publish'):
        run, plan = prepare(project, notes)
        args = command(executable or 'steamcmd', account or 'STEAM_ACCOUNT', run / 'upload.vdf')
        c.write_json(run / 'command.json', args)
        print(f'Workshop item: {plan["item_id"]}; version: {plan["version"]}')
        print('Upload files:', run)
        print('Change note:\n' + plan['change_note'])
        print('Command:', shlex.join(args))
        if dry_run:
            print('Dry run: no Steam login or publication attempted.')
            return run
        submit(args, run, plan)
        return run
