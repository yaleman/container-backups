# container-backup

Backing up things in containers using other containers. Because it's containers all the way down.

## PostgreSQL backup

This'll dump a full PostgreSQL server.

Env vars:

- POSTGRESQL_SERVER - the hostname

## S3 backup

- Backs up a file to S3, in a bucket and optional path. Will automagically rotate out old files.

Env vars:

- BACKUP_FILENAME - the filename to upload
- BUCKET_NAME - s3 bucket name
- BUCKET_PATH - s3 bucket path
- BACKUP_MAX_AGE_DAYS - older than this? Delete!
- BACKUP_MIN_FILES - less than this number of files and we'll just bail
- S3_ENDPOINT_URL - optional S3 endpoint URL to target (if you're using Minio or similar)
