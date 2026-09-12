import json
import os
import pathlib
import subprocess
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
HOOK = REPO / "bin" / "sudogate-hook"


def run(command):
    env = dict(os.environ, PYTHONPATH=str(REPO))
    payload = json.dumps({"tool_input": {"command": command}})
    return subprocess.run([str(HOOK)], input=payload, capture_output=True, text=True, env=env, timeout=10)


class TestGateHook(unittest.TestCase):
    def test_nega_sudo_diretto(self):
        r = run("sudo apt update")
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_claude_sudo_non_scatta(self):
        r = run("sudogate apt update")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    def test_comando_senza_sudo(self):
        r = run("ls -la")
        self.assertEqual(r.stdout.strip(), "")

    def test_sudo_come_argomento(self):
        r = run('echo "sudo"')
        self.assertEqual(r.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
