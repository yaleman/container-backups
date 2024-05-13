#!/bin/bash

set -e

postgresql-backup.sh

if [ -n "${S3_BACKUP_BUCKET_NAME}" ]; then
    s3_backup
else
    echo "No S3_BACKUP_BUCKET_NAME specified, skipping upload."
fi

