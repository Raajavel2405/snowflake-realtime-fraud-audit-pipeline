-- ============================================================================
-- 03 — Declarative Transformation (Dynamic Tables)
-- Medallion: RAW (VARIANT) -> HARMONIZED silver (typed) -> HARMONIZED gold (features)
-- Snowflake manages refresh + dependency ordering. No Airflow, no cron.
-- ============================================================================
USE ROLE FRAUD_ENGINEER;
USE WAREHOUSE FRAUD_INGEST_WH;

-- Dynamic Tables require change tracking on the source (usually auto-enabled).
ALTER TABLE FRAUD_DB.RAW.TRANSACTIONS_RAW SET CHANGE_TRACKING = TRUE;

-- ---------------------------------------------------------------------------
-- DT #1 (silver): flatten VARIANT into typed, query-ready columns.
-- DOWNSTREAM lag = refresh only when the leaf needs it. Pure projection = incremental.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE DYNAMIC TABLE FRAUD_DB.HARMONIZED.TRANSACTIONS_ENRICHED
  TARGET_LAG   = DOWNSTREAM
  WAREHOUSE    = FRAUD_INGEST_WH
  REFRESH_MODE = INCREMENTAL
  COMMENT = 'Silver layer: VARIANT flattened to typed, query-ready columns'
  AS
    SELECT
        RECORD_CONTENT:txn_id::STRING                 AS txn_id,
        RECORD_CONTENT:event_timestamp::TIMESTAMP_NTZ AS event_ts,
        RECORD_CONTENT:user_id::STRING                AS user_id,
        RECORD_CONTENT:account_id::STRING             AS account_id,
        RECORD_CONTENT:amount::FLOAT                  AS amount,
        RECORD_CONTENT:currency::STRING               AS currency,
        RECORD_CONTENT:merchant_name::STRING          AS merchant_name,
        RECORD_CONTENT:merchant_category::STRING      AS merchant_category,
        RECORD_CONTENT:card_type::STRING              AS card_type,
        RECORD_CONTENT:card_present::BOOLEAN          AS card_present,
        RECORD_CONTENT:channel::STRING                AS channel,
        RECORD_CONTENT:country_code::STRING           AS country_code,
        RECORD_CONTENT:device_id::STRING              AS device_id,
        RECORD_CONTENT:ip_address::STRING             AS ip_address,
        RECORD_METADATA:ingest_ts::TIMESTAMP_NTZ      AS ingest_ts,
        RECORD_METADATA:offset::NUMBER                AS stream_offset,
        RECORD_METADATA:is_synthetic_anomaly::BOOLEAN AS is_synthetic_anomaly  -- eval-only label
    FROM FRAUD_DB.RAW.TRANSACTIONS_RAW;

-- ---------------------------------------------------------------------------
-- DT #2 (gold): per-user rolling spend stats + anomaly z-score.
-- 1-minute freshness SLA. The z-score is the core fraud-aware feature.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE DYNAMIC TABLE FRAUD_DB.HARMONIZED.USER_SPEND_FEATURES
  TARGET_LAG   = '1 minute'
  WAREHOUSE    = FRAUD_INGEST_WH
  REFRESH_MODE = AUTO
  COMMENT = 'Gold layer: per-user rolling spend stats and anomaly z-score'
  AS
    SELECT
        txn_id, event_ts, user_id, amount, merchant_category, country_code,
        card_present, channel, is_synthetic_anomaly,
        ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY event_ts) AS user_txn_seq,
        AVG(amount) OVER (
            PARTITION BY user_id ORDER BY event_ts
            ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS rolling_avg_amount,
        STDDEV(amount) OVER (
            PARTITION BY user_id ORDER BY event_ts
            ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS rolling_std_amount,
        -- z-score: how many std-devs above the user's personal norm?
        -- NULLIF guards division-by-zero (and NULL for a user's first few txns).
        (amount - AVG(amount) OVER (
            PARTITION BY user_id ORDER BY event_ts
            ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING))
        / NULLIF(STDDEV(amount) OVER (
            PARTITION BY user_id ORDER BY event_ts
            ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING), 0) AS amount_zscore
    FROM FRAUD_DB.HARMONIZED.TRANSACTIONS_ENRICHED;

-- Pause overnight / when idle to save serverless refresh credits:
--   ALTER DYNAMIC TABLE FRAUD_DB.HARMONIZED.USER_SPEND_FEATURES SUSPEND;
--   ALTER DYNAMIC TABLE FRAUD_DB.HARMONIZED.TRANSACTIONS_ENRICHED SUSPEND;
