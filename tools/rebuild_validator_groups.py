import argparse

import psycopg2
from psycopg2.extras import Json

import _bootstrap  # noqa: F401
from iota_stake_ownership.config import DB_PARAMS
from iota_stake_ownership.schema import ensure_schema
from iota_stake_ownership.validator_identity import (
    MIN_COMMISSION_ACTIVATION_EPOCH,
    build_validator_identity_mapping,
)


def connect_db():
    return psycopg2.connect(**DB_PARAMS)


def load_name_history(cursor):
    cursor.execute(
        """
        SELECT validator_address, epoch_id, validator_name
        FROM validator_snapshots
        WHERE validator_name IS NOT NULL
          AND BTRIM(validator_name) <> ''
        ORDER BY validator_address, epoch_id;
        """
    )
    return cursor.fetchall()


def rebuild_validator_identities(cursor):
    mapping = build_validator_identity_mapping(load_name_history(cursor))
    cursor.execute("TRUNCATE validator_identities;")
    for address, identity in mapping.items():
        cursor.execute(
            """
            INSERT INTO validator_identities
                (validator_address, validator_name, validator_group, first_epoch,
                 last_epoch, names_seen, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, now());
            """,
            (
                address,
                identity["validator_name"],
                identity["validator_group"],
                identity["first_epoch"],
                identity["last_epoch"],
                Json(identity["names_seen"]),
            ),
        )
    return len(mapping)


def recompute_address_effective_fees(cursor):
    cursor.execute(
        """
        UPDATE validator_snapshots
        SET
            effective_fee = CASE
                WHEN epoch_id < %s THEN COALESCE(applied_fee, 0)
                ELSE GREATEST(COALESCE(applied_fee, 0), COALESCE(voting_power, 0))
            END,
            effective_fee_rule = CASE
                WHEN epoch_id < %s THEN 'nominal'
                ELSE 'voting_power_floor'
            END;
        """,
        (MIN_COMMISSION_ACTIVATION_EPOCH, MIN_COMMISSION_ACTIVATION_EPOCH),
    )


def rebuild_group_snapshots(cursor):
    cursor.execute("TRUNCATE validator_group_snapshots;")
    cursor.execute(
        """
        WITH members AS (
            SELECT
                vs.*,
                COALESCE(vi.validator_group, vs.validator_name, vs.validator_address) AS validator_group,
                GREATEST(COALESCE(vs.delegated_stake, 0), 0) AS fee_weight
            FROM validator_snapshots vs
            LEFT JOIN validator_identities vi
              ON vi.validator_address = vs.validator_address
        ),
        grouped AS (
            SELECT
                epoch_id,
                validator_group,
                COUNT(*) AS member_count,
                ARRAY_AGG(validator_address ORDER BY validator_address) AS member_addresses,
                ARRAY_AGG(COALESCE(validator_name, validator_address) ORDER BY validator_address) AS member_names,
                SUM(COALESCE(voting_power, 0)) AS voting_power,
                SUM(COALESCE(total_stake, 0))::bigint AS total_stake,
                SUM(COALESCE(own_stake, 0))::bigint AS own_stake,
                SUM(COALESCE(delegated_stake, 0))::bigint AS delegated_stake,
                COALESCE(
                    SUM(COALESCE(applied_fee, 0) * fee_weight) / NULLIF(SUM(fee_weight), 0),
                    AVG(COALESCE(applied_fee, 0))
                ) AS nominal_fee,
                COALESCE(
                    SUM(COALESCE(effective_fee, 0) * fee_weight) / NULLIF(SUM(fee_weight), 0),
                    AVG(COALESCE(effective_fee, 0))
                ) AS network_effective_fee,
                SUM(COALESCE(validator_reward, 0))::bigint AS validator_reward
            FROM members
            GROUP BY epoch_id, validator_group
        )
        INSERT INTO validator_group_snapshots
            (epoch_id, validator_group, member_count, member_addresses, member_names,
             voting_power, total_stake, own_stake, delegated_stake, nominal_fee,
             network_effective_fee, identity_adjusted_effective_fee,
             effective_fee_rule, validator_reward, updated_at)
        SELECT
            epoch_id,
            validator_group,
            member_count,
            member_addresses,
            member_names,
            voting_power,
            total_stake,
            own_stake,
            delegated_stake,
            nominal_fee,
            network_effective_fee,
            CASE
                WHEN epoch_id < %s THEN nominal_fee
                ELSE GREATEST(nominal_fee, voting_power)
            END,
            CASE
                WHEN epoch_id < %s THEN 'nominal'
                ELSE 'group_voting_power_floor'
            END,
            validator_reward,
            now()
        FROM grouped;
        """,
        (MIN_COMMISSION_ACTIVATION_EPOCH, MIN_COMMISSION_ACTIVATION_EPOCH),
    )
    return cursor.rowcount


def rebuild_validator_groups():
    ensure_schema()
    with connect_db() as conn:
        with conn.cursor() as cursor:
            identity_count = rebuild_validator_identities(cursor)
            recompute_address_effective_fees(cursor)
            group_snapshot_count = rebuild_group_snapshots(cursor)
        conn.commit()
    return {
        "validator_identities": identity_count,
        "validator_group_snapshots": group_snapshot_count,
        "activation_epoch": MIN_COMMISSION_ACTIVATION_EPOCH,
    }


def main():
    parser = argparse.ArgumentParser(description="Rebuild validator identities and grouped epoch snapshots.")
    parser.parse_args()
    print(rebuild_validator_groups())


if __name__ == "__main__":
    main()
