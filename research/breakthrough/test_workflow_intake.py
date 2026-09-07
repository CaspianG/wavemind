"""Synthetic parser/security controls only. These are not public-data results."""

import csv
from datetime import datetime
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo

from workflow_intake_audit import (
    HERE, assignment, canonical, digest, incidents_profile, license_profile,
    manifest, normalize, parse_time, ratio, safe_members, sms_profile, verify_provenance,
)


def protocol():
    return json.loads((HERE / "workflow_intake_protocol.json").read_text())


def zipped(members):
    target = io.BytesIO()
    with ZipFile(target, "w") as archive:
        for name, value in members:
            archive.writestr(name, value)
    return target.getvalue()


def event(**updates):
    rules = protocol()["lanes"]["incidents"]
    row = dict.fromkeys(rules["expected_columns"], "?")
    row.update(number="SYNTHETIC-INCIDENT", incident_state="New", sys_mod_count="0",
               sys_updated_at="02/01/2020 10:00", opened_at="02/01/2020 09:00")
    row.update(updates)
    return row


def events_blob(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=protocol()["lanes"]["incidents"]["expected_columns"])
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


class IntakeTests(unittest.TestCase):
    def test_normalization_and_grouping(self):
        self.assertEqual(normalize("  Ａ Test\n  MESSAGE  "), "a test message")
        report, split = sms_profile(b"ham\tHello   WORLD\nham\thello world\n", protocol())
        self.assertEqual(report["normalized_groups"], 1)
        self.assertEqual(split[0]["source_rows"], [1, 2])
        self.assertNotIn("hello", canonical(report) + canonical(split))

    def test_conflicting_labels_quarantine_whole_group(self):
        report, split = sms_profile(b"ham\tSome example\nspam\tSOME EXAMPLE\n", protocol())
        self.assertEqual(report["conflicting_label_groups"], 1)
        self.assertEqual(report["quarantined_group_rows"], 2)
        self.assertFalse(split[0]["eligible"])

    def test_sms_malformed_and_missing_not_silently_removed(self):
        report, split = sms_profile(b"broken\nunknown\ttest\nham\t\n", protocol())
        self.assertEqual(report["rows"], 3)
        self.assertEqual(report["malformed_rows"], [1, 2])
        self.assertEqual(report["empty_message"]["count"], 1)
        self.assertFalse(split[0]["eligible"])

    def test_split_deterministic_and_entity_disjoint(self):
        first = manifest({"A": [1, 3], "B": [2]}, "incidents", protocol())
        second = manifest({"B": [2], "A": [1, 3]}, "incidents", protocol())
        self.assertEqual(first, second)
        self.assertEqual(assignment("incidents", "A", protocol()), assignment("incidents", "A", protocol()))
        self.assertEqual(sorted(n for r in first for n in r["source_rows"]), [1, 2, 3])

    def test_known_independent_split_hash(self):
        import hashlib
        token = hashlib.sha256(b"wavemind-public-intake-v1|sms|example").hexdigest()
        bucket = int(token[:16], 16) % 10000
        expected = "train" if bucket < 7000 else "development" if bucket < 8500 else "evaluation"
        self.assertEqual(assignment("sms", "example", protocol())[1], expected)

    def test_archive_valid_and_license_not_automatic_admission(self):
        members = safe_members(zipped([("SMSSpamCollection", "ham\tSynthetic\n"), ("readme", "research only")]), "sms", protocol())
        result = license_profile(members, "sms", protocol())
        self.assertIn("research only", result["bundled_terms"][0]["review_flags"])
        self.assertFalse(result["baseline_admitted"])

    def test_archive_traversal_and_unknown_member_rejected(self):
        for name in ("../SMSSpamCollection", "/SMSSpamCollection", "C:/SMSSpamCollection", "a\\SMSSpamCollection", "run.exe"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_members(zipped([(name, "test")]), "sms", protocol())

    def test_archive_symlink_rejected(self):
        info = ZipInfo("SMSSpamCollection")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(ValueError):
            safe_members(zipped([(info, "target")]), "sms", protocol())

    def test_archive_size_and_missing_readme_rejected(self):
        tiny = protocol()
        tiny["limits"]["archive_bytes"] = 2
        with self.assertRaises(ValueError):
            safe_members(b"large", "sms", tiny)
        with self.assertRaises(ValueError):
            safe_members(zipped([("SMSSpamCollection", "ham\tSynthetic")]), "sms", protocol())

    def test_timestamp_day_first_and_timezone_unknown(self):
        rules = protocol()["lanes"]["incidents"]
        self.assertEqual(parse_time("02/01/2020 10:00", rules), datetime(2020, 1, 2, 10))
        self.assertIsNone(parse_time("?", rules))
        with self.assertRaises(ValueError):
            parse_time("2020-01-02", rules)

    def test_events_duplicates_kept_and_one_partition(self):
        report, split = incidents_profile(events_blob([event(), event()]), protocol())
        self.assertEqual(report["rows"], 2)
        self.assertEqual(report["exact_duplicate_excess"]["count"], 1)
        self.assertEqual(split[0]["source_rows"], [1, 2])
        self.assertEqual(report["conflicting_equal_event_keys"], 0)

    def test_events_time_regression_and_future_fields(self):
        rows = [event(sys_mod_count="2", closed_at="03/01/2020 10:00"),
                event(sys_mod_count="?", sys_updated_at="?"),
                event(sys_mod_count="1", sys_updated_at="02/01/2020 08:00")]
        report, _ = incidents_profile(events_blob(rows), protocol())
        self.assertEqual(report["within_incident_file_order_regressions"], {"timestamp": 1, "update_counter": 1})
        self.assertEqual(report["future_outcome_values"]["closed_at_after_record_update"], 1)
        self.assertEqual(report["future_outcome_values"]["update_before_opened"], 1)

    def test_events_same_key_conflict_and_schema_failure(self):
        report, _ = incidents_profile(events_blob([event(), event(incident_state="Closed")]), protocol())
        self.assertEqual(report["conflicting_equal_event_keys"], 1)
        bad, split = incidents_profile(b"not-the-real-schema\n", protocol())
        self.assertFalse(bad["schema_accepted"])
        self.assertEqual(split, [])

    def test_empty_denominator_is_not_zero_success(self):
        self.assertIsNone(ratio(0, 0)["rate"])

    def test_provenance_hash_and_official_origin(self):
        rules = protocol()
        archive = b"synthetic-provenance-fixture-not-a-dataset"
        url = "https://archive.ics.uci.edu/static/public/228/SYNTHETIC.zip"
        snapshot = (url + " https://creativecommons.org/licenses/by/4.0").encode()
        record = {"source_page": rules["lanes"]["sms"]["source_page"], "archive_url": url,
                  "archive_sha256": digest(archive), "source_snapshot_sha256": digest(snapshot),
                  "retrieved_utc": "2026-09-07T12:00:00Z", "retrieval_method": "SYNTHETIC unit test",
                  "license": "CC-BY-4.0"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "sms.source.html").write_bytes(snapshot)
            (path / "sms.provenance.json").write_text(json.dumps(record))
            self.assertEqual(verify_provenance(path, "sms", rules, archive)["archive_sha256"], digest(archive))
            record["archive_url"] = "https://example.org/archive.zip"
            (path / "sms.provenance.json").write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                verify_provenance(path, "sms", rules, archive)


if __name__ == "__main__":
    unittest.main()
