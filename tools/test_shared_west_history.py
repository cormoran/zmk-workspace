"""Tests for local shared West task history."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import record_shared_west_history as history


class SharedWestHistoryTest(unittest.TestCase):
    def test_profile_and_nested_branch_append(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "projects" / "sample"
            source.mkdir(parents=True)
            for command in (
                ("git", "init", "-q"),
                ("git", "config", "user.name", "History Test"),
                ("git", "config", "user.email", "history@example.invalid"),
                ("git", "commit", "--allow-empty", "-qm", "seed"),
            ):
                subprocess.run(command, cwd=source, check=True)
            profile = root / "ws" / "example"
            metadata = profile / "workspace-config" / "profile.json"
            metadata.parent.mkdir(parents=True)
            metadata.write_text(json.dumps({"zephyr_sha": "abc", "zmk_branch": "main"}))
            target = profile / "wt-sample" / "issue" / "feature"
            target.parent.mkdir(parents=True)
            subprocess.run(("git", "worktree", "add", "-qb", "issue/feature", str(target)), cwd=source, check=True)
            with patch.object(history, "WORKSPACES", root / "ws"):
                profile_log = history.record_profile(profile, source, "issue 42: fix split")
                history.record_profile(profile, source, "issue 43: follow up")
                worktree_log = history.record_worktree(profile, source, "issue/feature", "issue 42: fix split")
                with self.assertRaises(ValueError):
                    history.record_worktree(profile, source, "../escape", "bad")
            profile_entries = [json.loads(line) for line in profile_log.read_text().splitlines()]
            self.assertEqual([entry["task"] for entry in profile_entries],
                             ["issue 42: fix split", "issue 43: follow up"])
            self.assertEqual(worktree_log, profile / "sample" / "issue" / "feature_log.jsonl")
            worktree_entries = [json.loads(line) for line in worktree_log.read_text().splitlines()]
            self.assertEqual(len(worktree_entries), 1)
            self.assertEqual(worktree_entries[0]["branch"], "issue/feature")
            self.assertEqual(worktree_entries[0]["worktree"], str(target))


if __name__ == "__main__":
    unittest.main()
