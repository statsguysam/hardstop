"""Check the static result inspector against the published release receipts."""
from pathlib import Path
import shutil
import subprocess
import unittest


class RecordedResultTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required for inspector rendering checks")
    def test_recorded_cases_validate_video_identity_and_safe_failure(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [shutil.which("node"), str(root / "tests/explore_render_test.js")],
            cwd=root, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
