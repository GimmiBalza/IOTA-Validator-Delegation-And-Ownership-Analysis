import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2

import _bootstrap  # noqa: F401
from iota_stake_ownership.config import DB_PARAMS
from iota_stake_ownership.schema import ensure_schema
from tools.ingest_validator_stake_object_history import (
    JsonRpcError,
    rebuild_snapshots_from_history,
    process_validator,
)


def load_missing_validators(limit=None, rescan=False):
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cursor:
            missing_filter = """
                AND NOT EXISTS (
                    SELECT 1
                    FROM validator_stake_object_history_scan_status status
                    WHERE status.validator_address = latest.validator_address
                      AND status.scan_complete = TRUE
                )
            """ if not rescan else ""
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


def mark_failed(address, exc):
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cursor:
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


def scan_one(address, max_pages_per_filter=None):
    try:
        with psycopg2.connect(**DB_PARAMS) as conn:
            with conn.cursor() as cursor:
                summary = process_validator(cursor, address, max_pages_per_filter)
            conn.commit()
        return address, summary
    except JsonRpcError as exc:
        mark_failed(address, exc)
        return address, {
            "tx_count": 0,
            "interval_count": 0,
            "unresolved_count": 0,
            "complete": False,
            "error": str(exc),
        }


def rebuild_owned_snapshots():
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cursor:
            rebuild_snapshots_from_history(cursor)
        conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Parallel historical validator-owned stake object scan.")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--rescan", action="store_true")
    parser.add_argument("--max-pages-per-filter", type=int, default=None)
    parser.add_argument("--skip-snapshots", action="store_true")
    args = parser.parse_args()

    ensure_schema()
    validators = load_missing_validators(limit=args.limit, rescan=args.rescan)
    print(f"validators_to_scan={len(validators)} workers={args.workers}", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(scan_one, address, args.max_pages_per_filter): address
            for address in validators
        }
        for index, future in enumerate(as_completed(futures), start=1):
            address, summary = future.result()
            message = (
                f"{index}/{len(validators)} {address[:10]}...{address[-6:]} "
                f"complete={summary.get('complete')} tx={summary.get('tx_count')} "
                f"intervals={summary.get('interval_count')} "
                f"unresolved={summary.get('unresolved_count')}"
            )
            if summary.get("error"):
                message += f" error={summary['error']}"
            print(message, flush=True)

    if not args.skip_snapshots:
        print("rebuilding validator_owned_stake_snapshots", flush=True)
        rebuild_owned_snapshots()
        print("snapshots_rebuilt", flush=True)


if __name__ == "__main__":
    main()
