-- ============================================================================
-- 04 — Native ML Inference View
-- Scores every transaction with the registered Isolation Forest (V2), in SQL,
-- over the live gold Dynamic Table. Always current; zero data movement.
--
-- PREREQUISITE: train + register the model first via src/train_fraud_model.py,
-- which creates model FRAUD_DB.ANALYTICS.FRAUD_ISOLATION_FOREST (V2 = default).
-- Model methods: PREDICT (-1/1), SCORE_SAMPLES, DECISION_FUNCTION.
-- ============================================================================
USE ROLE FRAUD_ENGINEER;
USE WAREHOUSE FRAUD_INGEST_WH;

CREATE OR REPLACE VIEW FRAUD_DB.ANALYTICS.FRAUD_PREDICTIONS AS
WITH feat AS (
    SELECT
        txn_id, event_ts, user_id, amount, merchant_category, country_code,
        card_present, channel, is_synthetic_anomaly, amount_zscore,
        -- Replicate the model's training-time cold-start imputation EXACTLY:
        COALESCE(amount_zscore, 0)                                              AS zscore_imp,
        COALESCE(amount / NULLIF(COALESCE(rolling_avg_amount, amount), 0), 1.0) AS amount_to_avg_ratio
    FROM FRAUD_DB.HARMONIZED.USER_SPEND_FEATURES
)
SELECT
    txn_id, event_ts, user_id, amount, merchant_category, country_code,
    card_present, channel, amount_zscore,
    ROUND(amount_to_avg_ratio, 2) AS amount_to_avg_ratio,
    -- score_samples: lower = more abnormal; negate so higher = more anomalous
    ROUND(-(MODEL(FRAUD_DB.ANALYTICS.FRAUD_ISOLATION_FOREST, V2)
            !SCORE_SAMPLES(zscore_imp, amount_to_avg_ratio):output_feature_0::FLOAT), 4) AS anomaly_score,
    (MODEL(FRAUD_DB.ANALYTICS.FRAUD_ISOLATION_FOREST, V2)
        !PREDICT(zscore_imp, amount_to_avg_ratio):output_feature_0::INT = -1)            AS ml_anomaly_flag,
    is_synthetic_anomaly   -- eval-only ground truth (never a model feature)
FROM feat;

-- Highest-risk transactions:
-- SELECT * FROM FRAUD_DB.ANALYTICS.FRAUD_PREDICTIONS
-- WHERE ml_anomaly_flag ORDER BY anomaly_score DESC;
