import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from analysis_outputs.common import DATA_DIR, get_connection, save_figure
from analysis_outputs.stake_distribution_timeseries import gini_index
from iota_stake_ownership.validator_identity import MIN_COMMISSION_ACTIVATION_EPOCH


PANDABYTE_GROUP = "PANDABYTE"


def add_policy_marker(ax, label=False):
    ax.axvline(
        MIN_COMMISSION_ACTIVATION_EPOCH,
        color="#b33f40",
        linestyle="--",
        linewidth=1.5,
        alpha=0.8,
    )
    if label:
        ax.annotate(
            "Minimum-fee rule\n(epoch 296)",
            xy=(MIN_COMMISSION_ACTIVATION_EPOCH, 1),
            xycoords=("data", "axes fraction"),
            xytext=(8, -8),
            textcoords="offset points",
            color="#8f2f31",
            fontsize=9,
            ha="left",
            va="top",
        )


def plot_latest_validator_group_stake():
    print("Generating graph 21: latest grouped validator own vs delegated stake...")
    query = """
        SELECT epoch_id, validator_group, member_count, own_stake, delegated_stake, total_stake
        FROM validator_group_snapshots
        WHERE epoch_id = (SELECT MAX(epoch_id) FROM validator_group_snapshots)
        ORDER BY total_stake DESC;
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)
    if df.empty:
        return

    x = np.arange(len(df))
    own_m = df["own_stake"].fillna(0) / 1_000_000
    delegated_m = df["delegated_stake"].fillna(0) / 1_000_000
    labels = df.apply(
        lambda row: f"{row['validator_group']} ({int(row['member_count'])})"
        if int(row["member_count"]) > 1
        else row["validator_group"],
        axis=1,
    )

    fig, ax = plt.subplots(figsize=(22, 10))
    ax.bar(x, own_m, label="Validator-Owned Stake", color="#2a9d8f", width=0.62)
    ax.bar(x, delegated_m, bottom=own_m, label="Delegated Stake", color="#e9c46a", width=0.62)
    ax.set_title(f"Validator Group Pool Stake (Epoch {int(df['epoch_id'].iloc[0])})", fontsize=18)
    ax.set_ylabel("Millions of IOTA")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=90, fontsize=8)
    ax.legend(loc="upper right")
    ax.grid(True, axis="y", color="#d0d0d0")
    plt.tight_layout()
    save_figure("21_latest_validator_group_own_vs_delegated.png")
    plt.close(fig)


def plot_top5_validator_group_voting_power():
    print("Generating graph 22: voting power over time for top validator groups...")
    query = """
        WITH top5 AS (
            SELECT validator_group
            FROM validator_group_snapshots
            WHERE epoch_id = (SELECT MAX(epoch_id) FROM validator_group_snapshots)
            ORDER BY total_stake DESC
            LIMIT 5
        )
        SELECT epoch_id, validator_group, voting_power
        FROM validator_group_snapshots
        WHERE validator_group IN (SELECT validator_group FROM top5)
        ORDER BY epoch_id, validator_group;
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)
    if df.empty:
        return

    fig, ax = plt.subplots(figsize=(14, 8))
    colors = sns.color_palette("colorblind", df["validator_group"].nunique())
    for color, (group_name, subset) in zip(colors, df.groupby("validator_group", sort=False)):
        ax.plot(subset["epoch_id"], subset["voting_power"], label=group_name, color=color, linewidth=2.4)
    add_policy_marker(ax, label=True)
    ax.set_title("Voting Power Over Time: Top 5 Validator Groups", fontsize=16)
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Combined voting power (%)")
    ax.legend(loc="best")
    ax.grid(True, color="#d0d0d0")
    plt.tight_layout()
    save_figure("22_top5_validator_group_voting_power.png")
    plt.close(fig)


