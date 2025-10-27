ALTER TABLE feature_requests
    ADD COLUMN closure_reason TEXT;

ALTER TABLE feature_requests
    DROP CONSTRAINT IF EXISTS feature_requests_status_check;