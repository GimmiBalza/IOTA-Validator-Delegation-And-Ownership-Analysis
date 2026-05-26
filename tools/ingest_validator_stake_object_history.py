import argparse
import time

import psycopg2

import _bootstrap  # noqa: F401
from iota_stake_ownership.config import DB_PARAMS, INDEXER_RPC_URL, JSON_RPC_URL, mist_to_iota_int
from iota_stake_ownership.json_rpc_client import JsonRpcError, json_rpc_request
from iota_stake_ownership.schema import ensure_schema


TX_OPTIONS = {
    "showEffects": True,
    "showEvents": True,
    "showInput": False,
    "showObjectChanges": True,
}

OBJECT_OPTIONS = {
    "showContent": True,
    "showOwner": True,
    "showPreviousTransaction": True,
    "showType": True,
}


def connect_db():
    return psycopg2.connect(**DB_PARAMS)


def as_int(value, default=None):
    if value is None:
        return default
    return int(value)


def stake_object_type(type_repr):
    if not type_repr:
        return None
    if "::timelocked_staking::TimelockedStakedIota" in type_repr:
        return "timelocked_staked_iota"
    if "::staking_pool::StakedIota" in type_repr:
        return "staked_iota"
    return None


def owner_address(owner):
    if not isinstance(owner, dict):
        return None
    return owner.get("AddressOwner")


def unwrap_field(value):
    if isinstance(value, dict):
        if "fields" in value:
            return unwrap_field(value["fields"])
        if "value" in value:
            return unwrap_field(value["value"])
        if "id" in value:
            return unwrap_field(value["id"])
    return value


def parse_past_stake_object(result, fallback_object_type=None):
    status = result.get("status")
    if status != "VersionFound":
        return {"status": status}

    details = result.get("details") or {}
    object_type = stake_object_type(details.get("type")) or fallback_object_type
    content = details.get("content") or {}
    fields = content.get("fields") or {}

    if object_type == "timelocked_staked_iota":
        staked = fields.get("staked_iota") or {}
        if isinstance(staked, dict) and "fields" in staked:
            staked = staked["fields"]
        fields = staked

    principal = unwrap_field(fields.get("principal"))
    pool_id = unwrap_field(fields.get("pool_id"))
    activation_epoch = unwrap_field(fields.get("stake_activation_epoch"))

    if principal is None:
        return {"status": "VersionFoundWithoutPrincipal", "object_type": object_type}

    return {
        "status": status,
        "object_type": object_type,
        "pool_id": pool_id,
        "principal_mist": int(principal),
        "principal": mist_to_iota_int(principal),
        "activation_epoch": as_int(activation_epoch),
        "previous_transaction": details.get("previousTransaction"),
        "owner_address": owner_address(details.get("owner")),
    }


def fetch_past_object(object_id, version):
    return json_rpc_request(
        "iota_tryGetPastObject",
        [object_id, int(version), OBJECT_OPTIONS],
        url=JSON_RPC_URL,
    )


def query_transaction_blocks(filter_value, max_pages=None, descending=False):
    cursor = None
    has_next = True
    pages = 0
    transactions = []
    complete = True

    while has_next:
        if max_pages is not None and pages >= max_pages:
            complete = False
            break

        result = json_rpc_request(
            "iotax_queryTransactionBlocks",
            [{"filter": filter_value, "options": TX_OPTIONS}, cursor, 50, descending],
            url=INDEXER_RPC_URL,
        )
        transactions.extend(result.get("data") or [])
        has_next = bool(result.get("hasNextPage"))
        cursor = result.get("nextCursor")
        pages += 1
        time.sleep(0.15)

    return transactions, complete


def tx_epoch(tx):
    return as_int((tx.get("effects") or {}).get("executedEpoch"), 0)


def tx_checkpoint(tx):
    return as_int(tx.get("checkpoint"))


def matching_stake_changes(tx):
    for change in tx.get("objectChanges") or []:
        object_type = stake_object_type(change.get("objectType"))
        if object_type:
            yield change, object_type


def unstake_events_for_validator(tx, validator_address):
    events = []
    for event in tx.get("events") or []:
        if not (event.get("type") or "").endswith("::validator::UnstakingRequestEvent"):
            continue
        data = event.get("parsedJson") or {}
        if data.get("staker_address") != validator_address:
            continue
        events.append(data)
    return events


