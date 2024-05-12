#!/bin/bash

set -e

postgresql-backup.sh

if [ -n "${S3_BUCKET}" ]; then
    s3_backup.py
fi

