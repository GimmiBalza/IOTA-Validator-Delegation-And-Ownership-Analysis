import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis_outputs.common import get_connection, save_figure


def plot_validator_wealth_all():
    """Stake validators and historical received delegation counts."""
    print("Generating graph 05: validator wealth and delegation counts...")
    query = """
        WITH max_epoch AS (
            SELECT MAX(epoch_id) AS max_e FROM validator_snapshots
        ),
        delegation_counts AS (
            SELECT validator_address, COUNT(*) AS delegation_count
            FROM delegation_events
            WHERE event_type = 'Stake'
              AND staked_amount >= 1000
              AND delegator_address != validator_address
              AND epoch_id < (SELECT max_e FROM max_epoch)
            GROUP BY validator_address
        )
        SELECT
            v.validator_address,
            v.own_stake,
            v.delegated_stake,
            v.total_stake,
            COALESCE(d.delegation_count, 0) AS delegation_count
        FROM validator_snapshots v
        LEFT JOIN delegation_counts d ON v.validator_address = d.validator_address
        WHERE v.epoch_id = (SELECT max_e FROM max_epoch)
        ORDER BY v.total_stake DESC;
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)
    if df.empty:
        return

    df["short_addr"] = df["validator_address"].apply(lambda x: f"{x[:4]}..{x[-4:]}")
    own_m = df["own_stake"].fillna(0) / 1_000_000
    delegated_m = df["delegated_stake"].fillna(0) / 1_000_000
    counts = df["delegation_count"].fillna(0)

    x = np.arange(len(df))
    width = 0.4

    fig, ax1 = plt.subplots(figsize=(14, 8))
    ax2 = ax1.twinx()

    ax1.bar(x - width / 2, own_m, width, label="Own Stake", color="#2a9d8f")
    ax1.bar(x - width / 2, delegated_m, width, bottom=own_m, label="Delegated Stake", color="#e9c46a")
    ax2.bar(x + width / 2, counts, width, label="N. Deleghe Ricevute (>= 1000 IOTA)", color="#e76f51", alpha=0.8)

    ax1.set_ylabel("Milioni di IOTA")
    ax2.set_ylabel("Numero Totale di Deleghe Storiche")
    ax1.set_title("Ricchezza Validatori e Numero Deleghe Ricevute (Ultima Epoca)", fontsize=16)
    ax1.set_xticks(x)
    ax1.set_xticklabels(df["short_addr"], rotation=90, fontsize=9)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")

    plt.tight_layout()
    save_figure("05_validator_wealth_and_delegation_counts.png")
    plt.close(fig)
