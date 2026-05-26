import argparse
import time

import psycopg2

import _bootstrap  # noqa: F401
from iota_stake_ownership.config import DB_PARAMS, mist_to_iota_int
from iota_stake_ownership.graphql_client import graphql_request
from iota_stake_ownership.schema import ensure_schema


STAKED_IOTAS_QUERY = """
query ValidatorStakedIotas($address: IotaAddress!, $cursor: String) {
  address(address: $address) {
    stakedIotas(first: 50, after: $cursor) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        address
        version
        poolId
        principal
        stakeStatus
        requestedEpoch { epochId }
        activatedEpoch { epochId }
      }
    }
  }
}
"""


OBJECTS_QUERY = """
query ValidatorObjects($address: IotaAddress!, $cursor: String) {
  address(address: $address) {
    objects(first: 50, after: $cursor) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        address
        version
        contents {
          type { repr }
          json
        }
      }
    }
  }
}
"""


def connect_db():
    return psycopg2.connect(**DB_PARAMS)


def epoch_id(epoch_node):
    if not epoch_node:
        return None
    value = epoch_node.get("epochId")
    return int(value) if value is not None else None


def load_validators(cursor, limit=None, missing_only=False):
    missing_filter = """
        AND NOT EXISTS (
            SELECT 1
            FROM validator_owned_stake_refresh_status status
            WHERE status.validator_address = latest.validator_address
        )
    """ if missing_only else ""
    cursor.execute(
        f"""
        WITH latest AS (
            SELECT DISTINCT ON (validator_address)
                validator_address,
                pool_id
            FROM validator_snapshots
            WHERE pool_id IS NOT NULL
            ORDER BY validator_address, epoch_id DESC
        )
        SELECT validator_address, pool_id
        FROM latest
        WHERE pool_id IS NOT NULL
        {missing_filter}
        ORDER BY validator_address
        LIMIT %s;
        """,
        (limit,),
    )
    return cursor.fetchall()


def load_one_validator(cursor, validator_address):
    cursor.execute(
        """
        SELECT pool_id
        FROM validator_snapshots
        WHERE validator_address = %s
          AND pool_id IS NOT NULL
        ORDER BY epoch_id DESC
        LIMIT 1;
        """,
        (validator_address,),
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"Validator address not found in validator_snapshots: {validator_address}")
    return [(validator_address, row[0])]


def fetch_standard_staked_iotas(address):
    cursor = None
    has_next = True
    objects = []
    while has_next:
        data = graphql_request(STAKED_IOTAS_QUERY, {"address": address, "cursor": cursor})
        connection = ((data.get("address") or {}).get("stakedIotas")) or {}
        for node in connection.get("nodes") or []:
            principal = int(node.get("principal") or 0)
            objects.append(
                {
                    "object_id": node["address"],
                    "validator_address": address,
                    "pool_id": node.get("poolId"),
                    "object_type": "staked_iota",
                    "principal_mist": principal,
                    "principal": mist_to_iota_int(principal),
                    "requested_epoch": epoch_id(node.get("requestedEpoch")),
                    "activated_epoch": epoch_id(node.get("activatedEpoch")),
                    "stake_status": node.get("stakeStatus"),
                    "object_version": int(node["version"]) if node.get("version") is not None else None,
                }
            )
        page_info = connection.get("pageInfo") or {}
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        time.sleep(0.1)
    return objects


def parse_timelocked_object(address, node):
    contents = node.get("contents") or {}
    type_repr = ((contents.get("type") or {}).get("repr")) or ""
    if "::timelocked_staking::TimelockedStakedIota" not in type_repr:
        return None

    data = contents.get("json") or {}
    staked = data.get("staked_iota") or {}
    principal = (staked.get("principal") or {}).get("value")
    if principal is None:
        return None

    activation_epoch = staked.get("stake_activation_epoch")
    return {
        "object_id": node["address"],
        "validator_address": address,
        "pool_id": staked.get("pool_id"),
        "object_type": "timelocked_staked_iota",
        "principal_mist": int(principal),
        "principal": mist_to_iota_int(principal),
        "requested_epoch": None,
        "activated_epoch": int(activation_epoch) if activation_epoch is not None else None,
        "stake_status": "ACTIVE",
        "object_version": int(node["version"]) if node.get("version") is not None else None,
    }


