import argparse
from pathlib import Path

import psycopg2

import _bootstrap  # noqa: F401
from iota_stake_ownership.config import DB_PARAMS
from iota_stake_ownership.schema import ensure_schema
from iota_stake_ownership.validator_identity import MIN_COMMISSION_ACTIVATION_EPOCH
from tools.generate_analysis_outputs import (
    export_delegator_gbmt_long,
    plot_delegator_action_sequence,
    plot_delegator_retention_all_time,
    plot_fee_change_amount_timeline,
    plot_fee_vs_delegations_top_validators,
    plot_fee_vs_voting_power_top_validators,
    plot_fee_change_event_timeline,
    plot_fee_distribution,
    plot_fixed_epoch_validator_stakes,
    plot_latest_validator_stake,
    plot_stake_and_fee_trends,
    plot_top_pool_delegators,
    plot_total_staked_iota_by_epoch,
    plot_validator_stake_gini_index,
    plot_validator_wealth_all,
)
from analysis_outputs.validator_group_analysis import plot_validator_group_outputs


GRAPH_OUTPUTS = [
    Path("outputs/figures/01_validator_stake_epoch_10.png"),
    Path("outputs/figures/02_validator_stake_epoch_100.png"),
    Path("outputs/figures/03_validator_stake_epoch_200.png"),
    Path("outputs/figures/04_latest_validator_own_vs_delegated.png"),
    Path("outputs/figures/05_validator_wealth_and_delegation_counts.png"),
    Path("outputs/figures/06_delegator_action_frequency.png"),
    Path("outputs/figures/07_fee_distribution.png"),
    Path("outputs/figures/08_stake_fee_migration.png"),
    Path("outputs/figures/09_fee_vs_voting_power_top_validators.png"),
    Path("outputs/figures/10_fee_vs_delegations_top_validators.png"),
    Path("outputs/figures/11_delegator_action_sequences.png"),
    Path("outputs/figures/12_top_pool_delegators_first.png"),
    Path("outputs/figures/13_top_pool_delegators_second.png"),
    Path("outputs/figures/14_top_pool_delegators_third.png"),
    Path("outputs/figures/15_top_pool_delegators_fourth.png"),
    Path("outputs/figures/16_top_pool_delegators_fifth.png"),
    Path("outputs/figures/17_fee_change_event_timeline.png"),
    Path("outputs/figures/18_fee_change_amount_timeline.png"),
    Path("outputs/figures/19_validator_stake_gini_index.png"),
    Path("outputs/figures/20_total_staked_iota_by_epoch.png"),
    Path("outputs/figures/21_latest_validator_group_own_vs_delegated.png"),
    Path("outputs/figures/22_top5_validator_group_voting_power.png"),
    Path("outputs/figures/23_validator_group_stake_gini_index.png"),
    Path("outputs/figures/24_pandabyte_i_stake_vp_fee.png"),
    Path("outputs/figures/25_pandabyte_group_stake_vp_fee.png"),
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
        "validator_identities": "SELECT COUNT(*) FROM validator_identities",
        "validator_group_snapshots": "SELECT COUNT(*) FROM validator_group_snapshots",
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
        "group_reconciliation_mismatch": """
            SELECT COUNT(*)
            FROM validator_group_snapshots
            WHERE COALESCE(total_stake, 0) != COALESCE(own_stake, 0) + COALESCE(delegated_stake, 0)
        """,
        "group_epoch_totals_mismatch": """
            WITH address_totals AS (
                SELECT epoch_id,
                       SUM(total_stake) AS total_stake,
                       SUM(own_stake) AS own_stake,
                       SUM(delegated_stake) AS delegated_stake,
                       SUM(voting_power) AS voting_power
                FROM validator_snapshots
                GROUP BY epoch_id
            ), group_totals AS (
                SELECT epoch_id,
                       SUM(total_stake) AS total_stake,
                       SUM(own_stake) AS own_stake,
                       SUM(delegated_stake) AS delegated_stake,
                       SUM(voting_power) AS voting_power
                FROM validator_group_snapshots
                GROUP BY epoch_id
            )
            SELECT COUNT(*)
            FROM address_totals a
            FULL JOIN group_totals g USING (epoch_id)
            WHERE a.epoch_id IS NULL
               OR g.epoch_id IS NULL
               OR a.total_stake IS DISTINCT FROM g.total_stake
               OR a.own_stake IS DISTINCT FROM g.own_stake
               OR a.delegated_stake IS DISTINCT FROM g.delegated_stake
               OR a.voting_power IS DISTINCT FROM g.voting_power
        """,
        "identity_coverage_mismatch": """
            SELECT COUNT(DISTINCT s.validator_address)
            FROM validator_snapshots s
            WHERE NOT EXISTS (
                SELECT 1
                FROM validator_identities i
                WHERE i.validator_address = s.validator_address
            )
        """,
        "address_fee_policy_mismatch": f"""
            SELECT COUNT(*)
            FROM validator_snapshots
            WHERE effective_fee IS DISTINCT FROM CASE
                WHEN epoch_id < {MIN_COMMISSION_ACTIVATION_EPOCH} THEN applied_fee
                ELSE GREATEST(applied_fee, voting_power)
            END
               OR effective_fee_rule IS DISTINCT FROM CASE
                WHEN epoch_id < {MIN_COMMISSION_ACTIVATION_EPOCH} THEN 'nominal'
                ELSE 'voting_power_floor'
            END
        """,
        "group_fee_policy_mismatch": f"""
            SELECT COUNT(*)
            FROM validator_group_snapshots
            WHERE identity_adjusted_effective_fee IS DISTINCT FROM CASE
                WHEN epoch_id < {MIN_COMMISSION_ACTIVATION_EPOCH} THEN nominal_fee
                ELSE GREATEST(nominal_fee, voting_power)
            END
               OR effective_fee_rule IS DISTINCT FROM CASE
                WHEN epoch_id < {MIN_COMMISSION_ACTIVATION_EPOCH} THEN 'nominal'
                ELSE 'group_voting_power_floor'
            END
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
    plot_fixed_epoch_validator_stakes()
    plot_latest_validator_stake()
    plot_validator_wealth_all()
    plot_delegator_retention_all_time()
    plot_fee_distribution()
    plot_stake_and_fee_trends()
    plot_fee_vs_voting_power_top_validators()
    plot_fee_vs_delegations_top_validators()
    plot_delegator_action_sequence()
    plot_top_pool_delegators()
    plot_fee_change_event_timeline()
    plot_fee_change_amount_timeline()
    plot_validator_stake_gini_index()
    plot_total_staked_iota_by_epoch()
    plot_validator_group_outputs()
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
    if counts["validator_group_snapshots"] == 0:
        raise SystemExit("No grouped validator history found. Run tools/rebuild_validator_groups.py first.")
    if counts["group_reconciliation_mismatch"] != 0:
        raise SystemExit("Grouped ownership reconciliation mismatches found.")
    if counts["group_epoch_totals_mismatch"] != 0:
        raise SystemExit("Grouped epoch totals do not match address-level totals.")
    if counts["identity_coverage_mismatch"] != 0:
        raise SystemExit("Validator addresses without an identity mapping found.")
    if counts["address_fee_policy_mismatch"] != 0 or counts["group_fee_policy_mismatch"] != 0:
        raise SystemExit("Effective-fee policy mismatches found.")

    if args.graphs:
        graph_results = run_graph_smoke()
        print(graph_results)
        missing = [name for name, ok in graph_results.items() if not ok]
        if missing:
            raise SystemExit(f"Graphs did not update: {missing}")


if __name__ == "__main__":
    main()
