import argparse

import _bootstrap  # noqa: F401
from tools.ingest_delegation_events import ingest_delegation_events
from tools.ingest_validator_actions import upsert_validator_actions
from tools.ingest_validator_owned_stake_objects import ingest_validator_owned_stake_objects
from tools.ingest_validator_stake_object_history import ingest_validator_stake_object_history
from tools.ingest_validator_snapshots import ingest_validator_snapshots
from tools.reconstruct_ownership import reconstruct_ownership


def main():
    parser = argparse.ArgumentParser(description="Rebuild IOTA validator/delegation database and ownership tables.")
    parser.add_argument("--start-epoch", type=int, default=0)
    parser.add_argument("--end-epoch", type=int, default=None)
    parser.add_argument("--event-max-pages", type=int, default=None, help="Limit event pages per type for smoke tests.")
    parser.add_argument("--actions-max-pages", type=int, default=None, help="Limit validator action pages for smoke tests.")
    parser.add_argument("--owned-object-limit", type=int, default=None, help="Limit validators for owned-object smoke tests.")
    parser.add_argument("--history-object-limit", type=int, default=None, help="Limit validators for historical object smoke tests.")
    parser.add_argument("--history-max-pages-per-filter", type=int, default=None, help="Bound historical address transaction pages per filter.")
    parser.add_argument("--rescan-object-history", action="store_true", help="Rescan validators that already have a complete object-history scan.")
    parser.add_argument("--skip-snapshots", action="store_true")
    parser.add_argument("--skip-events", action="store_true")
    parser.add_argument("--skip-actions", action="store_true")
    parser.add_argument("--skip-owned-objects", action="store_true")
    parser.add_argument("--skip-object-history", action="store_true")
    args = parser.parse_args()

    if not args.skip_snapshots:
        ingest_validator_snapshots(args.start_epoch, args.end_epoch)
    if not args.skip_events:
        ingest_delegation_events(max_pages=args.event_max_pages, start_epoch=args.start_epoch)
    if not args.skip_actions:
        upsert_validator_actions(max_pages=args.actions_max_pages, start_epoch=args.start_epoch)
    if not args.skip_owned_objects:
        ingest_validator_owned_stake_objects(limit=args.owned_object_limit)
    if not args.skip_object_history:
        ingest_validator_stake_object_history(
            limit=args.history_object_limit,
            missing_only=not args.rescan_object_history,
            max_pages_per_filter=args.history_max_pages_per_filter,
        )

    summary = reconstruct_ownership()
    print("Rebuild complete.")
    print(summary)


if __name__ == "__main__":
    main()
