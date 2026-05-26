import os


GRAPHQL_URL = os.getenv("IOTA_GRAPHQL_URL", "https://graphql.mainnet.iota.cafe")
JSON_RPC_URL = os.getenv("IOTA_JSON_RPC_URL", "https://api.mainnet.iota.cafe")
INDEXER_RPC_URL = os.getenv("IOTA_INDEXER_RPC_URL", "https://indexer.mainnet.iota.cafe")

DB_PARAMS = {
    "dbname": os.getenv("IOTA_DB_NAME", "IOTA_history"),
    "user": os.getenv("IOTA_DB_USER", "postgres"),
    "password": os.getenv("IOTA_DB_PASSWORD", "password"),
    "host": os.getenv("IOTA_DB_HOST", "localhost"),
    "port": os.getenv("IOTA_DB_PORT", "5432"),
}

MIST_PER_IOTA = 1_000_000_000


def mist_to_iota_int(value):
    if value is None:
        return None
    return int(int(value) / MIST_PER_IOTA)
