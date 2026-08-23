from __future__ import annotations
import shutil
from pathlib import Path
from typing import Protocol

SNAPSHOT_KEY = "easynotes.db"


class SnapshotBackend(Protocol):
    def put(self, key: str, path: str) -> None: ...
    def get(self, key: str, dest: str) -> bool: ...
    def exists(self, key: str) -> bool: ...


class NoneBackend:
    def put(self, key, path): pass
    def get(self, key, dest): return False
    def exists(self, key): return False


class LocalSnapshotBackend:
    def __init__(self, directory: str):
        self.dir = Path(directory); self.dir.mkdir(parents=True, exist_ok=True)

    def put(self, key, path):
        shutil.copy2(path, self.dir / key)

    def get(self, key, dest):
        src = self.dir / key
        if not src.exists():
            return False
        shutil.copy2(src, dest); return True

    def exists(self, key):
        return (self.dir / key).exists()


class S3SnapshotBackend:
    def __init__(self, settings):
        import boto3
        self.bucket = settings.snapshot_bucket
        self.s3 = boto3.client("s3", endpoint_url=settings.snapshot_endpoint,
                               aws_access_key_id=settings.snapshot_access_key,
                               aws_secret_access_key=settings.snapshot_secret_key)

    def put(self, key, path):
        self.s3.upload_file(path, self.bucket, key)

    def get(self, key, dest):
        try:
            self.s3.download_file(self.bucket, key, dest); return True
        except Exception:
            return False

    def exists(self, key):
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key); return True
        except Exception:
            return False


def make_backend(settings) -> SnapshotBackend:
    kind = settings.snapshot_backend
    if kind == "s3":
        return S3SnapshotBackend(settings)
    if kind == "local":
        return LocalSnapshotBackend(str(Path(settings.data_dir) / "_snapshots"))
    return NoneBackend()