def fetch_timelocked_staked_iotas(address):
    cursor = None
    has_next = True
    objects = []
    while has_next:
        data = graphql_request(OBJECTS_QUERY, {"address": address, "cursor": cursor})
        connection = ((data.get("address") or {}).get("objects")) or {}
        for node in connection.get("nodes") or []:
            parsed = parse_timelocked_object(address, node)
            if parsed:
                objects.append(parsed)
        page_info = connection.get("pageInfo") or {}
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        time.sleep(0.1)
    return objects


def upsert_objects(cursor, objects):
    for obj in objects:
        cursor.execute(
            """
            INSERT INTO validator_owned_stake_objects
                (object_id, validator_address, pool_id, object_type, principal_mist, principal,
                 requested_epoch, activated_epoch, stake_status, object_version, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (object_id) DO UPDATE SET
                validator_address = EXCLUDED.validator_address,
                pool_id = EXCLUDED.pool_id,
                object_type = EXCLUDED.object_type,
                principal_mist = EXCLUDED.principal_mist,
                principal = EXCLUDED.principal,
                requested_epoch = EXCLUDED.requested_epoch,
                activated_epoch = EXCLUDED.activated_epoch,
                stake_status = EXCLUDED.stake_status,
                object_version = EXCLUDED.object_version,
                updated_at = now();
            """,
            (
                obj["object_id"],
                obj["validator_address"],
                obj["pool_id"],
                obj["object_type"],
                obj["principal_mist"],
                obj["principal"],
                obj["requested_epoch"],
                obj["activated_epoch"],
                obj["stake_status"],
                obj["object_version"],
            ),
        )


def rebuild_snapshots_from_objects(cursor):
    cursor.execute("TRUNCATE validator_owned_stake_snapshots;")
    cursor.execute(
        """
        INSERT INTO validator_owned_stake_snapshots
            (epoch_id, validator_address, pool_id, staked_iota_amount_mist, staked_iota_amount,
             timelocked_staked_iota_amount_mist, timelocked_staked_iota_amount,
             total_owned_stake_mist, total_owned_stake,
             staked_iota_objects, timelocked_staked_iota_objects, updated_at)
        SELECT
            vs.epoch_id,
            vs.validator_address,
            vs.pool_id,
            COALESCE(SUM(COALESCE(vo.principal_mist, vo.principal::numeric * 1000000000)) FILTER (WHERE vo.object_type = 'staked_iota'), 0) AS staked_iota_amount_mist,
            FLOOR(COALESCE(SUM(COALESCE(vo.principal_mist, vo.principal::numeric * 1000000000)) FILTER (WHERE vo.object_type = 'staked_iota'), 0) / 1000000000)::bigint AS staked_iota_amount,
            COALESCE(SUM(COALESCE(vo.principal_mist, vo.principal::numeric * 1000000000)) FILTER (WHERE vo.object_type = 'timelocked_staked_iota'), 0) AS timelocked_staked_iota_amount_mist,
            FLOOR(COALESCE(SUM(COALESCE(vo.principal_mist, vo.principal::numeric * 1000000000)) FILTER (WHERE vo.object_type = 'timelocked_staked_iota'), 0) / 1000000000)::bigint AS timelocked_staked_iota_amount,
            COALESCE(SUM(COALESCE(vo.principal_mist, vo.principal::numeric * 1000000000)), 0) AS total_owned_stake_mist,
            FLOOR(COALESCE(SUM(COALESCE(vo.principal_mist, vo.principal::numeric * 1000000000)), 0) / 1000000000)::bigint AS total_owned_stake,
            COALESCE(COUNT(*) FILTER (WHERE vo.object_type = 'staked_iota'), 0) AS staked_iota_objects,
            COALESCE(COUNT(*) FILTER (WHERE vo.object_type = 'timelocked_staked_iota'), 0) AS timelocked_staked_iota_objects,
            now()
        FROM validator_snapshots vs
        JOIN (
            SELECT validator_address
            FROM validator_owned_stake_refresh_status
        ) refreshed
          ON refreshed.validator_address = vs.validator_address
        LEFT JOIN validator_owned_stake_objects vo
          ON vo.validator_address = vs.validator_address
         AND vo.pool_id = vs.pool_id
         AND COALESCE(vo.activated_epoch, vo.requested_epoch, 0) <= vs.epoch_id
         AND COALESCE(vo.stake_status, 'ACTIVE') = 'ACTIVE'
        GROUP BY vs.epoch_id, vs.validator_address, vs.pool_id
        ON CONFLICT (epoch_id, validator_address) DO UPDATE SET
            pool_id = EXCLUDED.pool_id,
            staked_iota_amount_mist = EXCLUDED.staked_iota_amount_mist,
            staked_iota_amount = EXCLUDED.staked_iota_amount,
            timelocked_staked_iota_amount_mist = EXCLUDED.timelocked_staked_iota_amount_mist,
            timelocked_staked_iota_amount = EXCLUDED.timelocked_staked_iota_amount,
            total_owned_stake_mist = EXCLUDED.total_owned_stake_mist,
            total_owned_stake = EXCLUDED.total_owned_stake,
            staked_iota_objects = EXCLUDED.staked_iota_objects,
            timelocked_staked_iota_objects = EXCLUDED.timelocked_staked_iota_objects,
            updated_at = now();
        """
    )


