import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from matplotlib.patches import Patch

from analysis_outputs.common import DATA_DIR, get_connection, save_figure, short_address


EVENT_TYPES = ["Stake", "Unstake"]
EVENT_COLORS = {"Stake": "#2a9d8f", "Unstake": "#e76f51"}


def fetch_fee_change_activity(window=50):
    """Return activity for the largest fee changes from -window to +window epochs."""
    query = """
        WITH fee_actions AS (
            SELECT
                validator_address,
                epoch_id,
                REPLACE(old_value, '%%', '')::numeric AS old_fee,
                REPLACE(new_value, '%%', '')::numeric AS new_fee,
                REPLACE(new_value, '%%', '')::numeric - REPLACE(old_value, '%%', '')::numeric AS fee_delta
            FROM validator_actions
            WHERE action_type = 'Fee Change'
              AND old_value IS NOT NULL
              AND new_value IS NOT NULL
        ),
        increases AS (
            SELECT *, ROW_NUMBER() OVER (ORDER BY fee_delta DESC, epoch_id DESC) AS rank_in_group
            FROM fee_actions
            WHERE fee_delta > 0
        ),
        decreases AS (
            SELECT *, ROW_NUMBER() OVER (ORDER BY fee_delta ASC, epoch_id DESC) AS rank_in_group
            FROM fee_actions
            WHERE fee_delta < 0
        ),
        selected AS (
            SELECT 'increase' AS change_group, * FROM increases WHERE rank_in_group <= 5
            UNION ALL
            SELECT 'decrease' AS change_group, * FROM decreases WHERE rank_in_group <= 5
        ),
        activity AS (
            SELECT
                s.change_group,
                s.rank_in_group,
                s.validator_address,
                s.epoch_id AS change_epoch,
                s.old_fee,
                s.new_fee,
                s.fee_delta,
                e.epoch_id AS activity_epoch,
                e.event_type,
                COUNT(e.event_id) AS event_count,
                COALESCE(SUM(e.staked_amount), 0) AS event_amount
            FROM selected s
            LEFT JOIN delegation_events e
              ON e.validator_address = s.validator_address
             AND e.delegator_address != e.validator_address
             AND e.epoch_id BETWEEN s.epoch_id - %s AND s.epoch_id + %s
             AND e.event_type IN ('Stake', 'Unstake')
            GROUP BY
                s.change_group, s.rank_in_group, s.validator_address, s.epoch_id,
                s.old_fee, s.new_fee, s.fee_delta, e.epoch_id, e.event_type
        )
        SELECT *
        FROM activity
        ORDER BY change_group, rank_in_group, activity_epoch, event_type;
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=(window, window))
    if df.empty:
        return df

    df["relative_epoch"] = df["activity_epoch"] - df["change_epoch"]
    df["panel"] = df.apply(
        lambda row: (
            f"{row['change_group']} {int(row['rank_in_group'])}: {short_address(row['validator_address'])} | epoch {int(row['change_epoch'])}\n"
            f"{row['old_fee']}% -> {row['new_fee']}% ({row['fee_delta']:+.2f})"
        ),
        axis=1,
    )
    return df


def fetch_voting_power_context(fee_change_df, window):
    """Return voting power for each selected fee-change panel in the same relative epoch window."""
    selected = (
        fee_change_df[
            [
                "panel",
                "validator_address",
                "change_epoch",
                "change_group",
                "rank_in_group",
                "old_fee",
                "new_fee",
                "fee_delta",
            ]
        ]
        .drop_duplicates()
        .copy()
    )
    if selected.empty:
        return selected

    min_epoch = int(selected["change_epoch"].min()) - window
    max_epoch = int(selected["change_epoch"].max()) + window
    validator_addresses = selected["validator_address"].drop_duplicates().tolist()
    placeholders = ",".join(["%s"] * len(validator_addresses))
    query = f"""
        SELECT epoch_id, validator_address, voting_power
        FROM validator_snapshots
        WHERE validator_address IN ({placeholders})
          AND epoch_id BETWEEN %s AND %s
        ORDER BY validator_address, epoch_id;
    """
    params = validator_addresses + [min_epoch, max_epoch]
    with get_connection() as conn:
        voting_power_df = pd.read_sql_query(query, conn, params=params)

    context = selected.merge(voting_power_df, on="validator_address", how="left")
    context = context[
        (context["epoch_id"] >= context["change_epoch"] - window)
        & (context["epoch_id"] <= context["change_epoch"] + window)
    ].copy()
    context["relative_epoch"] = context["epoch_id"] - context["change_epoch"]
    return context


def panel_order_for(df):
    return (
        df[["change_group", "rank_in_group", "panel"]]
        .drop_duplicates()
        .sort_values(["change_group", "rank_in_group"], ascending=[False, True])["panel"]
        .tolist()
    )


def complete_relative_epoch_grid(df, value_column, window):
    panel_order = panel_order_for(df)
    relative_epochs = list(range(-window, window + 1))
    complete_index = pd.MultiIndex.from_product(
        [panel_order, relative_epochs, EVENT_TYPES],
        names=["panel", "relative_epoch", "event_type"],
    )
    complete_df = (
        df.set_index(["panel", "relative_epoch", "event_type"])
        .reindex(complete_index)
        .reset_index()
    )
    complete_df[value_column] = complete_df[value_column].fillna(0)
    return complete_df, panel_order, relative_epochs


def draw_relative_epoch_bars(data, value_column, **kwargs):
    ax = plt.gca()
    for event_type in EVENT_TYPES:
        subset = data[data["event_type"] == event_type].sort_values("relative_epoch")
        ax.bar(
            subset["relative_epoch"],
            subset[value_column],
            width=0.9,
            color=EVENT_COLORS[event_type],
            alpha=0.95,
            label=event_type,
        )


def draw_fee_change_facet_bars(df, value_column, output_filename, title, ylabel, window):
    complete_df, panel_order, relative_epochs = complete_relative_epoch_grid(df, value_column, window)
    voting_power_df = fetch_voting_power_context(df, window)
    g = sns.FacetGrid(complete_df, col="panel", col_wrap=2, col_order=panel_order, height=3.2, aspect=1.85, sharey=False)
    g.set_titles("{col_name}")
    g.map_dataframe(
        draw_relative_epoch_bars,
        value_column=value_column,
    )
    legend_handles = [Patch(facecolor=EVENT_COLORS[event_type], label=event_type) for event_type in EVENT_TYPES]
    g.fig.legend(handles=legend_handles, title="Event", loc="upper right", bbox_to_anchor=(0.985, 0.985))
    for ax in g.axes.flatten():
        panel = ax.get_title()
        ax.axhline(0, color="black", linewidth=0.8)
        ax.axvline(0, color="#333333", linestyle="--", linewidth=1.1)
        ax.set_xlim(-window - 0.5, window + 0.5)
        ax.set_xlabel("Epochs relative to fee change")
        ax.set_ylabel("")
        tick_positions = list(range(-window, window + 1, 10))
        ax.set_xticks(tick_positions)
        ax.set_xticklabels([str(value) for value in tick_positions], rotation=45)

        panel_voting_power = voting_power_df[voting_power_df["panel"] == panel].sort_values("relative_epoch")
        if not panel_voting_power.empty:
            ax2 = ax.twinx()
            ax2.plot(
                panel_voting_power["relative_epoch"],
                panel_voting_power["voting_power"],
                color="#222222",
                linewidth=1.8,
                alpha=0.55,
                label="Voting power",
                zorder=0,
            )
            ax2.set_ylabel("VP (%)", color="#222222")
            ax2.tick_params(axis="y", colors="#222222")
            upper = panel_voting_power["voting_power"].max()
            ax2.set_ylim(0, max(1, upper * 1.2))
    g.fig.suptitle(title, fontsize=16)
    g.fig.text(0.015, 0.5, ylabel, rotation="vertical", va="center", fontsize=11)
    g.fig.tight_layout(rect=(0.035, 0, 0.94, 0.96))
    save_figure(output_filename)
    plt.close(g.fig)


def plot_fee_change_event_timeline(window=50):
    """Stake/unstake event counts for 50 epochs before and after the largest fee changes."""
    print("Generating graph 17: fee-change stake/unstake event timeline...")
    df = fetch_fee_change_activity(window)
    if df.empty:
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(DATA_DIR / "fee_change_event_timeline.csv", index=False)

    df["signed_count"] = df.apply(
        lambda row: row["event_count"] if row["event_type"] == "Stake" else -row["event_count"],
        axis=1,
    )
    draw_fee_change_facet_bars(
        df,
        value_column="signed_count",
        output_filename="17_fee_change_event_timeline.png",
        title="Stake/unstake event counts before and after the largest fee changes",
        ylabel="Stake events (+) / unstake events (-)",
        window=window,
    )


def plot_fee_change_amount_timeline(window=50):
    """Staked/unstaked IOTA amounts for 50 epochs before and after the largest fee changes."""
    print("Generating graph 18: fee-change staked/unstaked amount timeline...")
    df = fetch_fee_change_activity(window)
    if df.empty:
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(DATA_DIR / "fee_change_amount_timeline.csv", index=False)

    df["signed_amount_millions"] = df.apply(
        lambda row: row["event_amount"] / 1_000_000 if row["event_type"] == "Stake" else -row["event_amount"] / 1_000_000,
        axis=1,
    )
    draw_fee_change_facet_bars(
        df,
        value_column="signed_amount_millions",
        output_filename="18_fee_change_amount_timeline.png",
        title="Staked/unstaked IOTA amounts before and after the largest fee changes",
        ylabel="Staked IOTA (+) / unstaked IOTA (-), millions",
        window=window,
    )
