#!/usr/bin/env python3

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from os.path import basename
import sys
from typing import Optional
import boto3
import re
import boto3.session
from botocore.client import Config as BotocoreConfig
from botocore.client import BaseClient
from pydantic import Field, field_validator
from pydantic_core import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "S3_BACKUP_"


class Config(BaseSettings):
    filename: str = Field()
    bucket_name: str = Field()
    bucket_path: str = Field(default="")
    max_age_days: int = Field(default=30, ge=0)
    min_files: int = Field(default=7, ge=0)
    endpoint_url: Optional[str] = None
    use_file_path: bool = Field(default=False)

    show_config: bool = Field(default=False)

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        if not value:
            raise ValueError("Filename is required to be non-empty!")
        if not Path(value).is_file():
            raise FileNotFoundError(
                f"Backup file {value} not found or not a regular file"
            )
        return value


def get_date_from_file_name(file_path: str) -> datetime:
    """parse the file path we use for a date"""
    res = re.fullmatch(r"[\w-]+-[\w-]+-(?P<datestring>\d{8}-\d{4})\.tar\.gz", file_path)
    if res is None:
        raise ValueError(f"Couldn't parse '{file_path}' for a matching date!")
    return datetime.strptime(res.group("datestring"), "%Y%m%d-%H%M").replace(tzinfo=UTC)


def clean_up_old_files(
    s3: BaseClient,
    config: Config,
) -> Optional[int]:
    print(f"Looking in s3://{config.bucket_name}/{config.bucket_path}", file=sys.stderr)
    # Treat bucket_path as a directory, not a partial prefix such as 'db-old'.
    prefix = config.bucket_path.strip("/")
    prefix = f"{prefix}/" if prefix else ""
    candidates = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=config.bucket_name, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            try:
                filename_date = get_date_from_file_name(basename(key))
            except ValueError:
                # Do not expire temporary uploads, unrelated objects, or invalid dates.
                continue
            modified = (
                filename_date if config.use_file_path else obj.get("LastModified")
            )
            if modified is None:
                print(
                    f"Couldn't get last modified date for {key}, skipping",
                    file=sys.stderr,
                )
                continue
            candidates.append((key, modified))

    # MIN_FILES remains the documented threshold for attempting cleanup. It is
    # deliberately not a survivor floor (see commit 9b9a6f5).
    if len(candidates) < config.min_files:
        print(
            f"Found less than {config.min_files} backup files total, exiting",
            file=sys.stderr,
        )
        return None

    age_cutoff = datetime.now(UTC) - timedelta(days=config.max_age_days)
    print(
        f"Files older than {age_cutoff.isoformat()} ({config.max_age_days} days) will be deleted",
        file=sys.stderr,
    )
    files_to_remove = [key for key, modified in candidates if modified < age_cutoff]
    if not files_to_remove:
        print("No files to delete", file=sys.stderr)
        return None

    # S3 accepts at most 1,000 keys per DeleteObjects request. An HTTP 200 may
    # still contain per-object errors, so never report these as successful.
    deleted = 0
    for start in range(0, len(files_to_remove), 1000):
        batch = files_to_remove[start : start + 1000]
        response = s3.delete_objects(
            Bucket=config.bucket_name,
            Delete={"Objects": [{"Key": key} for key in batch]},
        )
        errors = response.get("Errors", [])
        if errors:
            raise RuntimeError(
                f"S3 cleanup failed for {len(errors)} objects: {errors!r}"
            )
        deleted += len(batch)
    print(f"Deleted {deleted} files", file=sys.stderr)
    return deleted


def upload_file(s3: BaseClient, config: Config) -> None:
    """upload the file!"""

    if not Path(config.filename).exists():
        raise FileNotFoundError(f"File {config.filename} not found")

    key = f"{config.bucket_path.strip('/')}/{basename(config.filename)}"
    if key.startswith("/"):
        key = key[1:]

    s3.upload_file(  # type: ignore
        Filename=config.filename,
        Bucket=config.bucket_name,
        Key=key,
    )


class BackupError(RuntimeError):
    """Combined operation outcome, preserving both original exceptions."""

    def __init__(
        self, upload_error: Exception | None, cleanup_error: Exception | None
    ) -> None:
        self.upload_error = upload_error
        self.cleanup_error = cleanup_error
        failures = []
        if upload_error is not None:
            failures.append(f"Upload failed: {upload_error}")
        if cleanup_error is not None:
            failures.append(f"Cleanup failed: {cleanup_error}")
        super().__init__("; ".join(failures))


def main() -> Optional[int]:
    """Attempt upload, always attempt cleanup, and fail if either operation fails."""

    try:
        config = Config.model_validate({})
    except ValidationError as ve:
        for error in ve.errors():
            if error.get("type") == "missing":
                print(
                    f"Missing environment variable {ENV_PREFIX}{error.get('loc')[0].upper()}"  # type: ignore
                )
            else:
                print(error)
        sys.exit(1)
    if config.show_config:
        print(config.model_dump_json(indent=2))
        AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
        AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")
        AWS_REGION = os.getenv("AWS_REGION")
        AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION")
        AWS_SECRET_ACCESS_KEY = (
            os.getenv("AWS_SECRET_ACCESS_KEY", "")[:5]
            + "..."
            + str(max(len(os.getenv("AWS_SECRET_ACCESS_KEY", "")) - 5, 0))
        )
        print(f"{AWS_ACCESS_KEY_ID=}")
        print(f"{AWS_SECRET_ACCESS_KEY=}")
        print(f"{AWS_ENDPOINT_URL=}")
        print(f"{AWS_REGION=}")
        print(f"{AWS_DEFAULT_REGION=}")

    session = boto3.session.Session()
    region_name = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION"))

    s3 = session.client(
        service_name="s3",
        endpoint_url=config.endpoint_url,
        region_name=region_name,
        config=BotocoreConfig(
            # default to "better" signatures. This is required for minio especially
            signature_version="s3v4",
            # ref https://github.com/fsspec/s3fs/issues/931#issuecomment-2601216629
            request_checksum_calculation="when_required",
            # response_checksum_validation="when_rewuired",
        ),
    )

    upload_error = None
    cleanup_error = None
    deleted = None
    try:
        upload_file(s3, config)
    except Exception as error:
        upload_error = error

    # Cleanup must run after the upload attempt, including when the destination
    # is full. Its outcome must not mask a failed upload (or vice versa).
    try:
        deleted = clean_up_old_files(s3=s3, config=config)
    except Exception as error:
        cleanup_error = error

    if upload_error is not None or cleanup_error is not None:
        raise BackupError(upload_error, cleanup_error) from (
            upload_error if upload_error is not None else cleanup_error
        )
    return deleted


def cli() -> None:
    """A successful cleanup count is not a process exit status."""
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    cli()
