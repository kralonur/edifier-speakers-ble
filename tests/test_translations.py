"""Translation tests: every translation key used in code must be defined."""

from pathlib import Path
import json
import re
import unittest

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "edifier_ble"


SECTIONS = ("exceptions", "issues")


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.strings = json.loads((COMPONENT / "strings.json").read_text())
        self.english = json.loads((COMPONENT / "translations" / "en.json").read_text())
        self.defined = {key for section in SECTIONS for key in self.strings.get(section, {})}

    def used_keys(self) -> dict[str, list[str]]:
        used: dict[str, list[str]] = {}
        for path in COMPONENT.rglob("*.py"):
            for key in re.findall(r'translation_key="([^"]+)"', path.read_text()):
                used.setdefault(key, []).append(path.name)
        return used

    def caller_placeholders(self) -> dict[str, set[str]]:
        callers: dict[str, set[str]] = {}
        for path in COMPONENT.rglob("*.py"):
            text = path.read_text()
            for key, body in re.findall(
                r'translation_key="([^"]+)",\s*\n\s*[^\n]*translation_placeholders=\{([^}]*)\}', text
            ):
                callers[key] = set(re.findall(r'"([^"]+)":', body))
        return callers

    def test_both_translation_files_agree(self):
        """Home Assistant reads translations/en.json; strings.json is the source."""
        for section in SECTIONS:
            with self.subTest(section=section):
                self.assertEqual(self.strings[section], self.english[section])

    def test_every_translation_key_used_in_code_exists(self):
        used = self.used_keys()
        self.assertTrue(used, "no translation keys found, did the pattern change?")
        for key, files in used.items():
            with self.subTest(key=key, files=files):
                self.assertIn(key, self.defined, f"{key} used in {files} is not defined")

    def test_no_unused_translation(self):
        used = set(self.used_keys())
        for key in self.defined:
            with self.subTest(key=key):
                self.assertIn(key, used, f"{key} is defined but never raised")

    def test_placeholders_match_the_translations(self):
        """A message may only use placeholders that its callers provide."""
        callers = self.caller_placeholders()
        for section, entries in ((s, self.strings[s]) for s in SECTIONS):
            for key, entry in entries.items():
                message = entry.get("message", "") + entry.get("title", "") + entry.get("description", "")
                placeholders = set(re.findall(r"\{(\w+)\}", message))
                with self.subTest(section=section, key=key):
                    if not placeholders:
                        continue
                    self.assertIn(key, callers, f"{key} has placeholders but no caller passes them")
                    self.assertTrue(placeholders <= callers[key],
                                    f"{key} uses {placeholders - callers[key]} that no caller provides")


if __name__ == "__main__":
    unittest.main()
