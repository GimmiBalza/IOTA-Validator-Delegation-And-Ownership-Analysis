# IOTA Validator Delegation And Ownership Analysis

This repository builds a PostgreSQL dataset for IOTA validator activity and produces analysis graphs about validator stake, delegator behavior, fees, and fee-change reactions.

The project has three main goals:

1. Ingest validator snapshots, delegation events, and validator action data from public IOTA endpoints.
2. Reconstruct validator-owned stake through strict ownership of `StakedIota` and `TimelockedStakedIota` objects.
3. Export clean CSV datasets for downstream analysis.

## Current Dataset Status

The local database currently stores data until 26/05/2026.

Current local table coverage:

| Table | Rows | Epoch Range |
|---|---:|---|
| `validator_snapshots` | 24709 | 0-386 |
| `delegation_events` | 178530 | 0-386 |
| `validator_actions` | 80 | 4-381 |

Integrity checks after reconstruction:

```text
negative delegated stake rows: 0
ownership reconciliation mismatches: 0
missing ownership rows: 0
duplicate delegation event ids: 0
```

The latest available epoch observed from the public endpoint during the last update was `386`.

## External Resources

Official IOTA endpoint documentation:

```text
https://docs.iota.org/developer/network-overview
```

Endpoints used by the project:

```text
GraphQL:  https://graphql.mainnet.iota.cafe
JSON-RPC: https://api.mainnet.iota.cafe
Indexer:  https://indexer.mainnet.iota.cafe
Explorer: https://explorer.iota.org
```

GraphQL is used for:

```text
validator snapshots
staking and unstaking events
validator fee/report events
current address-owned staking objects
```

JSON-RPC and indexer APIs are used for:

```text
historical transaction blocks
historical object versions
stake object ownership intervals
```

JSON-RPC/indexer methods used or verified:

```text
rpc.discover
iotax_queryTransactionBlocks
iotax_getOwnedObjects
iota_getObject
iota_tryGetPastObject
iota_tryMultiGetPastObjects
```

Important limitation:

```text
iota_tryGetPastObject can retrieve a known historical object version only when the public node still retains it. Public endpoints do not guarantee full archival object history forever. The code compensates by recovering deleted validator-owned stake from unstaking events when possible.
```

## Architecture Overview

The repository is split into five layers.

### Core Package

The `iota_stake_ownership/` package contains shared configuration, database schema creation, and endpoint clients.

### Ingestion Tools

The `tools/` directory contains command-line scripts that ingest raw or semi-raw data into PostgreSQL. Each ingestion tool is idempotent: existing rows are updated through primary keys or unique keys instead of duplicated.

### Ownership Reconstruction

Ownership reconstruction writes the final `own_stake` and `delegated_stake` values into `validator_snapshots`. It uses object ownership first and event-based strict self-delegation only as a fallback.

### Analysis Outputs

The `analysis_outputs/` package contains one file per graph plus shared export utilities. This keeps plotting logic easy to read, review, and change.

### Generated Artifacts

The `outputs/` directory contains generated PNG figures and CSV files. These files can be regenerated from the database.

## Folder Layout

```text
.
|-- README.md
|-- analysis_outputs/
|   |-- __init__.py
|   |-- common.py
|   |-- delegator_actions_sequence.py
|   |-- delegator_frequency.py
|   |-- fee_change_event_timeline.py
|   |-- fee_distribution.py
|   |-- fee_vs_delegations.py
|   |-- fee_vs_voting_power.py
|   |-- gbmt_export.py
|   |-- latest_validator_stake.py
|   |-- stake_fee_migration.py
|   |-- top_pool_delegators.py
|   `-- validator_wealth_delegations.py
|-- iota_stake_ownership/
|   |-- config.py
|   |-- graphql_client.py
|   |-- json_rpc_client.py
|   |-- schema.py
|   `-- strict_ownership.py
|-- outputs/
|   |-- data/
|   `-- figures/
|-- tests/
|   `-- test_strict_ownership.py
`-- tools/
    |-- __init__.py
    |-- _bootstrap.py
    |-- generate_analysis_outputs.py
    |-- ingest_delegation_events.py
    |-- ingest_validator_actions.py
    |-- ingest_validator_owned_stake_objects.py
    |-- ingest_validator_snapshots.py
    |-- ingest_validator_stake_object_history.py
    |-- rebuild_database.py
    |-- reconstruct_ownership.py
    `-- smoke_checks.py
```

