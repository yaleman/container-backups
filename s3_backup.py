#!/usr/bin/env python3

from datetime import UTC, datetime, timedelta
from pathlib import Path
from os.path import basename
import sys
from typing import Optional
import boto3
import re
import boto3.session
from botocore.client import BaseClient
from pydantic import Field
from pydantic_settings import BaseSettings


class Config(BaseSettings):
    backup_filename: str
    bucket_name: str
    bucket_path: str = Field(default="")
    backup_max_age_days: int = Field(default=30)
    backup_min_files: int = Field(default=7)
    s3_endpoint_url: Optional[str] = None


def get_date_from_file_path(file_path: str) -> datetime:
    """parse the file path we use for a date"""
    res = re.search(r"^[\w]+-[\w]+-(?P<datestring>\d{8}-\d{4}).tar.gz", file_path)
    if res is None:
        raise ValueError(f"Couldn't parse '{file_path}' for a matching date!")
    print(res.group("datestring"))
    return datetime.strptime(res.group("datestring"), "%Y%m%d-%H%M").astimezone(UTC)


def clean_up_old_files(
    s3: BaseClient,
    config: Config,
    use_file_path: bool = False,
) -> Optional[int]:

    print(f"Looking in s3://{config.bucket_name}/{config.bucket_path}", file=sys.stderr)
    response = s3.list_objects_v2(Bucket=config.bucket_name, Prefix=config.bucket_path)  # type: ignore

    if len(response.get("Contents", [])) < config.backup_min_files:
        print(
            f"Found less than {config.backup_min_files} files total, exiting",
            file=sys.stderr,
        )
        return None

    age_cutoff = datetime.now(UTC) - timedelta(days=config.backup_max_age_days)
    print(
        f"Files older than {age_cutoff.isoformat()} ({config.backup_max_age_days} days) will be deleted",
        file=sys.stderr,
    )

    files_to_remove = []
    files_to_keep = []

    for obj in response.get("Contents", []):
        if use_file_path:
            last_modified = get_date_from_file_path(obj["Key"])
        else:
            last_modified = obj.get("LastModified")
        if last_modified < age_cutoff:
            print(
                f"{obj.get('Key')} is older than {age_cutoff.isoformat()}: {last_modified.isoformat()}"
            )
            files_to_remove.append(obj["Key"])
        else:
            print(
                f"{obj.get('Key')} is younger than {age_cutoff.isoformat()}: {last_modified.isoformat()}"
            )
            files_to_keep.append(obj["Key"])

    if len(files_to_keep) < config.backup_min_files:
        print(
            f"Found less than {config.backup_min_files} files younger than {age_cutoff.isoformat()}, exiting",
            file=sys.stderr,
        )
        return None
    if files_to_remove:
        print(f"Deleting {files_to_remove}", file=sys.stderr)
        s3.delete_objects(  # type: ignore
            Bucket=config.bucket_name,
            Delete={
                "Objects": [
                    {"Key": f"{config.bucket_path}/{filename}"}
                    for filename in files_to_remove
                ]
            },
        )
        return len(files_to_remove)
    else:
        print("No files to delete", file=sys.stderr)
    return None


def upload_file(s3: BaseClient, config: Config) -> None:
    """upload the file!"""

    if not Path(config.backup_filename).exists():
        raise FileNotFoundError(f"File {config.backup_filename} not found")
    s3.upload_file(  # type: ignore
        Filename=config.backup_filename,
        Bucket=config.bucket_name,
        Key=f"{config.bucket_path}/{basename(config.backup_filename)}",
    )


def main(use_file_path: bool = False) -> Optional[int]:
    """returns the number of files deleted"""

    config = Config()  # type: ignore
    session = boto3.session.Session()

    s3 = session.client(
        service_name="s3",
        endpoint_url=config.s3_endpoint_url,
    )
    upload_file(s3, config)
    return clean_up_old_files(s3=s3, config=config, use_file_path=use_file_path)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}")
        exit(1)
