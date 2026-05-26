import psycopg2

from iota_stake_ownership.config import DB_PARAMS


SCHEMA_SQL = """
DROP VIEW IF EXISTS validator_epoch_ownership_with_fees;
DROP TABLE IF EXISTS validator_epoch_ownership;
DROP TABLE IF EXISTS validator_wallet_aliases;
DROP TABLE IF EXISTS stake_receipt_owner_history;
DROP TABLE IF EXISTS stake_receipts;
DROP INDEX IF EXISTS idx_delegation_events_event_key;
DROP INDEX IF EXISTS idx_validator_actions_event_key;

CREATE TABLE IF NOT EXISTS validator_snapshots (
    epoch_id INTEGER NOT NULL,
    validator_address VARCHAR NOT NULL,
    voting_power NUMERIC,
    total_stake BIGINT,
    own_stake BIGINT,
    delegated_stake BIGINT,
    applied_fee NUMERIC,
    effective_fee NUMERIC,
    validator_reward BIGINT,
    global_tallying_score INTEGER,
    pool_id VARCHAR,
    PRIMARY KEY (epoch_id, validator_address)
);

CREATE TABLE IF NOT EXISTS delegation_events (
    event_id VARCHAR PRIMARY KEY,
    delegator_address VARCHAR,
    validator_address VARCHAR,
    pool_id VARCHAR,
    epoch_id INTEGER,
    timestamp TIMESTAMP,
    event_type VARCHAR,
    staked_amount BIGINT,
    realized_revenue BIGINT
);

CREATE TABLE IF NOT EXISTS validator_actions (
    event_id VARCHAR PRIMARY KEY,
    validator_address VARCHAR,
    epoch_id INTEGER,
    timestamp TIMESTAMP,
    action_type VARCHAR,
    target_validator VARCHAR,
    old_value VARCHAR,
    new_value VARCHAR
);

CREATE TABLE IF NOT EXISTS validator_owned_stake_objects (
    object_id VARCHAR PRIMARY KEY,
    validator_address VARCHAR NOT NULL,
    pool_id VARCHAR NOT NULL,
    object_type VARCHAR NOT NULL,
    principal_mist NUMERIC(40, 0),
    principal BIGINT NOT NULL,
    requested_epoch INTEGER,
    activated_epoch INTEGER,
    stake_status VARCHAR,
    object_version BIGINT,
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS validator_owned_stake_snapshots (
    epoch_id INTEGER NOT NULL,
    validator_address VARCHAR NOT NULL,
    pool_id VARCHAR,
    staked_iota_amount_mist NUMERIC(40, 0) NOT NULL DEFAULT 0,
    staked_iota_amount BIGINT NOT NULL DEFAULT 0,
    timelocked_staked_iota_amount_mist NUMERIC(40, 0) NOT NULL DEFAULT 0,
    timelocked_staked_iota_amount BIGINT NOT NULL DEFAULT 0,
    total_owned_stake_mist NUMERIC(40, 0) NOT NULL DEFAULT 0,
    total_owned_stake BIGINT NOT NULL DEFAULT 0,
    staked_iota_objects INTEGER NOT NULL DEFAULT 0,
    timelocked_staked_iota_objects INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT now(),
    PRIMARY KEY (epoch_id, validator_address)
);

CREATE TABLE IF NOT EXISTS validator_owned_stake_refresh_status (
    validator_address VARCHAR PRIMARY KEY,
    refreshed_at TIMESTAMP DEFAULT now(),
    object_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS validator_stake_object_intervals (
    object_id VARCHAR NOT NULL,
    validator_address VARCHAR NOT NULL,
    interval_start_tx VARCHAR NOT NULL,
    object_type VARCHAR NOT NULL,
    pool_id VARCHAR,
    principal_mist NUMERIC(40, 0),
    principal BIGINT NOT NULL DEFAULT 0,
    activation_epoch INTEGER,
    start_epoch INTEGER NOT NULL,
    start_checkpoint BIGINT,
    start_version BIGINT,
    end_epoch INTEGER,
    end_checkpoint BIGINT,
    end_tx VARCHAR,
    end_version BIGINT,
    end_reason VARCHAR,
    past_object_status VARCHAR,
    updated_at TIMESTAMP DEFAULT now(),
    PRIMARY KEY (object_id, validator_address, interval_start_tx)
);

CREATE TABLE IF NOT EXISTS validator_stake_object_history_scan_status (
    validator_address VARCHAR PRIMARY KEY,
    scanned_at TIMESTAMP DEFAULT now(),
    tx_count INTEGER NOT NULL DEFAULT 0,
    interval_count INTEGER NOT NULL DEFAULT 0,
    unresolved_count INTEGER NOT NULL DEFAULT 0,
    scan_complete BOOLEAN NOT NULL DEFAULT TRUE,
    last_error TEXT
);

ALTER TABLE validator_snapshots DROP COLUMN IF EXISTS total_stake_mist;
ALTER TABLE validator_snapshots DROP COLUMN IF EXISTS validator_reward_mist;
ALTER TABLE validator_snapshots DROP COLUMN IF EXISTS known_receipt_stake;
ALTER TABLE validator_snapshots DROP COLUMN IF EXISTS known_receipt_stake_mist;
ALTER TABLE validator_snapshots DROP COLUMN IF EXISTS unexplained_stake;
ALTER TABLE validator_snapshots DROP COLUMN IF EXISTS unexplained_stake_mist;
ALTER TABLE validator_snapshots DROP COLUMN IF EXISTS own_stake_strict;
ALTER TABLE validator_snapshots DROP COLUMN IF EXISTS own_stake_adjusted;
ALTER TABLE validator_snapshots DROP COLUMN IF EXISTS timelocked_stake;

ALTER TABLE delegation_events DROP COLUMN IF EXISTS tx_digest;
ALTER TABLE delegation_events DROP COLUMN IF EXISTS event_key;
ALTER TABLE delegation_events DROP COLUMN IF EXISTS event_seq;
ALTER TABLE delegation_events DROP COLUMN IF EXISTS staked_amount_mist;
ALTER TABLE delegation_events DROP COLUMN IF EXISTS realized_revenue_mist;
ALTER TABLE delegation_events DROP COLUMN IF EXISTS checkpoint;

ALTER TABLE validator_actions DROP COLUMN IF EXISTS tx_digest;
ALTER TABLE validator_actions DROP COLUMN IF EXISTS event_key;

ALTER TABLE validator_owned_stake_objects ADD COLUMN IF NOT EXISTS principal_mist NUMERIC(40, 0);
ALTER TABLE validator_owned_stake_snapshots ADD COLUMN IF NOT EXISTS staked_iota_amount_mist NUMERIC(40, 0) NOT NULL DEFAULT 0;
ALTER TABLE validator_owned_stake_snapshots ADD COLUMN IF NOT EXISTS timelocked_staked_iota_amount_mist NUMERIC(40, 0) NOT NULL DEFAULT 0;
ALTER TABLE validator_owned_stake_snapshots ADD COLUMN IF NOT EXISTS total_owned_stake_mist NUMERIC(40, 0) NOT NULL DEFAULT 0;
ALTER TABLE validator_stake_object_history_scan_status ADD COLUMN IF NOT EXISTS scan_complete BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_validator_snapshots_epoch
    ON validator_snapshots(epoch_id);
CREATE INDEX IF NOT EXISTS idx_validator_snapshots_validator
    ON validator_snapshots(validator_address, epoch_id);
CREATE INDEX IF NOT EXISTS idx_delegation_events_validator_epoch
    ON delegation_events(validator_address, epoch_id);
CREATE INDEX IF NOT EXISTS idx_delegation_events_delegator_epoch
    ON delegation_events(delegator_address, epoch_id);
CREATE INDEX IF NOT EXISTS idx_validator_actions_validator_epoch
    ON validator_actions(validator_address, epoch_id);
CREATE INDEX IF NOT EXISTS idx_validator_owned_objects_validator_epoch
    ON validator_owned_stake_objects(validator_address, activated_epoch);
CREATE INDEX IF NOT EXISTS idx_validator_owned_snapshots_validator_epoch
    ON validator_owned_stake_snapshots(validator_address, epoch_id);
CREATE INDEX IF NOT EXISTS idx_validator_stake_intervals_validator_epoch
    ON validator_stake_object_intervals(validator_address, start_epoch, end_epoch);
CREATE INDEX IF NOT EXISTS idx_validator_stake_intervals_object
    ON validator_stake_object_intervals(object_id);

INSERT INTO validator_owned_stake_refresh_status (validator_address, object_count, refreshed_at)
SELECT validator_address, COUNT(*), now()
FROM validator_owned_stake_objects
GROUP BY validator_address
ON CONFLICT (validator_address) DO NOTHING;
"""


def ensure_schema():
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cursor:
            cursor.execute(SCHEMA_SQL)
        conn.commit()


if __name__ == "__main__":
    ensure_schema()
    print("Schema ready.")
