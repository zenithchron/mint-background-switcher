#!/usr/bin/env python3
"""Deterministic validation helpers for the GitHub Release workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

SCHEMA = 1
SEMANTIC_MISMATCH = 10
NOT_FOUND = 11
SCHEMA_FAILURE = 12
STRICT_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
MANIFEST_START = "<!-- mint-background-switcher-release-manifest-v1\n"
MANIFEST_END = "\n-->"


class SemanticMismatch(Exception):
    """The external state is well-formed but not the expected release state."""


class SchemaFailure(Exception):
    """External data is malformed or uses an unsupported schema."""


class NotFound(Exception):
    """The requested release was not present in a successful API listing."""


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, ValueError) as error:
        raise SchemaFailure(f"invalid JSON in {path.name}: {error}") from error


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SemanticMismatch(message)


def require_schema(condition: bool, message: str) -> None:
    if not condition:
        raise SchemaFailure(message)


def validate_identity(tag: str, version: str, commit: str, *, structural: bool = False) -> None:
    check = require_schema if structural else require
    match = STRICT_TAG.fullmatch(tag)
    check(match is not None, f"non-canonical release tag: {tag}")
    check(version == tag.removeprefix("v"), "tag/version mismatch")
    check(COMMIT.fullmatch(commit) is not None, "invalid release commit")


def expected_names(version: str) -> list[str]:
    return [
        f"mint_background_switcher-{version}-py3-none-any.whl",
        f"mint_background_switcher-{version}.tar.gz",
    ]


def inspect_artifact(path: Path) -> dict[str, Any]:
    require(path.exists(), f"missing artifact: {path.name}")
    require(path.is_file() and not path.is_symlink(), f"artifact is not a regular file: {path.name}")
    size = path.stat().st_size
    require(size > 0, f"empty artifact: {path.name}")
    return {"name": path.name, "sha256": file_sha256(path), "size": size}


def manifest_from_dist(dist: Path, *, tag: str, version: str, commit: str) -> dict[str, Any]:
    validate_identity(tag, version, commit)
    require(dist.is_dir() and not dist.is_symlink(), "distribution directory is missing or invalid")
    names = expected_names(version)
    actual = sorted(path.name for path in dist.iterdir())
    require(actual == names, f"unexpected distribution set: {actual}")
    artifacts = [inspect_artifact(dist / name) for name in names]
    return {
        "artifacts": artifacts,
        "commit": commit,
        "schema": SCHEMA,
        "tag": tag,
        "version": version,
    }


def validate_manifest(
    manifest: Any,
    *,
    tag: str | None = None,
    version: str | None = None,
    commit: str | None = None,
    dist: Path | None = None,
) -> dict[str, Any]:
    require_schema(isinstance(manifest, dict), "release manifest is not an object")
    require_schema(
        set(manifest) == {"artifacts", "commit", "schema", "tag", "version"},
        "release manifest has unexpected fields",
    )
    require_schema(type(manifest["schema"]) is int and manifest["schema"] == SCHEMA, "unsupported release manifest schema")
    manifest_tag = manifest["tag"]
    manifest_version = manifest["version"]
    manifest_commit = manifest["commit"]
    require_schema(all(isinstance(value, str) for value in (manifest_tag, manifest_version, manifest_commit)), "release identity fields are not strings")
    validate_identity(manifest_tag, manifest_version, manifest_commit, structural=True)
    if tag is not None:
        require(manifest_tag == tag, "release manifest tag mismatch")
    if version is not None:
        require(manifest_version == version, "release manifest version mismatch")
    if commit is not None:
        require(manifest_commit == commit, "release manifest commit mismatch")

    artifacts = manifest["artifacts"]
    require_schema(isinstance(artifacts, list), "release manifest artifacts are not a list")
    names = expected_names(manifest_version)
    require_schema(len(artifacts) == len(names), "release manifest has the wrong artifact count")
    for artifact, expected_name in zip(artifacts, names, strict=True):
        require_schema(isinstance(artifact, dict), "release manifest artifact is not an object")
        require_schema(set(artifact) == {"name", "sha256", "size"}, "release manifest artifact has unexpected fields")
        require_schema(artifact["name"] == expected_name, "release manifest artifact order or name mismatch")
        require_schema(isinstance(artifact["sha256"], str) and SHA256.fullmatch(artifact["sha256"]) is not None, "invalid artifact SHA-256")
        require_schema(isinstance(artifact["size"], int) and not isinstance(artifact["size"], bool) and artifact["size"] > 0, "invalid artifact size")

    if dist is not None:
        rebuilt = manifest_from_dist(
            dist,
            tag=manifest_tag,
            version=manifest_version,
            commit=manifest_commit,
        )
        require(rebuilt == manifest, "release manifest differs from the artifact bytes")
    return manifest


def changelog_body(changelog: Path, version: str) -> str:
    text = changelog.read_text(encoding="utf-8")
    heading = re.compile(rf"^## \[{re.escape(version)}\](?:[ \t]+-[ \t]+[^\r\n]*)?$", re.MULTILINE)
    matches = list(heading.finditer(text))
    require(len(matches) == 1, f"expected one changelog section for {version}")
    body_start = text.find("\n", matches[0].end())
    require(body_start >= 0, f"empty changelog section for {version}")
    next_heading = re.search(r"^## \[", text[body_start + 1 :], re.MULTILINE)
    body_end = body_start + 1 + next_heading.start() if next_heading else len(text)
    body = text[body_start + 1 : body_end].strip()
    require(bool(body), f"empty changelog section for {version}")
    return body


def render_notes(changelog: Path, manifest: dict[str, Any]) -> str:
    body = changelog_body(changelog, manifest["version"])
    artifact_lines = [
        f"- `{artifact['name']}`: `{artifact['sha256']}` (`{artifact['size']}` bytes)"
        for artifact in manifest["artifacts"]
    ]
    commit_line = f"- Tagged commit: `{manifest['commit']}`"
    hashes = "\n".join(artifact_lines)
    notes = (
        f"{body}\n\n"
        "### Release verification\n\n"
        f"{commit_line}\n"
        "- The tagged test suite passed under Xvfb before publication.\n"
        "- The wheel and source distribution passed `twine check` and fresh-install CLI smokes.\n\n"
        "### Artifact SHA-256 and size\n\n"
        f"{hashes}\n\n"
        f"{MANIFEST_START}{compact_json(manifest)}{MANIFEST_END}\n"
    )
    require(parse_embedded_manifest(notes) == manifest, "rendered notes do not contain the expected unique manifest")
    require(notes.count(commit_line) == 1, "rendered notes do not contain one unique commit assertion")
    for artifact, line in zip(manifest["artifacts"], artifact_lines, strict=True):
        require(notes.count(line) == 1, f"rendered notes do not contain one unique artifact assertion: {artifact['name']}")
    return notes


def parse_embedded_manifest(body: str) -> dict[str, Any]:
    pattern = re.compile(re.escape(MANIFEST_START) + r"(.*?)" + re.escape(MANIFEST_END), re.DOTALL)
    matches = pattern.findall(body)
    if not matches:
        raise SemanticMismatch("release body has no verification manifest")
    require_schema(len(matches) == 1, "release body contains duplicate verification manifests")
    try:
        manifest = json.loads(
            matches[0],
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise SchemaFailure(f"invalid embedded release manifest: {error}") from error
    return validate_manifest(manifest)


def manifest_artifacts(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {artifact["name"]: artifact for artifact in manifest["artifacts"]}


def validate_downloads(downloads: Path, manifest: dict[str, Any]) -> None:
    require(downloads.is_dir() and not downloads.is_symlink(), "download directory is missing or invalid")
    expected = manifest_artifacts(manifest)
    actual_names = sorted(path.name for path in downloads.iterdir())
    require(actual_names == sorted(expected), f"unexpected downloaded asset set: {actual_names}")
    for name, artifact in expected.items():
        path = downloads / name
        require(path.is_file() and not path.is_symlink(), f"download is not a regular file: {name}")
        require(path.stat().st_size == artifact["size"], f"downloaded size mismatch: {name}")
        require(file_sha256(path) == artifact["sha256"], f"downloaded SHA-256 mismatch: {name}")


def validate_bundle(bundle: Path, changelog: Path, *, tag: str, version: str, commit: str) -> dict[str, Any]:
    expected_top = {"dist", "release-manifest.json", "release-notes.md", "release-tool.py"}
    require(bundle.is_dir() and not bundle.is_symlink(), "release bundle directory is missing or invalid")
    require({path.name for path in bundle.iterdir()} == expected_top, "release bundle has unexpected top-level entries")
    for path in bundle.rglob("*"):
        require(not path.is_symlink(), f"release bundle contains a symlink: {path.relative_to(bundle)}")
    manifest = validate_manifest(
        load_json(bundle / "release-manifest.json"),
        tag=tag,
        version=version,
        commit=commit,
        dist=bundle / "dist",
    )
    notes_path = bundle / "release-notes.md"
    require(notes_path.is_file(), "release notes are missing")
    require(notes_path.read_text(encoding="utf-8") == render_notes(changelog, manifest), "release notes are not deterministic for the tagged changelog and bundle")
    require((bundle / "release-tool.py").is_file(), "release validation helper is missing")
    return manifest


def parsed_assets(release: dict[str, Any]) -> list[dict[str, Any]]:
    assets = release.get("assets")
    require_schema(isinstance(assets, list), "Release assets are not a list")
    result: list[dict[str, Any]] = []
    ids: list[int] = []
    names: list[str] = []
    for asset in cast(list[Any], assets):
        require_schema(isinstance(asset, dict), "Release asset is not an object")
        asset_id = asset.get("id")
        name = asset.get("name")
        state = asset.get("state")
        size = asset.get("size")
        require_schema(isinstance(asset_id, int) and not isinstance(asset_id, bool) and asset_id > 0, "Release asset ID is invalid")
        require_schema(isinstance(name, str), "Release asset name is not a string")
        require_schema(isinstance(state, str), f"Release asset state is not a string: {name}")
        require_schema(isinstance(size, int) and not isinstance(size, bool) and size >= 0, f"Release asset size is invalid: {name}")
        ids.append(asset_id)
        names.append(name)
        result.append({"id": asset_id, "name": name, "state": state, "size": size})
    require_schema(len(ids) == len(set(ids)), "Release contains duplicate asset IDs")
    require_schema(len(names) == len(set(names)), "Release contains duplicate asset names")
    return result


def release_assets(release: dict[str, Any], manifest: dict[str, Any]) -> None:
    assets = parsed_assets(release)
    expected = manifest_artifacts(manifest)
    names = [asset["name"] for asset in assets]
    require(set(names) == set(expected), f"unexpected Release asset set: {names}")
    for asset in assets:
        name = asset["name"]
        require(asset["state"] == "uploaded", f"Release asset is not uploaded: {name}")
        require(asset["size"] == expected[name]["size"], f"Release API size mismatch: {name}")


def release_core(release: Any) -> dict[str, Any]:
    require_schema(isinstance(release, dict), "Release API value is not an object")
    actual_id = release.get("id")
    tag_name = release.get("tag_name")
    draft = release.get("draft")
    prerelease = release.get("prerelease")
    immutable = release.get("immutable")
    require_schema(isinstance(actual_id, int) and not isinstance(actual_id, bool) and actual_id > 0, "Release ID is invalid")
    require_schema(isinstance(tag_name, str), "Release tag is not a string")
    require_schema(isinstance(draft, bool), "Release draft state is invalid")
    require_schema(isinstance(prerelease, bool), "Release prerelease state is invalid")
    require_schema(isinstance(immutable, bool), "Release immutable state is missing or invalid")
    parsed_assets(release)
    return cast(dict[str, Any], release)


def validate_record(
    release: Any,
    *,
    tag: str,
    state: str,
    release_id: int | None = None,
) -> dict[str, Any]:
    release = release_core(release)
    actual_id = release["id"]
    if release_id is not None:
        require(actual_id == release_id, "Release ID changed")
    require(release["tag_name"] == tag, "Release tag mismatch")
    require_schema(state in {"draft", "final"}, "invalid expected Release state")
    require(release["draft"] is (state == "draft"), f"Release is not {state}")
    require(release["prerelease"] is False, "Release is marked as a prerelease")
    if state == "draft":
        require(release["immutable"] is False, "draft Release is immutable")
    return release


def validate_repair_record(
    release: Any,
    *,
    tag: str,
    state: str,
    release_id: int,
) -> dict[str, Any]:
    """Validate mutation identity without rejecting a repairable prerelease."""
    release = release_core(release)
    require(release["id"] == release_id, "Release ID changed")
    require(release["tag_name"] == tag, "Release tag mismatch")
    require_schema(state in {"draft", "final"}, "invalid expected Release state")
    require(release["draft"] is (state == "draft"), f"Release is not {state}")
    return release


def validate_release(
    release: Any,
    bundle: Path,
    changelog: Path,
    *,
    tag: str,
    version: str,
    commit: str,
    state: str,
    downloads: Path | None,
) -> None:
    release = validate_record(release, tag=tag, state=state)
    manifest = validate_bundle(bundle, changelog, tag=tag, version=version, commit=commit)
    name = release.get("name")
    prerelease = release["prerelease"]
    body = release.get("body")
    require_schema(isinstance(name, str), "Release title is not a string")
    require_schema(isinstance(body, str), "Release body is not a string")
    require(name == f"Mint Background Switcher {version}", "Release title mismatch")
    require(prerelease is False, "Release is marked as a prerelease")
    expected_body = (bundle / "release-notes.md").read_text(encoding="utf-8")
    require(body == expected_body, "Release notes differ from the verified notes")
    release_assets(release, manifest)
    if downloads is not None:
        validate_downloads(downloads, manifest)


def validate_existing(
    release: Any,
    changelog: Path,
    *,
    tag: str,
    version: str,
    commit: str,
    downloads: Path | None,
) -> None:
    release = validate_record(release, tag=tag, state="final")
    name = release.get("name")
    prerelease = release["prerelease"]
    body = release.get("body")
    require_schema(isinstance(name, str), "Release title is not a string")
    require_schema(isinstance(body, str), "Release body is not a string")
    require(name == f"Mint Background Switcher {version}", "Release title mismatch")
    require(prerelease is False, "Release is marked as a prerelease")
    manifest = parse_embedded_manifest(body)
    validate_manifest(manifest, tag=tag, version=version, commit=commit)
    expected_body = render_notes(changelog, manifest)
    require(body == expected_body, "Release notes differ from the tagged changelog and embedded manifest")
    release_assets(release, manifest)
    if downloads is not None:
        validate_downloads(downloads, manifest)


def validate_latest(release: Any, *, tag: str, commit: str, downloads: Path | None) -> None:
    release = validate_record(release, tag=tag, state="final")
    name = release.get("name")
    body = release.get("body")
    require_schema(isinstance(name, str), "Latest candidate title is not a string")
    require_schema(isinstance(body, str), "Latest candidate body is not a string")
    require(name == f"Mint Background Switcher {tag.removeprefix('v')}", "Latest candidate title mismatch")
    require(release["prerelease"] is False, "Latest candidate is a prerelease")
    manifest = parse_embedded_manifest(body)
    validate_manifest(manifest, tag=tag, version=tag.removeprefix("v"), commit=commit)
    require(body.count(f"- Tagged commit: `{commit}`") == 1, "Latest candidate body has no unique commit assertion")
    for artifact in manifest["artifacts"]:
        line = f"- `{artifact['name']}`: `{artifact['sha256']}` (`{artifact['size']}` bytes)"
        require(body.count(line) == 1, f"Latest candidate body has no unique artifact assertion: {artifact['name']}")
    release_assets(release, manifest)
    if downloads is not None:
        validate_downloads(downloads, manifest)


def remote_versions(path: Path) -> dict[str, tuple[str, tuple[int, int, int]]]:
    peeled = re.compile(r"([0-9a-f]{40})\trefs/tags/(.+)\^\{\}")
    values: dict[str, tuple[str, tuple[int, int, int]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = peeled.fullmatch(line)
        if match is None:
            raise SchemaFailure(f"malformed remote peeled-tag entry: {line}")
        tag = match[2]
        version = STRICT_TAG.fullmatch(tag)
        if version is None:
            continue
        candidate = (match[1], (int(version[1]), int(version[2]), int(version[3])))
        require_schema(tag not in values, f"duplicate remote peeled tag entry: {tag}")
        values[tag] = candidate
    return values


def remote_candidates(remote_path: Path) -> list[tuple[str, str]]:
    remote = remote_versions(remote_path)
    ordered = sorted(remote, key=lambda item: remote[item][1], reverse=True)
    return [(tag, remote[tag][0]) for tag in ordered]


def graphql_release_id(response: Path, tag: str) -> int:
    value = load_json(response)
    require_schema(isinstance(value, dict), "GraphQL response is not an object")
    require_schema("errors" not in value, "GraphQL response contains errors")
    require_schema(set(value) == {"data"}, "GraphQL response has unexpected fields")
    data = value["data"]
    require_schema(isinstance(data, dict) and set(data) == {"repository"}, "GraphQL data is malformed")
    repository = data["repository"]
    require_schema(isinstance(repository, dict) and set(repository) == {"release"}, "GraphQL repository data is malformed")
    release = repository["release"]
    if release is None:
        raise NotFound(tag)
    require_schema(isinstance(release, dict), "GraphQL Release value is malformed")
    require_schema(set(release) == {"databaseId", "isDraft", "isPrerelease", "tagName"}, "GraphQL Release has unexpected fields")
    release_id = release["databaseId"]
    require_schema(isinstance(release_id, int) and not isinstance(release_id, bool) and release_id > 0, "GraphQL Release ID is invalid")
    require_schema(isinstance(release["isDraft"], bool), "GraphQL draft state is invalid")
    require_schema(isinstance(release["isPrerelease"], bool), "GraphQL prerelease state is invalid")
    require_schema(isinstance(release["tagName"], str), "GraphQL tag is invalid")
    require(release["tagName"] == tag, "GraphQL Release tag mismatch")
    return release_id


def asset_ids(release: Any) -> list[int]:
    release = release_core(release)
    return [asset["id"] for asset in parsed_assets(release)]


def asset_download_rows(release: Any, version: str) -> list[tuple[int, str]]:
    release = release_core(release)
    assets = parsed_assets(release)
    expected = expected_names(version)
    by_name = {asset["name"]: asset for asset in assets}
    require(set(by_name) == set(expected), f"unexpected Release asset set: {sorted(by_name)}")
    return [(by_name[name]["id"], name) for name in expected]


def release_upload_url(release: Any, repository: str, release_id: int, server_url: str) -> str:
    from urllib.parse import urlsplit

    trusted_server = urlsplit(server_url)
    require_schema(
        trusted_server.scheme == "https"
        and trusted_server.netloc == "github.com"
        and trusted_server.path in {"", "/"}
        and not trusted_server.query
        and not trusted_server.fragment,
        "unsupported or malformed GitHub server URL",
    )
    release = release_core(release)
    require(release["id"] == release_id, "Release ID changed")
    value = release.get("upload_url")
    require_schema(isinstance(value, str), "Release upload URL is missing or invalid")
    suffix = "{?name,label}"
    require_schema(value.endswith(suffix), "Release upload URL template is malformed")
    base = value[: -len(suffix)]
    parsed = urlsplit(base)
    expected_path = f"/repos/{repository}/releases/{release_id}/assets"
    require_schema(
        parsed.scheme == "https"
        and parsed.netloc == "uploads.github.com"
        and parsed.hostname == "uploads.github.com"
        and parsed.username is None
        and parsed.password is None
        and parsed.port is None,
        "Release upload URL origin mismatch",
    )
    require_schema(parsed.path == expected_path and not parsed.query and not parsed.fragment, "Release upload URL identity mismatch")
    return base


def validate_upload_response(response: Path, name: str, size: int) -> None:
    require_schema(bool(name) and "\n" not in name and "\r" not in name, "expected upload name is invalid")
    require_schema(size > 0, "expected upload size is invalid")
    value = load_json(response)
    require_schema(isinstance(value, dict), "Release asset upload response is not an object")
    asset_id = value.get("id")
    response_name = value.get("name")
    state = value.get("state")
    response_size = value.get("size")
    require_schema(isinstance(asset_id, int) and not isinstance(asset_id, bool) and asset_id > 0, "Release asset upload response has an invalid ID")
    require_schema(isinstance(response_name, str), "Release asset upload response name is invalid")
    require_schema(isinstance(state, str), "Release asset upload response state is invalid")
    require_schema(isinstance(response_size, int) and not isinstance(response_size, bool) and response_size >= 0, "Release asset upload response size is invalid")
    require(response_name == name and state == "uploaded" and response_size == size, "Release asset upload response does not match the uploaded file")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser("render")
    render.add_argument("--dist", type=Path, required=True)
    render.add_argument("--changelog", type=Path, required=True)
    render.add_argument("--notes", type=Path, required=True)
    render.add_argument("--manifest", type=Path, required=True)
    render.add_argument("--tag", required=True)
    render.add_argument("--version", required=True)
    render.add_argument("--commit", required=True)

    bundle = subparsers.add_parser("validate-bundle")
    bundle.add_argument("--bundle", type=Path, required=True)
    bundle.add_argument("--changelog", type=Path, required=True)
    bundle.add_argument("--tag", required=True)
    bundle.add_argument("--version", required=True)
    bundle.add_argument("--commit", required=True)


    validate = subparsers.add_parser("validate-release")
    validate.add_argument("--release", type=Path, required=True)
    validate.add_argument("--bundle", type=Path, required=True)
    validate.add_argument("--changelog", type=Path, required=True)
    validate.add_argument("--tag", required=True)
    validate.add_argument("--version", required=True)
    validate.add_argument("--commit", required=True)
    validate.add_argument("--state", choices=("draft", "final"), required=True)
    validate.add_argument("--downloads", type=Path)

    existing = subparsers.add_parser("validate-existing")
    existing.add_argument("--release", type=Path, required=True)
    existing.add_argument("--changelog", type=Path, required=True)
    existing.add_argument("--tag", required=True)
    existing.add_argument("--version", required=True)
    existing.add_argument("--commit", required=True)
    existing.add_argument("--downloads", type=Path)

    record = subparsers.add_parser("validate-record")
    record.add_argument("--release", type=Path, required=True)
    record.add_argument("--tag", required=True)
    record.add_argument("--state", choices=("draft", "final"), required=True)
    record.add_argument("--id", type=int)

    repair_record = subparsers.add_parser("validate-repair-record")
    repair_record.add_argument("--release", type=Path, required=True)
    repair_record.add_argument("--tag", required=True)
    repair_record.add_argument("--state", choices=("draft", "final"), required=True)
    repair_record.add_argument("--id", type=int, required=True)

    latest = subparsers.add_parser("validate-latest")
    latest.add_argument("--release", type=Path, required=True)
    latest.add_argument("--tag", required=True)
    latest.add_argument("--commit", required=True)
    latest.add_argument("--downloads", type=Path)


    remote = subparsers.add_parser("remote-candidates")
    remote.add_argument("--remote-tags", type=Path, required=True)

    graphql = subparsers.add_parser("graphql-release-id")
    graphql.add_argument("--response", type=Path, required=True)
    graphql.add_argument("--tag", required=True)

    assets = subparsers.add_parser("asset-ids")
    assets.add_argument("--release", type=Path, required=True)

    downloads = subparsers.add_parser("asset-downloads")
    downloads.add_argument("--release", type=Path, required=True)
    downloads.add_argument("--version", required=True)

    upload = subparsers.add_parser("release-upload-url")
    upload.add_argument("--release", type=Path, required=True)
    upload.add_argument("--repository", required=True)
    upload.add_argument("--id", type=int, required=True)
    upload.add_argument("--server-url", required=True)

    upload_response = subparsers.add_parser("validate-upload-response")
    upload_response.add_argument("--response", type=Path, required=True)
    upload_response.add_argument("--name", required=True)
    upload_response.add_argument("--size", type=int, required=True)

    state = subparsers.add_parser("release-state")
    state.add_argument("--release", type=Path, required=True)

    release_id = subparsers.add_parser("release-id")
    release_id.add_argument("--release", type=Path, required=True)

    immutable = subparsers.add_parser("release-immutable")
    immutable.add_argument("--release", type=Path, required=True)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "render":
            manifest = manifest_from_dist(args.dist, tag=args.tag, version=args.version, commit=args.commit)
            args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            args.notes.write_text(render_notes(args.changelog, manifest), encoding="utf-8")
        elif args.command == "validate-bundle":
            validate_bundle(args.bundle, args.changelog, tag=args.tag, version=args.version, commit=args.commit)
        elif args.command == "validate-release":
            validate_release(
                load_json(args.release),
                args.bundle,
                args.changelog,
                tag=args.tag,
                version=args.version,
                commit=args.commit,
                state=args.state,
                downloads=args.downloads,
            )
        elif args.command == "validate-existing":
            validate_existing(
                load_json(args.release),
                args.changelog,
                tag=args.tag,
                version=args.version,
                commit=args.commit,
                downloads=args.downloads,
            )
        elif args.command == "validate-record":
            validate_record(
                load_json(args.release),
                tag=args.tag,
                state=args.state,
                release_id=args.id,
            )
        elif args.command == "validate-repair-record":
            validate_repair_record(
                load_json(args.release),
                tag=args.tag,
                state=args.state,
                release_id=args.id,
            )
        elif args.command == "validate-latest":
            validate_latest(load_json(args.release), tag=args.tag, commit=args.commit, downloads=args.downloads)
        elif args.command == "remote-candidates":
            for tag, commit in remote_candidates(args.remote_tags):
                print(f"{tag}\t{commit}")
        elif args.command == "graphql-release-id":
            print(graphql_release_id(args.response, args.tag))
        elif args.command == "asset-ids":
            for asset_id in asset_ids(load_json(args.release)):
                print(asset_id)
        elif args.command == "asset-downloads":
            for asset_id, name in asset_download_rows(load_json(args.release), args.version):
                print(f"{asset_id}\t{name}")
        elif args.command == "release-upload-url":
            print(release_upload_url(load_json(args.release), args.repository, args.id, args.server_url))
        elif args.command == "validate-upload-response":
            validate_upload_response(args.response, args.name, args.size)
        elif args.command == "release-state":
            release = release_core(load_json(args.release))
            print("draft" if release["draft"] else "final")
        elif args.command == "release-id":
            release = release_core(load_json(args.release))
            print(release["id"])
        elif args.command == "release-immutable":
            release = release_core(load_json(args.release))
            print("true" if release["immutable"] else "false")
        else:  # pragma: no cover - argparse guarantees a command
            raise AssertionError(args.command)
    except SemanticMismatch as error:
        print(f"release state mismatch: {error}", file=sys.stderr)
        return SEMANTIC_MISMATCH
    except SchemaFailure as error:
        print(f"release schema failure: {error}", file=sys.stderr)
        return SCHEMA_FAILURE
    except NotFound:
        return NOT_FOUND
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
