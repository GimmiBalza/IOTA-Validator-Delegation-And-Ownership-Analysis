import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from analysis_outputs.common import get_connection, save_figure, short_address
from analysis_outputs.stake_fee_migration import sql_in


def plot_fee_vs_voting_power_top_validators():
    """Effective fee vs voting power for the top 5 validators."""
    print("Generazione Grafico 6: Fee vs voting power top 5...")
    with get_connection() as conn:
        top_vals_df = pd.read_sql_query(
            """
            SELECT validator_address
            FROM validator_snapshots
            WHERE epoch_id = (SELECT MAX(epoch_id) FROM validator_snapshots)
            ORDER BY total_stake DESC
            LIMIT 5;
            """,
            conn,
        )
        top_addresses = top_vals_df["validator_address"].tolist()
        if not top_addresses:
            return
        query = f"""
            SELECT epoch_id, validator_address, effective_fee, voting_power
            FROM validator_snapshots
            WHERE validator_address IN {sql_in(top_addresses)}
            ORDER BY epoch_id ASC;
        """
        df = pd.read_sql_query(query, conn, params=top_addresses)
    if df.empty:
        return

    fig, ax1 = plt.subplots(figsize=(14, 8))
    ax2 = ax1.twinx()
    ax1.set_ylim(0, 20)
    ax2.set_ylim(0, 20)

    validators = df["validator_address"].unique()
    colors = sns.color_palette("Set1", len(validators))
    for idx, addr in enumerate(validators):
        subset = df[df["validator_address"] == addr]
        label = short_address(addr)
        ax1.plot(subset["epoch_id"], subset["effective_fee"], label=f"Fee: {label}", color=colors[idx], linewidth=2.5, linestyle="--")
        ax2.plot(subset["epoch_id"], subset["voting_power"], label=f"VP: {label}", color=colors[idx], linewidth=2.5)

    ax1.set_xlabel("Epoca")
    ax1.set_ylabel("Fee / Voting Power (%)")
    ax2.set_ylabel("")
    ax1.set_title("Fee Effettiva vs Voting Power nel tempo (Top 5 Validatori)", fontsize=16)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, bbox_to_anchor=(1.05, 1), loc="upper left")

    plt.tight_layout()
    save_figure("fee_vs_voting_power_top_validators.png")
    plt.close(fig)
