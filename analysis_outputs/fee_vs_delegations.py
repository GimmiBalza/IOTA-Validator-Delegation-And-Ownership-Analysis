import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from analysis_outputs.common import get_connection, save_figure, short_address


def plot_fee_vs_delegations_top_validators():
    """Effective fee vs number of stake events for the top 5 validators."""
    print("Generating graph 10: fee vs delegation count for top validators...")
    query = """
        WITH top5 AS (
            SELECT validator_address
            FROM validator_snapshots
            WHERE epoch_id = (SELECT MAX(epoch_id) FROM validator_snapshots)
            ORDER BY total_stake DESC
            LIMIT 5
        ),
        deleg_counts AS (
            SELECT epoch_id, validator_address, COUNT(*) AS deleg_count
            FROM delegation_events
            WHERE event_type = 'Stake'
              AND delegator_address != validator_address
            GROUP BY epoch_id, validator_address
        )
        SELECT v.epoch_id, v.validator_address, v.effective_fee, COALESCE(d.deleg_count, 0) AS num_delegations
        FROM validator_snapshots v
        JOIN top5 t ON v.validator_address = t.validator_address
        LEFT JOIN deleg_counts d ON v.epoch_id = d.epoch_id AND v.validator_address = d.validator_address
        ORDER BY v.epoch_id ASC;
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)
    if df.empty:
        return

    fig, ax1 = plt.subplots(figsize=(14, 8))
    ax2 = ax1.twinx()

    validators = df["validator_address"].unique()
    colors = sns.color_palette("Set2", len(validators))
    for idx, addr in enumerate(validators):
        subset = df[df["validator_address"] == addr]
        label = short_address(addr)
        ax1.plot(subset["epoch_id"], subset["effective_fee"], label=f"Fee: {label}", color=colors[idx], linewidth=2.5)
        ax2.plot(
            subset["epoch_id"],
            subset["num_delegations"],
            label=f"N. Deleghe: {label}",
            color=colors[idx],
            linewidth=2.5,
            linestyle="-.",
            alpha=0.7,
        )

    normal_max = df[df["epoch_id"] > 2]["num_delegations"].max()
    if pd.isna(normal_max) or normal_max == 0:
        normal_max = df["num_delegations"].max()
    if normal_max > 0:
        ax2.set_ylim(0, normal_max * 1.1)

    ax1.set_xlabel("Epoca")
    ax1.set_ylabel("Fee Effettiva (%)")
    ax2.set_ylabel("Numero di Deleghe (Operazioni Stake)")
    ax1.set_title("Fee Effettiva vs Nuove Deleghe nel tempo (Top 5 Validatori)", fontsize=16)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, bbox_to_anchor=(1.05, 1), loc="upper left")

    plt.tight_layout()
    save_figure("10_fee_vs_delegations_top_validators.png")
    plt.close(fig)
