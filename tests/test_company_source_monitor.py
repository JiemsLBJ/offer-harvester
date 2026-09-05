"""Native company skill uses the same dashboard source as sync_seen events."""
import json
import tempfile
import unittest
from pathlib import Path

from automation.apply_bot.source_monitor import SOURCES, _seen_inventory


class CompanySourceMonitorTests(unittest.TestCase):
    def test_skill_portal_is_mapped_to_company_monitor(self):
        with tempfile.TemporaryDirectory() as directory:
            seen = Path(directory) / "seen.json"
            seen.write_text(json.dumps({"seen": {"company:moka:demo:1": {
                "portal": "company-careers-search",
                "url": "https://app.mokahr.com/apply/demo/123#/job/one",
            }}}), encoding="utf-8")
            counts, _ = _seen_inventory(seen)
            self.assertEqual(counts, {"company": 1})
            self.assertTrue(any(s["portal"] == "company" and s["enabled"] for s in SOURCES))


if __name__ == "__main__":
    unittest.main()
