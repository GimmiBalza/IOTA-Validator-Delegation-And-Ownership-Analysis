import pandas as pd

from analysis_outputs.common import DATA_DIR, get_connection


def export_delegator_gbmt_long():
    """Export delegator trajectories in long format for GBMT/R workflows."""
    print("Export dataset long per GBMT...")
    query = """
        WITH selected_delegators AS (
            SELECT delegator_address
            FROM delegation_events
            WHERE delegator_address != validator_address
              AND staked_amount >= 1000
            GROUP BY delegator_address
            HAVING COUNT(*) >= 21 AND COUNT(DISTINCT validator_address) <= 5
        ),
        ranked_events AS (
            SELECT
                de.delegator_address,
                de.validator_address,
                de.event_type,
                de.epoch_id,
                de.timestamp,
                de.staked_amount,
                DENSE_RANK() OVER (PARTITION BY de.delegator_address ORDER BY de.validator_address) AS validator_slot,
                ROW_NUMBER() OVER (PARTITION BY de.delegator_address ORDER BY de.timestamp, de.event_id) AS time
            FROM delegation_events de
            JOIN selected_delegators sd ON sd.delegator_address = de.delegator_address
            WHERE de.delegator_address != de.validator_address
              AND de.staked_amount >= 1000
        )
        SELECT
            delegator_address AS id,
            time,
            epoch_id,
            validator_slot,
            validator_address,
            CASE WHEN event_type = 'Stake' THEN 1 ELSE 0 END AS stake_action,
            CASE WHEN event_type = 'Unstake' THEN 1 ELSE 0 END AS unstake_action,
            staked_amount
        FROM ranked_events
        ORDER BY id, time;
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)
    if not df.empty:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(DATA_DIR / "delegator_trajectory_long.csv", index=False)
