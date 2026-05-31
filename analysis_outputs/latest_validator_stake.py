import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis_outputs.common import get_connection, save_figure, short_address


FIXED_EPOCH_OUTPUTS = {
    10: "01_validator_stake_epoch_10.png",
    100: "02_validator_stake_epoch_100.png",
    200: "03_validator_stake_epoch_200.png",
}


def fetch_validator_stake_epoch(epoch_id):
    query = """
        SELECT validator_address, own_stake, delegated_stake, total_stake
        FROM validator_snapshots
        WHERE epoch_id = %s
        ORDER BY total_stake DESC;
    """
    with get_connection() as conn:
        return pd.read_sql_query(query, conn, params=(epoch_id,))


def fetch_latest_epoch_id():
    query = """
        SELECT MAX(epoch_id) AS epoch_id
        FROM validator_snapshots;
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)
    if df.empty or pd.isna(df.loc[0, "epoch_id"]):
        return None
    return int(df.loc[0, "epoch_id"])


def draw_validator_stake_chart(df, epoch_id, output_filename):
    if df.empty:
        return

    df = df.copy()
    df["short_addr"] = df["validator_address"].apply(short_address)
    x = np.arange(len(df))
    own_m = df["own_stake"].fillna(0) / 1_000_000
    delegated_m = df["delegated_stake"].fillna(0) / 1_000_000

    fig, ax = plt.subplots(figsize=(20, 10))
    ax.bar(x, own_m, label="Own Stake", color="#2a9d8f", width=0.62)
    ax.bar(x, delegated_m, bottom=own_m, label="Delegated Stake", color="#e9c46a", width=0.62)

    ax.set_title(f"Validator Wealth: Own vs Delegated Stake (Epoch {epoch_id})", fontsize=18)
    ax.set_ylabel("Millions of IOTA")
    ax.set_xticks(x)
    ax.set_xticklabels(df["short_addr"], rotation=90, fontsize=8)
    ax.legend(loc="upper right")
    ax.grid(True, axis="y", color="#d0d0d0")
    ax.grid(True, axis="x", color="#d0d0d0")
    plt.tight_layout()
    save_figure(output_filename)
    plt.close(fig)


def plot_validator_stake_for_epoch(epoch_id, output_filename):
    """Stacked own/delegated stake for every validator in a specific epoch."""
    graph_number = output_filename.split("_", 1)[0]
    print(f"Generating graph {graph_number}: validator own vs delegated stake for epoch {epoch_id}...")
    df = fetch_validator_stake_epoch(epoch_id)
    if df.empty:
        print(f"No validator snapshot rows found for epoch {epoch_id}.")
        return
    draw_validator_stake_chart(df, epoch_id, output_filename)


def plot_fixed_epoch_validator_stakes():
    """Stacked own/delegated stake for epochs 10, 100, and 200."""
    for epoch_id, output_filename in FIXED_EPOCH_OUTPUTS.items():
        plot_validator_stake_for_epoch(epoch_id, output_filename)


def plot_latest_validator_stake():
    """Stacked own/delegated stake for every validator in the latest epoch."""
    latest_epoch_id = fetch_latest_epoch_id()
    if latest_epoch_id is None:
        return
    print(f"Generating graph 04: validator own vs delegated stake for latest epoch ({latest_epoch_id})...")
    df = fetch_validator_stake_epoch(latest_epoch_id)
    draw_validator_stake_chart(df, latest_epoch_id, "04_latest_validator_own_vs_delegated.png")
