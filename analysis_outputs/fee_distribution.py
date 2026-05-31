import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from analysis_outputs.common import get_connection, save_figure


def plot_fee_distribution():
    """Average fee distribution over the last 50 epochs."""
    print("Generating graph 07: fee distribution...")
    query = """
        SELECT epoch_id, applied_fee, effective_fee
        FROM validator_snapshots
        WHERE epoch_id >= (SELECT MAX(epoch_id) - 50 FROM validator_snapshots);
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)
    if df.empty:
        return

    num_epochs = df["epoch_id"].nunique()
    df_melted = df.melt(
        id_vars=["epoch_id"],
        value_vars=["applied_fee", "effective_fee"],
        var_name="Tipo di Fee",
        value_name="Percentuale (%)",
    )
    df_melted["Tipo di Fee"] = df_melted["Tipo di Fee"].map(
        {
            "applied_fee": "Fee Nominale (Dichiarata)",
            "effective_fee": "Fee Effettiva (Applicata)",
        }
    )
    df_melted["Peso"] = 1.0 / num_epochs

    fig, ax = plt.subplots(figsize=(12, 8))
    max_fee = df_melted["Percentuale (%)"].max()
    max_x = int(np.ceil(max_fee / 5.0)) * 5 if max_fee > 0 else 20

    sns.histplot(
        data=df_melted,
        x="Percentuale (%)",
        hue="Tipo di Fee",
        weights="Peso",
        multiple="dodge",
        binwidth=1,
        ax=ax,
        palette=["#457b9d", "#e63946"],
    )

    ax.set_title(f"Distribuzione Media delle Commissioni (Ultime {num_epochs} Epoche)", fontsize=16)
    ax.set_ylabel("Numero Medio di Validatori per Epoca")
    ax.set_xlabel("Percentuale di Commissione (%)")

    step = 2 if max_x <= 15 else 5
    ax.set_xticks(np.arange(0, max_x + 1, step))
    ax.set_xlim(0, max_x)

    plt.tight_layout()
    save_figure("07_fee_distribution.png")
    plt.close(fig)
