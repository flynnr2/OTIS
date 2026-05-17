WARN manifest.json: firmware_version is not populated
WARN manifest.json: host_tool_version is not populated
WARN manifest.json: firmware_git_commit is not populated
WARN manifest.json: host_git_commit is not populated
WARN run_002: COMPLETE marker is missing; run may not be ready to commit as a fixture
WARN csv/evt.csv: CSV has headers but no data rows
ERROR csv/sts.csv: row 9: status_seq must be strictly increasing; previous=64, current=1
ERROR csv/sts.csv: row 9: timestamp_ticks must be monotonic; previous=92139104, current=24098256
ERROR raw_events.csv: PPS interval 1 in rp2040_timer0 is 31999536 ticks; expected approximately 16000000
OK csv/evt.csv: 0 rows
OK csv/ref.csv: 96205 rows
OK csv/cnt.csv: 8763 rows
