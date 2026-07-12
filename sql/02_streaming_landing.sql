-- ============================================================================
-- 02 — Real-Time Ingestion Landing (Snowpipe Streaming, High-Performance Arch.)
-- ============================================================================
-- Key-pair auth is required by the Snowpipe Streaming SDK. Generate a key with
-- src/generate_keys.py, then register the PUBLIC key on the streaming user:
--
--   ALTER USER <YOUR_USER> SET RSA_PUBLIC_KEY='<public_key_body>';
--   DESC USER <YOUR_USER>;   -- confirm RSA_PUBLIC_KEY_FP shows a SHA256 fingerprint
-- ============================================================================
USE ROLE FRAUD_ENGINEER;
USE WAREHOUSE FRAUD_INGEST_WH;

-- Immutable, schema-on-read landing table. Two VARIANT columns mirror the
-- shape Snowflake's own Kafka connector produces (RECORD_CONTENT / RECORD_METADATA).
CREATE TABLE IF NOT EXISTS FRAUD_DB.RAW.TRANSACTIONS_RAW (
    RECORD_CONTENT  VARIANT,   -- full transaction event, unparsed
    RECORD_METADATA VARIANT    -- ingest metadata: channel, offset, ingest_ts, eval-only label
)
COMMENT = 'Immutable landing zone for streamed financial transactions';

-- The default pipe TRANSACTIONS_RAW-STREAMING is auto-created by the Python SDK
-- on first channel open (requires CREATE PIPE, granted in 01_setup_and_rbac.sql).
-- Ingestion is serverless: no warehouse runs during streaming.
-- See src/stream_transactions.py (client) and src/transaction_generator.py (source).

-- Verify data is landing as structured VARIANT (OBJECT, not VARCHAR):
-- SELECT RECORD_CONTENT, TYPEOF(RECORD_CONTENT) FROM FRAUD_DB.RAW.TRANSACTIONS_RAW LIMIT 5;
