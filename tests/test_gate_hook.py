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
    def test_denies_direct_escalation(self):
        r = run("sudo apt update")
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_shim_does_not_trigger(self):
        r = run("sudogate apt update")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    def test_unrelated_command(self):
        r = run("ls -la")
        self.assertEqual(r.stdout.strip(), "")

    def test_word_as_argument(self):
        r = run('echo "sudo"')
        self.assertEqual(r.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
