import unittest

from iota_stake_ownership.strict_ownership import cumulative_strict_own_stake


class StrictOwnershipTests(unittest.TestCase):
    def test_only_self_delegation_counts_as_own_stake(self):
        snapshots = [
            {"epoch_id": 0, "validator_address": "v1", "total_stake": 150},
            {"epoch_id": 1, "validator_address": "v1", "total_stake": 220},
        ]
        events = [
            {"epoch_id": 0, "validator_address": "v1", "delegator_address": "v1", "event_type": "Stake", "staked_amount": 100},
            {"epoch_id": 0, "validator_address": "v1", "delegator_address": "d1", "event_type": "Stake", "staked_amount": 50},
            {"epoch_id": 1, "validator_address": "v1", "delegator_address": "v1", "event_type": "Stake", "staked_amount": 20},
        ]

        result = cumulative_strict_own_stake(snapshots, events)

        self.assertEqual(result[0]["own_stake"], 100)
        self.assertEqual(result[0]["delegated_stake"], 50)
        self.assertEqual(result[1]["own_stake"], 120)
        self.assertEqual(result[1]["delegated_stake"], 100)

    def test_self_unstake_reduces_own_stake(self):
        snapshots = [
            {"epoch_id": 0, "validator_address": "v1", "total_stake": 100},
            {"epoch_id": 1, "validator_address": "v1", "total_stake": 70},
        ]
        events = [
            {"epoch_id": 0, "validator_address": "v1", "delegator_address": "v1", "event_type": "Stake", "staked_amount": 100},
            {"epoch_id": 1, "validator_address": "v1", "delegator_address": "v1", "event_type": "Unstake", "staked_amount": 30},
        ]

        result = cumulative_strict_own_stake(snapshots, events)

        self.assertEqual(result[1]["own_stake"], 70)
        self.assertEqual(result[1]["delegated_stake"], 0)


if __name__ == "__main__":
    unittest.main()