The old `sql/` folder was removed because exploratory SQL snippets were no longer part of the maintained workflow.

## Configuration

Configuration lives in:

```text
iota_stake_ownership/config.py
```

Default values:

```text
IOTA_GRAPHQL_URL     = https://graphql.mainnet.iota.cafe
IOTA_JSON_RPC_URL    = https://api.mainnet.iota.cafe
IOTA_INDEXER_RPC_URL = https://indexer.mainnet.iota.cafe
IOTA_DB_NAME         = IOTA_history
IOTA_DB_USER         = postgres
IOTA_DB_PASSWORD     = Calpezta1!
IOTA_DB_HOST         = localhost
IOTA_DB_PORT         = 5432
```

Environment variables can override each value:

```powershell
$env:IOTA_DB_NAME='IOTA_history'
$env:IOTA_DB_USER='postgres'
$env:IOTA_DB_PASSWORD='your_password'
$env:IOTA_DB_HOST='localhost'
$env:IOTA_DB_PORT='5432'
$env:IOTA_GRAPHQL_URL='https://graphql.mainnet.iota.cafe'
$env:IOTA_JSON_RPC_URL='https://api.mainnet.iota.cafe'
$env:IOTA_INDEXER_RPC_URL='https://indexer.mainnet.iota.cafe'
```

## Database Schema

Schema creation and migrations are centralized in:

```text
iota_stake_ownership/schema.py
```

Run:

```powershell
python -m iota_stake_ownership.schema
```

### `validator_snapshots`

One row per validator per epoch.

Primary key:

```text
(epoch_id, validator_address)
```

Main columns:

| Column | Meaning |
|---|---|
| `epoch_id` | IOTA epoch |
| `validator_address` | Validator address |
| `voting_power` | Validator voting power percentage |
| `total_stake` | Total validator pool stake in whole IOTA |
| `own_stake` | Validator-owned stake in whole IOTA |
| `delegated_stake` | `total_stake - own_stake` |
| `applied_fee` | Protocol commission rate |
| `effective_fee` | Effective fee used in analysis |
| `validator_reward` | Reward pool amount in whole IOTA |
| `global_tallying_score` | Validator performance/report score |
| `pool_id` | Staking pool object id |

### `delegation_events`

One row per staking or unstaking transaction digest.

Primary key:

```text
event_id
```

Project rule:

```text
event_id = transaction digest
```

Main columns:

| Column | Meaning |
|---|---|
| `event_id` | Transaction digest |
| `delegator_address` | Address that staked or unstaked |
| `validator_address` | Validator selected by the delegator |
| `pool_id` | Pool id reported by the event |
| `epoch_id` | Staking or unstaking epoch |
| `timestamp` | Event timestamp |
| `event_type` | `Stake` or `Unstake` |
| `staked_amount` | Principal amount in whole IOTA |
| `realized_revenue` | Reward amount on unstake, in whole IOTA |

### `validator_actions`

One row per validator fee-change or report transaction digest.

Primary key:

```text
event_id
```

Main columns:

| Column | Meaning |
|---|---|
| `event_id` | Transaction digest |
| `validator_address` | Validator that changed fee or reporter address |
| `epoch_id` | Epoch |
| `timestamp` | Event timestamp |
| `action_type` | `Fee Change` or `Report` |
| `target_validator` | Report target when action is `Report` |
| `old_value` | Old fee value |
| `new_value` | New fee value |

### `validator_owned_stake_objects`

Current explorer-style fallback table.

It stores the staking objects currently owned by validator addresses, fetched from GraphQL:

```text
address.stakedIotas
address.objects
```

This table is useful for matching the explorer's current address page, but it cannot see objects that were owned in the past and later unstaked or transferred.

### `validator_owned_stake_snapshots`

Derived per-epoch ownership table.

Primary key:

```text
(epoch_id, validator_address)
```

This is the handoff table used by `tools/reconstruct_ownership.py`.

It is populated from:

1. Complete historical object intervals, when available.
2. Current explorer-style owned objects, when no complete history scan exists.
3. Strict self-delegation event fallback, only when no object snapshot exists.

### `validator_stake_object_intervals`

Historical object ownership intervals.

Each row says that a validator address owned one `StakedIota` or `TimelockedStakedIota` object for a period of time.

