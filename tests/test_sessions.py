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
    def test_legge_nome_e_directory(self):
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

    def test_tmux_assente_o_senza_server(self):
        self.assertEqual(sessions.tmux_sessions(fake_runner("", returncode=1)), {})

    def test_riga_malformata_ignorata(self):
        runner = fake_runner("senza-tab\nrc-crm\t/tmp/crm\n")
        self.assertEqual(sessions.tmux_sessions(runner), {"rc-crm": "/tmp/crm"})


class TestLabelForCwd(unittest.TestCase):
    def test_match_esatto(self):
        self.assertEqual(
            sessions.label_for_cwd("/home/dev/Projects/acme", TMUX),
            "maybecompany",
        )

    def test_sottodirectory(self):
        self.assertEqual(
            sessions.label_for_cwd("/home/dev/Projects/personal/claude-telegram", TMUX),
            "personal",
        )

    def test_vince_il_prefisso_piu_lungo(self):
        self.assertEqual(
            sessions.label_for_cwd("/home/dev/Projects/acme/CRM/src", TMUX),
            "crm",
        )

    def test_nessuna_sessione_usa_il_basename(self):
        self.assertEqual(sessions.label_for_cwd("/srv/qualcosa", TMUX), "qualcosa")

    def test_senza_tmux_usa_il_basename(self):
        self.assertEqual(sessions.label_for_cwd("/home/dev/Projects/personal", {}), "personal")

    def test_non_confonde_prefissi_parziali(self):
        tmux = {"rc-papayamarket": "/home/dev/Projects/acme/papaya"}
        self.assertEqual(
            sessions.label_for_cwd("/home/dev/Projects/acme/papayaShopper", tmux),
            "papayaShopper",
        )


if __name__ == "__main__":
    unittest.main()
