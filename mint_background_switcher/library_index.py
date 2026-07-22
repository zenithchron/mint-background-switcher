"""Persistent, scalable image indexing and no-repeat batch selection."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import time
import uuid

from .images import SUPPORTED_EXTENSIONS

INDEX_FILENAME = "library-index.sqlite3"
SCHEMA_VERSION = 2
DEFAULT_MAX_AGE_SECONDS = 300.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY,
    signature TEXT NOT NULL UNIQUE,
    roots_json TEXT NOT NULL,
    recursive INTEGER NOT NULL,
    refreshed_ns INTEGER NOT NULL,
    image_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY,
    scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    UNIQUE (scan_id, path)
);
CREATE INDEX IF NOT EXISTS images_by_signature_path
    ON images (scan_id, path);
CREATE TABLE IF NOT EXISTS remaining (
    scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    bucket TEXT NOT NULL,
    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    PRIMARY KEY (scan_id, bucket, image_id)
);
CREATE INDEX IF NOT EXISTS remaining_draw_order
    ON remaining (scan_id, bucket, rank, image_id);
"""


class LibraryIndexError(RuntimeError):
    """Raised when the persistent image index cannot be used safely."""


class LibraryScanCancelled(LibraryIndexError):
    """Raised when a caller cancels an in-progress source-folder scan."""


@dataclass(frozen=True, slots=True)
class IndexSnapshot:
    signature: str
    roots: tuple[str, ...]
    recursive: bool
    refreshed_ns: int
    image_count: int


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def normalized_scan_roots(folders: Iterable[str]) -> tuple[str, ...]:
    """Canonicalize each configured root once and return a stable unique tuple."""

    roots: set[str] = set()
    for raw_folder in folders:
        if not raw_folder:
            continue
        root = _absolute(raw_folder)
        try:
            root = root.resolve(strict=False)
        except OSError:
            pass
        roots.add(str(root))
    return tuple(sorted(roots))


