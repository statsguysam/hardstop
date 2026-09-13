"""Run the offline browser-rendering contract checks when Node is available."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ReviewInterfaceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required for UI rendering checks")
    def test_recorded_interpretations_and_failure_states_render_safely(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([shutil.which("node"), str(root / "tests/ui_render_test.js")],
                                cwd=root, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
