"""Retention regressions using only in-memory S3 fakes."""

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from container_backups import s3_backup as backup

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)
OLD = "backup-test-20200101-0000.tar.gz"
NEW = "backup-test-20261022-1200.tar.gz"


class FakeS3:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.deleted: list[list[str]] = []
        self.events: list[str] = []
        self.errors: list[dict[str, str]] = []
        self.upload_error: Exception | None = None
        self.list_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.free_space = False

    def get_paginator(self, operation: str) -> "FakeS3":
        assert operation == "list_objects_v2"
        return self

    def paginate(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.events.append("list")
        self.list_args = kwargs
        if self.list_error:
            raise self.list_error
        return self.pages

    def delete_objects(self, **kwargs: Any) -> dict[str, Any]:
        self.events.append("delete")
        if self.delete_error:
            raise self.delete_error
        self.deleted.append([item["Key"] for item in kwargs["Delete"]["Objects"]])
        self.free_space = True
        return {"Errors": self.errors}

    def upload_file(self, **kwargs: Any) -> None:
        self.events.append("upload")
        self.upload_args = kwargs
        if self.upload_error:
            raise self.upload_error
        if not self.free_space:
            raise RuntimeError("No space left on device")


@pytest.fixture
def config(tmp_path: Path) -> backup.Config:
    filename = tmp_path / NEW
    filename.write_text("local test backup")
    return backup.Config.model_validate(
        dict(
            filename=str(filename),
            bucket_name="bucket",
            bucket_path="database",
            use_file_path=True,
            min_files=1,
        )
    )


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch: pytest.MonkeyPatch) -> None:
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return NOW

    monkeypatch.setattr(backup, "datetime", FixedDatetime)


def cleanup(s3: FakeS3, config: backup.Config) -> int | None:
    return backup.clean_up_old_files(cast(Any, s3), config)


def test_all_pages_are_considered_and_delete_batches_are_limited(
    config: backup.Config,
) -> None:
    keys = [
        f"database/backup-test-{(NOW - timedelta(days=60, minutes=i)).strftime('%Y%m%d-%H%M')}.tar.gz"
        for i in range(1005)
    ]
    s3 = FakeS3(
        [
            {"Contents": [{"Key": k} for k in keys[:600]]},
            {"Contents": [{"Key": k} for k in keys[600:]]},
        ]
    )
    assert cleanup(s3, config) == 1005
    assert [len(batch) for batch in s3.deleted] == [1000, 5]
    assert sum(s3.deleted, []) == keys
    assert s3.list_args == {"Bucket": "bucket", "Prefix": "database/"}


@pytest.mark.parametrize("path,prefix", [("/database/", "database/"), ("", "")])
def test_directory_prefix(config: backup.Config, path: str, prefix: str) -> None:
    config.bucket_path = path
    s3 = FakeS3([{}])
    assert cleanup(s3, config) is None
    assert s3.list_args["Prefix"] == prefix


@pytest.mark.parametrize(
    "filename",
    [
        OLD + ".1.123.tmp",
        "backup-test-20260230-0000.tar.gz",
        "backup-test-20200101-2500.tar.gz",
        "backup-test-20200101-0000XtarXgz",
        "notes.txt",
        "backup-test-20200101-0000.tar.gz.extra",
    ],
)
def test_unrelated_and_temporary_files_are_ignored(
    config: backup.Config, filename: str
) -> None:
    s3 = FakeS3(
        [{"Contents": [{"Key": f"database/{filename}"}, {"Key": f"database/{OLD}"}]}]
    )
    assert cleanup(s3, config) == 1
    assert s3.deleted == [[f"database/{OLD}"]]


def test_only_eligible_files_count_toward_min_files(config: backup.Config) -> None:
    config.min_files = 2
    s3 = FakeS3(
        [{"Contents": [{"Key": OLD}, {"Key": OLD + ".tmp"}, {"Key": "notes.txt"}]}]
    )
    assert cleanup(s3, config) is None
    assert not s3.deleted


def test_documented_min_files_threshold_is_not_a_survivor_floor(
    config: backup.Config,
) -> None:
    config.min_files = 2
    s3 = FakeS3(
        [{"Contents": [{"Key": OLD}, {"Key": "backup-test-20200102-0000.tar.gz"}]}]
    )
    assert cleanup(s3, config) == 2
    assert len(s3.deleted[0]) == 2


