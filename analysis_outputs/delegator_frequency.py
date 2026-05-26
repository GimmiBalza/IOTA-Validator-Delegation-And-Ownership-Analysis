import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from analysis_outputs.common import get_connection, save_figure


def plot_delegator_retention_all_time():
    """Delegator action frequency over the full history."""
    print("Generazione Grafico 3: Frequenza azioni delegatori...")
    query = """
        SELECT delegator_address, COUNT(*) AS total_actions
        FROM delegation_events
        WHERE delegator_address != validator_address
          AND staked_amount >= 1000
        GROUP BY delegator_address;
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)
    if df.empty:
        return

    df["actions_group"] = np.where(df["total_actions"] > 20, "21+", df["total_actions"].astype(str))
    order = [str(i) for i in range(1, 21)] + ["21+"]

    fig, ax = plt.subplots(figsize=(12, 8))
    sns.countplot(data=df, x="actions_group", order=order, hue="actions_group", palette="magma", legend=False, ax=ax)
    ax.set_xlabel("Numero Totale di Interazioni (Stake / Unstake >= 1000 IOTA)")
    ax.set_ylabel("Numero di Delegatori Unici")
    ax.set_title("Frequenza di Interazione dei Delegatori (Tutta la Storia)", fontsize=16)

    plt.tight_layout()
    save_figure("delegator_action_frequency.png")
    plt.close(fig)
