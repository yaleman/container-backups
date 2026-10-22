# container-backup

Backing up things in containers using other containers. Because it's containers all the way down.

## PostgreSQL backup

This'll dump a full PostgreSQL server.

Env vars:

- POSTGRESQL_SERVER - the hostname

## S3 backup

- Backs up a file to S3, in a bucket and optional path. Will automagically rotate out old files.

Environment variables (all S3 settings use the `S3_BACKUP_` prefix):

- `S3_BACKUP_FILENAME` - local file to upload.
- `S3_BACKUP_BUCKET_NAME` - destination bucket.
- `S3_BACKUP_BUCKET_PATH` - optional directory within the bucket.
- `S3_BACKUP_MAX_AGE_DAYS` - expire backups strictly older than this age; default 30.
- `S3_BACKUP_MIN_FILES` - skip cleanup when fewer than this many eligible backup
  files exist remotely; default 7. This is a threshold, **not a minimum survivor
  count**: when the threshold is met, all expired files can be deleted.
- `S3_BACKUP_USE_FILE_PATH` - use the UTC timestamp in the filename when true;
  otherwise use S3 `LastModified` (default).
- `S3_BACKUP_ENDPOINT_URL` - optional S3-compatible endpoint.

The command attempts upload first, then runs cleanup whether upload succeeds or
fails. It returns success only when both operations succeed; cleanup success does
not hide an upload failure, and if both fail both errors are reported. A full
destination can therefore reclaim expired backups after the failed upload, but
that run still fails and the backup needs another upload attempt. There is no
automatic retry after cleanup.

A successfully uploaded backup counts toward `MIN_FILES` when listed. Cleanup
can delete expired backups even if the new upload failed, according to the same
retention policy. Configuration and local-file validation must succeed before
either S3 operation starts. Dump, compression, upload, and cleanup failures
propagate through the command and shell entrypoints as unsuccessful exits.

Only final filenames matching `<prefix>-<name>-YYYYMMDD-HHMM.tar.gz` with valid
UTC dates are eligible in either date mode. Temporary suffixes, unrelated files,
and malformed dates are ignored and do not count toward `MIN_FILES`. Filename
matching does not validate backup contents. Cleanup covers all listing pages
within the configured directory and checks per-object deletion errors.

Offline regression tests (no S3 access or Docker required):

```sh
uv run pytest tests/test_retention_offline.py tests/test_entrypoints.py
```
