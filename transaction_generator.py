"""
transaction_generator.py
------------------------------------------------------------------
Source-system SIMULATOR for the Real-Time Fraud & Audit Pipeline.

Design goals (the "why"):
  1. A FIXED pool of users, each with a personal spend profile, so that
     downstream rolling-average transformations (Dynamic Tables) have
     real per-user signal to average over.
  2. RARE injected anomalies (~1.5%): large amount spikes at odd hours
     from unusual countries. These are the "fraud" events our
     UNSUPERVISED ML model must surface WITHOUT ever seeing a label.

This module is intentionally transport-agnostic: it only KNOWS HOW TO
GENERATE a transaction. In Phase 3, the Snowpipe Streaming client will
import generate_transaction() and handle delivery. Separation of
concerns: generation != transport.
"""

import random
import uuid
from datetime import datetime, timezone

from faker import Faker

fake = Faker()

# ---------------------------------------------------------------------
# 1. A FIXED pool of users, each with a stable spending "personality".
#    We seed the RNG so the user pool is identical on every run --
#    reproducibility matters when you demo a pipeline to stakeholders.
# ---------------------------------------------------------------------
NUM_USERS = 50
_profile_rng = random.Random(42)  # dedicated RNG so we don't disturb live randomness

USER_PROFILES = {}
for i in range(1, NUM_USERS + 1):
    user_id = f"USER_{i:04d}"
    USER_PROFILES[user_id] = {
        "account_id": f"ACCT_{i:06d}",
        # each user's typical transaction size (their "normal")
        "avg_amount": _profile_rng.uniform(20, 400),
        # how spread out their spending is
        "std_amount": _profile_rng.uniform(5, 80),
        # the country they usually transact from
        "home_country": _profile_rng.choice(["US", "US", "US", "GB", "IN", "CA", "DE"]),
    }

USER_IDS = list(USER_PROFILES.keys())

MERCHANT_CATEGORIES = [
    "GROCERY", "RESTAURANT", "TRAVEL", "ELECTRONICS", "FUEL",
    "ENTERTAINMENT", "HEALTHCARE", "UTILITIES", "APPAREL", "ONLINE_RETAIL",
]
CARD_TYPES = ["VISA", "MASTERCARD", "AMEX", "DISCOVER"]
CHANNELS = ["ONLINE", "IN_STORE", "ATM"]
FOREIGN_COUNTRIES = ["RU", "NG", "BR", "CN", "RO", "UA"]  # unusual-for-our-users

# Probability that any given transaction is an injected anomaly.
ANOMALY_RATE = 0.015


def generate_transaction() -> dict:
    """Generate ONE financial transaction as a plain dict (JSON-ready)."""
    user_id = random.choice(USER_IDS)
    profile = USER_PROFILES[user_id]

    is_anomaly = random.random() < ANOMALY_RATE

    if is_anomaly:
        # Fraud-like: 15x-60x the user's normal amount, foreign country,
        # card-not-present online purchase. We do NOT store the is_anomaly
        # flag in the payload sent to Snowflake -- detection must be
        # UNSUPERVISED. We only return it here for local visibility.
        multiplier = random.uniform(15, 60)
        amount = round(profile["avg_amount"] * multiplier, 2)
        country = random.choice(FOREIGN_COUNTRIES)
        channel = "ONLINE"
        card_present = False
    else:
        # Normal: sample around the user's personal spend profile.
        amount = max(1.0, random.gauss(profile["avg_amount"], profile["std_amount"]))
        amount = round(amount, 2)
        country = profile["home_country"]
        channel = random.choice(CHANNELS)
        card_present = channel in ("IN_STORE", "ATM")

    txn = {
        "txn_id": str(uuid.uuid4()),
        "event_timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "account_id": profile["account_id"],
        "amount": amount,
        "currency": "USD",
        "merchant_name": fake.company(),
        "merchant_category": random.choice(MERCHANT_CATEGORIES),
        "card_type": random.choice(CARD_TYPES),
        "card_present": card_present,
        "channel": channel,
        "country_code": country,
        "device_id": f"DEV_{random.randint(1, 9999):04d}",
        "ip_address": fake.ipv4_public(),
    }

    # _is_anomaly is a LOCAL-ONLY hint for you to eyeball the generator.
    # Phase 3 will strip it before streaming so the model stays unsupervised.
    txn["_is_anomaly"] = is_anomaly
    return txn


if __name__ == "__main__":
    # Quick self-test: print 10 transactions so you can SEE the data
    # before we ever wire up streaming. Anomalies are flagged with <== ANOMALY.
    import json

    print(f"Generating sample transactions from {NUM_USERS} users...\n")
    for _ in range(10):
        t = generate_transaction()
        flag = "   <== ANOMALY" if t["_is_anomaly"] else ""
        print(json.dumps({k: v for k, v in t.items() if k != "_is_anomaly"}) + flag)
