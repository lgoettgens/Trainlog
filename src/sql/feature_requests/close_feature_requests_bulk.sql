UPDATE feature_requests
SET
    status = 'not_doing',
    description = description || E'\n\n---\nMerged into #' || :target_id,
    last_modified = NOW()
WHERE id = ANY(:source_ids);