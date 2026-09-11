import unittest

from ctg import messages


class TestNotification(unittest.TestCase):
    def test_contiene_etichetta_e_testo(self):
        out = messages.notification("crm", "Claude ha bisogno del permesso di eseguire ls")
        self.assertIn("crm", out)
        self.assertIn("permesso", out)

    def test_etichetta_in_prima_riga(self):
        out = messages.notification("crm", "qualcosa")
        self.assertIn("crm", out.splitlines()[0])


class TestStop(unittest.TestCase):
    def test_con_riassunto(self):
        out = messages.stop("papayamarket", "Ho finito la migrazione")
        self.assertIn("papayamarket", out)
        self.assertIn("Ho finito la migrazione", out)

    def test_senza_riassunto(self):
        out = messages.stop("papayamarket", None)
        self.assertIn("papayamarket", out)
        self.assertTrue(out.strip())

    def test_riassunto_vuoto_trattato_come_assente(self):
        self.assertEqual(messages.stop("x", "   "), messages.stop("x", None))


if __name__ == "__main__":
    unittest.main()
