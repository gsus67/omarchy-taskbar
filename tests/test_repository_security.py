"""Repository and CI guards for audited security policy."""
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github/workflows/ci.yml").read_text()


class RepositorySecurityTest(unittest.TestCase):
    def test_session_fix_note_is_not_shipped(self):
        self.assertFalse((ROOT / "FIX-WINDOWS-PINS.md").exists())

    def test_every_ci_job_has_timeout_without_renaming_required_jobs(self):
        expected_names = {
            "test": "Tests",
            "native-runtime": "Native security and runtime",
            "codeql": "CodeQL (actions)",
            "shellcheck": "ShellCheck (embedded commands)",
            "zizmor": "zizmor (workflow security)",
        }
        jobs_text = WORKFLOW.split("jobs:\n", 1)[1]
        starts = list(re.finditer(r"(?m)^  ([a-z][a-z0-9-]*):\n", jobs_text))
        jobs = {}
        for index, match in enumerate(starts):
            end = starts[index + 1].start() if index + 1 < len(starts) else len(jobs_text)
            jobs[match.group(1)] = jobs_text[match.end():end]
        self.assertEqual(set(jobs), set(expected_names))
        for job, display_name in expected_names.items():
            with self.subTest(job=job):
                self.assertIn(f"    name: {display_name}\n", jobs[job])
                self.assertRegex(jobs[job], r"(?m)^    timeout-minutes: [1-9][0-9]*$")


if __name__ == "__main__":
    unittest.main()
