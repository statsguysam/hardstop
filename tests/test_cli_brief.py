import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hardstop.cli import read_brief_file


class BriefFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / 'brief.txt'

    def test_utf8_file_preserves_content_and_normalizes_line_endings(self):
        self.path.write_bytes('Keep the résumé.\r\nFit within 90 seconds.\rDone.\n'.encode())
        self.assertEqual(read_brief_file(self.path), 'Keep the résumé.\nFit within 90 seconds.\nDone.\n')

    def test_fifo_is_rejected_without_waiting_for_a_writer(self):
        os.mkfifo(self.path)
        with self.assertRaisesRegex(ValueError, 'regular file'):
            read_brief_file(self.path)

    def test_symbolic_link_is_rejected(self):
        target = self.root / 'target.txt'
        target.write_text('Brief')
        self.path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'regular file'):
            read_brief_file(self.path)

    def test_size_boundary_is_enforced(self):
        self.path.write_bytes(b'a' * 80000)
        self.assertEqual(len(read_brief_file(self.path)), 80000)
        self.path.write_bytes(b'a' * 80001)
        with self.assertRaisesRegex(ValueError, '80,000 bytes'):
            read_brief_file(self.path)

    def test_read_remains_bounded_if_stat_underreports_the_file(self):
        self.path.write_bytes(b'a' * 80001)
        small = self.root / 'small.txt'
        small.write_bytes(b'brief')
        with patch('hardstop.cli.os.fstat', return_value=small.stat()):
            with self.assertRaisesRegex(ValueError, '80,000 bytes'):
                read_brief_file(self.path)

    def test_invalid_utf8_is_reported_before_registration(self):
        self.path.write_bytes(b'\xff\xfe')
        with self.assertRaisesRegex(ValueError, 'UTF-8'):
            read_brief_file(self.path)


if __name__ == '__main__':
    unittest.main()
