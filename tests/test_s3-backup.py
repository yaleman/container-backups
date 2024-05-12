import io
import os
import tempfile
from unittest import mock
from testcontainers.minio import MinioContainer # type: ignore
from datetime import datetime, timedelta, UTC
from s3_backup import main,get_date_from_file_path


@mock.patch.dict(
    os.environ,
    {
        "BUCKET_NAME": "testbucket",
        "BACKUP_MAX_AGE_DAYS" : "3",
        "BACKUP_MIN_FILES" : "2",
        "AWS_ACCESS_KEY_ID": "minioadmin",
        "AWS_SECRET_ACCESS_KEY": "minioadmin",
    },
)
def test_minio_container() -> None:
    with MinioContainer() as minio:
        with mock.patch.dict(os.environ, {"S3_ENDPOINT" : f"http://{minio.get_config()["endpoint"]}"}, clear=False):
            client = minio.get_client()
            client.make_bucket(os.getenv("BUCKET_NAME"))
            test_content = b"Hello World"
            for daynum in range(1, 7):
                yesterday = datetime.now(UTC) - timedelta(days=daynum)
                filename = f"backup-testfile-{yesterday.strftime('%Y%m%d-%H%M')}.tar.gz"
                client.put_object(
                    os.getenv("BUCKET_NAME"),
                    filename,
                    io.BytesIO(test_content),
                    length=len(test_content),
                    metadata={"LastModified" : yesterday.isoformat() }
                )
                print(f"Put {filename}")
            # with NamedTemporaryFile(prefix=f"backup-testfile-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}", suffix=".tar.gz") as tmpfile:
            tempdir = tempfile.gettempdir()
            tempfilename = os.path.join(tempdir,f"backup-testfile-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}.tar.gz")
            with open(tempfilename, "w") as f:
                f.write(f"backup_filename: backup-testfile\nbucket_name: {os.getenv('BUCKET_NAME')}\n")
            with mock.patch.dict(os.environ, {"BACKUP_FILENAME": tempfilename}):
                res = main(use_file_path=True)
            assert res == 4


def test_get_date_from_file_path() -> None:
    assert get_date_from_file_path("backup-testfile-20240505-0556.tar.gz") == datetime(2024, 5, 5, 5, 56).astimezone(UTC)
