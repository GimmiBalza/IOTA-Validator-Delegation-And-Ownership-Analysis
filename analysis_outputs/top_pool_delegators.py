import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis_outputs.common import DATA_DIR, get_connection, save_figure, short_address

POOL_RANK_NAMES = ["first", "second", "third", "fourth", "fifth"]


def plot_top_pool_delegators():
    """Delegator balances for each of the top 5 pools in the latest epoch."""
    print("Generazione Grafico 9: Delegatori top pool...")
    query = """
        WITH latest_top5 AS (
            SELECT validator_address, pool_id, total_stake
            FROM validator_snapshots
            WHERE epoch_id = (SELECT MAX(epoch_id) FROM validator_snapshots)
            ORDER BY total_stake DESC
            LIMIT 5
        ),
        net_delegations AS (
            SELECT
                de.validator_address,
                de.pool_id,
                de.delegator_address,
                SUM(
                    CASE
                        WHEN de.event_type = 'Stake' THEN COALESCE(de.staked_amount, 0)
                        WHEN de.event_type = 'Unstake' THEN -COALESCE(de.staked_amount, 0)
                        ELSE 0
                    END
                ) AS net_delegated_iota
            FROM delegation_events de
            JOIN latest_top5 t
              ON t.validator_address = de.validator_address
             AND t.pool_id = de.pool_id
            WHERE de.delegator_address != de.validator_address
            GROUP BY de.validator_address, de.pool_id, de.delegator_address
        )
        SELECT
            t.validator_address,
            t.pool_id,
            t.total_stake,
            nd.delegator_address,
            nd.net_delegated_iota
        FROM latest_top5 t
        JOIN net_delegations nd
          ON nd.validator_address = t.validator_address
         AND nd.pool_id = t.pool_id
        WHERE nd.net_delegated_iota > 0
        ORDER BY t.total_stake DESC, nd.net_delegated_iota DESC;
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)
    if df.empty:
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(DATA_DIR / "top_pool_delegator_balances.csv", index=False)

    for rank, validator in enumerate(df["validator_address"].drop_duplicates().tolist(), start=1):
        subset = df[df["validator_address"] == validator].head(80).copy()
        subset["short_addr"] = subset["delegator_address"].apply(short_address)
        x = np.arange(len(subset))
        y_m = subset["net_delegated_iota"].fillna(0) / 1_000_000

        fig, ax = plt.subplots(figsize=(20, 9))
        ax.bar(x, y_m, color="#457b9d", width=0.65)
        ax.set_title(f"Top delegatori pool {rank}: {short_address(validator)}", fontsize=16)
        ax.set_ylabel("Milioni di IOTA delegati netti")
        ax.set_xlabel("Delegatori")
        ax.set_xticks(x)
        ax.set_xticklabels(subset["short_addr"], rotation=90, fontsize=8)
        ax.grid(True, axis="y", color="#d0d0d0")
        plt.tight_layout()
        rank_name = POOL_RANK_NAMES[rank - 1] if rank <= len(POOL_RANK_NAMES) else str(rank)
        save_figure(f"top_pool_delegators_{rank_name}.png")
        plt.close(fig)