Primary key:

```text
(object_id, validator_address, interval_start_tx)
```

Important columns:

| Column | Meaning |
|---|---|
| `object_id` | Stake receipt object id |
| `validator_address` | Address that owned the receipt |
| `object_type` | `staked_iota` or `timelocked_staked_iota` |
| `pool_id` | Validator pool id stored in the receipt |
| `principal_mist` | Principal in MIST |
| `principal` | Principal in whole IOTA |
| `activation_epoch` | Epoch when stake becomes active |
| `start_epoch` | Epoch when ownership interval starts |
| `end_epoch` | Epoch when ownership interval ends |
| `end_reason` | Usually `deleted`, `wrapped`, or `transferred` |
| `past_object_status` | RPC recovery status |

### `validator_stake_object_history_scan_status`

Tracks historical object scan status per validator.

Important columns:

| Column | Meaning |
|---|---|
| `validator_address` | Validator address |
| `scanned_at` | Last scan time |
| `tx_count` | Number of address-related transactions scanned |
| `interval_count` | Number of reconstructed intervals |
| `unresolved_count` | Objects that could not be resolved |
| `scan_complete` | True only when the full address scan completed |
| `last_error` | Last JSON-RPC/indexer error |

Only complete scans are used for historical object ownership reconstruction.

## Ownership Rule

Validator ownership is strict.

```text
validator-owned stake = stake receipt object owned by the validator address
```

No wallet aliases are used. No adjusted ownership is used. If a validator controls another wallet, that wallet is not counted unless it is the validator address itself.

The final values are:

```text
own_stake = validator-owned stake
delegated_stake = total_stake - own_stake
```

The update caps `own_stake` between `0` and `total_stake` so delegated stake cannot become negative.

## Historical Object Ownership Process

Historical ownership is implemented in:

```text
tools/ingest_validator_stake_object_history.py
```

Process:

1. Query indexer transactions where the validator address receives objects:

```text
iotax_queryTransactionBlocks filter = { "ToAddress": validator_address }
```

2. Query indexer transactions where the validator address sends objects:

```text
iotax_queryTransactionBlocks filter = { "FromAddress": validator_address }
```

3. Parse transaction `objectChanges` for:

```text
0x3::staking_pool::StakedIota
0x3::timelocked_staking::TimelockedStakedIota
```

4. For created or transferred-in objects, fetch the exact historical object version:

```text
iota_tryGetPastObject(object_id, version)
```

5. Open an ownership interval with object id, pool id, principal, owner, activation epoch, and start epoch.

6. For deleted, wrapped, or transferred-out objects, close the interval.

7. If an old object version is unavailable from public RPC, recover the interval from `UnstakingRequestEvent` when possible. The event contains pool id, principal, activation epoch, staker address, unstaking epoch, and validator address.

8. Expand intervals into `validator_owned_stake_snapshots`.

An interval counts in epoch `e` when:

```text
max(activation_epoch, start_epoch) <= e
and
(end_epoch is null or end_epoch > e)
```

## Ingestion Workflow

### Full Rebuild

Full rebuild from epoch 0:

```powershell
python tools/rebuild_database.py --start-epoch 0
```

This can take a long time because historical object scanning requires JSON-RPC/indexer pagination per validator address.

### Recommended Incremental Update

When the database already contains old data and only newer epochs are needed:

```powershell
python tools/ingest_validator_snapshots.py --start-epoch 380
python tools/ingest_delegation_events.py --start-epoch 380
python tools/ingest_validator_actions.py --start-epoch 380
python tools/ingest_validator_stake_object_history.py --snapshots-only
python tools/reconstruct_ownership.py
python tools/generate_analysis_outputs.py
```

`--start-epoch` on event/action ingestion uses backward GraphQL pagination. The scripts start from the newest events and stop when pages fall below the requested epoch.

### Faster Pipeline Command

This avoids full historical object rescanning and reuses stored complete scans:

```powershell
python tools/rebuild_database.py --start-epoch 380 --skip-owned-objects --skip-object-history
python tools/ingest_validator_stake_object_history.py --snapshots-only
python tools/reconstruct_ownership.py
python tools/generate_analysis_outputs.py
```

## Output Files

Generated figures are stored in:

```text
outputs/figures/
```

Current figure filenames:

