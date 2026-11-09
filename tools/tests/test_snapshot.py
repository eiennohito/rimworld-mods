import errno
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from rwlib import lifecycle, snapshot


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.lease = lifecycle.session('snapshot-check')
        self.folder = self.lease.__enter__()
        self.temp = tempfile.TemporaryDirectory(dir=self.folder)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.write_bytes(b'original' * 1024)
        self.source.chmod(0o640)
        self.destination = self.root / 'destination'

    def tearDown(self):
        self.temp.cleanup()
        self.lease.__exit__(None, None, None)

    def assert_independent(self):
        self.assertEqual(self.source.read_bytes(), self.destination.read_bytes())
        self.assertEqual(self.source.stat().st_mtime_ns, self.destination.stat().st_mtime_ns)
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o640)
        self.assertNotEqual(self.source.stat().st_ino, self.destination.stat().st_ino)
        self.destination.write_bytes(b'changed sandbox')
        self.assertEqual(self.source.read_bytes(), b'original' * 1024)
        self.source.write_bytes(b'updated upstream')
        self.assertEqual(self.destination.read_bytes(), b'changed sandbox')

    def test_real_reflink_shares_extents_without_sharing_writes(self):
        ioctl = snapshot.fcntl.ioctl
        def clone(*args):
            try:
                return ioctl(*args)
            except OSError as error:
                if error.errno in snapshot.UNSUPPORTED:
                    self.skipTest('Test filesystem does not support reflinks')
                raise
        with patch.object(snapshot.fcntl, 'ioctl', side_effect=clone), \
             patch.object(snapshot.shutil, 'copyfileobj', side_effect=AssertionError('unexpected full copy')):
            snapshot.copy_file(self.source, self.destination)
        self.assert_independent()

    def test_unsupported_clone_falls_back_to_independent_copy(self):
        for code in snapshot.UNSUPPORTED:
            with self.subTest(errno=code):
                self.source.write_bytes(b'original' * 1024)
                self.source.chmod(0o640)
                with patch.object(snapshot.fcntl, 'ioctl', side_effect=OSError(code, 'unsupported')):
                    snapshot.copy_file(self.source, self.destination)
                self.assert_independent()
                self.destination.unlink()

    def test_storage_failure_is_not_hidden_by_fallback(self):
        with patch.object(snapshot.fcntl, 'ioctl', side_effect=OSError(errno.ENOSPC, 'full')), \
             patch.object(snapshot.shutil, 'copyfileobj') as fallback:
            with self.assertRaises(OSError) as raised:
                snapshot.copy_file(self.source, self.destination)
            self.assertEqual(raised.exception.errno, errno.ENOSPC)
            fallback.assert_not_called()

    def test_existing_destination_is_not_truncated(self):
        self.destination.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            snapshot.copy_file(self.source, self.destination)
        self.assertEqual(self.destination.read_bytes(), b'keep')

    def test_tree_keeps_ignore_rules_and_dereferences_source_links(self):
        tree = self.root / 'mod'
        (tree / 'Textures').mkdir(parents=True)
        (tree / '.git').mkdir()
        (tree / '.git/config').write_text('private')
        (tree / 'Textures/image').symlink_to(self.source)
        snapshot.copy_tree(tree, self.destination, ignore=shutil.ignore_patterns('.git'))
        image = self.destination / 'Textures/image'
        self.assertFalse((self.destination / '.git').exists())
        self.assertFalse(image.is_symlink())
        image.write_bytes(b'sandbox write')
        self.assertEqual(self.source.read_bytes(), b'original' * 1024)
