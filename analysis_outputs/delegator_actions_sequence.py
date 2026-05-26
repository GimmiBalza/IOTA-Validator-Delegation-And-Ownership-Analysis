import itertools

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis_outputs.common import get_connection, save_figure


def tuple_sql(values):
    return "(" + ",".join(["%s"] * len(values)) + ")"


def plot_delegator_action_sequence():
    """Action sequence for three active delegators."""
    print("Generazione Grafico 8: Sequenza azioni delegatori...")
    query_candidates = """
        SELECT delegator_address, array_agg(DISTINCT validator_address) AS val_list
        FROM delegation_events
        WHERE event_type IN ('Stake', 'Unstake')
          AND delegator_address != validator_address
          AND staked_amount >= 1000
        GROUP BY delegator_address
        HAVING COUNT(*) >= 21 AND COUNT(DISTINCT validator_address) <= 5
        ORDER BY COUNT(*) DESC
        LIMIT 50;
    """
    with get_connection() as conn:
        candidates_df = pd.read_sql_query(query_candidates, conn)
        if candidates_df.empty:
            print("Nessun delegatore trovato con i parametri richiesti.")
            return

        selected = []
        for combo in itertools.combinations(candidates_df.to_dict("records"), 3):
            validator_sets = [set(item["val_list"]) for item in combo]
            if len(set.union(*validator_sets)) <= 10 and len(set.intersection(*validator_sets)) >= 1:
                selected = [item["delegator_address"] for item in combo]
                break
        if not selected:
            for combo in itertools.combinations(candidates_df.to_dict("records"), 3):
                validator_sets = [set(item["val_list"]) for item in combo]
                if len(set.union(*validator_sets)) <= 10:
                    selected = [item["delegator_address"] for item in combo]
                    break
        if not selected:
            selected = candidates_df["delegator_address"].head(3).tolist()

        query_events = f"""
            SELECT delegator_address, validator_address, event_type, timestamp, epoch_id
            FROM delegation_events
            WHERE delegator_address IN {tuple_sql(selected)}
              AND staked_amount >= 1000
            ORDER BY delegator_address, timestamp ASC;
        """
        events_df = pd.read_sql_query(query_events, conn, params=selected)

    if events_df.empty:
        return

    validators = events_df["validator_address"].unique()
    val_to_idx = {val: i + 1 for i, val in enumerate(validators)}
    val_labels = [f"{v[:4]}..{v[-4:]}" for v in validators]

    fig, axes = plt.subplots(len(selected), 1, figsize=(14, 10), sharex=False, sharey=True)
    if len(selected) == 1:
        axes = [axes]

    for ax, delegator in zip(axes, selected):
        subset = events_df[events_df["delegator_address"] == delegator].copy().head(50)
        subset["action_number"] = np.arange(1, len(subset) + 1)
        subset["y_quote"] = subset["validator_address"].map(val_to_idx)

        stakes = subset[subset["event_type"] == "Stake"]
        unstakes = subset[subset["event_type"] == "Unstake"]

        ax.plot(subset["action_number"], subset["y_quote"], color="gray", linestyle="-", alpha=0.5, zorder=1)
        ax.scatter(stakes["action_number"], stakes["y_quote"], color="green", label="Stake", s=60, zorder=2)
        ax.scatter(unstakes["action_number"], unstakes["y_quote"], color="red", label="Unstake", s=60, marker="X", zorder=2)
        ax.set_title(f"Delegatore: {delegator[:6]}..{delegator[-4:]} ({len(subset)} azioni mostrate)")
        ax.set_yticks(list(val_to_idx.values()))
        ax.set_yticklabels(val_labels)
        ax.set_xticks(subset["action_number"])
        ax.set_xticklabels([f"Ep.{ep}" for ep in subset["epoch_id"]], rotation=45, ha="right", fontsize=9)
        ax.grid(True, axis="y", linestyle="--", alpha=0.7)
        if ax == axes[0]:
            ax.legend(loc="upper right")

    axes[-1].set_xlabel("Epoca in cui e avvenuta l'azione")
    plt.tight_layout()
    save_figure("delegator_action_sequences.png")
    plt.close(fig)
