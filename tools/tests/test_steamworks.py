import ctypes as ct
import struct
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile
from rwlib import steamworks as sw


class SteamworksTests(unittest.TestCase):
    def test_namespace_guard_runs_before_loading_native_library(self):
        for namespaces in (('pid:[1]', 'pid:[2]'), FileNotFoundError('hidden host PID')):
            with self.subTest(namespaces=namespaces), \
                    patch.object(sw.Path, 'read_text', side_effect=['21684\n', 'steam\n']), \
                    patch.object(sw.os, 'readlink', side_effect=namespaces), \
                    patch.object(sw.ct, 'CDLL') as load:
                with self.assertRaisesRegex(ValueError, 'unsandboxed execution'):
                    sw.Client('unused.so')
                load.assert_not_called()

    def test_namespace_guard_accepts_shared_namespace_and_rejects_stale_pid(self):
        with patch.object(sw.Path, 'read_text', side_effect=['21684\n', 'steam\n']), \
                patch.object(sw.os, 'readlink', return_value='pid:[1]'):
            sw.require_steam_namespace()
        for contents in (['8\n', 'kworker\n'], ['invalid'], ['0']):
            with self.subTest(contents=contents), \
                    patch.object(sw.Path, 'read_text', side_effect=contents), \
                    patch.object(sw.os, 'readlink') as readlink:
                with self.assertRaisesRegex(ValueError, 'Cannot verify'):
                    sw.require_steam_namespace()
                readlink.assert_not_called()

    def client(self):
        client = sw.Client.__new__(sw.Client)
        client.user, client.utils, client.ugc = 10, 11, 12
        client.callbacks = Mock()
        client.completed = Mock(return_value=True)
        client.failure_reason = Mock(return_value=1)
        client.identity = Mock(return_value={'app_id': sw.APP_ID, 'logged_on': True})
        client.start = Mock(return_value=2**50 + 3)
        client.submit = Mock(return_value=2**51 + 7)
        client.setters = {name: Mock(return_value=True) for name in ('Content', 'Title', 'Description', 'Preview')}
        return client

    def reply(self, client, result=1, agreement=False, item=123456):
        # Independent wire bytes exercise bool padding, uint64 width and final
        # callback decoding instead of returning an already constructed object.
        payload = struct.pack('<i?3xQ', result, agreement, item)
        def receive(utils, handle, target, size, callback, failed):
            self.assertEqual(size, len(payload))
            self.assertEqual(callback, 3404)
            self.assertEqual(handle, 2**51 + 7)
            ct.memmove(target, payload, len(payload))
            return True
        client.call_result = Mock(side_effect=receive)

    def test_submit_layout_and_dependency_linux_packing(self):
        self.assertEqual(ct.sizeof(sw.SubmitResult), 16)
        self.assertEqual(sw.SubmitResult.item_id.offset, 8)
        self.assertEqual(sw.DependenciesResult.item_id.offset, 4)
        self.assertEqual(ct.sizeof(sw.DependenciesResult), 148)

    def test_async_wait_uses_final_result_and_rejects_transport_failures(self):
        client = self.client()
        self.reply(client)
        result = client.wait(2**51 + 7, sw.SubmitResult, 3404, 2)
        self.assertEqual(result.item_id, 123456)
        def failed(utils, handle, flag):
            ct.cast(flag, ct.POINTER(ct.c_bool))[0] = True
            return True
        client.completed.side_effect = failed
        client.call_result.reset_mock()
        with self.assertRaisesRegex(ValueError, 'asynchronous call failed'):
            client.wait(2**51 + 7, sw.SubmitResult, 3404, 2)
        client.call_result.assert_not_called()

    def test_missing_result_and_timeout_never_count_as_success(self):
        client = self.client()
        client.call_result = Mock(return_value=False)
        with self.assertRaisesRegex(ValueError, 'valid final call result'):
            client.wait(1, sw.SubmitResult, 3404, 2)
        with self.assertRaisesRegex(ValueError, 'invalid asynchronous'):
            client.wait(0, sw.SubmitResult, 3404, 2)
        with patch.object(sw.time, 'monotonic', side_effect=[0, 3]):
            with self.assertRaisesRegex(ValueError, 'timed out'):
                client.wait(1, sw.SubmitResult, 3404, 2)

    def test_upload_stages_utf8_and_checks_final_item_and_agreement(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            about = run / 'content/About'
            about.mkdir(parents=True)
            (about / 'PublishedFileId.txt').write_text('123456\n')
            (about / 'Preview.png').write_bytes(b'preview')
            plan = {'item_id': '123456', 'title': 'Example', 'description': '日本語\nText', 'change_note': 'Release'}
            client = self.client()
            self.reply(client)
            result = client.upload(run, plan, 2)
            self.assertEqual(result['item_id'], '123456')
            client.setters['Description'].assert_called_once_with(12, 2**50 + 3, '日本語\nText'.encode())
            client.submit.assert_called_once_with(12, 2**50 + 3, b'Release')
            for code, agreement, item in ((9, False, 123456), (1, True, 123456), (1, False, 999)):
                self.reply(client, code, agreement, item)
                with self.subTest(code=code, agreement=agreement, item=item), self.assertRaisesRegex(ValueError, 'publication unconfirmed'):
                    client.upload(run, plan, 2)

    def test_setter_rejection_prevents_submit(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / 'content/About').mkdir(parents=True)
            (run / 'content/About/PublishedFileId.txt').write_text('123456')
            client = self.client()
            client.setters['Content'].return_value = False
            with self.assertRaisesRegex(ValueError, 'rejected item Content'):
                client.upload(run, {'item_id': '123456', 'title': 'Example', 'description': 'Text'}, 2)
            client.submit.assert_not_called()

    def test_wrong_app_or_offline_session_shuts_down_before_use(self):
        for app, online in ((999, True), (sw.APP_ID, False)):
            client = self.client()
            client.initialized = False
            client.init = Mock(return_value=True)
            client.get_user, client.get_utils, client.get_ugc = Mock(return_value=10), Mock(return_value=11), Mock(return_value=12)
            client.app_id, client.logged_on = Mock(return_value=app), Mock(return_value=online)
            client.shutdown = Mock()
            with self.assertRaises(ValueError):
                client.__enter__()
            client.shutdown.assert_called_once()
            client.start.assert_not_called()

    def test_invalid_item_ids_and_timeouts(self):
        for item in (0, -1, 2**64, '1 +quit', '１２'):
            with self.assertRaises(ValueError): sw.item_id(item)
        for timeout in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError): sw.timeout_value(timeout)


if __name__ == '__main__':
    unittest.main()
