import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from analysis_outputs.common import get_connection, save_figure, short_address


def sql_in(values):
    return "(" + ",".join(["%s"] * len(values)) + ")"


def plot_stake_and_fee_trends():
    """Delegated stake and effective fee trends for the top 5 validators."""
    print("Generazione Grafico 5: Trend stake e fee top 5...")
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
            SELECT epoch_id, validator_address, delegated_stake, effective_fee
            FROM validator_snapshots
            WHERE validator_address IN {sql_in(top_addresses)}
            ORDER BY epoch_id ASC;
        """
        df_top5 = pd.read_sql_query(query, conn, params=top_addresses)
    if df_top5.empty:
        return

    df_top5["delegated_m"] = df_top5["delegated_stake"].fillna(0) / 1_000_000

    fig, ax1 = plt.subplots(figsize=(14, 8))
    ax2 = ax1.twinx()
    validators = df_top5["validator_address"].unique()
    colors = sns.color_palette("husl", len(validators))

    for idx, addr in enumerate(validators):
        subset = df_top5[df_top5["validator_address"] == addr]
        label = short_address(addr)
        ax1.plot(subset["epoch_id"], subset["delegated_m"], label=f"Stake: {label}", color=colors[idx], linewidth=2.5)
        ax2.plot(
            subset["epoch_id"],
            subset["effective_fee"],
            label=f"Fee: {label}",
            color=colors[idx],
            linewidth=2.5,
            linestyle="--",
            alpha=0.8,
        )

    ax1.set_xlabel("Epoca")
    ax1.set_ylabel("Stake Delegato (Milioni IOTA)")
    ax2.set_ylabel("Fee Effettiva (%)")
    ax1.set_title("Sovrapposizione: Andamento Capitale Delegato vs Fee Effettiva (Top 5)", fontsize=16)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, bbox_to_anchor=(1.05, 1), loc="upper left")

    plt.tight_layout()
    save_figure("stake_fee_migration.png")
    plt.close(fig)