def test_cutoff_is_strict_and_filename_date_overrides_mtime(
    config: backup.Config,
) -> None:
    boundary = "backup-test-20260922-1200.tar.gz"
    expired = "backup-test-20260922-1159.tar.gz"
    s3 = FakeS3(
        [
            {
                "Contents": [
                    {"Key": boundary, "LastModified": NOW - timedelta(days=200)},
                    {"Key": expired, "LastModified": NOW},
                ]
            }
        ]
    )
    assert cleanup(s3, config) == 1
    assert s3.deleted == [[expired]]


def test_mtime_remains_default_date_source(config: backup.Config) -> None:
    config.use_file_path = False
    s3 = FakeS3(
        [
            {
                "Contents": [
                    {"Key": OLD, "LastModified": NOW},
                    {"Key": NEW, "LastModified": NOW - timedelta(days=31)},
                    {"Key": "backup-test-20200103-0000.tar.gz"},
                ]
            }
        ]
    )
    assert cleanup(s3, config) == 1
    assert s3.deleted == [[NEW]]


def test_filename_is_utc_independent_of_host_timezone() -> None:
    old_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Australia/Brisbane"
        time.tzset()
        assert backup.get_date_from_file_name(NEW) == NOW
        assert (
            backup.get_date_from_file_name("backup-my-database-20261022-1200.tar.gz")
            == NOW
        )
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


def test_per_object_delete_error_stops_cleanup(config: backup.Config) -> None:
    s3 = FakeS3([{"Contents": [{"Key": OLD}]}])
    s3.errors = [{"Key": OLD, "Code": "AccessDenied"}]
    with pytest.raises(RuntimeError, match="AccessDenied"):
        cleanup(s3, config)


def wire_main(
    monkeypatch: pytest.MonkeyPatch, config: backup.Config, s3: FakeS3
) -> None:
    monkeypatch.setattr(backup.Config, "model_validate", lambda _: config)
    monkeypatch.setattr(
        backup.boto3.session, "Session", lambda: Mock(client=Mock(return_value=s3))
    )


@pytest.mark.parametrize("upload_fails", [False, True])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_combined_outcome_and_upload_before_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    config: backup.Config,
    upload_fails: bool,
    cleanup_fails: bool,
) -> None:
    s3 = FakeS3([{"Contents": [{"Key": OLD}]}])
    s3.free_space = True
    upload_error = RuntimeError("upload unavailable") if upload_fails else None
    cleanup_error = RuntimeError("delete unavailable") if cleanup_fails else None
    s3.upload_error = upload_error
    s3.delete_error = cleanup_error
    wire_main(monkeypatch, config, s3)
    if upload_fails or cleanup_fails:
        with pytest.raises(backup.BackupError) as error:
            backup.main()
        assert error.value.upload_error is upload_error
        assert error.value.cleanup_error is cleanup_error
        assert error.value.__cause__ is (
            upload_error if upload_fails else cleanup_error
        )
        assert ("Upload failed: upload unavailable" in str(error.value)) == upload_fails
        assert (
            "Cleanup failed: delete unavailable" in str(error.value)
        ) == cleanup_fails
    else:
        assert backup.main() == 1
    assert s3.events == ["upload", "list", "delete"]


@pytest.mark.parametrize("upload_fails", [False, True])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_cli_final_exit_and_both_error_messages(
    monkeypatch: pytest.MonkeyPatch,
    config: backup.Config,
    capsys: pytest.CaptureFixture[str],
    upload_fails: bool,
    cleanup_fails: bool,
) -> None:
    s3 = FakeS3([{"Contents": [{"Key": OLD}]}])
    s3.free_space = True
    if upload_fails:
        s3.upload_error = RuntimeError("original upload problem")
    if cleanup_fails:
        s3.delete_error = RuntimeError("original cleanup problem")
    wire_main(monkeypatch, config, s3)
    if upload_fails or cleanup_fails:
        with pytest.raises(SystemExit) as error:
            backup.cli()
        assert error.value.code == 1
    else:
        assert backup.cli() is None
    assert s3.events == ["upload", "list", "delete"]
    stderr = capsys.readouterr().err
    assert ("Upload failed: original upload problem" in stderr) == upload_fails
    assert ("Cleanup failed: original cleanup problem" in stderr) == cleanup_fails


