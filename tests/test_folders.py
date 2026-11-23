import json
import os
import tempfile
import unittest

from sw2sc import folders, vault


def make_vault(d, items):
    with open(os.path.join(d, vault.INDEX), "w", encoding="utf-8") as fh:
        json.dump({"format": "sw2sc-vault/1", "source": "proj", "items": items}, fh)


class FolderTests(unittest.TestCase):
    def test_folders_sort_designs_without_moving_files(self):
        with tempfile.TemporaryDirectory() as d:
            make_vault(d, {"a.sldprt.solidcraft": {"source": "a.SLDPRT"},
                           "sub/b.sldprt.solidcraft": {"source": "sub/b.SLDPRT"}})
            v = folders.view(d)
            self.assertEqual(v["folders"], ["sub"])  # where its SolidWorks file came from
            self.assertEqual(v["items"]["a.sldprt.solidcraft"], "")
            self.assertEqual(folders.create(d, "me", " Bobbin / Idlers "), "Bobbin/Idlers")
            self.assertEqual(folders.move(d, "me", ["a.sldprt.solidcraft", "nope"], "Bobbin/Idlers"), 1)
            self.assertEqual(folders.view(d)["items"]["a.sldprt.solidcraft"], "Bobbin/Idlers")
            folders.rename(d, "me", "Bobbin", "Drive")
            v = folders.view(d)
            self.assertEqual(v["items"]["a.sldprt.solidcraft"], "Drive/Idlers")
            self.assertNotIn("Bobbin", v["folders"])
            self.assertEqual(folders.remove(d, "me", "Drive"), 1)
            v = folders.view(d)
            self.assertEqual(v["items"]["a.sldprt.solidcraft"], "")
            self.assertEqual(v["items"]["sub/b.sldprt.solidcraft"], "sub")  # other folders untouched
            self.assertEqual(sorted(os.listdir(d)), sorted([vault.INDEX, folders.FOLDERS]))

    def test_bad_folder_names_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            make_vault(d, {})
            for bad in ("", "..", "a/../b", "x:y", "a?"):
                with self.assertRaises(folders.FolderError):
                    folders.create(d, "me", bad)
            folders.create(d, "me", "A")
            with self.assertRaises(folders.FolderError):
                folders.create(d, "me", "A")
            with self.assertRaises(folders.FolderError):
                folders.rename(d, "me", "A", "A/B")


class SourceCheckTests(unittest.TestCase):
    def test_import_guard(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as v:
            open(os.path.join(src, "a.SLDPRT"), "wb").close()
            self.assertEqual(vault.check_source(src, v), [])
            for i in range(vault.MANY_OTHER):
                open(os.path.join(src, f"n{i}.txt"), "wb").close()
            self.assertTrue(any("Only 1 of" in w for w in vault.check_source(src, v)))
            make_vault(v, {"x.sldprt.solidcraft": {}})  # a vault of another project
            self.assertTrue(any("replaces them" in w for w in vault.check_source(src, v)))
            self.assertTrue(vault.check_source(os.path.expanduser("~"), v)[0].endswith("into the vault."))


if __name__ == "__main__":
    unittest.main()
