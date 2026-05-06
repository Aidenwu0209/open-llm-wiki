#!/usr/bin/env python3
"""Install the optional Obsidian experience layer for an open-llm-wiki vault."""

from __future__ import annotations

import argparse
import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from wiki_common import ensure_within, json_dump, read_text, write_text


PLUGIN_ASSETS = ("main.js", "manifest.json")
OPTIONAL_PLUGIN_ASSETS = ("styles.css",)
PROFILE_DIRS = {
    "minimal": ["raw/inbox"],
    "research": ["raw/inbox", "canvas", "assets/excalidraw"],
    "full": ["raw/inbox", "canvas", "assets/excalidraw"],
}
OBSIDIAN_GITIGNORE = """# Obsidian workspace state
workspace.json
workspace-mobile.json
cache/
*.bak
"""
PLUGIN_DATA_DEFAULTS: dict[str, dict[str, Any]] = {
    "custom-sort": {
        "suspended": False,
        "statusBarEntryEnabled": True,
        "notificationsEnabled": True,
        "customSortContextSubmenu": True,
    },
    "homepage": {
        "homepage": "index",
        "openOnStartup": True,
        "openMode": "replace-all",
        "manualOpenMode": "replace-all",
        "view": "reading",
        "refreshDataview": True,
    },
}


def record(actions: list[tuple[str, str, str]], status: str, path: Path | str, message: str) -> None:
    actions.append((status, str(path), message))


def safe_child(vault: Path, *parts: str) -> Path:
    return ensure_within(vault.joinpath(*parts), vault, "Obsidian setup output must stay inside the vault")


def load_resource_json(resource_dir: Path, name: str) -> Any:
    path = resource_dir / name
    if not path.exists():
        raise SystemExit(f"missing Obsidian resource: {path}")
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON resource {path}: {exc}") from exc


def load_json_target(path: Path, expected_type: type, force: bool, actions: list[tuple[str, str, str]]) -> Any:
    if not path.exists():
        return expected_type()
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        if force:
            record(actions, "warn", path, f"replacing invalid JSON because --force was set: {exc}")
            return expected_type()
        raise SystemExit(f"refusing to overwrite invalid JSON at {path}: {exc}") from exc
    if not isinstance(data, expected_type):
        if force:
            record(actions, "warn", path, f"replacing JSON {type(data).__name__} because --force was set")
            return expected_type()
        raise SystemExit(f"refusing to overwrite {path}: expected {expected_type.__name__}")
    return data


