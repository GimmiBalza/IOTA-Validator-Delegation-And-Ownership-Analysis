import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis_outputs.common import get_connection, save_figure


def plot_latest_validator_stake():
    """Stacked own/delegated stake for every validator in the latest epoch."""
    print("Generazione Grafico 1: Own vs delegated stake ultima epoca...")
    query = """
        SELECT validator_address, own_stake, delegated_stake, total_stake
        FROM validator_snapshots
        WHERE epoch_id = (SELECT MAX(epoch_id) FROM validator_snapshots)
        ORDER BY total_stake DESC;
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)
    if df.empty:
        return

    df["short_addr"] = df["validator_address"].apply(lambda x: f"{x[:4]}..{x[-4:]}")
    x = np.arange(len(df))
    own_m = df["own_stake"].fillna(0) / 1_000_000
    delegated_m = df["delegated_stake"].fillna(0) / 1_000_000

    fig, ax = plt.subplots(figsize=(20, 10))
    ax.bar(x, own_m, label="Own Stake", color="#2a9d8f", width=0.62)
    ax.bar(x, delegated_m, bottom=own_m, label="Delegated Stake", color="#e9c46a", width=0.62)

    ax.set_title("Ricchezza Validatori: Capitale Proprio vs Delegato (Ultima Epoca)", fontsize=18)
    ax.set_ylabel("Milioni di IOTA")
    ax.set_xticks(x)
    ax.set_xticklabels(df["short_addr"], rotation=90, fontsize=8)
    ax.legend(loc="upper right")
    ax.grid(True, axis="y", color="#d0d0d0")
    ax.grid(True, axis="x", color="#d0d0d0")
    plt.tight_layout()
    save_figure("latest_validator_own_vs_delegated.png")
    plt.close(fig)
