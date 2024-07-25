#!/bin/bash

if [ -z "${BACKUP_NAME}" ]; then
    echo "Please specify the BACKUP_NAME environment variable."
    exit 1
fi

if [ -z "${DB_SERVER}" ]; then
    echo "Please specify the DB_SERVER environment variable."
    exit 1
fi
if [ -z "${DB_USER}" ]; then
    echo "Please specify the DB_USER environment variable."
    exit 1
fi
if [ -z "${DB_PASS}" ]; then
    echo "Please specify the DB_PASS environment variable."
    exit 1
fi

if [ -z "${BACKUP_PREFIX}" ]; then
    BACKUP_PREFIX="backup"
fi

BACKUP_FILE="${BACKUP_PREFIX}-${BACKUP_NAME}-$(date +%Y%m%d-%H%M).tar"

echo "Dumping to ${BACKUP_FILE}..."

mysqldump \
    --host="${DB_SERVER}" \
    --user="${DB_USER}" \
    --password="${DB_PASS}" \
    --result-file="${BACKUP_FILE}" \
    --all-databases
#Compressing backup file for upload

echo "Compressing to ${BACKUP_FILE}.gz..."
gzip -9 "${BACKUP_FILE}"

echo "Listing backup files..."
ls -lah ./
echo "Saved backup as '${BACKUP_FILE}.gz'"