def plot_validator_group_gini_index():
    print("Generating graph 23: grouped validator stake Gini index...")
    query = """
        SELECT epoch_id, validator_group, total_stake
        FROM validator_group_snapshots
        ORDER BY epoch_id, validator_group;
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)
    if df.empty:
        return

    gini_df = (
        df.groupby("epoch_id")["total_stake"]
        .apply(gini_index)
        .reset_index(name="gini_index")
        .sort_values("epoch_id")
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    gini_df.to_csv(DATA_DIR / "validator_group_total_stake_gini_by_epoch.csv", index=False)

    fig, ax = plt.subplots(figsize=(14, 8))
    sns.lineplot(data=gini_df, x="epoch_id", y="gini_index", ax=ax, color="#264653", linewidth=2.5)
    add_policy_marker(ax, label=True)
    ax.set_title("Gini Index of Total Stake Among Validator Groups", fontsize=16)
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Gini index")
    ax.set_ylim(0, min(1, max(0.1, gini_df["gini_index"].max() * 1.15)))
    ax.grid(True, color="#d0d0d0")
    plt.tight_layout()
    save_figure("23_validator_group_stake_gini_index.png")
    plt.close(fig)


def fetch_pandabyte_i_history():
    query = """
        WITH target AS (
            SELECT validator_address
            FROM validator_snapshots
            WHERE UPPER(validator_name) = 'PANDABYTE I'
            ORDER BY epoch_id DESC
            LIMIT 1
        )
        SELECT epoch_id, validator_address, validator_name, voting_power, delegated_stake,
               applied_fee, effective_fee
        FROM validator_snapshots
        WHERE validator_address = (SELECT validator_address FROM target)
        ORDER BY epoch_id;
    """
    with get_connection() as conn:
        return pd.read_sql_query(query, conn)


def fetch_pandabyte_group_history():
    query = """
        SELECT epoch_id, validator_group, member_count, voting_power, delegated_stake,
               nominal_fee, network_effective_fee, identity_adjusted_effective_fee
        FROM validator_group_snapshots
        WHERE UPPER(validator_group) = %s
        ORDER BY epoch_id;
    """
    with get_connection() as conn:
        return pd.read_sql_query(query, conn, params=(PANDABYTE_GROUP,))


def draw_pandabyte_history(df, grouped, output_filename):
    if df.empty:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data_filename = "pandabyte_group_history.csv" if grouped else "pandabyte_i_history.csv"
    df.to_csv(DATA_DIR / data_filename, index=False)

    fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
    axes[0].plot(df["epoch_id"], df["delegated_stake"] / 1_000_000, color="#2a9d8f", linewidth=2.4)
    axes[0].set_ylabel("Delegated stake\n(million IOTA)")
    axes[1].plot(df["epoch_id"], df["voting_power"], color="#457b9d", linewidth=2.4)
    axes[1].set_ylabel("Voting power (%)")

    if grouped:
        axes[2].plot(df["epoch_id"], df["nominal_fee"], label="Weighted nominal fee", color="#555555", linewidth=2)
        axes[2].plot(
            df["epoch_id"],
            df["network_effective_fee"],
            label="Network effective fee",
            color="#e9a23b",
            linewidth=2.2,
        )
        axes[2].plot(
            df["epoch_id"],
            df["identity_adjusted_effective_fee"],
            label="Identity-adjusted effective fee",
            color="#b33f40",
            linewidth=2.4,
        )
        title = "PANDABYTE I + II: Combined Stake, Voting Power and Fees"
    else:
        axes[2].plot(df["epoch_id"], df["applied_fee"], label="Nominal fee", color="#555555", linewidth=2)
        axes[2].plot(df["epoch_id"], df["effective_fee"], label="Effective fee", color="#b33f40", linewidth=2.4)
        title = "PANDABYTE I: Stake, Voting Power and Fees"

    axes[2].set_ylabel("Fee (%)")
    axes[2].set_xlabel("Epoch")
    axes[2].legend(loc="best")
    for index, ax in enumerate(axes):
        add_policy_marker(ax, label=index == 0)
        ax.grid(True, color="#d0d0d0")
    fig.suptitle(title, fontsize=17)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    save_figure(output_filename)
    plt.close(fig)


def plot_pandabyte_case_study():
    print("Generating graphs 24-25: PANDABYTE fee-floor case study...")
    draw_pandabyte_history(
        fetch_pandabyte_i_history(),
        grouped=False,
        output_filename="24_pandabyte_i_stake_vp_fee.png",
    )
    draw_pandabyte_history(
        fetch_pandabyte_group_history(),
        grouped=True,
        output_filename="25_pandabyte_group_stake_vp_fee.png",
    )


def plot_validator_group_outputs():
    plot_latest_validator_group_stake()
    plot_top5_validator_group_voting_power()
    plot_validator_group_gini_index()
    plot_pandabyte_case_study()
