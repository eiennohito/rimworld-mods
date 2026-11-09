import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from rwlib import build, core, lifecycle, publish, steamworks
from rwlib import __main__ as cli


class PublishTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'projects/example'
        (self.source / 'About').mkdir(parents=True)
        self.description = 'Storage "limits"\nKeep C:\\Mods & <examples> intact.'
        about = ET.Element('ModMetaData')
        for key, value in {'name': 'Example', 'packageId': 'local.example',
                           'modVersion': '1.1', 'description': self.description}.items():
            ET.SubElement(about, key).text = value
        ET.ElementTree(about).write(self.source / 'About/About.xml', encoding='utf-8')
        (self.source / 'About/PublishedFileId.txt').write_text('123456\n')
        (self.source / 'About/Preview.png').write_bytes(b'preview')
        (self.source / 'CHANGELOG.md').write_text('## 1.1\n\n- Carry several stacks.\n\n## 1.0\n\n- Old behavior.\n')
        self.package = self.root / 'outputs/mods/example/build'
        shutil.copytree(self.source / 'About', self.package / 'About')
        (self.package / 'payload').write_bytes(b'runtime content')
        self.record = {'package_id': 'local.example', 'build_id': 'build',
                       'inputs': {'git': {'commit': 'abc', 'dirty': False}},
                       'files': [p.relative_to(self.package).as_posix()
                                 for p in self.package.rglob('*') if p.is_file()]}
        (self.package / 'build.json').write_text(json.dumps(self.record))
        self.project = {'key': 'example', 'root': self.source, 'package_id': 'local.example'}
        self.enterContext(patch.object(core, 'ROOT', self.root))
        self.compile = self.enterContext(patch.object(build, 'build', return_value=self.package))
        self.enterContext(lifecycle.session('publish-test'))

    def process(self, output, code=0, rewrite=None):
        class Process:
            pid = 999999999
            def __init__(inner, args, **kwargs):
                self.assertNotIn('stdin', kwargs)  # First login can use the caller's terminal.
                self.assertNotIn('shell', kwargs)
                inner.stdout = io.BytesIO(output.encode())
                if rewrite:
                    rewrite(Path(args[args.index('+workshop_build_item') + 1]))
            def wait(inner, timeout=None): return code
        return Process

    def test_dry_run_keeps_multiline_text_and_uses_private_snapshot(self):
        with patch.object(publish.subprocess, 'Popen') as process:
            run = publish.publish(self.project, dry_run=True)
        process.assert_not_called()
        self.assertEqual((run / 'description.txt').read_text(), self.description + '\n')
        self.assertEqual((run / 'change-note.txt').read_text(), 'Version 1.1\n\n- Carry several stacks.\n')
        vdf = (run / 'upload.vdf').read_text()
        self.assertIn('"appid" "294100"', vdf)
        self.assertIn('"publishedfileid" "123456"', vdf)
        self.assertIn('Storage \\"limits\\"\nKeep C:\\\\Mods', vdf)
        self.assertNotIn('Old behavior', vdf)
        self.assertNotIn('visibility', vdf)
        self.assertNotIn('tags', vdf)
        self.assertEqual(build.validate(run / 'content'), self.record)
        (run / 'content/payload').write_bytes(b'changed private staging')
        self.assertEqual((self.package / 'payload').read_bytes(), b'runtime content')
        self.assertFalse((self.root / 'state/publications').exists())

    def test_missing_or_zero_item_id_never_creates_a_new_item(self):
        path = self.source / 'About/PublishedFileId.txt'
        for value in ('0', '-1', 'new item', '', str(2**64), '9' * 100):
            path.write_text(value)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'existing item ID'):
                publish.prepare(self.project)
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'existing item ID'):
            publish.prepare(self.project)
        self.compile.assert_not_called()

    def test_wrong_release_note_requires_an_explicit_file(self):
        (self.source / 'CHANGELOG.md').write_text('## Unreleased\n\n- Not a release.\n\n## 1.0\n\n- Old.\n')
        with self.assertRaisesRegex(ValueError, 'No release notes for version 1.1'):
            publish.prepare(self.project)
        notes = self.root / 'release-note.txt'
        notes.write_text('1.1\n\nCustom "note" with \\slashes.\n')
        run, plan = publish.prepare(self.project, notes)
        self.assertEqual(plan['change_note'], notes.read_text().strip())
        self.assertIn('Custom \\"note\\"', (run / 'upload.vdf').read_text())

    def test_preparation_uses_current_package_contents(self):
        (self.package / 'payload').write_bytes(b'changed')
        run, plan = publish.prepare(self.project)
        self.assertEqual((run / 'content/payload').read_bytes(), b'changed')

    def test_live_upload_requires_account_and_steamcmd_before_building(self):
        with self.assertRaisesRegex(ValueError, '--account'):
            publish.publish(self.project)
        with patch.object(publish.shutil, 'which', return_value=None), self.assertRaisesRegex(ValueError, 'not installed'):
            publish.publish(self.project, account='example')
        self.compile.assert_not_called()

    def test_account_cannot_add_steam_console_commands(self):
        for account in ('owner +quit', '+quit', '-command', 'owner\nquit'):
            with self.subTest(account=account), self.assertRaises(ValueError):
                publish.command('steamcmd', account, 'upload.vdf')

    def test_custom_executable_path_is_resolved_before_changing_directory(self):
        executable = self.root / 'tools/steamcmd.sh'
        executable.parent.mkdir()
        executable.write_text('#!/bin/sh\nexit 1\n')
        executable.chmod(0o755)
        with patch.object(publish.subprocess, 'Popen') as process:
            run = publish.publish(self.project, dry_run=True, steamcmd='tools/steamcmd.sh')
        self.assertEqual(json.loads((run / 'command.json').read_text())[0], str(executable))
        process.assert_not_called()

    def test_success_requires_confirmation_for_the_exact_item(self):
        process = self.process('Success. Published File ID: 123456\n')
        with patch.object(publish.shutil, 'which', return_value='/fake/steamcmd'), patch.object(publish.subprocess, 'Popen', process):
            run = publish.publish(self.project, account='owner')
        receipts = list((self.root / 'state/publications/example').glob('*.json'))
        self.assertEqual(len(receipts), 1)
        result = json.loads(receipts[0].read_text())
        self.assertEqual(result['status'], 'published')
        self.assertEqual(result['item_id'], '123456')
        self.assertEqual(result['change_note'], 'Version 1.1\n\n- Carry several stacks.')
        self.assertEqual((run / 'steamcmd.log').read_text(), 'Success. Published File ID: 123456\n')
        self.assertTrue(publish.successful('Success. Published item 123456.\n', '123456'))
        self.assertFalse(publish.successful('Success. Published item 1234567.\n', '123456'))

    def test_zero_exit_without_publication_is_not_success(self):
        process = self.process('ERROR! Not logged on.\n')
        with patch.object(publish.shutil, 'which', return_value='/fake/steamcmd'), patch.object(publish.subprocess, 'Popen', process):
            with self.assertRaisesRegex(ValueError, 'did not confirm publication'):
                publish.publish(self.project, account='owner')
        receipt = next((self.root / 'state/publications/example').glob('*.json'))
        self.assertEqual(json.loads(receipt.read_text())['status'], 'failed/unconfirmed')

    def test_current_steamcmd_commit_message_with_terminal_colors(self):
        output = '\x1b[0mCommitting update...\x1b[0mSuccess.\x1b[0mUnloading Steam API...OK\n'
        process = self.process(output)
        with patch.object(publish.shutil, 'which', return_value='/fake/steamcmd'), patch.object(publish.subprocess, 'Popen', process):
            run = publish.publish(self.project, account='owner')
        receipt = next((self.root / 'state/publications/example').glob('*.json'))
        result = json.loads(receipt.read_text())
        self.assertEqual(result['status'], 'published')
        # Reconcile the old parser's false failure without executing SteamCMD.
        result.update(status='failed/unconfirmed', error='old parser did not recognize success')
        receipt.write_text(json.dumps(result))
        with patch.object(publish.subprocess, 'Popen') as retry:
            confirmed = publish.reconcile(run)
        retry.assert_not_called()
        self.assertEqual(confirmed['status'], 'published')
        self.assertIn('previous_error', confirmed)
        self.assertFalse(publish.successful('Connecting...Success.\n', '123456'))
        self.assertFalse(publish.successful('Committing update...ERROR!\nSuccess.\n', '123456'))

    def test_changed_item_id_after_submit_is_reported(self):
        def rewrite(path): path.write_text(path.read_text().replace('"123456"', '"999999"'))
        process = self.process('Success. Published item 123456.\n', rewrite=rewrite)
        with patch.object(publish.shutil, 'which', return_value='/fake/steamcmd'), patch.object(publish.subprocess, 'Popen', process):
            with self.assertRaisesRegex(ValueError, 'changed the item ID'):
                publish.publish(self.project, account='owner')

    def test_nonzero_exit_is_failure_even_with_a_success_line(self):
        process = self.process('Success. Published item 123456.\n', code=1)
        with patch.object(publish.shutil, 'which', return_value='/fake/steamcmd'), patch.object(publish.subprocess, 'Popen', process):
            with self.assertRaisesRegex(ValueError, 'did not confirm publication'):
                publish.publish(self.project, account='owner')

    def test_vdf_rejects_control_characters(self):
        for bad in ('note\0text', 'note\x1btext'):
            with self.assertRaises(ValueError): publish.quote(bad)

    def test_cli_accepts_publish_options(self):
        args = ['rw', 'publish', 'example', '--dry-run', '--account', 'owner', '--notes', 'release.txt', '--steamcmd', '/bin/steamcmd']
        with patch.object(sys, 'argv', args), patch.object(cli, 'dispatch') as dispatch, patch.object(lifecycle, 'session'):
            cli.execute()
        parsed = dispatch.call_args.args[0]
        self.assertTrue(parsed.dry_run)
        self.assertEqual(parsed.account, 'owner')
        self.assertEqual(parsed.notes, Path('release.txt'))

    def test_desktop_dry_run_does_not_load_native_library_or_submit(self):
        with patch.object(steamworks, 'worker') as worker, patch.object(steamworks.ct, 'CDLL') as load:
            run = publish.publish(self.project, dry_run=True, backend='desktop')
        worker.assert_not_called()
        load.assert_not_called()
        self.assertEqual(json.loads((run / 'plan.json').read_text())['title'], 'Example')
        self.assertFalse((self.root / 'state/publications').exists())

    def test_desktop_receipt_requires_exact_final_result_and_never_falls_back(self):
        replies = [dict(result=1, item_id='123456', needs_agreement=False),
                   dict(result=1, item_id='999999', needs_agreement=False),
                   dict(result=9, item_id='123456', needs_agreement=False)]
        for reply in replies:
            with self.subTest(reply=reply), patch.object(steamworks, 'worker', return_value=reply) as worker, patch.object(publish, 'submit') as fallback:
                if reply == replies[0]:
                    run = publish.publish(self.project, backend='desktop')
                    receipt = self.root / 'state/publications/example' / (run.name + '.json')
                    self.assertEqual(json.loads(receipt.read_text())['status'], 'published')
                    self.assertEqual(publish.reconcile(run)['status'], 'published')
                else:
                    with self.assertRaisesRegex(ValueError, 'publication unconfirmed'):
                        publish.publish(self.project, backend='desktop')
                    run = worker.call_args.args[0]
                    receipt = self.root / 'state/publications/example' / (run.name + '.json')
                    self.assertEqual(json.loads(receipt.read_text())['status'], 'failed/unconfirmed')
                self.assertEqual(worker.call_count, 1)
                fallback.assert_not_called()

    def test_desktop_worker_failure_retains_unconfirmed_receipt(self):
        with patch.object(steamworks, 'worker', side_effect=ValueError('worker crashed')) as worker:
            with self.assertRaisesRegex(ValueError, 'worker crashed'):
                publish.publish(self.project, backend='desktop')
        run = worker.call_args.args[0]
        receipt = self.root / 'state/publications/example' / (run.name + '.json')
        self.assertEqual(json.loads(receipt.read_text())['status'], 'failed/unconfirmed')

    def test_desktop_cli_selects_backend(self):
        with patch.object(sys, 'argv', ['rw', 'publish', 'example', '--backend', 'desktop', '--dry-run']), patch.object(cli, 'dispatch') as dispatch, patch.object(lifecycle, 'session'):
            cli.execute()
        self.assertEqual(dispatch.call_args.args[0].backend, 'desktop')


if __name__ == '__main__':
    unittest.main()
