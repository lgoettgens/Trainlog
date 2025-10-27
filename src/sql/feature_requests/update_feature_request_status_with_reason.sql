UPDATE feature_requests
SET status = :status,
    closure_reason = CASE
        WHEN :status IN ('completed','not_doing','merged') THEN :closure_reason
        ELSE closure_reason
    END,
    last_modified = NOW()
WHERE id = :request_id;