def test_full_destination_is_cleaned_after_failed_upload_without_hiding_failure(
    monkeypatch: pytest.MonkeyPatch,
    config: backup.Config,
) -> None:
    s3 = FakeS3([{"Contents": [{"Key": OLD}]}])
    wire_main(monkeypatch, config, s3)
    with pytest.raises(backup.BackupError, match="No space left on device") as error:
        backup.main()
    assert error.value.upload_error is not None
    assert error.value.cleanup_error is None
    assert s3.free_space
    assert s3.deleted == [[OLD]]
    assert s3.events == ["upload", "list", "delete"]


@pytest.mark.parametrize("cleanup_fails_during_listing", [False, True])
def test_cleanup_failures_after_upload_are_reported(
    monkeypatch: pytest.MonkeyPatch,
    config: backup.Config,
    cleanup_fails_during_listing: bool,
) -> None:
    s3 = FakeS3([{"Contents": [{"Key": OLD}]}])
    s3.free_space = True
    if cleanup_fails_during_listing:
        s3.list_error = RuntimeError("listing failed")
    else:
        s3.errors = [{"Key": OLD, "Code": "InternalError"}]
    wire_main(monkeypatch, config, s3)
    with pytest.raises(backup.BackupError) as error:
        backup.main()
    assert error.value.upload_error is None
    assert error.value.cleanup_error is not None
    assert s3.events == (
        ["upload", "list"]
        if cleanup_fails_during_listing
        else ["upload", "list", "delete"]
    )


def test_missing_local_file_prevents_any_s3_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("S3_BACKUP_FILENAME", str(tmp_path / "missing.tar.gz"))
    monkeypatch.setenv("S3_BACKUP_BUCKET_NAME", "bucket")
    session = Mock()
    monkeypatch.setattr(backup.boto3.session, "Session", session)
    with pytest.raises(SystemExit):
        backup.cli()
    session.assert_not_called()


@pytest.mark.parametrize("field", ["min_files", "max_age_days"])
def test_negative_retention_settings_rejected(
    config: backup.Config, field: str
) -> None:
    with pytest.raises(ValidationError):
        backup.Config.model_validate(config.model_dump() | {field: -1})


@pytest.mark.parametrize("path,key", [("/database/", "database/" + NEW), ("", NEW)])
def test_upload_and_cleanup_use_the_same_directory(
    config: backup.Config, path: str, key: str
) -> None:
    config.bucket_path = path
    s3 = FakeS3([])
    s3.free_space = True
    backup.upload_file(cast(Any, s3), config)
    assert s3.upload_args["Key"] == key


def test_nothing_expired_still_uploads_successfully(
    monkeypatch: pytest.MonkeyPatch, config: backup.Config
) -> None:
    s3 = FakeS3([{"Contents": [{"Key": NEW}]}])
    s3.free_space = True
    wire_main(monkeypatch, config, s3)
    assert backup.cli() is None
    assert s3.events == ["upload", "list"]


def test_failure_on_later_page_deletes_nothing(config: backup.Config) -> None:
    class FailingPaginator(FakeS3):
        def paginate(self, **kwargs: Any) -> Any:
            yield {"Contents": [{"Key": OLD}]}
            raise RuntimeError("later page failed")

    s3 = FailingPaginator([])
    with pytest.raises(RuntimeError, match="later page"):
        cleanup(s3, config)
    assert s3.deleted == []


def test_partial_batch_failure_does_not_continue(config: backup.Config) -> None:
    s3 = FakeS3([{"Contents": [{"Key": f"prefix{i}/{OLD}"} for i in range(1001)]}])
    s3.errors = [{"Key": "prefix0/" + OLD, "Code": "AccessDenied"}]
    with pytest.raises(RuntimeError, match="AccessDenied"):
        cleanup(s3, config)
    assert len(s3.deleted) == 1
    assert len(s3.deleted[0]) == 1000


def test_local_directory_prevents_any_s3_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("S3_BACKUP_FILENAME", str(tmp_path))
    monkeypatch.setenv("S3_BACKUP_BUCKET_NAME", "bucket")
    session = Mock()
    monkeypatch.setattr(backup.boto3.session, "Session", session)
    with pytest.raises(SystemExit):
        backup.cli()
    session.assert_not_called()