| File | Description |
|---|---|
| `latest_validator_own_vs_delegated.png` | Latest-epoch stacked own/delegated stake for all validators |
| `validator_wealth_and_delegation_counts.png` | Latest-epoch stake plus historical delegation counts |
| `delegator_action_frequency.png` | Distribution of delegator interaction counts |
| `fee_distribution.png` | Distribution of nominal/effective fees over recent epochs |
| `stake_fee_migration.png` | Delegated stake and fee trends for top validators |
| `fee_vs_voting_power_top_validators.png` | Fee versus voting power for top validators |
| `fee_vs_delegations_top_validators.png` | Fee versus number of delegation events |
| `delegator_action_sequences.png` | Action sequence for active multi-validator delegators |
| `top_pool_delegators_first.png` | Delegator balances for the largest pool |
| `top_pool_delegators_second.png` | Delegator balances for the second largest pool |
| `top_pool_delegators_third.png` | Delegator balances for the third largest pool |
| `top_pool_delegators_fourth.png` | Delegator balances for the fourth largest pool |
| `top_pool_delegators_fifth.png` | Delegator balances for the fifth largest pool |
| `fee_change_event_timeline.png` | Stake/unstake activity around the largest fee changes |

Generated CSV files are stored in:

```text
outputs/data/
```

Current CSV filenames:

| File | Description |
|---|---|
| `validator_snapshots.csv` | Full export of `validator_snapshots` |
| `validator_actions.csv` | Full export of `validator_actions` |
| `delegation_events.csv` | Full export of `delegation_events` |
| `delegator_trajectory_long.csv` | Long-format delegator trajectory dataset for GBMT/R workflows |
| `top_pool_delegator_balances.csv` | Net delegator balances for top pools |
| `fee_change_event_timeline.csv` | Data behind the fee-change event timeline graph |

## Source File Reference

### Root

#### `README.md`

Project documentation and operational guide.

### `iota_stake_ownership/`

#### `iota_stake_ownership/config.py`

Central configuration for endpoints, database credentials, and MIST-to-IOTA conversion.

#### `iota_stake_ownership/graphql_client.py`

Small GraphQL HTTP client with retry handling and 429 backoff. Used by snapshot, event, action, and current-object ingesters.

#### `iota_stake_ownership/json_rpc_client.py`

Small JSON-RPC HTTP client with retry handling. Used by historical object ownership scanning.

#### `iota_stake_ownership/schema.py`

Creates and updates all PostgreSQL tables and indexes used by the project. Also removes obsolete columns/tables from previous designs.

#### `iota_stake_ownership/strict_ownership.py`

Pure helper logic and test target for strict event-based ownership fallback.

### `tools/`

#### `tools/__init__.py`

Marks `tools/` as an importable Python package.

#### `tools/_bootstrap.py`

Adds the repository root to `sys.path` so command-line scripts can import project modules reliably when run from the `tools/` directory or project root.

#### `tools/ingest_validator_snapshots.py`

Ingests active validator snapshots from GraphQL, one epoch at a time. It writes to `validator_snapshots` using `(epoch_id, validator_address)` as the upsert key.

#### `tools/ingest_delegation_events.py`

Ingests `StakingRequestEvent` and `UnstakingRequestEvent` records from GraphQL into `delegation_events`.

Supports:

```powershell
python tools/ingest_delegation_events.py --start-epoch 380
```

When `--start-epoch` is used, the script paginates backward from newest events and stops once it reaches older epochs.

#### `tools/ingest_validator_actions.py`

Ingests validator epoch information events from GraphQL. It updates fee and tallying score fields on `validator_snapshots` and records fee changes/reports in `validator_actions`.

Supports:

```powershell
python tools/ingest_validator_actions.py --start-epoch 380
```

#### `tools/ingest_validator_owned_stake_objects.py`

Fetches currently owned `StakedIota` and `TimelockedStakedIota` objects for validator addresses from GraphQL. This is the explorer-style fallback source for current object ownership.

#### `tools/ingest_validator_stake_object_history.py`

Builds historical validator-owned stake object intervals from JSON-RPC/indexer transaction history. It can also rebuild per-epoch owned-stake snapshots from already stored intervals:

```powershell
python tools/ingest_validator_stake_object_history.py --snapshots-only
```

#### `tools/reconstruct_ownership.py`

Writes final `own_stake` and `delegated_stake` into `validator_snapshots`.