def scan_signature(roots: Iterable[str], *, recursive: bool) -> str:
    payload = json.dumps(
        {"recursive": bool(recursive), "roots": list(roots)},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _cancel_if_requested(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise LibraryScanCancelled("image-library scan was cancelled")


def _iter_image_paths(
    roots: tuple[str, ...],
    *,
    recursive: bool,
    cancelled: Callable[[], bool] | None,
    progress: Callable[[int, str], None] | None,
    root_counts: dict[str, int] | None = None,
):
    count = 0
    for raw_root in roots:
        _cancel_if_requested(cancelled)
        if root_counts is not None:
            root_counts[raw_root] = 0
        root = Path(raw_root)
        try:
            if root.is_file():
                if root.suffix.lower() in SUPPORTED_EXTENSIONS:
                    count += 1
                    if root_counts is not None:
                        root_counts[raw_root] += 1
                    path = str(_absolute(root))
                    if progress is not None and (count == 1 or count % 500 == 0):
                        progress(count, path)
                    yield path
                continue
            if not root.is_dir():
                continue
        except OSError:
            continue

        if recursive:
            for directory, directories, filenames in os.walk(root, onerror=lambda _error: None):
                _cancel_if_requested(cancelled)
                directories.sort()
                filenames.sort()
                for filename in filenames:
                    _cancel_if_requested(cancelled)
                    if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
                        continue
                    path = os.path.abspath(os.path.join(directory, filename))
                    count += 1
                    if root_counts is not None:
                        root_counts[raw_root] += 1
                    if progress is not None and (count == 1 or count % 500 == 0):
                        progress(count, path)
                    yield path
        else:
            try:
                entries = sorted(root.iterdir(), key=lambda entry: entry.name)
            except OSError:
                continue
            for entry in entries:
                _cancel_if_requested(cancelled)
                try:
                    is_image = entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS
                except OSError:
                    continue
                if not is_image:
                    continue
                path = str(_absolute(entry))
                count += 1
                if root_counts is not None:
                    root_counts[raw_root] += 1
                if progress is not None and (count == 1 or count % 500 == 0):
                    progress(count, path)
                yield path


class LibraryIndex:
    """SQLite-backed image index and no-repeat pool stored in an MBS working directory."""

    def __init__(self, working_directory: str | Path):
        self.working_directory = _absolute(working_directory)
        self.database_path = self.working_directory / INDEX_FILENAME

    def _validate_database_path(self) -> None:
        try:
            self.working_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LibraryIndexError(f"could not create image-index directory {self.working_directory}: {exc}") from exc
        try:
            if self.database_path.is_symlink():
                raise LibraryIndexError(f"image-index database must not be a symbolic link: {self.database_path}")
            if self.database_path.exists() and not self.database_path.is_file():
                raise LibraryIndexError(f"image-index database is not a regular file: {self.database_path}")
        except OSError as exc:
            raise LibraryIndexError(f"could not inspect image-index database {self.database_path}: {exc}") from exc

    def _open(self, *, recover: bool = True) -> sqlite3.Connection:
        self._validate_database_path()
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.database_path, timeout=10.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA synchronous = FULL")
            current_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if current_version not in (0, SCHEMA_VERSION):
                raise sqlite3.DatabaseError(f"unsupported image-index schema version: {current_version}")
            connection.executescript(_SCHEMA)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return connection
        except sqlite3.OperationalError as exc:
            if connection is not None:
                connection.close()
            raise LibraryIndexError(f"could not open image-index database: {exc}") from exc
        except sqlite3.DatabaseError as exc:
            if connection is not None:
                connection.close()
            if not recover:
                raise LibraryIndexError(f"could not open image-index database: {exc}") from exc
            self._quarantine_corrupt_database()
            return self._open(recover=False)
        except OSError as exc:
            if connection is not None:
                connection.close()
            raise LibraryIndexError(f"could not open image-index database {self.database_path}: {exc}") from exc

    def _quarantine_corrupt_database(self) -> None:
        if not self.database_path.exists():
            return
        identifier = uuid.uuid4().hex
        quarantine = self.working_directory / f"library-index.corrupt-{identifier}.sqlite3"
        try:
            os.replace(self.database_path, quarantine)
            for suffix in ("-journal", "-shm", "-wal"):
                sidecar = Path(f"{self.database_path}{suffix}")
                if sidecar.exists() and not sidecar.is_symlink() and sidecar.is_file():
                    os.replace(sidecar, Path(f"{quarantine}{suffix}"))
        except OSError as exc:
            raise LibraryIndexError(f"could not quarantine corrupt image index: {exc}") from exc

    @staticmethod
    def _snapshot_from_row(row: sqlite3.Row | None) -> IndexSnapshot | None:
        if row is None:
            return None
        roots_raw = json.loads(row["roots_json"])
        roots = tuple(str(root) for root in roots_raw) if isinstance(roots_raw, list) else ()
        return IndexSnapshot(
            signature=str(row["signature"]),
            roots=roots,
            recursive=bool(row["recursive"]),
            refreshed_ns=int(row["refreshed_ns"]),
            image_count=int(row["image_count"]),
        )

    def snapshot(self, signature: str) -> IndexSnapshot | None:
        try:
            with self._open() as connection:
                row = connection.execute(
                    "SELECT signature, roots_json, recursive, refreshed_ns, image_count FROM scans WHERE signature = ?",
                    (signature,),
                ).fetchone()
                return self._snapshot_from_row(row)
        except (json.JSONDecodeError, TypeError, ValueError):
            self._quarantine_corrupt_database()
            return None

    def refresh(
        self,
        folders: Iterable[str],
        *,
        recursive: bool,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[int, str], None] | None = None,
        now_ns: int | None = None,
    ) -> IndexSnapshot:
        roots = normalized_scan_roots(folders)
        signature = scan_signature(roots, recursive=recursive)
        refreshed_ns = time.time_ns() if now_ns is None else int(now_ns)
        connection = self._open()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DROP TABLE IF EXISTS temp.scan_stage")
            connection.execute("CREATE TEMP TABLE scan_stage (path TEXT PRIMARY KEY)")
            batch: list[tuple[str]] = []
            root_counts: dict[str, int] = {}
            for path in _iter_image_paths(
                roots,
                recursive=recursive,
                cancelled=cancelled,
                progress=progress,
                root_counts=root_counts,
            ):
                batch.append((path,))
                if len(batch) >= 1000:
                    connection.executemany("INSERT OR IGNORE INTO scan_stage(path) VALUES (?)", batch)
                    batch.clear()
            if batch:
                connection.executemany("INSERT OR IGNORE INTO scan_stage(path) VALUES (?)", batch)
            _cancel_if_requested(cancelled)
            image_count = int(connection.execute("SELECT COUNT(*) FROM scan_stage").fetchone()[0])
            complete = bool(roots) and all(root_counts.get(root, 0) > 0 for root in roots)
            effective_refreshed_ns = refreshed_ns if complete else 0
            if progress is not None and image_count > 1 and image_count % 500:
                progress(image_count, "")
            scan_row = connection.execute("SELECT id FROM scans WHERE signature = ?", (signature,)).fetchone()
            if scan_row is None:
                cursor = connection.execute(
                    "INSERT INTO scans(signature, roots_json, recursive, refreshed_ns, image_count) "
                    "VALUES (?, ?, ?, ?, 0)",
                    (signature, json.dumps(list(roots)), int(recursive), effective_refreshed_ns),
                )
                if cursor.lastrowid is None:  # pragma: no cover - SQLite contract
                    raise LibraryIndexError("image-index scan row was not created")
                scan_id = int(cursor.lastrowid)
            else:
                scan_id = int(scan_row["id"])
            connection.execute(
                "INSERT INTO images(scan_id, path) "
                "SELECT ?, stage.path FROM scan_stage AS stage "
                "WHERE NOT EXISTS (SELECT 1 FROM images AS current "
                "WHERE current.scan_id = ? AND current.path = stage.path)",
                (scan_id, scan_id),
            )
            connection.execute(
                "DELETE FROM images WHERE scan_id = ? AND path NOT IN (SELECT path FROM scan_stage)",
                (scan_id,),
            )
            connection.execute(
                "UPDATE scans SET roots_json = ?, recursive = ?, refreshed_ns = ?, image_count = ? "
                "WHERE id = ?",
                (json.dumps(list(roots)), int(recursive), effective_refreshed_ns, image_count, scan_id),
            )
            connection.execute("DROP TABLE scan_stage")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return IndexSnapshot(signature, roots, bool(recursive), effective_refreshed_ns, image_count)

    def ensure(
        self,
        folders: Iterable[str],
        *,
        recursive: bool,
        max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[int, str], None] | None = None,
        now_ns: int | None = None,
    ) -> IndexSnapshot:
        roots = normalized_scan_roots(folders)
        signature = scan_signature(roots, recursive=recursive)
        current = self.snapshot(signature)
        current_time = time.time_ns() if now_ns is None else int(now_ns)
        max_age_ns = max(0, int(max_age_seconds * 1_000_000_000))
        if (
            current is not None
            and current.refreshed_ns > 0
            and 0 <= current_time - current.refreshed_ns <= max_age_ns
        ):
            return current
        return self.refresh(
            roots,
            recursive=recursive,
            cancelled=cancelled,
            progress=progress,
            now_ns=current_time,
        )

    def paths(self, signature: str) -> list[str]:
        with self._open() as connection:
            rows = connection.execute(
                "SELECT images.path FROM images JOIN scans ON scans.id = images.scan_id "
                "WHERE scans.signature = ? ORDER BY images.path",
                (signature,),
            ).fetchall()
            return [str(row["path"]) for row in rows]

    @staticmethod
    def _scan_id(connection: sqlite3.Connection, signature: str) -> int | None:
        row = connection.execute("SELECT id FROM scans WHERE signature = ?", (signature,)).fetchone()
        return None if row is None else int(row["id"])

    @staticmethod
    def _refill(
        connection: sqlite3.Connection,
        scan_id: int,
        bucket: str,
        rng: random.Random,
    ) -> int:
        image_ids = [
            int(row["id"])
            for row in connection.execute(
                "SELECT id FROM images WHERE scan_id = ? ORDER BY path",
                (scan_id,),
            )
        ]
        if not image_ids:
            return 0
        rng.shuffle(image_ids)
        connection.execute(
            "DELETE FROM remaining WHERE scan_id = ? AND bucket = ?",
            (scan_id, bucket),
        )
        connection.executemany(
            "INSERT INTO remaining(scan_id, bucket, image_id, rank) VALUES (?, ?, ?, ?)",
            ((scan_id, bucket, image_id, rank) for rank, image_id in enumerate(image_ids)),
        )
        return len(image_ids)

    def _draw_in_transaction(
        self,
        connection: sqlite3.Connection,
        signature: str,
        bucket: str,
        count: int,
        *,
        rng: random.Random | None = None,
    ) -> list[str]:
        if count <= 0:
            return []
        random_source = rng or random.SystemRandom()
        selected: list[str] = []
        selected_in_batch: set[str] = set()
        scan_id = self._scan_id(connection, signature)
        if scan_id is None:
            return []
        while len(selected) < count:
            fetch_limit = max(1, count - len(selected) + len(selected_in_batch))
            rows = connection.execute(
                "SELECT remaining.image_id, images.path FROM remaining "
                "JOIN images ON images.id = remaining.image_id "
                "WHERE remaining.scan_id = ? AND remaining.bucket = ? "
                "ORDER BY remaining.rank, remaining.image_id LIMIT ?",
                (scan_id, bucket, fetch_limit),
            ).fetchall()
            candidates = [
                (int(row["image_id"]), str(row["path"]))
                for row in rows
                if str(row["path"]) not in selected_in_batch
            ]
            if not candidates:
                image_count = self._refill(connection, scan_id, bucket, random_source)
                if image_count == 0:
                    break
                rows = connection.execute(
                    "SELECT remaining.image_id, images.path FROM remaining "
                    "JOIN images ON images.id = remaining.image_id "
                    "WHERE remaining.scan_id = ? AND remaining.bucket = ? "
                    "ORDER BY remaining.rank, remaining.image_id LIMIT ?",
                    (scan_id, bucket, fetch_limit),
                ).fetchall()
                candidates = [
                    (int(row["image_id"]), str(row["path"]))
                    for row in rows
                    if str(row["path"]) not in selected_in_batch
                ]
                if not candidates:
                    selected_in_batch.clear()
                    candidates = [(int(row["image_id"]), str(row["path"])) for row in rows]
            needed = count - len(selected)
            chosen = candidates[:needed]
            if not chosen:
                break
            connection.executemany(
                "DELETE FROM remaining WHERE scan_id = ? AND bucket = ? AND image_id = ?",
                ((scan_id, bucket, image_id) for image_id, _path in chosen),
            )
            chosen_paths = [path for _image_id, path in chosen]
            selected.extend(chosen_paths)
            selected_in_batch.update(chosen_paths)
        return selected

    def selection(self) -> LibrarySelection:
        """Return a lazy transaction that can span selection and wallpaper composition."""

        return LibrarySelection(self)

    def draw(
        self,
        signature: str,
        bucket: str,
        count: int,
        *,
        rng: random.Random | None = None,
    ) -> list[str]:
        with self.selection() as selection:
            return selection.draw(signature, bucket, count, rng=rng)

    def remaining_count(self, signature: str, bucket: str) -> int:
        with self._open() as connection:
            scan_id = self._scan_id(connection, signature)
            if scan_id is None:
                return 0
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM remaining WHERE scan_id = ? AND bucket = ?",
                    (scan_id, bucket),
                ).fetchone()[0]
            )

    def _discard_in_transaction(self, connection: sqlite3.Connection, signature: str, path: str) -> None:
        scan_id = self._scan_id(connection, signature)
        if scan_id is None:
            return
        connection.execute("DELETE FROM images WHERE scan_id = ? AND path = ?", (scan_id, path))
        connection.execute(
            "UPDATE scans SET image_count = (SELECT COUNT(*) FROM images WHERE scan_id = ?) "
            "WHERE id = ?",
            (scan_id, scan_id),
        )

    def discard(self, signature: str, path: str) -> None:
        """Remove one missing or undecodable source from the current index and pools."""

        with self._open() as connection:
            self._discard_in_transaction(connection, signature, path)


class LibrarySelection:
    """Lazy SQLite transaction for one wallpaper selection/composition attempt."""

    def __init__(self, index: LibraryIndex):
        self._index = index
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> LibrarySelection:
        return self

    def _transaction(self) -> sqlite3.Connection:
        if self._connection is None:
            connection = self._index._open()
            try:
                connection.execute("BEGIN IMMEDIATE")
            except BaseException:
                connection.close()
                raise
            self._connection = connection
        return self._connection

    def draw(
        self,
        signature: str,
        bucket: str,
        count: int,
        *,
        rng: random.Random | None = None,
    ) -> list[str]:
        return self._index._draw_in_transaction(
            self._transaction(),
            signature,
            bucket,
            count,
            rng=rng,
        )

    def discard(self, signature: str, path: str) -> None:
        self._index._discard_in_transaction(self._transaction(), signature, path)

    def __exit__(self, _exc_type: object, error: BaseException | None, _traceback: object) -> None:
        if self._connection is not None:
            try:
                if error is None:
                    self._connection.commit()
                else:
                    self._connection.rollback()
            finally:
                self._connection.close()
                self._connection = None
