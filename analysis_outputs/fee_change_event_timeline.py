import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from analysis_outputs.common import DATA_DIR, get_connection, save_figure, short_address


def plot_fee_change_event_timeline(window=10):
    """Stake/unstake activity around the largest fee increases and decreases."""
    print("Generazione Grafico 10: Eventi attorno ai maggiori cambi fee...")
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
                COUNT(*) AS event_count
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
        WHERE activity_epoch IS NOT NULL
        ORDER BY change_group, rank_in_group, activity_epoch, event_type;
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=(window, window))
    if df.empty:
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(DATA_DIR / "fee_change_event_timeline.csv", index=False)

    df["relative_epoch"] = df["activity_epoch"] - df["change_epoch"]
    df["signed_count"] = df.apply(
        lambda row: row["event_count"] if row["event_type"] == "Stake" else -row["event_count"],
        axis=1,
    )
    df["panel"] = df.apply(
        lambda row: (
            f"{row['change_group']} {int(row['rank_in_group'])}: {short_address(row['validator_address'])}\n"
            f"{row['old_fee']}% -> {row['new_fee']}% ({row['fee_delta']:+.2f})"
        ),
        axis=1,
    )

    panel_order = (
        df[["change_group", "rank_in_group", "panel"]]
        .drop_duplicates()
        .sort_values(["change_group", "rank_in_group"], ascending=[False, True])["panel"]
        .tolist()
    )

    relative_epochs = list(range(-window, window + 1))
    event_types = ["Stake", "Unstake"]
    complete_index = pd.MultiIndex.from_product(
        [panel_order, relative_epochs, event_types],
        names=["panel", "relative_epoch", "event_type"],
    )
    complete_df = (
        df.set_index(["panel", "relative_epoch", "event_type"])
        .reindex(complete_index)
        .reset_index()
    )
    complete_df["signed_count"] = complete_df["signed_count"].fillna(0)
    complete_df["relative_epoch_label"] = complete_df["relative_epoch"].astype(str)
    epoch_labels = [str(value) for value in relative_epochs]

    g = sns.FacetGrid(complete_df, col="panel", col_wrap=2, col_order=panel_order, height=3.2, aspect=1.7, sharey=False)
    g.map_dataframe(
        sns.barplot,
        x="relative_epoch_label",
        y="signed_count",
        hue="event_type",
        order=epoch_labels,
        hue_order=event_types,
        palette={"Stake": "#2a9d8f", "Unstake": "#e76f51"},
        dodge=False,
    )
    g.add_legend(title="Evento")
    for ax in g.axes.flatten():
        ax.axhline(0, color="black", linewidth=0.8)
        ax.axvline(window, color="#333333", linestyle="--", linewidth=1)
        ax.set_xlim(-0.5, len(epoch_labels) - 0.5)
        ax.set_xlabel("Epoch relativa al cambio fee")
        ax.set_ylabel("Stake (+) / Unstake (-)")
        ax.tick_params(axis="x", rotation=45)
    g.fig.suptitle("Eventi stake/unstake attorno ai maggiori cambi fee", fontsize=16)
    g.fig.tight_layout(rect=(0, 0, 1, 0.96))
    save_figure("fee_change_event_timeline.png")
    plt.close(g.fig)