def merge_preserving(existing: dict[str, Any], defaults: dict[str, Any], force_keys: set[str]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in defaults.items():
        if key in force_keys:
            merged[key] = value
        elif key not in merged:
            merged[key] = value
        elif isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_preserving(merged[key], value, set())
    return merged


def write_json_if_changed(
    path: Path,
    data: Any,
    dry_run: bool,
    actions: list[tuple[str, str, str]],
    message: str,
) -> None:
    rendered = json_dump(data) + "\n"
    if path.exists() and read_text(path) == rendered:
        record(actions, "ok", path, "already current")
        return
    if dry_run:
        record(actions, "plan", path, message)
        return
    write_text(path, rendered)
    record(actions, "write", path, message)


def merge_json_object(
    path: Path,
    defaults: dict[str, Any],
    force_keys: set[str],
    force: bool,
    dry_run: bool,
    actions: list[tuple[str, str, str]],
    label: str,
) -> None:
    existing = load_json_target(path, dict, force, actions)
    merged = merge_preserving(existing, defaults, force_keys)
    write_json_if_changed(path, merged, dry_run, actions, f"merged {label}")


def write_text_if_absent_or_forced(
    path: Path,
    text: str,
    force: bool,
    dry_run: bool,
    actions: list[tuple[str, str, str]],
    message: str,
) -> None:
    if path.exists() and not force:
        record(actions, "keep", path, "preserved existing file")
        return
    if path.exists() and read_text(path) == text:
        record(actions, "ok", path, "already current")
        return
    if dry_run:
        record(actions, "plan", path, message)
        return
    write_text(path, text)
    record(actions, "write", path, message)


def create_dir(path: Path, dry_run: bool, actions: list[tuple[str, str, str]]) -> None:
    if path.is_dir():
        record(actions, "ok", path, "directory exists")
        return
    if dry_run:
        record(actions, "plan", path, "create directory")
        return
    path.mkdir(parents=True, exist_ok=True)
    record(actions, "write", path, "created directory")


def release_url(repo: str, asset: str) -> str:
    return f"https://github.com/{repo}/releases/latest/download/{asset}"


def download_asset(url: str, target: Path, timeout: int, required: bool) -> bool:
    request = urllib.request.Request(url, headers={"User-Agent": "open-llm-wiki-obsidian-setup"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            data = response.read()
    except urllib.error.HTTPError as exc:
        if not required and exc.code == 404:
            return False
        raise RuntimeError(f"HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"download failed for {url}: {exc}") from exc
    if status != 200:
        if not required and status == 404:
            return False
        raise RuntimeError(f"HTTP {status} for {url}")
    if required and not data:
        raise RuntimeError(f"empty required asset: {url}")
    target.write_bytes(data)
    return True


def install_plugin(
    vault: Path,
    plugin_id: str,
    plugin: dict[str, Any],
    skip_downloads: bool,
    dry_run: bool,
    timeout: int,
    actions: list[tuple[str, str, str]],
) -> bool:
    plugin_dir = safe_child(vault, ".obsidian", "plugins", plugin_id)
    manifest_path = safe_child(vault, ".obsidian", "plugins", plugin_id, "manifest.json")
    if manifest_path.exists() and manifest_path.stat().st_size > 0:
        record(actions, "ok", plugin_dir, "plugin already installed")
        return True
    if plugin.get("requires") == "git" and not shutil.which("git"):
        record(actions, "skip", plugin_dir, "skipped because git is not installed")
        return False
    if skip_downloads:
        record(actions, "skip", plugin_dir, "download skipped; plugin id will still be enabled")
        return True
    if dry_run:
        record(actions, "plan", plugin_dir, f"download plugin {plugin_id}")
        return True

    created_dir = not plugin_dir.exists()
    plugin_dir.mkdir(parents=True, exist_ok=True)
    try:
        repo = str(plugin["repo"])
        for asset in PLUGIN_ASSETS:
            download_asset(release_url(repo, asset), plugin_dir / asset, timeout, required=True)
        for asset in OPTIONAL_PLUGIN_ASSETS:
            try:
                downloaded = download_asset(release_url(repo, asset), plugin_dir / asset, timeout, required=False)
            except RuntimeError as exc:
                record(actions, "warn", plugin_dir / asset, str(exc))
                continue
            if not downloaded:
                optional_path = plugin_dir / asset
                if optional_path.exists():
                    optional_path.unlink()
    except Exception as exc:
        if created_dir and plugin_dir.exists():
            shutil.rmtree(plugin_dir)
        record(actions, "warn", plugin_dir, f"plugin download failed: {exc}")
        return False

    record(actions, "write", plugin_dir, f"installed plugin {plugin_id}")
    return True


def install_theme(
    vault: Path,
    theme: dict[str, Any],
    skip_downloads: bool,
    dry_run: bool,
    timeout: int,
    actions: list[tuple[str, str, str]],
) -> bool:
    theme_id = str(theme["id"])
    theme_dir = safe_child(vault, ".obsidian", "themes", theme_id)
    if (theme_dir / "manifest.json").exists() and (theme_dir / "theme.css").exists():
        record(actions, "ok", theme_dir, "theme already installed")
        return True
    if skip_downloads:
        record(actions, "skip", theme_dir, "theme download skipped")
        return False
    if dry_run:
        record(actions, "plan", theme_dir, f"download theme {theme_id}")
        return True

    created_dir = not theme_dir.exists()
    theme_dir.mkdir(parents=True, exist_ok=True)
    try:
        repo = str(theme["repo"])
        download_asset(release_url(repo, "manifest.json"), theme_dir / "manifest.json", timeout, required=True)
        download_asset(release_url(repo, "theme.css"), theme_dir / "theme.css", timeout, required=True)
    except Exception as exc:
        if created_dir and theme_dir.exists():
            shutil.rmtree(theme_dir)
        record(actions, "warn", theme_dir, f"theme download failed: {exc}")
        return False

    record(actions, "write", theme_dir, f"installed theme {theme_id}")
    return True


def merge_community_plugins(
    vault: Path,
    plugin_ids: list[str],
    force: bool,
    dry_run: bool,
    actions: list[tuple[str, str, str]],
) -> None:
    path = safe_child(vault, ".obsidian", "community-plugins.json")
    existing = load_json_target(path, list, force, actions)
    merged: list[str] = []
    for plugin_id in [*existing, *plugin_ids]:
        if not isinstance(plugin_id, str):
            continue
        if plugin_id not in merged:
            merged.append(plugin_id)
    write_json_if_changed(path, merged, dry_run, actions, "merged enabled community plugins")


def configure_plugin_data(
    vault: Path,
    plugin_ids: list[str],
    force: bool,
    dry_run: bool,
    actions: list[tuple[str, str, str]],
) -> None:
    for plugin_id, defaults in PLUGIN_DATA_DEFAULTS.items():
        if plugin_id not in plugin_ids:
            continue
        plugin_dir = safe_child(vault, ".obsidian", "plugins", plugin_id)
        if not plugin_dir.exists() and not dry_run:
            continue
        data_path = safe_child(vault, ".obsidian", "plugins", plugin_id, "data.json")
        merge_json_object(data_path, defaults, set(), force, dry_run, actions, f"{plugin_id} data.json")


def setup_obsidian(
    vault: Path,
    resource_dir: Path,
    profile: str = "minimal",
    dry_run: bool = False,
    skip_downloads: bool = False,
    force: bool = False,
    timeout: int = 30,
) -> list[tuple[str, str, str]]:
    actions: list[tuple[str, str, str]] = []
    vault = vault.resolve()
    resource_dir = resource_dir.resolve()
    manifest = load_resource_json(resource_dir, "plugin-manifest.json")
    profiles = manifest.get("profiles", {})
    plugins = manifest.get("plugins", {})
    if profile not in profiles:
        raise SystemExit(f"unknown Obsidian profile {profile!r}; available: {', '.join(sorted(profiles))}")
    profile_plugins = [str(item) for item in profiles[profile]]
    missing_plugins = [plugin_id for plugin_id in profile_plugins if plugin_id not in plugins]
    if missing_plugins:
        raise SystemExit(f"plugin manifest missing plugin entries: {', '.join(missing_plugins)}")

    create_dir(vault, dry_run, actions)
    create_dir(safe_child(vault, ".obsidian"), dry_run, actions)
    for item in PROFILE_DIRS[profile]:
        create_dir(safe_child(vault, *item.split("/")), dry_run, actions)

    app_defaults = load_resource_json(resource_dir, "app.json")
    appearance_defaults = load_resource_json(resource_dir, "appearance.json")
    hotkey_defaults = load_resource_json(resource_dir, "hotkeys.json")
    merge_json_object(
        safe_child(vault, ".obsidian", "app.json"),
        app_defaults,
        {"communityPluginsEnabled"},
        force,
        dry_run,
        actions,
        "app.json",
    )
    merge_json_object(
        safe_child(vault, ".obsidian", "appearance.json"),
        appearance_defaults,
        set(),
        force,
        dry_run,
        actions,
        "appearance.json",
    )
    merge_json_object(
        safe_child(vault, ".obsidian", "hotkeys.json"),
        hotkey_defaults,
        set(),
        force,
        dry_run,
        actions,
        "hotkeys.json",
    )

    sortspec = read_text(resource_dir / "sortspec.md")
    write_text_if_absent_or_forced(
        safe_child(vault, "sortspec.md"),
        sortspec,
        force,
        dry_run,
        actions,
        "wrote Custom Sort sortspec.md",
    )
    write_text_if_absent_or_forced(
        safe_child(vault, ".obsidian", ".gitignore"),
        OBSIDIAN_GITIGNORE,
        force,
        dry_run,
        actions,
        "wrote Obsidian personal-state ignore rules",
    )

    enabled_plugins: list[str] = []
    for plugin_id in profile_plugins:
        installed = install_plugin(
            vault,
            plugin_id,
            plugins[plugin_id],
            skip_downloads=skip_downloads,
            dry_run=dry_run,
            timeout=timeout,
            actions=actions,
        )
        if installed:
            enabled_plugins.append(plugin_id)
    merge_community_plugins(vault, enabled_plugins, force, dry_run, actions)
    configure_plugin_data(vault, enabled_plugins, force, dry_run, actions)
    install_theme(vault, manifest["theme"], skip_downloads, dry_run, timeout, actions)
    return actions


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Install optional Obsidian settings, plugins, theme, inbox, and diagram "
            "folders for an open-llm-wiki vault without overwriting user settings."
        )
    )
    parser.add_argument("vault", type=Path)
    parser.add_argument(
        "--resource-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "obsidian",
        help="Directory containing Obsidian config resources.",
    )
    parser.add_argument("--profile", choices=["minimal", "research", "full"], default="minimal")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned changes without writing files.")
    parser.add_argument("--skip-downloads", action="store_true", help="Configure Obsidian without downloading plugins or themes.")
    parser.add_argument("--force", action="store_true", help="Overwrite managed files and invalid JSON instead of preserving them.")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds for plugin and theme downloads.")
    args = parser.parse_args()

    actions = setup_obsidian(
        args.vault,
        args.resource_dir,
        profile=args.profile,
        dry_run=args.dry_run,
        skip_downloads=args.skip_downloads,
        force=args.force,
        timeout=args.timeout,
    )

    print("# Obsidian Setup Report")
    print(f"- vault: {args.vault.resolve()}")
    print(f"- profile: {args.profile}")
    print(f"- dry_run: {args.dry_run}")
    print(f"- skip_downloads: {args.skip_downloads}")
    print("\n## Actions")
    for status, path, message in actions:
        print(f"- [{status}] `{path}`: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
