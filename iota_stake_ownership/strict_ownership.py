from collections import defaultdict


def cumulative_strict_own_stake(snapshots, events):
    """Return strict own/delegated stake per snapshot from self-delegation events.

    A validator owns only stake where delegator_address == validator_address.
    Every other address is treated as delegated stake.
    """
    flows = defaultdict(int)
    for event in events:
        if event.get("delegator_address") != event.get("validator_address"):
            continue
        amount = int(event.get("staked_amount") or 0)
        if event.get("event_type") == "Stake":
            flows[(event["validator_address"], event["epoch_id"])] += amount
        elif event.get("event_type") == "Unstake":
            flows[(event["validator_address"], event["epoch_id"])] -= amount

    running = defaultdict(int)
    results = []
    for snapshot in sorted(snapshots, key=lambda item: (item["validator_address"], item["epoch_id"])):
        validator = snapshot["validator_address"]
        running[validator] += flows[(validator, snapshot["epoch_id"])]
        own_stake = max(0, running[validator])
        total_stake = int(snapshot.get("total_stake") or 0)
        results.append(
            {
                "epoch_id": snapshot["epoch_id"],
                "validator_address": validator,
                "total_stake": total_stake,
                "own_stake": own_stake,
                "delegated_stake": total_stake - own_stake,
            }
        )
    return results
