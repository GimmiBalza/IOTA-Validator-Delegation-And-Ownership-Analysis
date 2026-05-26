import time

import requests

from iota_stake_ownership.config import INDEXER_RPC_URL


class JsonRpcError(RuntimeError):
    pass


def json_rpc_request(method, params=None, url=None, retries=6):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or [],
    }
    endpoint = url or INDEXER_RPC_URL
    delay = 2

    for attempt in range(retries):
        try:
            response = requests.post(endpoint, json=payload, timeout=60)
            if response.status_code == 429:
                time.sleep(max(delay, 10))
                delay = min(delay * 2, 60)
                continue
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as exc:
            if attempt == retries - 1:
                raise JsonRpcError(str(exc)) from exc
            time.sleep(delay)
            delay = min(delay * 2, 60)
            continue

        if data.get("error"):
            raise JsonRpcError(data["error"])
        return data.get("result")

    raise JsonRpcError(f"JSON-RPC request failed after retries: {method}")
