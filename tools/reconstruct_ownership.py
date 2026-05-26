import argparse

import psycopg2

import _bootstrap  # noqa: F401
from iota_stake_ownership.config import DB_PARAMS
from iota_stake_ownership.schema import ensure_schema


EVENT_RECONSTRUCT_SQL = """
WITH self_flows AS (
    SELECT
        validator_address,
        epoch_id,
        SUM(
            CASE
                WHEN event_type = 'Stake' THEN COALESCE(staked_amount, 0)
                WHEN event_type = 'Unstake' THEN -COALESCE(staked_amount, 0)
                ELSE 0
            END
        ) AS net_self_flow
    FROM delegation_events
    WHERE delegator_address = validator_address
    GROUP BY validator_address, epoch_id
),
snapshot_with_flow AS (
    SELECT
        vs.epoch_id,
        vs.validator_address,
        vs.total_stake,
        COALESCE(sf.net_self_flow, 0) AS net_self_flow
    FROM validator_snapshots vs
    LEFT JOIN self_flows sf
      ON sf.validator_address = vs.validator_address
     AND sf.epoch_id = vs.epoch_id
),
cumulative AS (
    SELECT
        epoch_id,
        validator_address,
        total_stake,
        SUM(net_self_flow) OVER (
            PARTITION BY validator_address
            ORDER BY epoch_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS strict_own_stake
    FROM snapshot_with_flow
),
event_own AS (
    SELECT
        epoch_id,
        validator_address,
        GREATEST(0, COALESCE(strict_own_stake, 0)) AS own_stake
    FROM cumulative
),
chosen_own AS (
    SELECT
        vs.epoch_id,
        vs.validator_address,
        CASE
            WHEN voss.validator_address IS NOT NULL
                THEN COALESCE(voss.total_owned_stake, 0)
            ELSE COALESCE(eo.own_stake, 0)
        END AS own_stake
    FROM validator_snapshots vs
    LEFT JOIN event_own eo
      ON eo.epoch_id = vs.epoch_id
     AND eo.validator_address = vs.validator_address
    LEFT JOIN validator_owned_stake_snapshots voss
      ON voss.epoch_id = vs.epoch_id
     AND voss.validator_address = vs.validator_address
)
UPDATE validator_snapshots vs
SET
    own_stake = LEAST(COALESCE(vs.total_stake, 0), GREATEST(0, COALESCE(co.own_stake, 0))),
    delegated_stake = COALESCE(vs.total_stake, 0)
        - LEAST(COALESCE(vs.total_stake, 0), GREATEST(0, COALESCE(co.own_stake, 0)))
FROM chosen_own co
WHERE co.epoch_id = vs.epoch_id
  AND co.validator_address = vs.validator_address;
"""


CHECK_SQL = """
SELECT
    COUNT(*) FILTER (WHERE delegated_stake < 0) AS negative_delegated_rows,
    COUNT(*) FILTER (WHERE COALESCE(own_stake, 0) + COALESCE(delegated_stake, 0) <> COALESCE(total_stake, 0))
        AS reconciliation_mismatch_rows,
    MIN(delegated_stake) AS min_delegated_stake,
    MAX(delegated_stake) AS max_delegated_stake
FROM validator_snapshots;
"""


def reconstruct_ownership():
    ensure_schema()
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cursor:
            cursor.execute(EVENT_RECONSTRUCT_SQL)
            cursor.execute(CHECK_SQL)
            summary = cursor.fetchone()
        conn.commit()
    return {
        "negative_delegated_rows": summary[0],
        "reconciliation_mismatch_rows": summary[1],
        "min_delegated_stake": summary[2],
        "max_delegated_stake": summary[3],
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruct validator own stake. Uses validator-owned object snapshots when "
            "available; these snapshots can come from historical JSON-RPC object intervals "
            "or the lighter current-object GraphQL collector. Falls back to strict "
            "self-delegation events when no object snapshot is available."
        )
    )
    parser.parse_args()
    summary = reconstruct_ownership()
    print("Ownership reconstruction complete.")
    print(summary)


if __name__ == "__main__":
    main()
