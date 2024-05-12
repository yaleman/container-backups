import io
import os
import tempfile
from unittest import mock
from testcontainers.minio import MinioContainer # type: ignore
from datetime import datetime, timedelta, UTC
from container_backups.s3_backup import ENV_PREFIX, Config, main,get_date_from_file_path


@mock.patch.dict(
    os.environ,
    {
        f"{ENV_PREFIX}BUCKET_NAME": "testbucket",
        f"{ENV_PREFIX}MAX_AGE_DAYS" : "3",
        f"{ENV_PREFIX}MIN_FILES" : "2",
        f"{ENV_PREFIX}FILENAME" : "2",
        "AWS_ACCESS_KEY_ID": "minioadmin",
        "AWS_SECRET_ACCESS_KEY": "minioadmin",

    },
)
def test_minio_container() -> None:
    tempdir = tempfile.gettempdir()
    tempfilename = os.path.join(tempdir,f"backup-testfile-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}.tar.gz")
    with open(tempfilename, "w") as f:
        f.write(f"backup_filename: backup-testfile\nbucket_name: {Config().bucket_name}\n")
    with MinioContainer() as minio:
        with mock.patch.dict(os.environ, {
            f"{ENV_PREFIX}ENDPOINT_URL" : f"http://{minio.get_config()["endpoint"]}",
            f"{ENV_PREFIX}FILENAME" : tempfilename,
            }
            , clear=False):
            client = minio.get_client()
            client.make_bucket(Config().bucket_name)
            test_content = b"Hello World"
            for daynum in range(1, 7):
                yesterday = datetime.now(UTC) - timedelta(days=daynum)
                filename = f"backup-testfile-{yesterday.strftime('%Y%m%d-%H%M')}.tar.gz"
                client.put_object(
                    Config().bucket_name,
                    filename,
                    io.BytesIO(test_content),
                    length=len(test_content),
                    metadata={"LastModified" : yesterday.isoformat() }
                )
                print(f"Put {filename}")
            # with NamedTemporaryFile(prefix=f"backup-testfile-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}", suffix=".tar.gz") as tmpfile:

            res = main(use_file_path=True)
            assert res == 4


def test_get_date_from_file_path() -> None:
    assert get_date_from_file_path("backup-testfile-20240505-0556.tar.gz") == datetime(2024, 5, 5, 5, 56).astimezone(UTC)

def test_config() -> None:
    settings = {
        f"{ENV_PREFIX}FILENAME": "foo",
        f"{ENV_PREFIX}BUCKET_NAME" : "bucket",
        }
    with mock.patch.dict(os.environ, settings):
        Config()
