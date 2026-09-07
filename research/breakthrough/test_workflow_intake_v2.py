"""Amendment scope controls; no additional real-data preview or model scoring."""

from copy import deepcopy
import json
import unittest

from test_workflow_intake import event, events_blob, protocol
from workflow_intake_audit import HERE, incidents_profile, sms_profile
from workflow_intake_v2 import effective_protocol, original_integrity


def amendment():
    return json.loads((HERE / "workflow_intake_amendment_v2.json").read_text())


class AmendmentTests(unittest.TestCase):
    def test_only_two_name_references_change(self):
        base = protocol()
        updated = effective_protocol(base, amendment())
        updated["lanes"]["incidents"]["expected_columns"][32] = "close_code"
        updated["lanes"]["incidents"]["future_sensitive_columns"][3] = "close_code"
        self.assertEqual(updated, base)

    def test_original_protocol_is_not_mutated(self):
        base = protocol()
        before = deepcopy(base)
        effective_protocol(base, amendment())
        self.assertEqual(base, before)

    def test_extra_patch_or_wrong_path_rejected(self):
        extra = amendment()
        extra["patches"].append(extra["patches"][0])
        with self.assertRaises(ValueError):
            effective_protocol(protocol(), extra)
        wrong = amendment()
        wrong["patches"][1]["path"][-1] = 2
        with self.assertRaises(ValueError):
            effective_protocol(protocol(), wrong)

    def test_new_header_accepted_old_header_not_silently_changed(self):
        base = protocol()
        updated = effective_protocol(base, amendment())
        old = events_blob([event()])
        self.assertFalse(incidents_profile(old, updated)[0]["schema_accepted"])
        new = old.replace(b",close_code,", b",closed_code,", 1)
        self.assertTrue(incidents_profile(new, updated)[0]["schema_accepted"])
        self.assertFalse(incidents_profile(new, base)[0]["schema_accepted"])

    def test_sms_and_split_rules_are_unchanged(self):
        base = protocol()
        updated = effective_protocol(base, amendment())
        blob = b"ham\tSynthetic example\nham\tSYNTHETIC EXAMPLE\nspam\tOther fixture\n"
        self.assertEqual(sms_profile(blob, base), sms_profile(blob, updated))
        self.assertEqual(base["split"], updated["split"])

    def test_original_failure_and_sources_are_preserved(self):
        stored = original_integrity(amendment())
        self.assertFalse(stored["lanes"]["incidents"]["profile"]["schema_accepted"])


if __name__ == "__main__":
    unittest.main()
