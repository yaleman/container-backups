#!/bin/bash

set -e

if [ -z "${BACKUP_NAME}" ]; then
    echo "Please specify the BACKUP_NAME environment variable."
    exit 1
fi

if [ -z "${POSTGRESQL_SERVER}" ]; then
    echo "Please specify the POSTGRESQL_SERVER environment variable."
    exit 1
fi
if [ -z "${POSTGRESQL_USER}" ]; then
    echo "Please specify the POSTGRESQL_USER environment variable."
    exit 1
fi
if [ -z "${POSTGRESQL_PASS}" ]; then
    echo "Please specify the POSTGRESQL_PASS environment variable."
    exit 1
fi

if [ -z "${BACKUP_PREFIX}" ]; then
    BACKUP_PREFIX="backup"
fi

BACKUP_FILE="${BACKUP_PREFIX}-${BACKUP_NAME}-$(date +%Y%m%d-%H%M).tar"

cd "$(mktemp -d)"

PGPASSWORD="${POSTGRESQL_PASS}" pg_dumpall \
    -h "${POSTGRESQL_SERVER}" \
    -p 5432 \
    --username="${POSTGRESQL_USER}" \
    --file="${BACKUP_FILE}"
#Compressing backup file for upload
gzip -9 "${BACKUP_FILE}"

export BACKUP_FILE="${BACKUP_FILE}.gz"

echo "Saved backup as '${BACKUP_FILE}'"
