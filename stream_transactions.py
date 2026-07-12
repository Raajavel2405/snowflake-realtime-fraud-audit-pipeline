"""
stream_transactions.py
------------------------------------------------------------------
Snowpipe Streaming client (High-Performance Architecture).

Fuses the Phase 2 generator with Snowflake's Ingest SDK to stream
financial transactions DIRECTLY into FRAUD_DB.RAW.TRANSACTIONS_RAW --
no S3 staging, no COPY, no warehouse. Sub-second latency.

Flow:
  generate_transaction()  ->  append_row() over a long-lived channel
                          ->  Snowflake commits rows to the table

Run:
  python stream_transactions.py --count 500 --sleep 0.2
  python stream_transactions.py --continuous          # until Ctrl+C
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone

from snowflake.ingest.streaming import StreamingIngestClient

from transaction_generator import generate_transaction

# ------------------------------------------------------------------
# CONNECTION SETTINGS -- edit ACCOUNT if your account URL differs.
# ACCOUNT is your account identifier (orgname-accountname form).
# ------------------------------------------------------------------
ACCOUNT = "XNKYJCY-PZB47052"
USER = "RAAJAVEL06"
ROLE = "FRAUD_ENGINEER"

DATABASE = "FRAUD_DB"
SCHEMA = "RAW"
TABLE = "TRANSACTIONS_RAW"
PIPE_NAME = f"{TABLE}-STREAMING"          # default pipe, auto-created on first use

PRIVATE_KEY_PATH = os.path.join("keys", "rsa_key.p8")
PROFILE_PATH = "profile.json"             # written locally, gitignored
CHANNEL_NAME = "channel_1"


def build_profile() -> str:
    """Write the SDK profile.json from the private key; return its path."""
    with open(PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()

    profile = {
        "account": ACCOUNT,
        "user": USER,
        "url": f"https://{ACCOUNT}.snowflakecomputing.com:443",
        "private_key": private_key,   # PEM CONTENT, not a path
        "role": ROLE,
    }
    with open(PROFILE_PATH, "w") as f:
        json.dump(profile, f)
    return PROFILE_PATH


def main():
    parser = argparse.ArgumentParser(description="Stream mock transactions to Snowflake.")
    parser.add_argument("--count", type=int, default=500, help="Number of rows to stream.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Seconds between rows.")
    parser.add_argument("--continuous", action="store_true", help="Stream until Ctrl+C.")
    args = parser.parse_args()

    profile_path = build_profile()

    # Open a long-lived client + channel. Channels are meant to be opened
    # ONCE and reused -- opening per-row would kill throughput.
    client = StreamingIngestClient(
        client_name="fraud_stream_client",
        db_name=DATABASE,
        schema_name=SCHEMA,
        pipe_name=PIPE_NAME,
        profile_json=profile_path,
    )
    channel, status = client.open_channel(channel_name=CHANNEL_NAME)
    print(f"Channel '{CHANNEL_NAME}' opened against pipe '{PIPE_NAME}'. Streaming...\n")

    # Graceful shutdown on Ctrl+C so buffered rows still flush.
    stop = {"flag": False}

    def _handle_sigint(signum, frame):
        print("\nStop requested -- flushing remaining rows...")
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_sigint)

    sent = 0
    anomalies = 0
    try:
        while not stop["flag"]:
            txn = generate_transaction()

            # Ground-truth label lives in METADATA only, for later model
            # EVALUATION. It is NEVER a feature the ML model sees.
            is_anomaly = txn.pop("_is_anomaly")

            record_metadata = {
                "channel_name": CHANNEL_NAME,
                "offset": sent,
                "ingest_ts": datetime.now(timezone.utc).isoformat(),
                "is_synthetic_anomaly": is_anomaly,   # eval-only ground truth
            }

            # Native dicts -> stored as VARIANT OBJECT (not string).
            channel.append_row(
                {"RECORD_CONTENT": txn, "RECORD_METADATA": record_metadata},
                offset_token=str(sent),
            )

            sent += 1
            anomalies += int(is_anomaly)

            if sent % 50 == 0:
                print(f"  streamed {sent} rows ({anomalies} synthetic anomalies so far)")

            if not args.continuous and sent >= args.count:
                break

            time.sleep(args.sleep)
    finally:
        # Block until Snowflake confirms the buffered rows are committed.
        channel.wait_for_flush(timeout_seconds=30)
        committed = channel.get_latest_committed_offset_token()
        print(f"\nDone. Streamed {sent} rows; last committed offset token = {committed}")
        client.close()


if __name__ == "__main__":
    main()
