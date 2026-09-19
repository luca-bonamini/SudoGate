"""The root wrapper must not trust anything the calling user can write.

These cover the import path and the policy paths, not the authorisation logic:
what the wrapper decides is only worth as much as where it loaded the deciding
code from.
"""
import importlib.util
import os
import pathlib
import stat
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
WRAPPER = REPO / "bin" / "sudogate-run"


def _load_wrapper_module():
    spec = importlib.util.spec_from_loader(
        "sudogate_run_entry", loader=None, origin=str(WRAPPER)
    )
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(WRAPPER)
    exec(compile(WRAPPER.read_text(), str(WRAPPER), "exec"), module.__dict__)
    return module


class TestImportPath(unittest.TestCase):
    def setUp(self):
        self.source = WRAPPER.read_text()

    def test_library_directory_is_a_fixed_root_owned_path(self):
        self.assertIn('LIB_DIR = pathlib.Path("/usr/local/lib/sudogate")', self.source)

    def test_no_fallback_into_the_users_home(self):
        """The wrapper runs as root; a library under ~ is attacker-controlled."""
        self.assertNotIn('".local"', self.source)
        self.assertNotIn(".local/lib/sudogate", self.source)

    def test_the_installer_puts_the_library_where_the_wrapper_looks(self):
        installer = (REPO / "install-root.sh").read_text()
        self.assertIn("/usr/local/lib/sudogate", installer)
        self.assertIn("chown -R root:root /usr/local/lib/sudogate", installer)

    def test_policy_paths_are_constants_in_the_root_branch(self):
        """As root, no path may come from the environment.

        env_reset in sudoers is outside this program; the guarantee has to be
        in it.
        """
        root_branch = self.source.split("if IS_ROOT:")[2].split("else:")[0]
        self.assertNotIn("os.environ", root_branch)
        for name in ("SUDOGATE_PATTERNS", "SUDOGATE_SEED", "SUDOGATE_STATE_HOME",
                     "SUDOGATE_AUDIT", "SUDOGATE_TOTP_ALWAYS"):
            self.assertNotIn(name, root_branch)


class TestRootOnlyAssertion(unittest.TestCase):
    def setUp(self):
        self.module = _load_wrapper_module()
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    @unittest.skipIf(os.geteuid() == 0, "needs a directory not owned by root")
    def test_a_directory_owned_by_the_user_is_refused(self):
        with self.assertRaises(SystemExit):
            self.module._assert_root_only(self.dir)

    def test_a_missing_path_is_refused(self):
        with self.assertRaises(SystemExit):
            self.module._assert_root_only(self.dir / "absent")

    @unittest.skipUnless(pathlib.Path("/usr/bin").is_dir(), "no /usr/bin")
    def test_a_root_owned_system_directory_passes(self):
        info = pathlib.Path("/usr/bin").stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            self.skipTest("/usr/bin is not root-only on this machine")
        self.module._assert_root_only(pathlib.Path("/usr/bin"))

    @unittest.skipUnless(os.geteuid() == 0, "only root can build the fixture")
    def test_a_group_writable_component_is_refused(self):
        lax = self.dir / "lax"
        lax.mkdir()
        os.chown(lax, 0, 0)
        lax.chmod(0o775)
        with self.assertRaises(SystemExit):
            self.module._assert_root_only(lax)

    @unittest.skipIf(os.geteuid() == 0, "needs a file not owned by root")
    def test_a_user_writable_source_file_is_refused(self):
        lib = self.dir / "lib"
        (lib / "sudogate").mkdir(parents=True)
        (lib / "sudogate" / "__init__.py").write_text("")
        with self.assertRaises(SystemExit):
            self.module._assert_library_root_only(lib)


class TestWrapperMode(unittest.TestCase):
    def test_wrapper_is_executable(self):
        self.assertTrue(WRAPPER.stat().st_mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
