import _bootstrap  # noqa: F401

from analysis_outputs.common import configure_plots, export_core_tables
from analysis_outputs.gbmt_export import export_delegator_gbmt_long
from analysis_outputs.delegator_actions_sequence import plot_delegator_action_sequence
from analysis_outputs.delegator_frequency import plot_delegator_retention_all_time
from analysis_outputs.fee_change_event_timeline import plot_fee_change_amount_timeline, plot_fee_change_event_timeline
from analysis_outputs.fee_distribution import plot_fee_distribution
from analysis_outputs.fee_vs_delegations import plot_fee_vs_delegations_top_validators
from analysis_outputs.fee_vs_voting_power import plot_fee_vs_voting_power_top_validators
from analysis_outputs.latest_validator_stake import plot_fixed_epoch_validator_stakes, plot_latest_validator_stake
from analysis_outputs.stake_distribution_timeseries import plot_total_staked_iota_by_epoch, plot_validator_stake_gini_index
from analysis_outputs.stake_fee_migration import plot_stake_and_fee_trends
from analysis_outputs.top_pool_delegators import plot_top_pool_delegators
from analysis_outputs.validator_wealth_delegations import plot_validator_wealth_all


def generate_all_outputs():
    configure_plots()
    print("Avvio generazione grafici ed export...")
    export_core_tables()
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
    export_delegator_gbmt_long()
    print("Tutti gli output sono stati salvati.")


def main():
    generate_all_outputs()


if __name__ == "__main__":
    main()
