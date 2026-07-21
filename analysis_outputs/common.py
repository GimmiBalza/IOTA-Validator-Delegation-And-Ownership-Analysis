from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import psycopg2
import seaborn as sns

from iota_stake_ownership.config import DB_PARAMS
from iota_stake_ownership.schema import ensure_schema


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
DATA_DIR = PROJECT_ROOT / "outputs" / "data"

CORE_TABLES = {
    "validator_snapshots": "epoch_id, validator_address",
    "validator_identities": "validator_group, validator_address",
    "validator_group_snapshots": "epoch_id, validator_group",
    "validator_actions": None,
    "delegation_events": None,
}


def configure_plots():
    sns.set_theme(style="whitegrid")
    plt.rcParams["figure.figsize"] = (14, 8)


def get_connection():
    ensure_schema()
    return psycopg2.connect(**DB_PARAMS)


def save_figure(filename):
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(FIGURES_DIR / filename, dpi=300)


def short_address(address):
    if not address:
        return ""
    return f"{address[:4]}..{address[-4:]}"


def validator_label(name, address):
    return name.strip() if isinstance(name, str) and name.strip() else short_address(address)


def export_core_tables():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        for table_name, order_by in CORE_TABLES.items():
            order_clause = f" ORDER BY {order_by}" if order_by else ""
            df = pd.read_sql_query(f"SELECT * FROM {table_name}{order_clause};", conn)
            df.to_csv(DATA_DIR / f"{table_name}.csv", index=False)
