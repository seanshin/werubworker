"""BackupManager -- automated backup and restore for WeruBWorker data stores.

Supports scheduled backups of SQLite databases (Wiki, Vault, Metrics, etc.),
local and S3-compatible storage, incremental backups, and one-click restore.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class BackupConfig:
    """백업 설정."""

    backup_dir: str = ""           # 로컬 백업 디렉토리
    s3_bucket: str = ""            # S3 버킷 (비어있으면 로컬만)
    s3_prefix: str = "backups/"    # S3 키 접두사
    retention_days: int = 30       # 보존 기간
    max_backups: int = 50          # 최대 백업 수


@dataclass
class BackupRecord:
    """백업 기록."""

    id: str = ""
    timestamp: float = 0.0
    targets: list[str] = field(default_factory=list)  # 백업 대상 DB 이름
    size_bytes: int = 0
    location: str = ""             # 파일 경로 또는 S3 URL
    status: str = "completed"      # completed, failed
    error: str = ""


class BackupManager:
    """WeruBWorker 데이터 백업/복원 관리자."""

    # 백업 대상 DB 파일 (data_dir 기준 상대 경로)
    BACKUP_TARGETS = {
        "wiki": "wiki_pages.db",
        "metrics": "metrics.db",
        "alerts": "alerting.db",
        "incidents": "incidents.db",
        "healthcheck": "healthcheck.db",
        "automation": "automation.db",
        "audit": "coworker.db",
        "workflows": "workflows.db",
        "gitea": "/opt/homebrew/var/gitea/data/gitea.db",
        "pipelines": "pipelines.db",
    }

    def __init__(self, data_dir: str | Path, config: BackupConfig | None = None) -> None:
        self._data_dir = Path(data_dir)
        self._config = config or BackupConfig()
        if not self._config.backup_dir:
            self._config.backup_dir = str(self._data_dir / "backups")
        self._backup_dir = Path(self._config.backup_dir)
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_dir / "backup_records.db"
        self._db = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS backup_records (
                id TEXT PRIMARY KEY,
                timestamp REAL NOT NULL,
                targets TEXT NOT NULL DEFAULT '[]',
                size_bytes INTEGER DEFAULT 0,
                location TEXT DEFAULT '',
                status TEXT DEFAULT 'completed',
                error TEXT DEFAULT ''
            );
        """)
        self._db.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_backup(self, targets: list[str] | None = None) -> dict:
        """지정된 대상을 백업한다. targets가 None이면 전체 백업."""
        import secrets as _secrets

        if targets is None:
            targets = list(self.BACKUP_TARGETS.keys())

        backup_id = f"bk-{_secrets.token_hex(5)}"
        timestamp = time.time()
        ts_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(timestamp))
        backup_subdir = self._backup_dir / f"backup_{ts_str}_{backup_id}"
        backup_subdir.mkdir(parents=True, exist_ok=True)

        total_size = 0
        backed_up: list[str] = []
        errors: list[str] = []

        for target in targets:
            db_file = self.BACKUP_TARGETS.get(target)
            if not db_file:
                errors.append(f"unknown target: {target}")
                continue

            # 절대 경로와 상대 경로 분기 처리
            if os.path.isabs(db_file):
                src = Path(db_file)
            else:
                src = self._data_dir / db_file
            if not src.exists():
                continue  # 아직 생성되지 않은 DB는 건너뜀

            dst = backup_subdir / Path(db_file).name
            try:
                # SQLite 안전 백업 (VACUUM INTO 사용)
                conn = sqlite3.connect(str(src))
                conn.execute(f"VACUUM INTO '{dst}'")
                conn.close()
                size = dst.stat().st_size
                total_size += size
                backed_up.append(target)
            except Exception:
                # 폴백: 파일 복사
                try:
                    shutil.copy2(str(src), str(dst))
                    size = dst.stat().st_size
                    total_size += size
                    backed_up.append(target)
                except Exception as e2:
                    errors.append(f"{target}: {e2}")

        status = "completed" if not errors else ("partial" if backed_up else "failed")
        location = str(backup_subdir)

        # Generate signed manifest for integrity verification
        manifest = self._create_manifest(backup_subdir, backed_up, backup_id, timestamp)

        self._db.execute(
            "INSERT INTO backup_records (id, timestamp, targets, size_bytes, location, status, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (backup_id, timestamp, json.dumps(backed_up), total_size, location, status, "; ".join(errors)),
        )
        self._db.commit()

        # S3 업로드 (설정된 경우)
        if self._config.s3_bucket:
            self._upload_to_s3(backup_subdir, backup_id)

        return {
            "ok": status != "failed",
            "id": backup_id,
            "targets": backed_up,
            "size_bytes": total_size,
            "size_human": self._human_size(total_size),
            "location": location,
            "status": status,
            "errors": errors,
            "manifest_signed": manifest.get("signed", False),
        }

    def restore(self, backup_id: str, targets: list[str] | None = None) -> dict:
        """백업에서 복원한다. 매니페스트 서명이 있으면 무결성 검증 후 진행."""
        record = self._get_record(backup_id)
        if not record:
            return {"ok": False, "error": "backup not found"}

        backup_dir = Path(record["location"])
        if not backup_dir.exists():
            return {"ok": False, "error": "backup directory not found"}

        # Verify manifest signature before restore
        manifest_ok, manifest_err = self._verify_manifest(backup_dir)
        if manifest_err:
            return {"ok": False, "error": f"Manifest verification failed: {manifest_err}"}

        restore_targets = targets or json.loads(record["targets"])
        restored: list[str] = []
        errors: list[str] = []

        for target in restore_targets:
            db_file = self.BACKUP_TARGETS.get(target)
            if not db_file:
                continue

            src = backup_dir / Path(db_file).name
            if not src.exists():
                errors.append(f"{target}: backup file not found")
                continue

            if os.path.isabs(db_file):
                dst = Path(db_file)
            else:
                dst = self._data_dir / db_file
            try:
                # 기존 파일 백업
                if dst.exists():
                    pre_restore = dst.with_suffix(".db.pre_restore")
                    shutil.copy2(str(dst), str(pre_restore))

                shutil.copy2(str(src), str(dst))
                restored.append(target)
            except Exception as e:
                errors.append(f"{target}: {e}")

        return {
            "ok": len(restored) > 0,
            "restored": restored,
            "errors": errors,
        }

    def list_backups(self, limit: int = 20) -> list[dict]:
        """백업 기록 조회."""
        rows = self._db.execute(
            "SELECT id, timestamp, targets, size_bytes, location, status, error "
            "FROM backup_records ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "targets": json.loads(r[2]),
                "size_bytes": r[3],
                "size_human": self._human_size(r[3]),
                "location": r[4],
                "status": r[5],
                "error": r[6],
            }
            for r in rows
        ]

    def delete_backup(self, backup_id: str) -> dict:
        """백업 삭제."""
        record = self._get_record(backup_id)
        if not record:
            return {"ok": False, "error": "not found"}

        # 파일 삭제
        backup_dir = Path(record["location"])
        if backup_dir.exists():
            shutil.rmtree(str(backup_dir), ignore_errors=True)

        self._db.execute("DELETE FROM backup_records WHERE id = ?", (backup_id,))
        self._db.commit()
        return {"ok": True}

    def prune(self) -> dict:
        """보존 기간/최대 수 초과 백업 삭제."""
        cutoff = time.time() - self._config.retention_days * 86400

        # 기간 초과 삭제
        old = self._db.execute(
            "SELECT id FROM backup_records WHERE timestamp < ?", (cutoff,),
        ).fetchall()
        for row in old:
            self.delete_backup(row[0])

        # 최대 수 초과 삭제
        excess = self._db.execute(
            "SELECT id FROM backup_records ORDER BY timestamp DESC LIMIT -1 OFFSET ?",
            (self._config.max_backups,),
        ).fetchall()
        for row in excess:
            self.delete_backup(row[0])

        return {"ok": True, "pruned": len(old) + len(excess)}

    def available_targets(self) -> list[dict]:
        """백업 가능한 대상 목록."""
        targets = []
        for name, db_file in self.BACKUP_TARGETS.items():
            if os.path.isabs(db_file):
                path = Path(db_file)
            else:
                path = self._data_dir / db_file
            targets.append({
                "name": name,
                "file": db_file,
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
                "size_human": self._human_size(path.stat().st_size) if path.exists() else "0 B",
            })
        return targets

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_record(self, backup_id: str) -> dict | None:
        row = self._db.execute(
            "SELECT id, timestamp, targets, size_bytes, location, status, error "
            "FROM backup_records WHERE id = ?",
            (backup_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "timestamp": row[1],
            "targets": row[2],
            "size_bytes": row[3],
            "location": row[4],
            "status": row[5],
            "error": row[6],
        }

    def _upload_to_s3(self, backup_dir: Path, backup_id: str) -> None:
        """S3 호환 스토리지에 업로드."""
        try:
            import boto3

            s3 = boto3.client("s3")
            for f in backup_dir.iterdir():
                key = f"{self._config.s3_prefix}{backup_id}/{f.name}"
                s3.upload_file(str(f), self._config.s3_bucket, key)
                log.info("uploaded %s to s3://%s/%s", f.name, self._config.s3_bucket, key)
        except Exception:
            log.warning("S3 upload failed", exc_info=True)

    def _create_manifest(
        self, backup_dir: Path, targets: list[str], backup_id: str, timestamp: float,
    ) -> dict:
        """Create a signed manifest for backup integrity verification."""
        import hashlib as _hashlib

        file_hashes: dict[str, str] = {}
        for f in sorted(backup_dir.iterdir()):
            if f.name == "manifest.json":
                continue
            h = _hashlib.sha256(f.read_bytes()).hexdigest()
            file_hashes[f.name] = h

        manifest: dict[str, Any] = {
            "backup_id": backup_id,
            "timestamp": timestamp,
            "targets": targets,
            "files": file_hashes,
        }

        # Sign with HMAC
        try:
            from ..security.hmac_signer import sign_payload
            payload = json.dumps(manifest, separators=(",", ":"), sort_keys=True)
            manifest["signature"] = sign_payload(payload, f"backup-{backup_id}")
            manifest["signed"] = True
        except Exception:
            manifest["signed"] = False

        manifest_path = backup_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        return manifest

    def _verify_manifest(self, backup_dir: Path) -> tuple[bool, str]:
        """Verify a backup manifest signature and file hashes.

        Returns (True, "") on success, or (True, "") if no manifest exists (legacy).
        Returns (False, error) on verification failure.
        """
        import hashlib as _hashlib

        manifest_path = backup_dir / "manifest.json"
        if not manifest_path.exists():
            return True, ""  # Legacy backup without manifest — allow restore

        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            return False, "Cannot read manifest"

        if not manifest.get("signed"):
            return True, ""  # Unsigned manifest — allow

        # Verify HMAC signature
        sig = manifest.pop("signature", "")
        signed_flag = manifest.pop("signed", True)
        try:
            from ..security.hmac_signer import sign_payload
            payload = json.dumps(manifest, separators=(",", ":"), sort_keys=True)
            expected = sign_payload(payload, f"backup-{manifest['backup_id']}")
            import hmac
            if not hmac.compare_digest(expected, sig):
                return False, "Signature mismatch — backup may have been tampered with"
        except Exception as exc:
            return False, f"Signature verification error: {exc}"

        # Verify file hashes
        for fname, expected_hash in manifest.get("files", {}).items():
            fpath = backup_dir / fname
            if not fpath.exists():
                return False, f"Missing file: {fname}"
            actual_hash = _hashlib.sha256(fpath.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                return False, f"Hash mismatch for {fname}"

        return True, ""

    @staticmethod
    def _human_size(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024  # type: ignore[assignment]
        return f"{size:.1f} TB"
