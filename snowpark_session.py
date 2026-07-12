"""
snowpark_session.py
------------------------------------------------------------------
Creates a Snowpark session using the SAME key-pair we generated in
Phase 3. One service identity authenticates ingestion (Snowpipe
Streaming) AND ML (Snowpark / Model Registry) -- clean, auditable.

Usage:
    from snowpark_session import create_session
    session = create_session()
"""

import os

from snowflake.snowpark import Session

# Resolve paths relative to THIS file so it works from any cwd.
_HERE = os.path.dirname(os.path.abspath(__file__))
PRIVATE_KEY_PATH = os.path.join(_HERE, "keys", "rsa_key.p8")

ACCOUNT = "XNKYJCY-PZB47052"
USER = "RAAJAVEL06"
ROLE = "FRAUD_ENGINEER"
WAREHOUSE = "FRAUD_INGEST_WH"
DATABASE = "FRAUD_DB"
SCHEMA = "ANALYTICS"


def create_session() -> Session:
    """Build a Snowpark session authenticated via key-pair."""
    connection_params = {
        "account": ACCOUNT,
        "user": USER,
        "role": ROLE,
        "warehouse": WAREHOUSE,
        "database": DATABASE,
        "schema": SCHEMA,
        "private_key_file": PRIVATE_KEY_PATH,  # reuse Phase 3 private key
    }
    return Session.builder.configs(connection_params).create()


if __name__ == "__main__":
    # Connectivity self-test.
    s = create_session()
    row = s.sql(
        "SELECT CURRENT_ROLE() AS role, CURRENT_WAREHOUSE() AS wh, "
        "CURRENT_DATABASE() AS db, CURRENT_SCHEMA() AS sch"
    ).collect()[0]
    print(f"Connected as role={row['ROLE']} wh={row['WH']} db={row['DB']} schema={row['SCH']}")
    s.close()
