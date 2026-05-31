import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from analysis_outputs.common import DATA_DIR, get_connection, save_figure


def gini_index(values):
    """Gini index for non-negative stake values."""
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    array = array[array >= 0]
    if len(array) == 0 or array.sum() == 0:
        return 0.0

    sorted_array = np.sort(array)
    n = len(sorted_array)
    index = np.arange(1, n + 1)
    return float((2 * np.sum(index * sorted_array)) / (n * np.sum(sorted_array)) - (n + 1) / n)


def fetch_epoch_total_stake_rows():
    query = """
        SELECT epoch_id, validator_address, total_stake
        FROM validator_snapshots
        ORDER BY epoch_id, validator_address;
    """
    with get_connection() as conn:
        return pd.read_sql_query(query, conn)


def plot_validator_stake_gini_index():
    """Gini index of total validator stake from epoch 0 to the latest epoch."""
    print("Generating graph 19: validator total stake Gini index...")
    df = fetch_epoch_total_stake_rows()
    if df.empty:
        return

    gini_df = (
        df.groupby("epoch_id")["total_stake"]
        .apply(gini_index)
        .reset_index(name="gini_index")
        .sort_values("epoch_id")
    )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    gini_df.to_csv(DATA_DIR / "validator_total_stake_gini_by_epoch.csv", index=False)

    fig, ax = plt.subplots(figsize=(14, 8))
    sns.lineplot(data=gini_df, x="epoch_id", y="gini_index", ax=ax, color="#264653", linewidth=2.5)
    ax.set_title("Gini Index of Total Staked IOTA Among Validators", fontsize=16)
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Gini index")
    ax.set_ylim(0, min(1, max(0.1, gini_df["gini_index"].max() * 1.15)))
    ax.grid(True, color="#d0d0d0")
    plt.tight_layout()
    save_figure("19_validator_stake_gini_index.png")
    plt.close(fig)


def plot_total_staked_iota_by_epoch():
    """Total validator stake from epoch 0 to the latest epoch."""
    print("Generating graph 20: total staked IOTA by epoch...")
    df = fetch_epoch_total_stake_rows()
    if df.empty:
        return

    total_df = (
        df.groupby("epoch_id", as_index=False)["total_stake"]
        .sum()
        .sort_values("epoch_id")
    )
    total_df["total_stake_millions"] = total_df["total_stake"] / 1_000_000

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    total_df.to_csv(DATA_DIR / "total_staked_iota_by_epoch.csv", index=False)

    fig, ax = plt.subplots(figsize=(14, 8))
    sns.lineplot(data=total_df, x="epoch_id", y="total_stake_millions", ax=ax, color="#457b9d", linewidth=2.5)
    ax.set_title("Total Staked IOTA Over Time", fontsize=16)
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Total staked IOTA, millions")
    ax.grid(True, color="#d0d0d0")
    plt.tight_layout()
    save_figure("20_total_staked_iota_by_epoch.png")
    plt.close(fig)
