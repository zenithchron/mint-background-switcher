"""Persistent, scalable image indexing and no-repeat batch selection."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import time
import uuid

from .images import SUPPORTED_EXTENSIONS, image_orientation, meets_min_image_size, name_matches_ignore_patterns

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
CREATE TABLE IF NOT EXISTS orientation_cache (
    path TEXT PRIMARY KEY,
    orientation TEXT NOT NULL,
    mtime_ns INTEGER NOT NULL
);
"""


class LibraryIndexError(RuntimeError):
    """Raised when the persistent image index cannot be used safely."""


class LibraryScanCancelled(LibraryIndexError):
    """Raised when a caller cancels an in-progress source-folder scan."""


def _file_mtime_ns(path: str) -> int | None:
    try:
        return os.lstat(path).st_mtime_ns
    except OSError:
        return None


def orientation_matches(required: str | None, actual: str) -> bool:
    """Whether an image with ``actual`` orientation may fill a slot requiring ``required``.

    A ``None`` requirement (or a square monitor) accepts any picture, and an
    unreadable (``"unknown"``) or square picture may serve any monitor, so one
    odd-shaped or damaged picture never blocks rotation.
    """
    if required is None or required == "square":
        return True
    if actual in ("unknown", "square"):
        return True
    return required == actual


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


def normalized_ignore_patterns(patterns: Iterable[str]) -> tuple[str, ...]:
    """Canonicalize ignore patterns so equivalent inputs share one scan signature."""

    return tuple(sorted({str(p).strip().lower() for p in patterns if str(p).strip()}))


