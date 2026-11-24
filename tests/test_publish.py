"""tools/publish.py: private names are replaced whole, aliases stay fixed, and the check finds the
shapes of personal data (made-up names only)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import publish  # noqa: E402


class PublishTests(unittest.TestCase):
    def test_scrub_whole_names_longest_first(self):
        al = {"Widget": "Part A", "Widget Qx7": "Part B"}
        self.assertEqual(publish.scrub("Widget Qx7.SLDPRT and Widget.SLDPRT, not Widgets", al, []),
                         "Part B.SLDPRT and Part A.SLDPRT, not Widgets")

    def test_scrub_roots(self):
        self.assertEqual(publish.scrub(r"C:\Work\repo\sw2sc\x.py", {}, [(r"C:\Work\repo", "<repo>")]), r"<repo>\sw2sc\x.py")

    def test_next_alias(self):
        self.assertEqual(publish.next_alias({"Part A", "Part B"}), "Part C")
        self.assertEqual(publish.next_alias({f"Part {chr(65 + k)}" for k in range(26)}), "Part AA")

    def test_find_new_needs_the_extension(self):
        names = {"gizmo holder": ("Gizmo Holder", True), "base": ("Base", True), "rocker arm": ("Rocker Arm", False)}
        self.assertEqual(publish.find_new("| Gizmo Holder.SLDPRT | ok |\nthe Base plate", names, {}), ["Gizmo Holder"])
        # the longest known name decides: a public sample named like a private name's tail is not it
        self.assertEqual(publish.find_new("the Rocker Arm.SLDPRT", names, {"arm": "Part B"}), [])
        self.assertEqual(publish.find_new("Gizmo Holder.sldprt", names, {"gizmo holder": "Part A"}), [])

    def test_check_shapes(self):
        # built from pieces, so this file passes the check itself
        users, home, cloud = "\\Us" + "ers\\", "/ho" + "me/", "\\Drop" + "box\\"
        text = "\n".join(["C:" + users + r"someone\Desktop\a.step", home + "someone/x", "D:" + cloud + "Projects",
                          "mail me" + "@mail.test.org", "ok noreply@anthropic.com", "C:" + users + r"Public\x", "ok"])
        found = [(i, w) for i, w, _f in publish.check_text(text, [])]
        self.assertEqual([i for i, _w in found], [1, 2, 3, 4])

    def test_check_terms_and_names(self):
        found = publish.check_text("by Alexandra\nAlexandrite\nGizmo Holder.SLDPRT", ["Alexandra"], {"gizmo holder": ("Gizmo Holder", True)})
        self.assertEqual([(i, w) for i, w, _f in found], [(1, "a private term"), (3, "a private file name")])


if __name__ == "__main__":
    unittest.main()