def deleted_stake_changes(tx):
    return [
        (change, object_type)
        for change, object_type in matching_stake_changes(tx)
        if change.get("type") in {"deleted", "wrapped"}
    ]


def unstake_event_map(tx, validator_address):
    deleted = deleted_stake_changes(tx)
    events = unstake_events_for_validator(tx, validator_address)
    if len(deleted) != len(events):
        return {}
    return {
        change["objectId"]: (event, object_type)
        for (change, object_type), event in zip(deleted, events)
    }


def load_validators(cursor, validator_address=None, limit=None, missing_only=False):
    if validator_address:
        cursor.execute(
            """
            SELECT DISTINCT validator_address
            FROM validator_snapshots
            WHERE validator_address = %s
            LIMIT 1;
            """,
            (validator_address,),
        )
    else:
        missing_filter = """
            AND NOT EXISTS (
                SELECT 1
                FROM validator_stake_object_history_scan_status status
                WHERE status.validator_address = latest.validator_address
                  AND status.scan_complete = TRUE
            )
        """ if missing_only else ""
        cursor.execute(
            f"""
            WITH latest AS (
                SELECT DISTINCT ON (validator_address)
                    validator_address
                FROM validator_snapshots
                ORDER BY validator_address, epoch_id DESC
            )
            SELECT validator_address
            FROM latest
            WHERE validator_address IS NOT NULL
            {missing_filter}
            ORDER BY validator_address
            LIMIT %s;
            """,
            (limit,),
        )
    return [row[0] for row in cursor.fetchall()]


def upsert_interval(cursor, interval):
    cursor.execute(
        """
        INSERT INTO validator_stake_object_intervals
            (object_id, validator_address, interval_start_tx, object_type, pool_id,
             principal_mist, principal, activation_epoch, start_epoch, start_checkpoint,
             start_version, end_epoch, end_checkpoint, end_tx, end_version, end_reason,
             past_object_status, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (object_id, validator_address, interval_start_tx) DO UPDATE SET
            object_type = EXCLUDED.object_type,
            pool_id = EXCLUDED.pool_id,
            principal_mist = EXCLUDED.principal_mist,
            principal = EXCLUDED.principal,
            activation_epoch = EXCLUDED.activation_epoch,
            start_epoch = EXCLUDED.start_epoch,
            start_checkpoint = EXCLUDED.start_checkpoint,
            start_version = EXCLUDED.start_version,
            end_epoch = COALESCE(EXCLUDED.end_epoch, validator_stake_object_intervals.end_epoch),
            end_checkpoint = COALESCE(EXCLUDED.end_checkpoint, validator_stake_object_intervals.end_checkpoint),
            end_tx = COALESCE(EXCLUDED.end_tx, validator_stake_object_intervals.end_tx),
            end_version = COALESCE(EXCLUDED.end_version, validator_stake_object_intervals.end_version),
            end_reason = COALESCE(EXCLUDED.end_reason, validator_stake_object_intervals.end_reason),
            past_object_status = EXCLUDED.past_object_status,
            updated_at = now();
        """,
        (
            interval["object_id"],
            interval["validator_address"],
            interval["interval_start_tx"],
            interval["object_type"],
            interval.get("pool_id"),
            interval.get("principal_mist"),
            interval["principal"],
            interval.get("activation_epoch"),
            interval["start_epoch"],
            interval.get("start_checkpoint"),
            interval.get("start_version"),
            interval.get("end_epoch"),
            interval.get("end_checkpoint"),
            interval.get("end_tx"),
            interval.get("end_version"),
            interval.get("end_reason"),
            interval.get("past_object_status"),
        ),
    )


def close_interval(cursor, validator_address, object_id, tx, change, reason):
    cursor.execute(
        """
        UPDATE validator_stake_object_intervals
        SET
            end_epoch = %s,
            end_checkpoint = %s,
            end_tx = %s,
            end_version = %s,
            end_reason = %s,
            updated_at = now()
        WHERE object_id = %s
          AND validator_address = %s
          AND end_tx IS NULL;
        """,
        (
            tx_epoch(tx),
            tx_checkpoint(tx),
            tx.get("digest"),
            as_int(change.get("version")),
            reason,
            object_id,
            validator_address,
        ),
    )
    return cursor.rowcount


