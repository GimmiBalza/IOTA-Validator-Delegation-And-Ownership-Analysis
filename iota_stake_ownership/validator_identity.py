import re
from collections import defaultdict


MIN_COMMISSION_ACTIVATION_DATE = "2026-02-25"
MIN_COMMISSION_ACTIVATION_EPOCH = 296

_SEPARATED_INSTANCE_SUFFIX = re.compile(r"^(.*?)[\s_-]+(?:[IVX]+|\d+)$", re.IGNORECASE)
_ATTACHED_NUMERIC_SUFFIX = re.compile(r"^(.*?[A-Za-z])(\d+)$")


def effective_fee_for_epoch(epoch_id, nominal_fee, voting_power):
    nominal = float(nominal_fee or 0)
    voting_power_pct = float(voting_power or 0)
    if int(epoch_id) < MIN_COMMISSION_ACTIVATION_EPOCH:
        return nominal
    return max(nominal, voting_power_pct)


def fee_rule_for_epoch(epoch_id):
    if int(epoch_id) < MIN_COMMISSION_ACTIVATION_EPOCH:
        return "nominal"
    return "voting_power_floor"


def instance_group_candidate(name):
    """Remove a trailing validator instance marker from a display name."""
    cleaned = " ".join((name or "").strip().split())
    if not cleaned:
        return ""

    match = _SEPARATED_INSTANCE_SUFFIX.match(cleaned)
    if not match:
        match = _ATTACHED_NUMERIC_SUFFIX.match(cleaned)
    if not match:
        return cleaned

    candidate = match.group(1).strip(" _-")
    return candidate if len(candidate) >= 2 else cleaned


def build_validator_identity_mapping(name_history_rows):
    """Return address metadata, grouping instance suffixes only across multiple addresses."""
    rows = [
        (str(address), int(epoch_id), " ".join((name or "").strip().split()))
        for address, epoch_id, name in name_history_rows
        if address and name and name.strip()
    ]

    candidates_by_key = {}
    addresses_by_key = defaultdict(set)
    latest_candidate_epoch = {}
    rows_by_address = defaultdict(list)

    for address, epoch_id, name in rows:
        candidate = instance_group_candidate(name)
        key = candidate.casefold()
        addresses_by_key[key].add(address)
        rows_by_address[address].append((epoch_id, name, key))
        if epoch_id >= latest_candidate_epoch.get(key, -1):
            latest_candidate_epoch[key] = epoch_id
            candidates_by_key[key] = candidate

    shared_keys = {key for key, addresses in addresses_by_key.items() if len(addresses) > 1}
    mapping = {}
    for address, address_rows in rows_by_address.items():
        address_rows.sort(key=lambda item: (item[0], item[1]))
        latest_epoch, latest_name, latest_key = address_rows[-1]
        shared_rows = [row for row in address_rows if row[2] in shared_keys]
        group_key = shared_rows[-1][2] if shared_rows else latest_key
        group_name = candidates_by_key[group_key] if group_key in shared_keys else latest_name
        mapping[address] = {
            "validator_name": latest_name,
            "validator_group": group_name,
            "first_epoch": min(row[0] for row in address_rows),
            "last_epoch": latest_epoch,
            "names_seen": sorted({row[1] for row in address_rows}, key=str.casefold),
        }
    return mapping
