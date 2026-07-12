-- ============================================================================
-- 05 — Automated Email Alerting
-- Native email notification integration + serverless Alert that emails auditors
-- when the ML model flags anomalies. Push governance: fraud escalates itself.
-- (Alert grants are in 01_setup_and_rbac.sql.)
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Email notification integration (create as ACCOUNTADMIN)
-- ---------------------------------------------------------------------------
USE ROLE ACCOUNTADMIN;
CREATE OR REPLACE NOTIFICATION INTEGRATION FRAUD_ALERT_EMAIL_INT
  TYPE = EMAIL
  ENABLED = TRUE;
GRANT USAGE ON INTEGRATION FRAUD_ALERT_EMAIL_INT TO ROLE FRAUD_ENGINEER;
-- NOTE: recipients must be VERIFIED email addresses of users in the account.

-- ---------------------------------------------------------------------------
-- Serverless alert (no warehouse cost). Fires when flagged anomalies exist and
-- emails a Snowflake-branded HTML table of the highest-risk transactions.
--
-- PRODUCTION ENHANCEMENT (deliberately omitted for the demo so it fires on
-- existing data): add a time-window + dedup so it only alerts on NEW anomalies:
--   AND event_ts >= COALESCE(
--       CONVERT_TIMEZONE('UTC', SNOWFLAKE.ALERT.LAST_SUCCESSFUL_SCHEDULED_TIME())::TIMESTAMP_NTZ,
--       DATEADD('minute', -60, CONVERT_TIMEZONE('UTC', SNOWFLAKE.ALERT.SCHEDULED_TIME())::TIMESTAMP_NTZ))
-- ---------------------------------------------------------------------------
USE ROLE FRAUD_ENGINEER;
USE SCHEMA FRAUD_DB.ANALYTICS;

CREATE OR REPLACE ALERT ALERT_FRAUD_ANOMALIES
  SCHEDULE = '60 MINUTE'
  IF (EXISTS (
    SELECT
        TO_VARCHAR(event_ts, 'YYYY-MM-DD HH24:MI:SS')   AS EVENT_TIME,
        user_id                                          AS USER_ID,
        '$' || TO_VARCHAR(amount, '999,999,990.00')      AS AMOUNT,
        country_code                                     AS COUNTRY,
        channel                                          AS CHANNEL,
        ROUND(anomaly_score, 3)                          AS ANOMALY_SCORE
    FROM FRAUD_DB.ANALYTICS.FRAUD_PREDICTIONS
    WHERE ml_anomaly_flag = TRUE
  ))
  THEN
  BEGIN
    LET header_row VARCHAR :=
         '<th style="padding:8px;text-align:left;font-weight:600;">EVENT_TIME</th>'
      || '<th style="padding:8px;text-align:left;font-weight:600;">USER_ID</th>'
      || '<th style="padding:8px;text-align:left;font-weight:600;">AMOUNT</th>'
      || '<th style="padding:8px;text-align:left;font-weight:600;">COUNTRY</th>'
      || '<th style="padding:8px;text-align:left;font-weight:600;">CHANNEL</th>'
      || '<th style="padding:8px;text-align:left;font-weight:600;">ANOMALY_SCORE</th>';
    LET table_rows VARCHAR := '';
    LET data_cursor CURSOR FOR (
      SELECT * FROM TABLE(RESULT_SCAN(SNOWFLAKE.ALERT.GET_CONDITION_QUERY_UUID()))
      ORDER BY ANOMALY_SCORE DESC LIMIT 100
    );
    FOR rec IN data_cursor DO
      table_rows := :table_rows
        || '<tr style="border-bottom:1px solid #D5DAE4;">'
        || '<td style="padding:8px;">' || COALESCE(rec.EVENT_TIME::VARCHAR, '')    || '</td>'
        || '<td style="padding:8px;">' || COALESCE(rec.USER_ID::VARCHAR, '')       || '</td>'
        || '<td style="padding:8px;">' || COALESCE(rec.AMOUNT::VARCHAR, '')        || '</td>'
        || '<td style="padding:8px;">' || COALESCE(rec.COUNTRY::VARCHAR, '')       || '</td>'
        || '<td style="padding:8px;">' || COALESCE(rec.CHANNEL::VARCHAR, '')       || '</td>'
        || '<td style="padding:8px;">' || COALESCE(rec.ANOMALY_SCORE::VARCHAR, '') || '</td>'
        || '</tr>';
    END FOR;
    LET row_count INTEGER := (
      SELECT COUNT(*) FROM TABLE(RESULT_SCAN(SNOWFLAKE.ALERT.GET_CONDITION_QUERY_UUID())));
    LET html_content VARCHAR :=
         '<html><body style="font-family:Arial,sans-serif;color:#666;">'
      || '<img src="https://www.snowflake.com/wp-content/themes/snowflake/img/snowflake-logo-blue.png" height="36" alt="Snowflake"/>'
      || '<h2 style="color:#29B5E8;">&#x26A0;&#xFE0F; High-Risk Fraud Anomalies Detected</h2>'
      || '<p>The Fraud &amp; Audit pipeline flagged <b>' || :row_count || '</b> transaction(s). Highest-risk first:</p>'
      || '<table style="border:1px solid #D5DAE4;border-collapse:collapse;width:100%;">'
      || '<tr style="background:#F7F7F7;">' || :header_row || '</tr>' || :table_rows || '</table>'
      || '<p style="color:#999;font-size:12px;">' || :row_count || ' row(s) | Powered by Snowflake Alerts</p>'
      || '</body></html>';
    CALL SYSTEM$SEND_SNOWFLAKE_NOTIFICATION(
      SNOWFLAKE.NOTIFICATION.TEXT_HTML(:html_content),
      '{"FRAUD_ALERT_EMAIL_INT": {"subject": "[FRAUD ALERT] High-risk anomalies detected", "toAddress": ["<YOUR_VERIFIED_EMAIL>"]}}'
    );
  END;

-- Alerts are created SUSPENDED. Test on demand, then RESUME for live monitoring:
--   EXECUTE ALERT ALERT_FRAUD_ANOMALIES;      -- run now (ignores schedule)
--   ALTER ALERT ALERT_FRAUD_ANOMALIES RESUME; -- enable the 60-minute schedule
