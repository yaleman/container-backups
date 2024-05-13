#!/bin/bash

set -e

cd "$(mktemp -d)"

mysql-backup.sh

if [ -n "${S3_BACKUP_BUCKET_NAME}" ]; then
    S3_BACKUP_FILENAME="$(ls ./*.tar.gz)" s3_backup
else
    echo "No S3_BACKUP_BUCKET_NAME specified, skipping upload."
fi
