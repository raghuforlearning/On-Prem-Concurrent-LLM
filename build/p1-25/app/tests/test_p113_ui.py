from pathlib import Path
import unittest


APP_ROOT = Path(__file__).parents[1]


class ClarificationUiTests(unittest.TestCase):
    def test_dotted_clarification_field_uses_literal_element_id(self):
        ui_source = (APP_ROOT / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn("document.getElementById('ans_' + field)", ui_source)
        self.assertNotIn("document.getElementById('ans_' + CSS.escape(field))", ui_source)


if __name__ == "__main__":
    unittest.main()