def interval_from_change(validator_address, tx, change, object_type):
    object_id = change["objectId"]
    version = as_int(change.get("version"))
    if version is None:
        return None

    past = parse_past_stake_object(fetch_past_object(object_id, version), object_type)
    if past.get("status") != "VersionFound":
        return {
            "object_id": object_id,
            "status": past.get("status"),
            "unresolved": True,
        }

    return {
        "object_id": object_id,
        "validator_address": validator_address,
        "interval_start_tx": past.get("previous_transaction") or tx.get("digest"),
        "object_type": past["object_type"] or object_type,
        "pool_id": past.get("pool_id"),
        "principal_mist": past.get("principal_mist"),
        "principal": past.get("principal") or 0,
        "activation_epoch": past.get("activation_epoch"),
        "start_epoch": tx_epoch(tx),
        "start_checkpoint": tx_checkpoint(tx),
        "start_version": version,
        "past_object_status": past.get("status"),
    }


def interval_from_unstake_event(validator_address, tx, change, event, object_type):
    principal_mist = int(event.get("principal_amount") or 0)
    activation_epoch = as_int(event.get("stake_activation_epoch"))
    unstaking_epoch = as_int(event.get("unstaking_epoch"), tx_epoch(tx))
    return {
        "object_id": change["objectId"],
        "validator_address": validator_address,
        "interval_start_tx": f"unstake-event:{tx.get('digest')}:{change['objectId']}",
        "object_type": object_type,
        "pool_id": event.get("pool_id"),
        "principal_mist": principal_mist,
        "principal": mist_to_iota_int(principal_mist),
        "activation_epoch": activation_epoch,
        "start_epoch": activation_epoch if activation_epoch is not None else tx_epoch(tx),
        "start_checkpoint": None,
        "start_version": None,
        "end_epoch": unstaking_epoch,
        "end_checkpoint": tx_checkpoint(tx),
        "end_tx": tx.get("digest"),
        "end_version": as_int(change.get("version")),
        "end_reason": change.get("type"),
        "past_object_status": "FromUnstakeEvent",
    }


def recover_open_interval_for_deleted_object(validator_address, object_id, close_tx, close_change):
    transactions, _complete = query_transaction_blocks({"ChangedObject": object_id}, descending=False)
    candidate = None
    for tx in transactions:
        for change, object_type in matching_stake_changes(tx):
            if change.get("objectId") != object_id:
                continue
            if owner_address(change.get("owner")) == validator_address:
                candidate = (tx, change, object_type)

    if not candidate:
        return None

    tx, change, object_type = candidate
    interval = interval_from_change(validator_address, tx, change, object_type)
    if not interval or interval.get("unresolved"):
        return interval

    interval.update(
        {
            "end_epoch": tx_epoch(close_tx),
            "end_checkpoint": tx_checkpoint(close_tx),
            "end_tx": close_tx.get("digest"),
            "end_version": as_int(close_change.get("version")),
            "end_reason": close_change.get("type"),
        }
    )
    return interval


