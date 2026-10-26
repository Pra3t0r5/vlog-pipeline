import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "pipeline"))

import triage


class LegacySheets(unittest.TestCase):
    def test_pre_0_2_manifest_and_index_are_accepted(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t) / "sheets"
            d.mkdir()
            (d / "manifest.json").write_text(json.dumps({
                "2026-01-01-01.jpg": {"day": "2026-01-01", "n_items": 2, "w": 1536, "h": 900, "tokens": 1843},
            }))
            (d / "index.json").write_text(json.dumps({
                "codes": {"P1": "a", "P2": "b"},
                "sheets": {"2026-01-01-01.jpg": ["P1", "P2"]},
            }))
            groups, man = triage.sheet_groups(t)
            self.assertEqual(groups["2026-01-01"]["codes"], ["P1", "P2"])
            self.assertEqual(man["frames"], 6)
            self.assertEqual(man["sheets"]["2026-01-01-01.jpg"]["tokens_est"], 1843)


if __name__ == "__main__":
    unittest.main()
