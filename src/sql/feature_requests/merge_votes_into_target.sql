WITH all_votes AS (
  SELECT v.username, v.vote_type, v.created
  FROM feature_request_votes v
  WHERE v.feature_request_id = :target_id
  UNION ALL
  SELECT v.username, v.vote_type, v.created
  FROM feature_request_votes v
  WHERE v.feature_request_id = ANY(:source_ids)
),
dedup AS (
  SELECT DISTINCT ON (username) username, vote_type, created
  FROM all_votes
  ORDER BY username, created DESC
)
INSERT INTO feature_request_votes (feature_request_id, username, vote_type, created)
SELECT :target_id, d.username, d.vote_type, d.created
FROM dedup d
ON CONFLICT (feature_request_id, username) DO UPDATE
SET vote_type = EXCLUDED.vote_type,
    created   = EXCLUDED.created;
