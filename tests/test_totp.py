import unittest

from sudogate import totp

# RFC 6238 Appendix B: seed ASCII "12345678901234567890" (20 byte, SHA1), period 30, 8 cifre.
RFC_SECRET_B32 = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


class TestGenerate(unittest.TestCase):
    def test_vettori_rfc6238(self):
        for t, expected in RFC_VECTORS:
            self.assertEqual(
                totp.generate(RFC_SECRET_B32, at_time=t, digits=8, period=30),
                expected,
                f"fallito a T={t}",
            )

    def test_sei_cifre(self):
        code = totp.generate(RFC_SECRET_B32, at_time=59, digits=6, period=30)
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())


class TestVerify(unittest.TestCase):
    def test_codice_corretto(self):
        self.assertTrue(
            totp.verify(RFC_SECRET_B32, "94287082", at_time=59, digits=8, window=0)
        )

    def test_codice_sbagliato(self):
        self.assertFalse(
            totp.verify(RFC_SECRET_B32, "00000000", at_time=59, digits=8, window=0)
        )

    def test_finestra_accetta_periodo_precedente(self):
        # codice di T=59 accettato anche 30s dopo con window=1
        self.assertTrue(
            totp.verify(RFC_SECRET_B32, "94287082", at_time=89, digits=8, window=1)
        )

    def test_finestra_zero_rifiuta_periodo_precedente(self):
        self.assertFalse(
            totp.verify(RFC_SECRET_B32, "94287082", at_time=89, digits=8, window=0)
        )

    def test_codice_con_spazi_e_non_cifre(self):
        self.assertTrue(
            totp.verify(RFC_SECRET_B32, " 94287082 ", at_time=59, digits=8, window=0)
        )
        self.assertFalse(
            totp.verify(RFC_SECRET_B32, "abc", at_time=59, digits=8, window=0)
        )

    def test_codice_vuoto(self):
        self.assertFalse(totp.verify(RFC_SECRET_B32, "", at_time=59, digits=8))


class TestSecretAndUri(unittest.TestCase):
    def test_new_secret_e_base32_valido(self):
        secret = totp.new_secret()
        self.assertGreaterEqual(len(secret), 32)
        # deve generare e verificare in modo coerente con se stesso
        code = totp.generate(secret, at_time=59)
        self.assertTrue(totp.verify(secret, code, at_time=59, window=0))

    def test_provisioning_uri(self):
        uri = totp.provisioning_uri(RFC_SECRET_B32, label="home-server", issuer="claude-gate")
        self.assertTrue(uri.startswith("otpauth://totp/"))
        self.assertIn("claude-gate", uri)
        self.assertIn(f"secret={RFC_SECRET_B32}", uri)
        self.assertIn("issuer=claude-gate", uri)


if __name__ == "__main__":
    unittest.main()