def scan_signature(
    roots: Iterable[str],
    *,
    recursive: bool,
    min_image_size: int = 0,
    ignore_hidden: bool = False,
    ignore_patterns: Iterable[str] = (),
) -> str:
    try:
        size = int(min_image_size)
    except (TypeError, ValueError, OverflowError):
        size = 0
    payload = json.dumps(
        {
            "recursive": bool(recursive),
            "min_image_size": max(0, size),
            "ignore_hidden": bool(ignore_hidden),
            "ignore_patterns": list(normalized_ignore_patterns(ignore_patterns)),
            "roots": list(roots),
        },
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
    min_image_size: int = 0,
    ignore_hidden: bool = False,
    ignore_patterns: tuple[str, ...] = (),
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
                    if root_counts is not None:
                        root_counts[raw_root] += 1
                    if not meets_min_image_size(root, min_image_size):
                        continue
                    count += 1
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
                if ignore_hidden:
                    directories[:] = [name for name in directories if not name.startswith(".")]
                directories.sort()
                filenames.sort()
                for filename in filenames:
                    _cancel_if_requested(cancelled)
                    if ignore_hidden and filename.startswith("."):
                        continue
                    if ignore_patterns and name_matches_ignore_patterns(filename, ignore_patterns):
                        continue
                    if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
                        continue
                    if root_counts is not None:
                        root_counts[raw_root] += 1
                    if not meets_min_image_size(os.path.join(directory, filename), min_image_size):
                        continue
                    path = os.path.abspath(os.path.join(directory, filename))
                    count += 1
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
                if ignore_hidden and entry.name.startswith("."):
                    continue
                if ignore_patterns and name_matches_ignore_patterns(entry.name, ignore_patterns):
                    continue
                try:
                    is_image = entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS
                except OSError:
                    continue
                if not is_image:
                    continue
                if root_counts is not None:
                    root_counts[raw_root] += 1
                if not meets_min_image_size(entry, min_image_size):
                    continue
                path = str(_absolute(entry))
                count += 1
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
        min_image_size: int = 0,
        ignore_hidden: bool = False,
        ignore_patterns: Iterable[str] = (),
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[int, str], None] | None = None,
        now_ns: int | None = None,
    ) -> IndexSnapshot:
        roots = normalized_scan_roots(folders)
        patterns = normalized_ignore_patterns(ignore_patterns)
        signature = scan_signature(
            roots,
            recursive=recursive,
            min_image_size=min_image_size,
            ignore_hidden=ignore_hidden,
            ignore_patterns=patterns,
        )
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
                min_image_size=min_image_size,
                ignore_hidden=ignore_hidden,
                ignore_patterns=patterns,
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
            # Drop orientation entries for files that left every scan.
            connection.execute(
                "DELETE FROM orientation_cache WHERE path NOT IN (SELECT DISTINCT path FROM images)"
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
        min_image_size: int = 0,
        ignore_hidden: bool = False,
        ignore_patterns: Iterable[str] = (),
        max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[int, str], None] | None = None,
        now_ns: int | None = None,
    ) -> IndexSnapshot:
        roots = normalized_scan_roots(folders)
        signature = scan_signature(
            roots,
            recursive=recursive,
            min_image_size=min_image_size,
            ignore_hidden=ignore_hidden,
            ignore_patterns=ignore_patterns,
        )
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
            min_image_size=min_image_size,
            ignore_hidden=ignore_hidden,
            ignore_patterns=ignore_patterns,
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

    def cached_orientation(self, path: str) -> str:
        """Return a source's orientation from the index cache.

        Header reads happen only on a cache miss or after the file changed.
        Rotations resolve orientations through the queue's orientation_cache
        join (``_queue_rows``); this is the direct single-path lookup.
        """
        with self._open() as connection:
            return self._cached_orientation(connection, path)

    def _cached_orientation(self, connection: sqlite3.Connection, path: str, mtime_ns: int | None = None) -> str:
        row = connection.execute(
            "SELECT orientation, mtime_ns FROM orientation_cache WHERE path = ?", (path,)
        ).fetchone()
        if mtime_ns is None:
            mtime_ns = _file_mtime_ns(path)
        if row is not None and row["mtime_ns"] == mtime_ns:
            return str(row["orientation"])
        orientation = image_orientation(path)
        connection.execute(
            "INSERT INTO orientation_cache(path, orientation, mtime_ns) VALUES (?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET orientation = excluded.orientation, mtime_ns = excluded.mtime_ns",
            (path, orientation, mtime_ns if mtime_ns is not None else 0),
        )
        return orientation

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
        sequential: bool = False,
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
        if not sequential:
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
        sequential: bool = False,
        orientations: Sequence[str | None] | None = None,
    ) -> list[str]:
        if count <= 0:
            return []
        if orientations is not None and len(orientations) == count:
            return self._draw_oriented_in_transaction(
                connection,
                signature,
                bucket,
                tuple(orientations),
                rng=rng,
                sequential=sequential,
            )
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
                image_count = self._refill(connection, scan_id, bucket, random_source, sequential=sequential)
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

    def _draw_oriented_in_transaction(
        self,
        connection: sqlite3.Connection,
        signature: str,
        bucket: str,
        orientations: tuple[str | None, ...],
        *,
        rng: random.Random | None,
        sequential: bool,
    ) -> list[str]:
        """Draw one candidate per slot, preferring each slot's monitor orientation.

        Non-matching pictures stay queued for a later slot or cycle. When the
        pool holds no matching picture at all, the slot falls back to whatever
        remains so rotation never blocks on shape alone. When fewer pictures
        than slots remain, the pool wraps around and reuses pictures, matching
        the ordinary draw path.
        """
        random_source = rng or random.SystemRandom()
        scan_id = self._scan_id(connection, signature)
        if scan_id is None:
            return []
        selected: list[str] = []
        for required in orientations:
            path = self._pick_oriented_candidate(
                connection,
                scan_id,
                bucket,
                required,
                random_source,
                sequential,
            )
            if path is None:
                break
            selected.append(path)
        return selected

    def _queue_rows(self, connection: sqlite3.Connection, scan_id: int, bucket: str) -> list[sqlite3.Row]:
        return connection.execute(
            "SELECT images.id AS image_id, images.path AS path, "
            "oc.orientation AS orientation, oc.mtime_ns AS cache_mtime "
            "FROM remaining "
            "JOIN images ON images.id = remaining.image_id "
            "LEFT JOIN orientation_cache AS oc ON oc.path = images.path "
            "WHERE remaining.scan_id = ? AND remaining.bucket = ? "
            "ORDER BY remaining.rank, remaining.image_id",
            (scan_id, bucket),
        ).fetchall()

    def _resolve_orientation(self, connection: sqlite3.Connection, row: sqlite3.Row) -> str:
        mtime_ns = _file_mtime_ns(str(row["path"]))
        if row["orientation"] is not None and row["cache_mtime"] == mtime_ns:
            return str(row["orientation"])
        return self._cached_orientation(connection, str(row["path"]), mtime_ns)

    @staticmethod
    def _take_candidate(connection: sqlite3.Connection, scan_id: int, bucket: str, row: sqlite3.Row) -> str:
        connection.execute(
            "DELETE FROM remaining WHERE scan_id = ? AND bucket = ? AND image_id = ?",
            (scan_id, bucket, int(row["image_id"])),
        )
        return str(row["path"])

    def _pick_oriented_candidate(
        self,
        connection: sqlite3.Connection,
        scan_id: int,
        bucket: str,
        required: str | None,
        random_source: random.Random,
        sequential: bool,
    ) -> str | None:
        for _attempt in range(2):
            rows = self._queue_rows(connection, scan_id, bucket)
            if not rows:
                if self._refill(connection, scan_id, bucket, random_source, sequential=sequential) == 0:
                    return None
                continue
            fallback_row = rows[0]
            for row in rows:
                if orientation_matches(required, self._resolve_orientation(connection, row)):
                    return self._take_candidate(connection, scan_id, bucket, row)
            # No matching picture: take the queued head so rotation never
            # blocks on shape alone (an already-used picture reappears here
            # only after the pool wrapped around, mirroring draw_many).
            return self._take_candidate(connection, scan_id, bucket, fallback_row)
        return None

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
        sequential: bool = False,
        orientations: Sequence[str | None] | None = None,
    ) -> list[str]:
        with self.selection() as selection:
            return selection.draw(
                signature, bucket, count, rng=rng, sequential=sequential, orientations=orientations
            )

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
        sequential: bool = False,
        orientations: Sequence[str | None] | None = None,
    ) -> list[str]:
        return self._index._draw_in_transaction(
            self._transaction(),
            signature,
            bucket,
            count,
            rng=rng,
            sequential=sequential,
            orientations=orientations,
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
