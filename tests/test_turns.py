import pathlib
import tempfile
import unittest

from ctg import turns


class TestShouldNotifyStop(unittest.TestCase):
    def test_turno_breve_resta_muto(self):
        self.assertFalse(turns.should_notify_stop(10.0, 120, from_telegram=False))

    def test_turno_lungo_notifica(self):
        self.assertTrue(turns.should_notify_stop(130.0, 120, from_telegram=False))

    def test_esattamente_la_soglia_notifica(self):
        self.assertTrue(turns.should_notify_stop(120.0, 120, from_telegram=False))

    def test_da_telegram_notifica_sempre(self):
        self.assertTrue(turns.should_notify_stop(1.0, 120, from_telegram=True))

    def test_senza_t0_e_senza_telegram_resta_muto(self):
        self.assertFalse(turns.should_notify_stop(None, 120, from_telegram=False))

    def test_senza_t0_ma_da_telegram_notifica(self):
        self.assertTrue(turns.should_notify_stop(None, 120, from_telegram=True))


class TestTurnClock(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self._tmp.name) / "turns.json"
        self.addCleanup(self._tmp.cleanup)

    def test_elapsed_dopo_mark(self):
        clock = turns.TurnClock(self.path)
        clock.mark_prompt("s1", now=1000.0)
        self.assertEqual(clock.elapsed("s1", now=1130.0), 130.0)

    def test_sessione_sconosciuta(self):
        self.assertIsNone(turns.TurnClock(self.path).elapsed("ignota", now=1.0))

    def test_lo_stato_sopravvive_a_una_nuova_istanza(self):
        turns.TurnClock(self.path).mark_prompt("s1", now=1000.0)
        self.assertEqual(turns.TurnClock(self.path).elapsed("s1", now=1005.0), 5.0)

    def test_sessioni_indipendenti(self):
        clock = turns.TurnClock(self.path)
        clock.mark_prompt("s1", now=1000.0)
        clock.mark_prompt("s2", now=1100.0)
        self.assertEqual(clock.elapsed("s1", now=1200.0), 200.0)
        self.assertEqual(clock.elapsed("s2", now=1200.0), 100.0)

    def test_clear_dimentica_la_sessione(self):
        clock = turns.TurnClock(self.path)
        clock.mark_prompt("s1", now=1000.0)
        clock.clear("s1")
        self.assertIsNone(clock.elapsed("s1", now=1200.0))

    def test_file_corrotto_non_solleva(self):
        self.path.write_text("{rotto")
        clock = turns.TurnClock(self.path)
        self.assertIsNone(clock.elapsed("s1", now=1.0))
        clock.mark_prompt("s1", now=1.0)
        self.assertEqual(clock.elapsed("s1", now=2.0), 1.0)


if __name__ == "__main__":
    unittest.main()
