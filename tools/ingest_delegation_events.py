import argparse
import time

import psycopg2

import _bootstrap  # noqa: F401
from iota_stake_ownership.config import DB_PARAMS, mist_to_iota_int
from iota_stake_ownership.graphql_client import graphql_request
from iota_stake_ownership.schema import ensure_schema


EVENT_TYPES = {
    "Stake": "0x3::validator::StakingRequestEvent",
    "Unstake": "0x3::validator::UnstakingRequestEvent",
}

EVENTS_QUERY_FORWARD = """
query GetDelegationEvents($cursor: String, $eventType: String!) {
  events(first: 50, after: $cursor, filter: { eventType: $eventType }) {
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      timestamp
      json
      transactionBlock {
        digest
      }
    }
  }
}
"""

EVENTS_QUERY_BACKWARD = """
query GetDelegationEventsBackward($cursor: String, $eventType: String!) {
  events(last: 50, before: $cursor, filter: { eventType: $eventType }) {
    pageInfo {
      hasPreviousPage
      startCursor
    }
    nodes {
      timestamp
      json
      transactionBlock {
        digest
      }
    }
  }
}
"""


def connect_db():
    return psycopg2.connect(**DB_PARAMS)


def fetch_events_data(event_type, cursor=None, backwards=False):
    query = EVENTS_QUERY_BACKWARD if backwards else EVENTS_QUERY_FORWARD
    return graphql_request(query, {"eventType": event_type, "cursor": cursor})


def event_epoch(event_label, event_node):
    json_data = event_node.get("json") or {}
    if event_label == "Stake":
        return int(json_data.get("epoch", 0))
    return int(json_data.get("unstaking_epoch", 0))


def upsert_delegation_event(cursor, event_label, event_node):
    json_data = event_node.get("json") or {}
    tx_digest = ((event_node.get("transactionBlock") or {}).get("digest"))
    if not tx_digest:
        raise ValueError("Cannot store event without transaction digest")

    if event_label == "Stake":
        epoch_id = int(json_data.get("epoch", 0))
        staked_amount_mist = int(json_data.get("amount", 0))
        realized_revenue_mist = None
    else:
        epoch_id = int(json_data.get("unstaking_epoch", 0))
        staked_amount_mist = int(json_data.get("principal_amount", 0))
        realized_revenue_mist = int(json_data.get("reward_amount", 0))

    cursor.execute(
        """
        INSERT INTO delegation_events
            (event_id, delegator_address, validator_address, pool_id, epoch_id,
             timestamp, event_type, staked_amount, realized_revenue)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (event_id) DO UPDATE SET
            delegator_address = EXCLUDED.delegator_address,
            validator_address = EXCLUDED.validator_address,
            pool_id = EXCLUDED.pool_id,
            epoch_id = EXCLUDED.epoch_id,
            timestamp = EXCLUDED.timestamp,
            event_type = EXCLUDED.event_type,
            staked_amount = EXCLUDED.staked_amount,
            realized_revenue = EXCLUDED.realized_revenue;
        """,
        (
            tx_digest,
            json_data.get("staker_address"),
            json_data.get("validator_address"),
            json_data.get("pool_id"),
            epoch_id,
            event_node.get("timestamp"),
            event_label,
            mist_to_iota_int(staked_amount_mist),
            mist_to_iota_int(realized_revenue_mist),
        ),
    )


def ingest_delegation_events(max_pages=None, start_epoch=None):
    ensure_schema()
    with connect_db() as conn:
        cursor = conn.cursor()
        backwards = start_epoch is not None
        for event_label, move_event_type in EVENT_TYPES.items():
            print(f"\nEstrazione eventi: {event_label}")
            has_next_page = True
            graphql_cursor = None
            page_count = 0
            event_count = 0

            while has_next_page:
                if max_pages is not None and page_count >= max_pages:
                    break

                data = fetch_events_data(move_event_type, graphql_cursor, backwards=backwards)
                events_connection = data.get("events") or {}
                nodes = events_connection.get("nodes") or []
                if backwards and not nodes:
                    break

                min_epoch_in_page = None
                for node in events_connection.get("nodes") or []:
                    epoch_id = event_epoch(event_label, node)
                    min_epoch_in_page = epoch_id if min_epoch_in_page is None else min(min_epoch_in_page, epoch_id)
                    if start_epoch is not None and epoch_id < start_epoch:
                        continue
                    upsert_delegation_event(cursor, event_label, node)
                    event_count += 1

                conn.commit()
                page_count += 1
                page_info = events_connection.get("pageInfo") or {}
                if backwards:
                    has_next_page = page_info.get("hasPreviousPage", False) and (
                        min_epoch_in_page is None or min_epoch_in_page >= start_epoch
                    )
                    graphql_cursor = page_info.get("startCursor")
                else:
                    has_next_page = page_info.get("hasNextPage", False)
                    graphql_cursor = page_info.get("endCursor")
                print(f"{event_label}: pagine {page_count}, eventi {event_count}", end="\r")
                time.sleep(0.3)
            print()
        cursor.close()


def main():
    parser = argparse.ArgumentParser(description="Ingest IOTA staking/unstaking events.")
    parser.add_argument("--max-pages", type=int, default=None, help="Limit pages per event type for smoke tests.")
    parser.add_argument("--start-epoch", type=int, default=None, help="Only ingest events from this epoch onward.")
    args = parser.parse_args()
    ingest_delegation_events(max_pages=args.max_pages, start_epoch=args.start_epoch)
    print("Delegation event ingestion complete.")


if __name__ == "__main__":
    main()
