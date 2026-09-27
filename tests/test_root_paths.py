"""Root must trust only root-owned locations.

Two holes this pins down:
  * the library search path fell back to ~/.local/lib/sudogate, so root
    imported code the invoking user could rewrite;
  * seed, patterns and policy paths came from os.environ, so anything able
    to set the environment of the sudo call could point them at its own files.

Both are closed the same way: when euid is 0 the paths are constants. Below
root the overrides stay, because a process with no privilege to escalate has
nothing to gain from them, and the test suite needs them.
"""
import ast
import pathlib
import unittest

from sudogate import wrapper

REPO = pathlib.Path(__file__).resolve().parent.parent
ENTRY = REPO / "bin" / "sudogate-run"

HOSTILE = {
    "SUDOGATE_SEED": "/home/user/seed",
    "SUDOGATE_PATTERNS": "/home/user/patterns",
    "SUDOGATE_TOTP_ALWAYS": "/home/user/absent",
    "SUDOGATE_AUDIT": "/home/user/audit.log",
    "SUDOGATE_STATE_HOME": "/home/user/state",
}
HOME = pathlib.Path("/home/user")


class TestRootIgnoresEnvironment(unittest.TestCase):
    def test_root_uses_fixed_paths(self):
        paths = wrapper.resolve_paths(0, HOSTILE, HOME)
        self.assertEqual(paths["seed"], pathlib.Path("/etc/sudogate/seed"))
        self.assertEqual(paths["patterns"], pathlib.Path("/etc/sudogate/destructive.patterns"))
        self.assertEqual(paths["totp_always"], pathlib.Path("/etc/sudogate/totp_always"))
        self.assertEqual(paths["audit"], pathlib.Path("/var/log/sudogate/audit.log"))

    def test_root_still_reads_state_from_the_invoking_user(self):
        # The state file is the user's by design; only its location is fixed.
        paths = wrapper.resolve_paths(0, HOSTILE, HOME)
        self.assertEqual(paths["state_home"], HOME / ".config" / "sudogate")

    def test_below_root_the_overrides_apply(self):
        paths = wrapper.resolve_paths(1000, HOSTILE, HOME)
        self.assertEqual(paths["seed"], pathlib.Path("/home/user/seed"))
        self.assertEqual(paths["state_home"], pathlib.Path("/home/user/state"))

    def test_below_root_falls_back_to_the_same_constants(self):
        paths = wrapper.resolve_paths(1000, {}, HOME)
        self.assertEqual(paths["seed"], pathlib.Path("/etc/sudogate/seed"))


class TestRootLibrarySearchPath(unittest.TestCase):
    def test_entry_point_never_imports_from_the_user_home(self):
        # String literals only: the comment above the fix names the old path
        # on purpose, and prose is not a search path.
        literals = [
            node.value
            for node in ast.walk(ast.parse(ENTRY.read_text()))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        offenders = [lit for lit in literals if ".local" in lit and "\n" not in lit]
        self.assertEqual(offenders, [], "root must not import from the user's home")

    def test_entry_point_pins_the_root_owned_library(self):
        self.assertIn("/usr/local/lib/sudogate", ENTRY.read_text())
