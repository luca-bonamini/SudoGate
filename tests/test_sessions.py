import subprocess
import unittest

from ctg import sessions


def fake_runner(stdout, returncode=0):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")

    return run


TMUX = {
    "rc-maybecompany": "/home/luca/Project/MayBeCompany",
    "rc-crm": "/home/luca/Project/MayBeCompany/CRM",
    "rc-personal": "/home/luca/Project/personal",
}


class TestTmuxSessions(unittest.TestCase):
    def test_legge_nome_e_directory(self):
        runner = fake_runner(
            "rc-crm\t/home/luca/Project/MayBeCompany/CRM\n"
            "rc-personal\t/home/luca/Project/personal\n"
        )
        self.assertEqual(
            sessions.tmux_sessions(runner),
            {
                "rc-crm": "/home/luca/Project/MayBeCompany/CRM",
                "rc-personal": "/home/luca/Project/personal",
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
            sessions.label_for_cwd("/home/luca/Project/MayBeCompany", TMUX),
            "maybecompany",
        )

    def test_sottodirectory(self):
        self.assertEqual(
            sessions.label_for_cwd("/home/luca/Project/personal/claude-telegram", TMUX),
            "personal",
        )

    def test_vince_il_prefisso_piu_lungo(self):
        self.assertEqual(
            sessions.label_for_cwd("/home/luca/Project/MayBeCompany/CRM/src", TMUX),
            "crm",
        )

    def test_nessuna_sessione_usa_il_basename(self):
        self.assertEqual(sessions.label_for_cwd("/srv/qualcosa", TMUX), "qualcosa")

    def test_senza_tmux_usa_il_basename(self):
        self.assertEqual(sessions.label_for_cwd("/home/luca/Project/personal", {}), "personal")

    def test_non_confonde_prefissi_parziali(self):
        tmux = {"rc-papayamarket": "/home/luca/Project/MayBeCompany/papaya"}
        self.assertEqual(
            sessions.label_for_cwd("/home/luca/Project/MayBeCompany/papayaShopper", tmux),
            "papayaShopper",
        )


if __name__ == "__main__":
    unittest.main()
