import argparse
import time

import psycopg2

import _bootstrap  # noqa: F401
from iota_stake_ownership.config import DB_PARAMS, mist_to_iota_int
from iota_stake_ownership.graphql_client import graphql_request
from iota_stake_ownership.schema import ensure_schema


QUERY = """
query GetEpochSnapshot($epochId: Int!, $cursor: String) {
  epoch(id: $epochId) {
    epochId
    validatorSet {
      activeValidators(first: 50, after: $cursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          name
          address { address }
          stakingPoolId
          votingPower
          stakingPoolIotaBalance
          effectiveCommissionRate
          rewardsPool
        }
      }
    }
  }
}
"""


def connect_db():
    return psycopg2.connect(**DB_PARAMS)


def fetch_epoch_data(epoch_id, cursor=None):
    return graphql_request(QUERY, {"epochId": epoch_id, "cursor": cursor})


def ingest_validator_snapshots(start_epoch=0, end_epoch=None):
    ensure_schema()
    with connect_db() as conn:
        cursor_db = conn.cursor()
        current_epoch = start_epoch
        print("Inizio estrazione validator snapshots...")

        while True:
            if end_epoch is not None and current_epoch > end_epoch:
                break

            has_next_page = True
            graphql_cursor = None
            validators_count = 0

            while has_next_page:
                data = fetch_epoch_data(current_epoch, graphql_cursor)
                epoch_info = data.get("epoch")
                if epoch_info is None:
                    print(f"Fine dati disponibili. Ultima epoca processata: {current_epoch - 1}")
                    cursor_db.close()
                    return

                validators_connection = epoch_info["validatorSet"]["activeValidators"]
                validators = validators_connection["nodes"]

                for val in validators:
                    val_address = val["address"]["address"]
                    pool_id = val.get("stakingPoolId")

                    voting_power_raw = int(val.get("votingPower") or 0)
                    voting_power_pct = voting_power_raw / 100.0

                    commission_raw = int(val.get("effectiveCommissionRate") or 0)
                    commission_pct = commission_raw / 100.0

                    total_stake_mist = int(val.get("stakingPoolIotaBalance") or 0)
                    total_stake = mist_to_iota_int(total_stake_mist)

                    reward_mist = int(val.get("rewardsPool") or 0)
                    reward_pool_iota = mist_to_iota_int(reward_mist)

                    effective_fee = max(commission_pct, voting_power_pct)

                    cursor_db.execute(
                        """
                        INSERT INTO validator_snapshots
                            (epoch_id, validator_address, pool_id, voting_power, total_stake,
                             own_stake, delegated_stake, applied_fee, effective_fee,
                             global_tallying_score, validator_reward)
                        VALUES (%s, %s, %s, %s, %s, NULL, NULL, %s, %s, NULL, %s)
                        ON CONFLICT (epoch_id, validator_address) DO UPDATE SET
                            pool_id = EXCLUDED.pool_id,
                            voting_power = EXCLUDED.voting_power,
                            total_stake = EXCLUDED.total_stake,
                            applied_fee = EXCLUDED.applied_fee,
                            effective_fee = EXCLUDED.effective_fee,
                            validator_reward = EXCLUDED.validator_reward;
                        """,
                        (
                            current_epoch,
                            val_address,
                            pool_id,
                            voting_power_pct,
                            total_stake,
                            commission_pct,
                            effective_fee,
                            reward_pool_iota,
                        ),
                    )
                    validators_count += 1

                page_info = validators_connection["pageInfo"]
                has_next_page = page_info["hasNextPage"]
                graphql_cursor = page_info["endCursor"]
                time.sleep(0.3)

            conn.commit()
            print(f"Epoch {current_epoch} salvata ({validators_count} validatori).")
            current_epoch += 1

        cursor_db.close()


def main():
    parser = argparse.ArgumentParser(description="Ingest IOTA active validator snapshots.")
    parser.add_argument("--start-epoch", type=int, default=0)
    parser.add_argument("--end-epoch", type=int, default=None)
    args = parser.parse_args()
    ingest_validator_snapshots(args.start_epoch, args.end_epoch)


if __name__ == "__main__":
    main()