def process_validator(cursor, validator_address, max_pages_per_filter=None):
    cursor.execute(
        "DELETE FROM validator_stake_object_intervals WHERE validator_address = %s;",
        (validator_address,),
    )
    by_digest = {}
    complete = True
    for filter_value in (
        {"ToAddress": validator_address},
        {"FromAddress": validator_address},
    ):
        transactions, filter_complete = query_transaction_blocks(
            filter_value,
            max_pages=max_pages_per_filter,
            descending=False,
        )
        complete = complete and filter_complete
        for tx in transactions:
            by_digest[tx["digest"]] = tx

    unresolved_object_ids = set()

    for tx in sorted(by_digest.values(), key=lambda item: (tx_epoch(item), tx_checkpoint(item) or 0, item["digest"])):
        event_map = unstake_event_map(tx, validator_address)
        for change, object_type in matching_stake_changes(tx):
            object_id = change.get("objectId")
            change_type = change.get("type")
            change_owner = owner_address(change.get("owner"))
            sender = change.get("sender")

            if change_owner == validator_address and change_type in {"created", "transferred", "mutated", "unwrapped"}:
                interval = interval_from_change(validator_address, tx, change, object_type)
                if interval and interval.get("unresolved"):
                    unresolved_object_ids.add(object_id)
                elif interval:
                    upsert_interval(cursor, interval)
                continue

            closes_validator_interval = (
                change_type in {"deleted", "wrapped"}
                or (change_type == "transferred" and sender == validator_address and change_owner != validator_address)
            )
            if not closes_validator_interval:
                continue

            closed_rows = close_interval(cursor, validator_address, object_id, tx, change, change_type)
            if closed_rows:
                continue

            mapped_event = event_map.get(object_id)
            if mapped_event:
                event, mapped_type = mapped_event
                upsert_interval(
                    cursor,
                    interval_from_unstake_event(
                        validator_address,
                        tx,
                        change,
                        event,
                        mapped_type,
                    ),
                )
                continue

            recovered = recover_open_interval_for_deleted_object(
                validator_address,
                object_id,
                tx,
                change,
            )
            if recovered and recovered.get("unresolved"):
                unresolved_object_ids.add(object_id)
            elif recovered:
                upsert_interval(cursor, recovered)

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM validator_stake_object_intervals
        WHERE validator_address = %s;
        """,
        (validator_address,),
    )
    interval_count = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT DISTINCT object_id
        FROM validator_stake_object_intervals
        WHERE validator_address = %s;
        """,
        (validator_address,),
    )
    resolved_object_ids = {row[0] for row in cursor.fetchall()}
    unresolved = len(unresolved_object_ids - resolved_object_ids)
    cursor.execute(
        """
        INSERT INTO validator_stake_object_history_scan_status
            (validator_address, scanned_at, tx_count, interval_count, unresolved_count,
             scan_complete, last_error)
        VALUES (%s, now(), %s, %s, %s, %s, NULL)
        ON CONFLICT (validator_address) DO UPDATE SET
            scanned_at = now(),
            tx_count = EXCLUDED.tx_count,
            interval_count = EXCLUDED.interval_count,
            unresolved_count = EXCLUDED.unresolved_count,
            scan_complete = EXCLUDED.scan_complete,
            last_error = NULL;
        """,
        (validator_address, len(by_digest), interval_count, unresolved, complete),
    )
    return {
        "tx_count": len(by_digest),
        "interval_count": interval_count,
        "unresolved_count": unresolved,
        "complete": complete,
    }


def rebuild_snapshots_from_history(cursor):
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
            COALESCE(SUM(vi.principal_mist) FILTER (WHERE vi.object_type = 'staked_iota'), 0),
            FLOOR(COALESCE(SUM(vi.principal_mist) FILTER (WHERE vi.object_type = 'staked_iota'), 0) / 1000000000)::bigint,
            COALESCE(SUM(vi.principal_mist) FILTER (WHERE vi.object_type = 'timelocked_staked_iota'), 0),
            FLOOR(COALESCE(SUM(vi.principal_mist) FILTER (WHERE vi.object_type = 'timelocked_staked_iota'), 0) / 1000000000)::bigint,
            COALESCE(SUM(vi.principal_mist), 0),
            FLOOR(COALESCE(SUM(vi.principal_mist), 0) / 1000000000)::bigint,
            COALESCE(COUNT(vi.object_id) FILTER (WHERE vi.object_type = 'staked_iota'), 0),
            COALESCE(COUNT(vi.object_id) FILTER (WHERE vi.object_type = 'timelocked_staked_iota'), 0),
            now()
        FROM validator_snapshots vs
        JOIN validator_stake_object_history_scan_status status
          ON status.validator_address = vs.validator_address
         AND status.scan_complete = TRUE
        LEFT JOIN validator_stake_object_intervals vi
          ON vi.validator_address = vs.validator_address
         AND vi.pool_id = vs.pool_id
         AND GREATEST(COALESCE(vi.activation_epoch, vi.start_epoch), vi.start_epoch) <= vs.epoch_id
         AND (vi.end_epoch IS NULL OR vi.end_epoch > vs.epoch_id)
        GROUP BY vs.epoch_id, vs.validator_address, vs.pool_id;
        """
    )
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
            COALESCE(SUM(COALESCE(vo.principal_mist, vo.principal::numeric * 1000000000)) FILTER (WHERE vo.object_type = 'staked_iota'), 0),
            FLOOR(COALESCE(SUM(COALESCE(vo.principal_mist, vo.principal::numeric * 1000000000)) FILTER (WHERE vo.object_type = 'staked_iota'), 0) / 1000000000)::bigint,
            COALESCE(SUM(COALESCE(vo.principal_mist, vo.principal::numeric * 1000000000)) FILTER (WHERE vo.object_type = 'timelocked_staked_iota'), 0),
            FLOOR(COALESCE(SUM(COALESCE(vo.principal_mist, vo.principal::numeric * 1000000000)) FILTER (WHERE vo.object_type = 'timelocked_staked_iota'), 0) / 1000000000)::bigint,
            COALESCE(SUM(COALESCE(vo.principal_mist, vo.principal::numeric * 1000000000)), 0),
            FLOOR(COALESCE(SUM(COALESCE(vo.principal_mist, vo.principal::numeric * 1000000000)), 0) / 1000000000)::bigint,
            COALESCE(COUNT(vo.object_id) FILTER (WHERE vo.object_type = 'staked_iota'), 0),
            COALESCE(COUNT(vo.object_id) FILTER (WHERE vo.object_type = 'timelocked_staked_iota'), 0),
            now()
        FROM validator_snapshots vs
        JOIN validator_owned_stake_refresh_status refreshed
          ON refreshed.validator_address = vs.validator_address
        LEFT JOIN validator_owned_stake_objects vo
          ON vo.validator_address = vs.validator_address
         AND vo.pool_id = vs.pool_id
         AND COALESCE(vo.activated_epoch, vo.requested_epoch, 0) <= vs.epoch_id
         AND COALESCE(vo.stake_status, 'ACTIVE') = 'ACTIVE'
        WHERE NOT EXISTS (
            SELECT 1
            FROM validator_stake_object_history_scan_status status
            WHERE status.validator_address = vs.validator_address
              AND status.scan_complete = TRUE
        )
        GROUP BY vs.epoch_id, vs.validator_address, vs.pool_id
        ON CONFLICT (epoch_id, validator_address) DO NOTHING;
        """
    )