def ingest_validator_owned_stake_objects(limit=None, validator_address=None, missing_only=False):
    ensure_schema()
    with connect_db() as conn:
        cursor = conn.cursor()
        validators = (
            load_one_validator(cursor, validator_address)
            if validator_address
            else load_validators(cursor, limit, missing_only=missing_only)
        )
        for index, (validator_address, pool_id) in enumerate(validators, start=1):
            standard = fetch_standard_staked_iotas(validator_address)
            timelocked = fetch_timelocked_staked_iotas(validator_address)
            owned_for_pool = [obj for obj in standard + timelocked if obj.get("pool_id") == pool_id]
            cursor.execute(
                "DELETE FROM validator_owned_stake_objects WHERE validator_address = %s;",
                (validator_address,),
            )
            upsert_objects(cursor, owned_for_pool)
            cursor.execute(
                """
                INSERT INTO validator_owned_stake_refresh_status
                    (validator_address, refreshed_at, object_count)
                VALUES (%s, now(), %s)
                ON CONFLICT (validator_address) DO UPDATE SET
                    refreshed_at = now(),
                    object_count = EXCLUDED.object_count;
                """,
                (validator_address, len(owned_for_pool)),
            )
            conn.commit()
            print(
                f"{index}/{len(validators)} {validator_address[:8]}... "
                f"standard={len(standard)} timelocked={len(timelocked)} matched_pool={len(owned_for_pool)}",
                end="\r",
            )
        rebuild_snapshots_from_objects(cursor)
        conn.commit()
        cursor.close()
    print("\nValidator-owned stake object snapshots complete.")


def main():
    parser = argparse.ArgumentParser(
        description="Ingest explorer-style validator-owned StakedIota and TimelockedStakedIota objects."
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit validators for smoke tests.")
    parser.add_argument("--validator-address", default=None, help="Refresh one validator address only.")
    parser.add_argument("--missing-only", action="store_true", help="Only ingest validators with no owned-object rows yet.")
    parser.add_argument(
        "--snapshots-only",
        action="store_true",
        help="Rebuild validator_owned_stake_snapshots from already stored objects without querying GraphQL.",
    )
    args = parser.parse_args()
    if args.snapshots_only:
        ensure_schema()
        with connect_db() as conn:
            cursor = conn.cursor()
            rebuild_snapshots_from_objects(cursor)
            conn.commit()
            cursor.close()
        print("Validator-owned stake snapshots rebuilt from stored objects.")
    else:
        ingest_validator_owned_stake_objects(
            limit=args.limit,
            validator_address=args.validator_address,
            missing_only=args.missing_only,
        )


if __name__ == "__main__":
    main()
