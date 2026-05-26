import argparse
from pathlib import Path

import psycopg2

import _bootstrap  # noqa: F401
from iota_stake_ownership.config import DB_PARAMS
from iota_stake_ownership.schema import ensure_schema
from tools.generate_analysis_outputs import (
    export_delegator_gbmt_long,
    plot_latest_validator_stake,
    plot_delegator_action_sequence,
    plot_fee_vs_delegations_top_validators,
    plot_fee_vs_voting_power_top_validators,
    plot_fee_change_event_timeline,
    plot_top_pool_delegators,
    plot_validator_wealth_all,
)


GRAPH_OUTPUTS = [
    Path("outputs/figures/latest_validator_own_vs_delegated.png"),
    Path("outputs/figures/validator_wealth_and_delegation_counts.png"),
    Path("outputs/figures/fee_vs_voting_power_top_validators.png"),
    Path("outputs/figures/fee_vs_delegations_top_validators.png"),
    Path("outputs/figures/delegator_action_sequences.png"),
    Path("outputs/figures/top_pool_delegators_first.png"),
    Path("outputs/figures/fee_change_event_timeline.png"),
]


def check_counts():
    ensure_schema()
    checks = {
        "validator_snapshots": "SELECT COUNT(*) FROM validator_snapshots",
        "delegation_events": "SELECT COUNT(*) FROM delegation_events",
        "validator_actions": "SELECT COUNT(*) FROM validator_actions",
        "validator_owned_stake_objects": "SELECT COUNT(*) FROM validator_owned_stake_objects",
        "validator_owned_stake_snapshots": "SELECT COUNT(*) FROM validator_owned_stake_snapshots",
        "validator_stake_object_intervals": "SELECT COUNT(*) FROM validator_stake_object_intervals",
        "complete_object_history_scans": """
            SELECT COUNT(*)
            FROM validator_stake_object_history_scan_status
            WHERE scan_complete = TRUE
        """,
        "negative_delegated": "SELECT COUNT(*) FROM validator_snapshots WHERE delegated_stake < 0",
        "reconciliation_mismatch": """
            SELECT COUNT(*)
            FROM validator_snapshots
            WHERE COALESCE(total_stake, 0) != COALESCE(own_stake, 0) + COALESCE(delegated_stake, 0)
        """,
    }
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cursor:
            results = {}
            for name, sql in checks.items():
                cursor.execute(sql)
                results[name] = cursor.fetchone()[0]
    return results


def run_graph_smoke():
    before = {path: path.stat().st_mtime if path.exists() else None for path in GRAPH_OUTPUTS}
    plot_latest_validator_stake()
    plot_validator_wealth_all()
    plot_fee_vs_voting_power_top_validators()
    plot_fee_vs_delegations_top_validators()
    plot_delegator_action_sequence()
    plot_top_pool_delegators()
    plot_fee_change_event_timeline()
    export_delegator_gbmt_long()
    after = {path: path.stat().st_mtime if path.exists() else None for path in GRAPH_OUTPUTS}
    return {str(path): after[path] is not None and after[path] != before[path] for path in GRAPH_OUTPUTS}


def main():
    parser = argparse.ArgumentParser(description="Run DB reconciliation and graph smoke checks after a rebuild.")
    parser.add_argument("--graphs", action="store_true", help="Also render graph smoke outputs.")
    args = parser.parse_args()

    counts = check_counts()
    print(counts)
    if counts["validator_snapshots"] == 0:
        raise SystemExit("No snapshot data found. Run tools/rebuild_database.py first.")
    if counts["negative_delegated"] != 0:
        raise SystemExit("Negative delegated stake rows found.")
    if counts["reconciliation_mismatch"] != 0:
        raise SystemExit("Ownership reconciliation mismatches found.")

    if args.graphs:
        graph_results = run_graph_smoke()
        print(graph_results)
        missing = [name for name, ok in graph_results.items() if not ok]
        if missing:
            raise SystemExit(f"Graphs did not update: {missing}")


if __name__ == "__main__":
    main()