def ingest_validator_stake_object_history(
    validator_address=None,
    limit=None,
    missing_only=False,
    max_pages_per_filter=None,
):
    ensure_schema()
    with connect_db() as conn:
        cursor = conn.cursor()
        validators = load_validators(cursor, validator_address, limit, missing_only)
        for index, address in enumerate(validators, start=1):
            try:
                summary = process_validator(cursor, address, max_pages_per_filter)
                conn.commit()
                print(
                    f"{index}/{len(validators)} {address[:8]}... "
                    f"tx={summary['tx_count']} intervals={summary['interval_count']} "
                    f"unresolved={summary['unresolved_count']} complete={summary['complete']}",
                    end="\r",
                )
            except JsonRpcError as exc:
                cursor.execute(
                    """
                    INSERT INTO validator_stake_object_history_scan_status
                        (validator_address, scanned_at, tx_count, interval_count,
                         unresolved_count, scan_complete, last_error)
                    VALUES (%s, now(), 0, 0, 0, FALSE, %s)
                    ON CONFLICT (validator_address) DO UPDATE SET
                        scanned_at = now(),
                        scan_complete = FALSE,
                        last_error = EXCLUDED.last_error;
                    """,
                    (address, str(exc)),
                )
                conn.commit()
                print(f"\n{address} failed: {exc}")
        rebuild_snapshots_from_history(cursor)
        conn.commit()
        cursor.close()
    print("\nHistorical validator-owned stake snapshots complete.")


def main():
    parser = argparse.ArgumentParser(
        description="Ingest historical validator-owned StakedIota object intervals from JSON-RPC/indexer."
    )
    parser.add_argument("--validator-address", default=None, help="Scan one validator address.")
    parser.add_argument("--limit", type=int, default=None, help="Limit validators for smoke runs.")
    parser.add_argument("--missing-only", action="store_true", help="Only scan validators without a complete history scan.")
    parser.add_argument("--max-pages-per-filter", type=int, default=None, help="Bound address transaction pages per filter.")
    parser.add_argument("--snapshots-only", action="store_true", help="Rebuild snapshots from stored intervals only.")
    args = parser.parse_args()

    if args.snapshots_only:
        ensure_schema()
        with connect_db() as conn:
            cursor = conn.cursor()
            rebuild_snapshots_from_history(cursor)
            conn.commit()
            cursor.close()
        print("Historical validator-owned stake snapshots rebuilt.")
    else:
        ingest_validator_stake_object_history(
            validator_address=args.validator_address,
            limit=args.limit,
            missing_only=args.missing_only,
            max_pages_per_filter=args.max_pages_per_filter,
        )


if __name__ == "__main__":
    main()
