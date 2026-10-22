"""Execute entrypoints with stub commands; never contact a DB or S3."""

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("engine", ["mysql", "postgresql"])
@pytest.mark.parametrize("failure", ["", "dump", "gzip", "s3"])
def test_entrypoint_stops_on_failure(tmp_path: Path, engine: str, failure: str) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    workdir = tmp_path / "work"
    workdir.mkdir()
    commands = {
        "mktemp": '#!/bin/bash\nprintf "%s\\n" "$TEST_WORKDIR"\n',
        "mysqldump": """#!/bin/bash
for arg in "$@"; do
    case "$arg" in --result-file=*) printf 'backup' > "${arg#*=}" ;; esac
done
[ "$FAIL_STAGE" != dump ]
""",
        "pg_dumpall": """#!/bin/bash
for arg in "$@"; do
    case "$arg" in --file=*) printf 'backup' > "${arg#*=}" ;; esac
done
[ "$FAIL_STAGE" != dump ]
""",
        "gzip": """#!/bin/bash
if [ "$FAIL_STAGE" = gzip ]; then exit 23; fi
for arg in "$@"; do
    case "$arg" in -*) ;; *) mv "$arg" "$arg.gz" ;; esac
done
""",
        "s3_backup": """#!/bin/bash
printf '%s\\n' "$S3_BACKUP_FILENAME" > "$TEST_WORKDIR/upload-called"
[ -f "$S3_BACKUP_FILENAME" ] || exit 31
[ "$FAIL_STAGE" != s3 ]
""",
    }
    for name, source in commands.items():
        p = bindir / name
        p.write_text(source)
        p.chmod(0o755)
    # A stale archive must not be selected as the new upload.
    (workdir / "stale.tar.gz").write_text("stale")
    env = os.environ | {
        "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
        "TEST_WORKDIR": str(workdir),
        "FAIL_STAGE": failure,
        "BACKUP_NAME": "test",
        "DB_SERVER": "offline",
        "DB_USER": "test",
        "DB_PASS": "test",
        "POSTGRESQL_SERVER": "offline",
        "POSTGRESQL_USER": "test",
        "POSTGRESQL_PASS": "test",
        "S3_BACKUP_BUCKET_NAME": "offline-test",
    }
    result = subprocess.run(
        ["bash", str(ROOT / f"entrypoint-{engine}-backup.sh")],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (result.returncode == 0) == (failure == ""), result.stdout + result.stderr
    assert ("Task complete" in result.stdout) == (failure == "")
    uploaded = workdir / "upload-called"
    assert uploaded.exists() == (failure in ["", "s3"])
    if uploaded.exists():
        assert uploaded.read_text().strip().startswith("backup-test-")
        assert uploaded.read_text().strip().endswith(".tar.gz")
