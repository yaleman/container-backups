#!/bin/bash

set -e

postgresql-backup.sh

if [ -n "${S3_BACKUP_BUCKET_NAME}" ]; then
    S3_BACKUP_FILENAME=$BACKUP_FILE s3_backup
else
    echo "No S3_BACKUP_BUCKET_NAME specified, skipping upload."
fi