Priority order:

1. `validator_owned_stake_snapshots`
2. strict self-delegation event fallback

#### `tools/rebuild_database.py`

Pipeline wrapper that runs the main ingestion and reconstruction steps. It accepts skip flags so expensive steps can be avoided during incremental work.

Useful incremental command:

```powershell
python tools/rebuild_database.py --start-epoch 380 --skip-owned-objects --skip-object-history
```

#### `tools/generate_analysis_outputs.py`

Main output command. It exports core CSVs, generates all figures, exports top-pool and fee-change analysis CSVs, and writes the GBMT long dataset.

#### `tools/smoke_checks.py`

Checks database row counts, negative delegated stake, ownership reconciliation, and optional graph generation.

### `analysis_outputs/`

#### `analysis_outputs/__init__.py`

Marks `analysis_outputs/` as an importable package.

#### `analysis_outputs/common.py`

Shared plotting configuration, output directories, database connection helper, `save_figure()`, address shortening, and core table CSV export.

#### `analysis_outputs/gbmt_export.py`

Exports `delegator_trajectory_long.csv`, a long-format dataset suitable for later GBMT/R workflow experiments.

#### `analysis_outputs/latest_validator_stake.py`

Generates `latest_validator_own_vs_delegated.png`, a stacked latest-epoch own/delegated stake chart for all validators.

#### `analysis_outputs/validator_wealth_delegations.py`

Generates `validator_wealth_and_delegation_counts.png`, combining stake composition and historical received delegation count.

#### `analysis_outputs/delegator_frequency.py`

Generates `delegator_action_frequency.png`, showing how many delegators interacted once, twice, and so on.

#### `analysis_outputs/fee_distribution.py`

Generates `fee_distribution.png`, showing recent nominal and effective fee distributions.

#### `analysis_outputs/stake_fee_migration.py`

Generates `stake_fee_migration.png`, showing delegated stake and fee trends for top validators.

#### `analysis_outputs/fee_vs_voting_power.py`

Generates `fee_vs_voting_power_top_validators.png`, comparing fees and voting power over time.

#### `analysis_outputs/fee_vs_delegations.py`

Generates `fee_vs_delegations_top_validators.png`, comparing fee changes with new stake event counts.

#### `analysis_outputs/delegator_actions_sequence.py`

Generates `delegator_action_sequences.png`, showing selected delegators' stake/unstake movement across validators.

#### `analysis_outputs/top_pool_delegators.py`

Generates five top-pool delegator charts:

```text
top_pool_delegators_first.png
top_pool_delegators_second.png
top_pool_delegators_third.png
top_pool_delegators_fourth.png
top_pool_delegators_fifth.png
```

Also exports:

```text
outputs/data/top_pool_delegator_balances.csv
```

#### `analysis_outputs/fee_change_event_timeline.py`

Generates `fee_change_event_timeline.png`, a faceted timeline of stake and unstake counts around the largest fee increases and decreases.

Also exports:

```text
outputs/data/fee_change_event_timeline.csv
```

### `tests/`

#### `tests/test_strict_ownership.py`

Unit tests for strict event-based ownership fallback. It verifies self-stake, third-party stake, and self-unstake behavior.

### `outputs/`

#### `outputs/data/`

Generated CSV export folder. Files can be regenerated with:

```powershell
python tools/generate_analysis_outputs.py
```

#### `outputs/figures/`

Generated PNG figure folder. Files can be regenerated with:

```powershell
python tools/generate_analysis_outputs.py
```

## Verification Commands

Run schema setup:

```powershell
python -m iota_stake_ownership.schema
```

Run ownership reconstruction:

```powershell
python tools/reconstruct_ownership.py
```

Run smoke checks:

```powershell
python tools/smoke_checks.py
```

Run tests:

```powershell
python -m unittest discover -s tests -v
```

Generate all outputs:

```powershell
python tools/generate_analysis_outputs.py
```

## Known Limitations

1. Public JSON-RPC nodes may prune old object versions. The code recovers many deleted stake objects from unstaking events, but a fully archival provider would be stronger for long-term exactness.
2. `event_id = transaction digest`, so multiple event records in the same transaction cannot be stored as separate rows in `delegation_events` or `validator_actions`.
3. Ownership attribution is strict. Separate wallets controlled by a validator are not counted as validator-owned.
