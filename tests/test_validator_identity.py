import unittest

from iota_stake_ownership.validator_identity import (
    build_validator_identity_mapping,
    effective_fee_for_epoch,
    fee_rule_for_epoch,
    instance_group_candidate,
)


class ValidatorFeeRuleTests(unittest.TestCase):
    def test_fee_is_nominal_before_activation_epoch(self):
        self.assertEqual(effective_fee_for_epoch(295, 0.99, 6.45), 0.99)
        self.assertEqual(fee_rule_for_epoch(295), "nominal")

    def test_voting_power_floor_starts_at_activation_epoch(self):
        self.assertEqual(effective_fee_for_epoch(296, 0.99, 6.45), 6.45)
        self.assertEqual(fee_rule_for_epoch(296), "voting_power_floor")

    def test_higher_nominal_fee_remains_effective(self):
        self.assertEqual(effective_fee_for_epoch(296, 10, 6.45), 10)


class ValidatorIdentityTests(unittest.TestCase):
    def test_instance_suffix_candidates(self):
        self.assertEqual(instance_group_candidate("IOTA 2"), "IOTA")
        self.assertEqual(instance_group_candidate("PANDABYTE II"), "PANDABYTE")
        self.assertEqual(instance_group_candidate("Kiln0"), "Kiln")
        self.assertEqual(instance_group_candidate("DLT.GREEN"), "DLT.GREEN")

    def test_suffix_is_grouped_only_across_multiple_addresses(self):
        rows = [
            ("0xiota1", 10, "IOTA 1"),
            ("0xiota2", 10, "IOTA 2"),
            ("0xsingle", 10, "Validator 2"),
        ]
        mapping = build_validator_identity_mapping(rows)
        self.assertEqual(mapping["0xiota1"]["validator_group"], "IOTA")
        self.assertEqual(mapping["0xiota2"]["validator_group"], "IOTA")
        self.assertEqual(mapping["0xsingle"]["validator_group"], "Validator 2")

    def test_identical_names_on_distinct_addresses_are_grouped(self):
        rows = [
            ("0xfirst", 10, "Same Operator"),
            ("0xsecond", 20, "Same Operator"),
        ]
        mapping = build_validator_identity_mapping(rows)
        self.assertEqual(mapping["0xfirst"]["validator_group"], "Same Operator")
        self.assertEqual(mapping["0xsecond"]["validator_group"], "Same Operator")

    def test_names_seen_and_latest_name_are_retained(self):
        rows = [
            ("0xpanda1", 10, "PANDABYTE I"),
            ("0xpanda1", 20, "PANDABYTE I Main"),
            ("0xpanda2", 10, "PANDABYTE II"),
        ]
        mapping = build_validator_identity_mapping(rows)
        self.assertEqual(mapping["0xpanda1"]["validator_name"], "PANDABYTE I Main")
        self.assertEqual(mapping["0xpanda1"]["validator_group"], "PANDABYTE")
        self.assertEqual(mapping["0xpanda1"]["names_seen"], ["PANDABYTE I", "PANDABYTE I Main"])


if __name__ == "__main__":
    unittest.main()
