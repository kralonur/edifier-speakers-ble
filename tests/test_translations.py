"""Translation tests: every translation key used in code must be defined."""

from pathlib import Path
import json
import re
import unittest

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "edifier_ble"


class ExceptionTranslationTests(unittest.TestCase):
    def setUp(self):
        self.strings = json.loads((COMPONENT / "strings.json").read_text())
        self.english = json.loads((COMPONENT / "translations" / "en.json").read_text())

    def test_both_translation_files_agree(self):
        """Home Assistant reads translations/en.json; strings.json is the source."""
        self.assertEqual(self.strings["exceptions"], self.english["exceptions"])

    def test_every_translation_key_used_in_code_exists(self):
        used = {}
        for path in COMPONENT.rglob("*.py"):
            for key in re.findall(r'translation_key="([^"]+)"', path.read_text()):
                used.setdefault(key, []).append(path.name)
        self.assertTrue(used, "no translation keys found, did the pattern change?")
        for key, files in used.items():
            with self.subTest(key=key, files=files):
                self.assertIn(key, self.strings["exceptions"], f"{key} used in {files} is not defined")

    def test_no_unused_exception_translations(self):
        used = set()
        for path in COMPONENT.rglob("*.py"):
            used.update(re.findall(r'translation_key="([^"]+)"', path.read_text()))
        for key in self.strings["exceptions"]:
            with self.subTest(key=key):
                self.assertIn(key, used, f"{key} is defined but never raised")

    def test_placeholders_match_the_translations(self):
        """A message may only use placeholders that its callers provide."""
        callers = {}
        for path in COMPONENT.rglob("*.py"):
            text = path.read_text()
            for block in re.findall(r"translation_key=\"([^\"]+)\",\s*\n\s*translation_placeholders=\{([^}]*)\}", text):
                key, body = block
                callers[key] = set(re.findall(r'"([^"]+)":', body))
        for key, message in self.strings["exceptions"].items():
            placeholders = set(re.findall(r"\{(\w+)\}", message["message"]))
            with self.subTest(key=key):
                if placeholders:
                    self.assertIn(key, callers, f"{key} has placeholders but no caller passes them")
                    self.assertTrue(placeholders <= callers[key],
                                    f"{key} uses {placeholders - callers[key]} that no caller provides")


if __name__ == "__main__":
    unittest.main()
