import argparse
import time

import psycopg2

import _bootstrap  
from iota_stake_ownership.config import DB_PARAMS
from iota_stake_ownership.graphql_client import graphql_request
from iota_stake_ownership.schema import ensure_schema


QUERY_FORWARD = """
query GetValidatorEpochInfoEvents($cursor: String) {
  events(
    first: 50
    after: $cursor
    filter: { eventType: "0x3::validator_set::ValidatorEpochInfoEventV1" }
  ) {
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      timestamp
      json
      transactionBlock {
        digest
        effects {
          epoch { epochId }
          checkpoint { sequenceNumber }
        }
      }
    }
  }
}
"""

QUERY_BACKWARD = """
query GetValidatorEpochInfoEventsBackward($cursor: String) {
  events(
    last: 50
    before: $cursor
    filter: { eventType: "0x3::validator_set::ValidatorEpochInfoEventV1" }
  ) {
    pageInfo {
      hasPreviousPage
      startCursor
    }
    nodes {
      timestamp
      json
      transactionBlock {
        digest
        effects {
          epoch { epochId }
          checkpoint { sequenceNumber }
        }
      }
    }
  }
}
"""


def connect_db():
    return psycopg2.connect(**DB_PARAMS)


def fetch_events(cursor=None, backwards=False):
    query = QUERY_BACKWARD if backwards else QUERY_FORWARD
    return graphql_request(query, {"cursor": cursor})


def load_initial_fees(cursor, start_epoch):
    if start_epoch is None:
        return {}
    cursor.execute(
        """
        SELECT DISTINCT ON (validator_address)
            validator_address,
            applied_fee
        FROM validator_snapshots
        WHERE epoch_id < %s
          AND applied_fee IS NOT NULL
        ORDER BY validator_address, epoch_id DESC;
        """,
        (start_epoch,),
    )
    return {row[0]: float(row[1]) for row in cursor.fetchall()}


def process_action_node(cursor_db, node, last_known_fees):
    json_data = node.get("json") or {}
    tx = node.get("transactionBlock") or {}
    tx_digest = tx.get("digest")
    timestamp_str = node.get("timestamp")

    epoch_id = int(json_data.get("epoch", 0))
    target_validator = json_data.get("validator_address")
    global_score = int(json_data.get("tallying_rule_global_score", 0))
    commission_pct = int(json_data.get("commission_rate", 0)) / 100.0
    saved_actions = 0

    cursor_db.execute(
        """
        UPDATE validator_snapshots
        SET global_tallying_score = %s,
            applied_fee = %s,
            effective_fee = GREATEST(%s, COALESCE(voting_power, 0))
        WHERE epoch_id = %s AND validator_address = %s;
        """,
        (global_score, commission_pct, commission_pct, epoch_id, target_validator),
    )

    if target_validator not in last_known_fees:
        last_known_fees[target_validator] = commission_pct
    elif last_known_fees[target_validator] != commission_pct:
        old_fee = last_known_fees[target_validator]
        if tx_digest:
            cursor_db.execute(
                """
                INSERT INTO validator_actions
                    (event_id, validator_address, epoch_id, timestamp, action_type,
                     target_validator, old_value, new_value)
                VALUES (%s, %s, %s, %s, 'Fee Change', NULL, %s, %s)
                ON CONFLICT (event_id) DO UPDATE SET
                    validator_address = EXCLUDED.validator_address,
                    epoch_id = EXCLUDED.epoch_id,
                    timestamp = EXCLUDED.timestamp,
                    action_type = EXCLUDED.action_type,
                    target_validator = EXCLUDED.target_validator,
                    old_value = EXCLUDED.old_value,
                    new_value = EXCLUDED.new_value;
                """,
                (
                    tx_digest,
                    target_validator,
                    epoch_id,
                    timestamp_str,
                    f"{old_fee}%",
                    f"{commission_pct}%",
                ),
            )
            saved_actions += 1
        last_known_fees[target_validator] = commission_pct

    for reporter in json_data.get("tallying_rule_reporters", []) or []:
        if not tx_digest:
            continue
        cursor_db.execute(
            """
            INSERT INTO validator_actions
                (event_id, validator_address, epoch_id, timestamp, action_type,
                 target_validator, old_value, new_value)
            VALUES (%s, %s, %s, %s, 'Report', %s, NULL, NULL)
            ON CONFLICT (event_id) DO UPDATE SET
                validator_address = EXCLUDED.validator_address,
                epoch_id = EXCLUDED.epoch_id,
                timestamp = EXCLUDED.timestamp,
                action_type = EXCLUDED.action_type,
                target_validator = EXCLUDED.target_validator,
                old_value = EXCLUDED.old_value,
                new_value = EXCLUDED.new_value;
            """,
            (tx_digest, reporter, epoch_id, timestamp_str, target_validator),
        )
        saved_actions += 1

    return saved_actions


def upsert_validator_actions(max_pages=None, start_epoch=None):
    ensure_schema()
    with connect_db() as conn:
        cursor_db = conn.cursor()
        print("Inizio estrazione validator actions e aggiornamento fee/score...")

        has_next_page = True
        graphql_cursor = None
        page_count = 0
        processed = 0
        saved_actions = 0
        last_known_fees = load_initial_fees(cursor_db, start_epoch)
        buffered_nodes = []
        backwards = start_epoch is not None

        while has_next_page:
            if max_pages is not None and page_count >= max_pages:
                break
            data = fetch_events(graphql_cursor, backwards=backwards)
            events_connection = data.get("events") or {}
            nodes = events_connection.get("nodes") or []
            min_epoch_in_page = None

            for node in nodes:
                json_data = node.get("json") or {}
                epoch_id = int(json_data.get("epoch", 0))
                min_epoch_in_page = epoch_id if min_epoch_in_page is None else min(min_epoch_in_page, epoch_id)
                if start_epoch is not None and epoch_id < start_epoch:
                    continue
                if backwards:
                    buffered_nodes.append(node)
                else:
                    saved_actions += process_action_node(cursor_db, node, last_known_fees)
                    processed += 1

            page_count += 1
            page_info = events_connection.get("pageInfo") or {}
            if backwards:
                has_next_page = page_info.get("hasPreviousPage", False) and (
                    min_epoch_in_page is None or min_epoch_in_page >= start_epoch
                )
                graphql_cursor = page_info.get("startCursor")
            else:
                conn.commit()
                has_next_page = page_info.get("hasNextPage", False)
                graphql_cursor = page_info.get("endCursor")
            print(f"Pagine {page_count}, eventi {processed}, azioni {saved_actions}", end="\r")
            time.sleep(0.3)

        if backwards:
            buffered_nodes.sort(
                key=lambda node: (
                    int((node.get("json") or {}).get("epoch", 0)),
                    node.get("timestamp") or "",
                    ((node.get("transactionBlock") or {}).get("digest")) or "",
                )
            )
            for node in buffered_nodes:
                saved_actions += process_action_node(cursor_db, node, last_known_fees)
                processed += 1
            conn.commit()

        print()
        cursor_db.close()


def main():
    parser = argparse.ArgumentParser(description="Ingest validator fee/report actions.")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--start-epoch", type=int, default=None, help="Only ingest action events from this epoch onward.")
    args = parser.parse_args()
    upsert_validator_actions(args.max_pages, start_epoch=args.start_epoch)
    print("Validator actions complete.")


if __name__ == "__main__":
    main()
