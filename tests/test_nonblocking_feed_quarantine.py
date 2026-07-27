import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/pointa_quarantine_failed_items.py"


class NonBlockingFeedQuarantineTest(unittest.TestCase):
    def test_bad_item_is_quarantined_and_valid_item_remains(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            feed_path = tmp_path / "feed.json"
            report_path = tmp_path / "report.json"
            quarantine_path = tmp_path / "quarantine.json"
            feed_path.write_text(json.dumps({
                "items": [
                    {"headline": "valid", "sourceUrl": "https://example.com/valid"},
                    {"headline": "bad", "sourceUrl": "https://example.com/bad"},
                ]
            }), encoding="utf-8")
            report_path.write_text(json.dumps({
                "errors": [{
                    "code": "foreign_item_not_relevant",
                    "message": "not relevant",
                    "url": "https://example.com/bad",
                }]
            }), encoding="utf-8")

            result = subprocess.run([
                "python3", str(SCRIPT),
                "--feed", str(feed_path),
                "--report", str(report_path),
                "--quarantine", str(quarantine_path),
            ], check=False, capture_output=True, text=True)

            self.assertEqual(result.returncode, 0, result.stderr)
            remaining = json.loads(feed_path.read_text(encoding="utf-8"))["items"]
            self.assertEqual([item["headline"] for item in remaining], ["valid"])
            quarantined = json.loads(quarantine_path.read_text(encoding="utf-8"))["items"]
            self.assertEqual(quarantined[0]["headline"], "bad")


if __name__ == "__main__":
    unittest.main()
