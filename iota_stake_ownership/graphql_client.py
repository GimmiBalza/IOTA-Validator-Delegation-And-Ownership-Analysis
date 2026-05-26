import time

import requests

from iota_stake_ownership.config import GRAPHQL_URL


class GraphQLError(RuntimeError):
    pass


def graphql_request(query, variables=None, retries=6):
    payload = {"query": query, "variables": variables or {}}
    headers = {"Content-Type": "application/json"}
    delay = 2

    for attempt in range(retries):
        try:
            response = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=30)
            if response.status_code == 429:
                time.sleep(max(delay, 10))
                delay = min(delay * 2, 60)
                continue
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as exc:
            if attempt == retries - 1:
                raise GraphQLError(str(exc)) from exc
            time.sleep(delay)
            delay = min(delay * 2, 60)
            continue

        if data.get("errors"):
            raise GraphQLError(data["errors"])
        return data.get("data") or {}

    raise GraphQLError("GraphQL request failed after retries")
