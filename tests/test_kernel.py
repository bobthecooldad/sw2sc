import os
import tempfile
import unittest

from sw2sc import verify


class VersionTests(unittest.TestCase):
    def test_rebuild_budget_is_five_minutes(self):
        self.assertEqual(verify.TIME_BUDGET, 300)

    def test_a_nightly_suffix_reads_as_its_release(self):
        # the daily build: the suffix must not throw the parse away (an older release would win)
        self.assertEqual(verify._parse_version("solidcraft-cli 0.47.0-nightly.20261123.157.1"), (0, 47, 0))

    def test_a_release(self):
        self.assertEqual(verify._parse_version("solidcraft-cli 0.44.1"), (0, 44, 1))

    def test_no_numbers_at_all(self):
        self.assertEqual(verify._parse_version("solidcraft-cli unknown"), ())


class SignatureTests(unittest.TestCase):
    def ev(self, volume=100.0, area=200.0, lo=(0, 0, 0), hi=(10, 10, 10), errors=()):
        return {"volume": volume, "area": area, "lo": list(lo), "hi": list(hi), "errors": list(errors)}

    def test_too_much_material_points_at_an_island_or_a_cut(self):
        s = verify.mismatch_signature(self.ev(volume=112.0), self.ev())
        self.assertIn("too much material", s)
        self.assertIn("cut", s)

    def test_too_little_material_points_at_a_missing_feature(self):
        self.assertIn("too little material", verify.mismatch_signature(self.ev(volume=80.0), self.ev()))

    def test_same_volume_and_area_off_points_at_a_fillet(self):
        s = verify.mismatch_signature(self.ev(area=260.0), self.ev())
        self.assertIn("fillet", s)

    def test_a_shifted_box_is_named_by_axis(self):
        s = verify.mismatch_signature(self.ev(lo=(5, 0, 0)), self.ev())
        self.assertIn("box", s)

    def test_a_design_that_does_not_build_says_what_stopped_it(self):
        s = verify.mismatch_signature(self.ev(errors=["not supported yet: the fillet is larger"]), self.ev())
        self.assertIn("does not build", s)
        self.assertIn("the fillet is larger", s)

    def test_nothing_built(self):
        self.assertIn("no build", verify.mismatch_signature(None, self.ev()))


class CheckoutTests(unittest.TestCase):
    def checkout(self):
        tmp = tempfile.mkdtemp(prefix="sw2sc-k-")
        with open(os.path.join(tmp, "Cargo.toml"), "w", encoding="utf-8") as fh:
            fh.write('[workspace.package]\nversion = "0.99.0"\nedition = "2024"\n')
        os.makedirs(os.path.join(tmp, "target", "release"))
        cli = os.path.join(tmp, "target", "release", "solidcraft-cli.exe")
        open(cli, "w").close()
        return tmp, cli

    def test_the_checkout_a_cli_sits_in_is_found(self):
        tmp, cli = self.checkout()
        self.assertEqual(verify.checkout_dir(cli), tmp)
        self.assertEqual(verify.checkout_version(tmp), (0, 99, 0))

    def test_an_unreadable_cli_is_stale_against_its_checkout(self):
        tmp, cli = self.checkout()
        status = verify.kernel_status(cli)
        self.assertTrue(status["stale"])
        line = verify.kernel_line(status)
        self.assertIn("0.99.0", line)           # the checkout's version
        self.assertIn("STALE", line)

    def test_a_checkout_build_outranks_an_installed_copy_at_the_same_version(self):
        # the app updates itself: same version, not the checkout's build (B-022)
        tmp, built = self.checkout()
        with tempfile.TemporaryDirectory() as other:
            installed = os.path.join(other, "solidcraft-cli.exe")
            open(installed, "w").close()
            self.assertGreater(verify._cli_rank(built), verify._cli_rank(installed))

    def test_an_installed_copy_is_stale_even_at_the_checkout_version(self):
        from unittest import mock
        tmp, _built = self.checkout()
        with tempfile.TemporaryDirectory() as other:
            installed = os.path.join(other, "solidcraft-cli.exe")
            open(installed, "w").close()
            with mock.patch.object(verify, "checkout_dir", return_value=tmp):
                status = verify.kernel_status(installed)
                self.assertTrue(status["stale"])
                self.assertIn("installed copy", status["why"])

    def test_no_checkout_leaves_a_reason_but_no_warning(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            cli = os.path.join(tmp, "solidcraft-cli.exe")
            open(cli, "w").close()
            with mock.patch.object(verify, "checkout_dir", return_value=None):
                status = verify.kernel_status(cli)
                self.assertFalse(status["stale"])
                self.assertIn("no SolidCraft checkout", status["why"])


if __name__ == "__main__":
    unittest.main()
