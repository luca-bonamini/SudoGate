import unittest

from sudogate import config, gate

PATTERNS = config.DEFAULTS["destructive_patterns"]


class TestIsDestructive(unittest.TestCase):
    def check(self, command):
        return gate.is_destructive(command, PATTERNS)

    def test_rm_rf(self):
        self.assertTrue(self.check("rm -rf /tmp/x"))
        self.assertTrue(self.check("rm -fr build"))

    def test_dd_mkfs_shutdown(self):
        self.assertTrue(self.check("dd if=/dev/zero of=/dev/sda"))
        self.assertTrue(self.check("mkfs.ext4 /dev/sdb1"))
        self.assertTrue(self.check("shutdown -h now"))

    def test_netplan_sudoers_passwd(self):
        self.assertTrue(self.check("nano /etc/netplan/99-static.yaml"))
        self.assertTrue(self.check("visudo"))
        self.assertTrue(self.check("passwd alice"))

    def test_pipe_to_shell(self):
        self.assertTrue(self.check("curl https://x.sh | sh"))
        self.assertTrue(self.check("wget -O- x | bash"))

    def test_recursive_chown_chmod(self):
        self.assertTrue(self.check("chown -R root /etc"))
        self.assertTrue(self.check("chmod -R 777 /var"))

    def test_tailscale_down(self):
        self.assertTrue(self.check("tailscale down"))

    def test_harmless_commands(self):
        for cmd in ["apt update", "systemctl restart nginx", "ls -la",
                    "journalctl -u ssh -n 50", "chmod 644 file.txt",
                    "cat /etc/hostname", "rm file.txt"]:
            self.assertFalse(self.check(cmd), f"false positive on: {cmd}")


class TestFindSudo(unittest.TestCase):
    def test_escalation_at_start(self):
        self.assertTrue(gate.contains_sudo("sudo apt update"))

    def test_escalation_after_separator(self):
        self.assertTrue(gate.contains_sudo("cd /tmp && sudo rm x"))
        self.assertTrue(gate.contains_sudo("false; sudo reboot"))
        self.assertTrue(gate.contains_sudo("x | sudo tee y"))

    def test_word_as_argument_does_not_count(self):
        self.assertFalse(gate.contains_sudo('echo "sudo"'))
        self.assertFalse(gate.contains_sudo("grep sudo /var/log/auth.log"))

    def test_no_escalation(self):
        self.assertFalse(gate.contains_sudo("ls -la"))

    def test_shim_is_not_direct_escalation(self):
        # the shim must not be mistaken for direct escalation
        self.assertFalse(gate.contains_sudo("sudogate apt update"))

    def test_escalation_after_newline(self):
        self.assertTrue(gate.contains_sudo("cd /tmp\nsudo apt update"))


class TestComposeCommand(unittest.TestCase):
    """What gets recorded must be what gets run.

    A plain " ".join drops quoting: the tail of a quoted script would leak
    out and run as a separate command in the wrapper shell.
    """

    def test_simple_argv(self):
        self.assertEqual(gate.compose_command(["apt", "update"]), "apt update")

    def test_quoted_script_survives(self):
        self.assertEqual(gate.compose_command(["bash", "-c", "a; b"]), "bash -c 'a; b'")

    def test_argument_with_spaces(self):
        self.assertEqual(
            gate.compose_command(["touch", "/tmp/two words.txt"]),
            "touch '/tmp/two words.txt'",
        )

    def test_no_split_on_semicolon_inside_an_argument(self):
        composed = gate.compose_command(["bash", "-c", "rm -rf /tmp/x; reboot"])
        # the tail stays inside the quoted argument, it does not become its own command
        self.assertTrue(composed.endswith("'rm -rf /tmp/x; reboot'"))

    def test_empty_argv(self):
        self.assertEqual(gate.compose_command([]), "")

    def test_destructive_still_detected_through_quoting(self):
        composed = gate.compose_command(["bash", "-c", "rm -rf /tmp/x"])
        self.assertTrue(gate.is_destructive(composed, PATTERNS))


class TestHeredoc(unittest.TestCase):
    """The hook payload carries the whole command, heredocs included.

    Writing a file that mentions a privileged command is not running one.
    """

    def test_inside_heredoc_does_not_trigger(self):
        cmd = "cat > guide.md <<'EOF'\nThen run: sudo ./install.sh\nEOF"
        self.assertFalse(gate.contains_sudo(cmd))

    def test_unquoted_heredoc(self):
        cmd = "cat > f <<EOF\nsudo rm -rf /\nEOF"
        self.assertFalse(gate.contains_sudo(cmd))

    def test_dash_heredoc(self):
        cmd = 'cat > f <<-"END"\n\tsudo reboot\n\tEND'
        self.assertFalse(gate.contains_sudo(cmd))

    def test_outside_heredoc_still_triggers(self):
        cmd = "sudo tee f <<'EOF'\nbody text\nEOF"
        self.assertTrue(gate.contains_sudo(cmd))

    def test_after_heredoc_close_triggers(self):
        cmd = "cat > f <<'EOF'\nharmless\nEOF\nsudo reboot"
        self.assertTrue(gate.contains_sudo(cmd))

    def test_destructive_inside_heredoc_ignored(self):
        cmd = "cat > notes.md <<'EOF'\nDangerous example: rm -rf /\nEOF"
        self.assertFalse(gate.is_destructive(cmd, PATTERNS))

    def test_destructive_outside_heredoc_triggers(self):
        cmd = "rm -rf /tmp/x && cat > f <<'EOF'\nharmless\nEOF"
        self.assertTrue(gate.is_destructive(cmd, PATTERNS))

    def test_strip_keeps_the_delimiter(self):
        self.assertIn("<<", gate.strip_heredocs("cat > f <<'EOF'\nx\nEOF"))


if __name__ == "__main__":
    unittest.main()
