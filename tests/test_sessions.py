import subprocess
import unittest

from sudogate import sessions


def fake_runner(stdout, returncode=0):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")

    return run


TMUX = {
    "rc-maybecompany": "/home/dev/Projects/acme",
    "rc-crm": "/home/dev/Projects/acme/CRM",
    "rc-personal": "/home/dev/Projects/personal",
}


class TestTmuxSessions(unittest.TestCase):
    def test_reads_name_and_directory(self):
        runner = fake_runner(
            "rc-crm\t/home/dev/Projects/acme/CRM\n"
            "rc-personal\t/home/dev/Projects/personal\n"
        )
        self.assertEqual(
            sessions.tmux_sessions(runner),
            {
                "rc-crm": "/home/dev/Projects/acme/CRM",
                "rc-personal": "/home/dev/Projects/personal",
            },
        )

    def test_tmux_missing_or_no_server(self):
        self.assertEqual(sessions.tmux_sessions(fake_runner("", returncode=1)), {})

    def test_malformed_line_ignored(self):
        runner = fake_runner("senza-tab\nrc-crm\t/tmp/crm\n")
        self.assertEqual(sessions.tmux_sessions(runner), {"rc-crm": "/tmp/crm"})


class TestLabelForCwd(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(
            sessions.label_for_cwd("/home/dev/Projects/acme", TMUX),
            "maybecompany",
        )

    def test_subdirectory(self):
        self.assertEqual(
            sessions.label_for_cwd("/home/dev/Projects/personal/claude-telegram", TMUX),
            "personal",
        )

    def test_longest_prefix_wins(self):
        self.assertEqual(
            sessions.label_for_cwd("/home/dev/Projects/acme/CRM/src", TMUX),
            "crm",
        )

    def test_no_session_falls_back_to_basename(self):
        self.assertEqual(sessions.label_for_cwd("/srv/qualcosa", TMUX), "qualcosa")

    def test_without_tmux_uses_basename(self):
        self.assertEqual(sessions.label_for_cwd("/home/dev/Projects/personal", {}), "personal")

    def test_partial_prefix_is_not_a_parent(self):
        tmux = {"rc-papayamarket": "/home/dev/Projects/acme/papaya"}
        self.assertEqual(
            sessions.label_for_cwd("/home/dev/Projects/acme/papayaShopper", tmux),
            "papayaShopper",
        )


if __name__ == "__main__":
    unittest.main()
