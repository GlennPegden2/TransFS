#!/usr/bin/env python3
"""
TransFS YAML Configuration Linter — CLI wrapper
=================================================
Thin CLI front-end for app.lint_config (the importable library module).

Usage:
    python tools/lint_config.py [--config-dir app/config] [--verbose]
    python tools/lint_config.py --file app/config/sources/Testing/Apple/AppleII.yaml

Exit codes:
    0 - No errors (warnings may be present)
    1 - One or more errors found
"""

import sys
import os
import argparse

# Force UTF-8 output so Unicode renders correctly on all platforms
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Allow running directly from the tools/ directory without pip-installing
_tools_dir    = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_tools_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.lint_config import Issue, LintResult, LintSummary, lint_all, lint_file  # noqa: E402


# ─────────────────────────────────────────────────────────────
# ANSI colours (skipped when not a TTY)
# ─────────────────────────────────────────────────────────────
def _use_colour() -> bool:
    return (sys.stdout.isatty() and os.name != "nt") or (os.name == "nt" and os.environ.get("TERM"))


RED    = "\033[91m" if _use_colour() else ""
YELLOW = "\033[93m" if _use_colour() else ""
GREEN  = "\033[92m" if _use_colour() else ""
CYAN   = "\033[96m" if _use_colour() else ""
BOLD   = "\033[1m"  if _use_colour() else ""
RESET  = "\033[0m"  if _use_colour() else ""


def _print_result(r: LintResult, verbose: bool = False):
    if not r.issues and not verbose:
        return
    status_str = (f"{RED}FAIL{RESET}" if r.has_errors
                  else f"{YELLOW}WARN{RESET}" if r.has_warnings
                  else f"{GREEN}OK  {RESET}")
    print(f"\n{BOLD}[{status_str}{BOLD}] {r.filepath}{RESET}")
    for issue in r.issues:
        if verbose or issue.severity != Issue.INFO:
            colour = RED if issue.severity == Issue.ERROR else YELLOW if issue.severity == Issue.WARNING else CYAN
            print(f"  {colour}{issue.severity}{RESET}  {issue.path}")
            print(f"         {issue.message}")
            if issue.suggestion:
                print(f"         {CYAN}Suggestion:{RESET} {issue.suggestion}")


def main():
    parser = argparse.ArgumentParser(
        description="TransFS YAML config linter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config-dir", "-c",
        default=os.path.join(_project_root, "app", "config"),
        help="Path to the config directory (default: app/config next to tools/)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Also print files with no issues.",
    )
    parser.add_argument(
        "--file", "-f",
        metavar="FILE",
        help="Lint a single YAML file instead of the whole config tree.",
    )
    args = parser.parse_args()

    if args.file:
        filepath = os.path.abspath(args.file)
        if not os.path.exists(filepath):
            print(f"{RED}File not found:{RESET} {filepath}")
            sys.exit(1)
        r = lint_file(filepath)
        _print_result(r, verbose=True)
        sys.exit(1 if r.has_errors else 0)

    summary = lint_all(args.config_dir)

    for r in summary.results:
        _print_result(r, verbose=args.verbose)

    print(f"\n{'-'*60}")
    print(f"{BOLD}Summary:{RESET} {summary.total_files} file(s) checked - "
          f"{GREEN}{summary.clean_files} clean{RESET}, "
          f"{YELLOW}{summary.total_warnings} warning(s){RESET}, "
          f"{RED}{summary.total_errors} error(s){RESET}")

    if summary.total_errors == 0 and summary.total_warnings == 0:
        print(f"{GREEN}All configs look good!{RESET}")
    elif summary.total_errors == 0:
        print(f"{YELLOW}No errors, but there are warnings worth addressing.{RESET}")
    else:
        print(f"{RED}Fix the errors above before deploying.{RESET}")

    sys.exit(1 if summary.has_errors else 0)


if __name__ == "__main__":
    main()


def _load_yaml_with_dup_check(text: str):
    """Return (data_as_pairs, duplicates_list, error_str)."""
    loader = _DupKeyLoader(text)
    try:
        data = loader.get_single_data()
        duplicates = getattr(loader, "_duplicates", [])
        return data, duplicates, None
    except yaml.YAMLError as exc:
        return None, [], str(exc)
    finally:
        loader.dispose()


# ─────────────────────────────────────────────────────────────
# Issue container
# ─────────────────────────────────────────────────────────────
class Issue:
    ERROR   = "ERROR"
    WARNING = "WARNING"
    INFO    = "INFO"

    def __init__(self, severity: str, path: str, message: str, suggestion: str = ""):
        self.severity   = severity
        self.path       = path
        self.message    = message
        self.suggestion = suggestion

    def __str__(self):
        colour = RED if self.severity == self.ERROR else YELLOW if self.severity == self.WARNING else CYAN
        lines  = [f"  {colour}{self.severity}{RESET}  {self.path}"]
        lines.append(f"         {self.message}")
        if self.suggestion:
            lines.append(f"         {CYAN}Suggestion:{RESET} {self.suggestion}")
        return "\n".join(lines)


class LintResult:
    def __init__(self, filename: str):
        self.filename = filename
        self.issues: list[Issue] = []

    def add(self, severity, path, message, suggestion=""):
        self.issues.append(Issue(severity, path, message, suggestion))

    def error(self, path, message, suggestion=""):
        self.add(Issue.ERROR, path, message, suggestion)

    def warn(self, path, message, suggestion=""):
        self.add(Issue.WARNING, path, message, suggestion)

    def info(self, path, message, suggestion=""):
        self.add(Issue.INFO, path, message, suggestion)

    @property
    def has_errors(self):
        return any(i.severity == Issue.ERROR for i in self.issues)

    @property
    def has_warnings(self):
        return any(i.severity == Issue.WARNING for i in self.issues)

    def print(self, verbose=False):
        if not self.issues and not verbose:
            return
        status = (f"{RED}FAIL{RESET}" if self.has_errors
                  else f"{YELLOW}WARN{RESET}" if self.has_warnings
                  else f"{GREEN}OK  {RESET}")
        print(f"\n{BOLD}[{status}{BOLD}] {self.filename}{RESET}")
        for issue in self.issues:
            if verbose or issue.severity != Issue.INFO:
                print(issue)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _get(data: dict, *keys, default=None):
    """Safe nested dict access."""
    obj = data
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k, default)
        if obj is None:
            return default
    return obj


def _require(result: LintResult, data: dict, field: str, ctx: str, suggestion: str = ""):
    """Check a top-level key exists and is non-empty."""
    if field not in data or data[field] is None or data[field] == "":
        result.error(f"{ctx}.{field}", f"Mandatory field '{field}' is missing or empty.", suggestion)
        return False
    return True


def _recommend(result: LintResult, data: dict, field: str, ctx: str, suggestion: str = ""):
    """Warn if a recommended key is missing."""
    if field not in data or data[field] is None:
        result.warn(f"{ctx}.{field}", f"Recommended field '{field}' is missing.", suggestion)


URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


def _is_valid_url(url) -> bool:
    return isinstance(url, str) and bool(URL_RE.match(url.strip()))


# ─────────────────────────────────────────────────────────────
# app.yaml linter
# ─────────────────────────────────────────────────────────────
def lint_app_yaml(filepath: str) -> LintResult:
    result = LintResult(filepath)

    with open(filepath, "r", encoding="utf-8") as fh:
        raw = fh.read()

    data, duplicates, err = _load_yaml_with_dup_check(raw)

    if err:
        result.error("app.yaml", f"YAML syntax error: {err}",
                     "Check indentation, special characters, and quote usage.")
        return result

    if not isinstance(data, dict):
        result.error("app.yaml", "Top-level structure must be a YAML mapping (key: value pairs).")
        return result

    for key, first_line, dup_line in duplicates:
        result.error(f"app.yaml[line {dup_line}]",
                     f"Duplicate key '{key}' (first seen at line {first_line}).",
                     "Remove or rename the duplicate key.")

    # ── Mandatory fields ──────────────────────────────────────
    _require(result, data, "filestore", "app.yaml",
             "Add: filestore: /mnt/filestorefs")

    cs = data.get("config_sets", {}) or {}
    if not isinstance(cs, dict) or not cs.get("active_client_config"):
        result.error("app.yaml.config_sets.active_client_config",
                     "Mandatory field 'config_sets.active_client_config' is missing.",
                     "Add: config_sets:\n           active_client_config: default")
    if not isinstance(cs, dict) or not cs.get("active_source_config"):
        result.error("app.yaml.config_sets.active_source_config",
                     "Mandatory field 'config_sets.active_source_config' is missing.",
                     "Add: config_sets:\n           active_source_config: default")

    # ── Database block ────────────────────────────────────────
    db = data.get("database", {}) or {}
    if not isinstance(db, dict) or not db:
        result.error("app.yaml.database",
                     "Mandatory 'database' block is missing.",
                     "Add a database: block with host, port, name, user, password.")
    else:
        for field in ("host", "port", "name", "user", "password"):
            if not db.get(field):
                result.error(f"app.yaml.database.{field}",
                             f"Mandatory database field '{field}' is missing or empty.")
        mode = db.get("mode", "")
        valid_modes = ("enabled", "disabled", "read_only")
        if mode and mode not in valid_modes:
            result.error("app.yaml.database.mode",
                         f"Invalid database mode '{mode}'.",
                         f"Valid values: {', '.join(valid_modes)}")

    # ── SMB block ─────────────────────────────────────────────
    smb = data.get("smb", {}) or {}
    if not isinstance(smb, dict) or not smb:
        result.warn("app.yaml.smb",
                    "Recommended 'smb' block is missing.",
                    "Add: smb:\n       username: root\n       password: '1'\n       allow_guest: false")
    else:
        for field in ("username", "password"):
            if smb.get(field) is None:
                result.warn(f"app.yaml.smb.{field}",
                            f"Recommended smb field '{field}' is missing.")

    # ── Recommended top-level fields ──────────────────────────
    _recommend(result, data, "cache", "app.yaml",
               "Add a cache: block to tune caching behaviour.")
    _recommend(result, data, "startup_prewarm", "app.yaml",
               "Add startup_prewarm: block to speed up initial directory listings.")
    _recommend(result, data, "mame", "app.yaml",
               "Add mame: block if you intend to use MAME software lists.")

    # ── Native external mounts ────────────────────────────────
    mounts = data.get("native_external_mounts", []) or []
    for i, mount in enumerate(mounts):
        ctx = f"app.yaml.native_external_mounts[{i}]"
        if not isinstance(mount, dict):
            result.error(ctx, "Mount entry must be a mapping.")
            continue
        for field in ("id", "target_subpath"):
            if not mount.get(field):
                result.error(f"{ctx}.{field}", f"Mandatory mount field '{field}' is missing.")
        if mount.get("smb_host") and not mount.get("credentials_file") and not mount.get("guest"):
            result.warn(f"{ctx}.credentials_file",
                        "SMB mount has no credentials_file set and guest is not true.",
                        "Add: credentials_file: /path/to/.cred  or set  guest: true")

    return result


# ─────────────────────────────────────────────────────────────
# Client config linter
# ─────────────────────────────────────────────────────────────
def _lint_map_entry(result: LintResult, map_dict: dict, ctx: str):
    """Validate a single map entry (the value under a map key)."""
    if not isinstance(map_dict, dict):
        result.error(ctx, "Map entry must be a mapping.")
        return

    has_file  = "file" in map_dict
    has_query = "query" in map_dict

    if not has_file and not has_query:
        result.error(ctx, "Map entry must contain either 'file' or 'query'.",
                     "Example:\n           CDs:\n             query:\n               source_dir: Software\n               extensions: [CUE, ISO]")
        return

    if has_file:
        f = map_dict["file"] or {}
        if not isinstance(f, dict) or not f.get("path"):
            result.error(f"{ctx}.file.path", "file entry must have a non-empty 'path'.")

    if has_query:
        q = map_dict["query"] or {}
        if not isinstance(q, dict):
            result.error(f"{ctx}.query", "query value must be a mapping.")
            return
        if not q.get("source_dir"):
            result.error(f"{ctx}.query.source_dir", "Mandatory query field 'source_dir' is missing.")
        exts = q.get("extensions")
        if exts is None:
            result.warn(f"{ctx}.query.extensions",
                        "Recommended query field 'extensions' is missing.",
                        "Add: extensions: [CUE, ISO, CHD]  (or ['*'] for all)")
        elif not isinstance(exts, list) or len(exts) == 0:
            result.warn(f"{ctx}.query.extensions", "extensions should be a non-empty list.")


def lint_client_yaml(filepath: str) -> LintResult:
    result = LintResult(filepath)

    with open(filepath, "r", encoding="utf-8") as fh:
        raw = fh.read()

    data, duplicates, err = _load_yaml_with_dup_check(raw)

    if err:
        result.error(os.path.basename(filepath),
                     f"YAML syntax error: {err}",
                     "Check indentation, special characters, and quote usage.")
        return result

    if not isinstance(data, dict):
        result.error(os.path.basename(filepath), "Top-level structure must be a YAML mapping.")
        return result

    for key, first_line, dup_line in duplicates:
        result.error(f"line {dup_line}",
                     f"Duplicate key '{key}' (first seen at line {first_line}).",
                     "Remove or rename the duplicate key.")

    name = os.path.basename(filepath)

    # ── Mandatory ─────────────────────────────────────────────
    _require(result, data, "name", name,
             "Add: name: MyClientName")

    # ── Recommended ───────────────────────────────────────────
    _recommend(result, data, "download_layout", name,
               "Add: download_layout: folder_based  (or flat / legacy_source_based)")
    _recommend(result, data, "category_paths", name,
               "Add a category_paths: block to define roms/bios path templates.")

    # ── Systems ───────────────────────────────────────────────
    systems = data.get("systems", []) or []
    if not isinstance(systems, list) or len(systems) == 0:
        result.warn(f"{name}.systems",
                    "No systems defined in this client config.",
                    "Add a systems: list with at least one system entry.")
        return result

    system_names_seen = set()
    for i, system in enumerate(systems):
        ctx = f"{name}.systems[{i}]"
        if not isinstance(system, dict):
            result.error(ctx, "System entry must be a mapping.")
            continue

        sys_name = system.get("name", f"<unnamed #{i}>")
        ctx = f"{name}.systems[{sys_name}]"

        if sys_name in system_names_seen:
            result.warn(ctx, f"Duplicate system name '{sys_name}'.")
        system_names_seen.add(sys_name)

        _require(result, system, "name",           ctx)
        _require(result, system, "manufacturer",   ctx,
                 "Add: manufacturer: SomeManufacturer")
        _require(result, system, "local_base_path", ctx,
                 "Add: local_base_path: Systems/Manufacturer/System")

        _recommend(result, system, "system_mapping_name", ctx,
                   "Add system_mapping_name to match the source config canonical name.")

        maps = system.get("maps", []) or []
        if not isinstance(maps, list) or len(maps) == 0:
            result.warn(f"{ctx}.maps",
                        "System has no maps defined — it won't appear in the virtual filesystem.")
        else:
            for j, map_entry in enumerate(maps):
                if not isinstance(map_entry, dict):
                    result.error(f"{ctx}.maps[{j}]", "Map entry must be a mapping.")
                    continue
                for map_key, map_val in map_entry.items():
                    _lint_map_entry(result, map_val or {}, f"{ctx}.maps[{map_key}]")

    return result


# ─────────────────────────────────────────────────────────────
# Source config linter
# ─────────────────────────────────────────────────────────────
def lint_source_yaml(filepath: str) -> LintResult:
    result = LintResult(filepath)

    with open(filepath, "r", encoding="utf-8") as fh:
        raw = fh.read()

    data, duplicates, err = _load_yaml_with_dup_check(raw)

    if err:
        result.error(os.path.basename(filepath),
                     f"YAML syntax error: {err}",
                     "Check indentation, special characters, and quote usage.")
        return result

    if data is None:
        result.warn(os.path.basename(filepath), "File is empty.")
        return result

    if not isinstance(data, dict):
        result.error(os.path.basename(filepath), "Top-level structure must be a YAML mapping.")
        return result

    name = os.path.basename(filepath)

    for key, first_line, dup_line in duplicates:
        result.error(f"{name} line {dup_line}",
                     f"Duplicate key '{key}' (first seen at line {first_line}).",
                     "YAML allows duplicate keys but Python will only see the last value. "
                     "This is almost certainly a bug — rename or merge the duplicates.")

    # ── Mandatory ─────────────────────────────────────────────
    _require(result, data, "base_path", name,
             "Add: base_path: Manufacturer/SystemName/")

    # ── Sources list ──────────────────────────────────────────
    sources = data.get("sources", []) or []
    if not isinstance(sources, list):
        result.error(f"{name}.sources", "sources must be a YAML list.")
        sources = []

    source_names: set[str] = set()

    for i, src in enumerate(sources):
        ctx = f"{name}.sources[{i}]"
        if not isinstance(src, dict):
            result.error(ctx, "Source entry must be a mapping.")
            continue

        src_name = src.get("name", f"<unnamed #{i}>")
        ctx = f"{name}.sources[{src_name}]"

        if src_name in source_names:
            result.warn(ctx, f"Duplicate source name '{src_name}'.",
                        "Each source name must be unique within a file.")
        source_names.add(src_name)

        _require(result, src, "name",   ctx)
        _require(result, src, "type",   ctx, "Add: type: ddl")

        # mame-type sources are managed by the MAME subsystem - folder is not applicable
        if src.get("type") != "mame":
            _require(result, src, "folder", ctx, "Add: folder: Software/roms")

        src_type = src.get("type", "")
        valid_types = ("ddl", "torrent", "tor", "base64", "git", "IA-COL", "mega", "mame")
        if src_type and src_type not in valid_types:
            result.warn(f"{ctx}.type",
                        f"Unrecognised source type '{src_type}'.",
                        f"Known types: {', '.join(valid_types)}")

        has_url  = "url"  in src
        has_urls = "urls" in src
        # Types that don't require url/urls
        url_optional_types = ("base64", "git", "mame", "IA-COL")
        if not has_url and not has_urls and src_type not in url_optional_types:
            result.error(f"{ctx}.url",
                         "Source must have 'url' or 'urls' field.",
                         "Add: url: https://example.com/file.zip\n"
                         "  or urls:\n    - https://example.com/file1.zip")

        if has_url:
            url = src.get("url")
            if not _is_valid_url(url):
                result.error(f"{ctx}.url",
                             f"'url' value does not look like a valid HTTP(S) URL: {url!r}")

        if has_urls:
            urls = src.get("urls") or []
            if not isinstance(urls, list):
                result.error(f"{ctx}.urls", "urls must be a list.")
            else:
                for j, u in enumerate(urls):
                    if u is None or u == "":
                        result.warn(f"{ctx}.urls[{j}]",
                                    "Empty/null URL in urls list — this entry will be ignored.",
                                    "Remove the blank line or add the missing URL.")
                    elif not _is_valid_url(u):
                        result.error(f"{ctx}.urls[{j}]",
                                     f"Invalid URL: {u!r}")

        # Suggest extract for archive-like URLs
        if src_type == "ddl" and not src.get("extract") and not src.get("extract_from_archive"):
            url_val = src.get("url") or ""
            urls_val = src.get("urls") or []
            archive_exts = (".zip", ".7z", ".tar.gz", ".tgz", ".rar")
            all_urls = ([url_val] if url_val else []) + (urls_val if isinstance(urls_val, list) else [])
            if any(str(u).lower().endswith(archive_exts) for u in all_urls if u):
                result.info(f"{ctx}.extract",
                            "Source downloads archives but 'extract' is not set.",
                            "Consider adding: extract: true  (or extract: '*.rom') "
                            "to auto-extract after download.")

    # ── Recommended: packs ────────────────────────────────────
    packs = data.get("packs", []) or []
    if not isinstance(packs, list):
        result.error(f"{name}.packs", "packs must be a YAML list.")
        packs = []

    if len(sources) > 0 and len(packs) == 0:
        result.info(f"{name}.packs",
                    "No packs defined — users won't be able to download content via the UI.",
                    "Add a packs: section grouping sources into downloadable bundles.")

    pack_ids_seen: set[str] = set()

    for i, pack in enumerate(packs):
        ctx = f"{name}.packs[{i}]"
        if not isinstance(pack, dict):
            result.error(ctx, "Pack entry must be a mapping.")
            continue

        pack_id = pack.get("id", f"<unnamed #{i}>")
        ctx = f"{name}.packs[{pack_id}]"

        if pack_id in pack_ids_seen:
            result.error(ctx, f"Duplicate pack id '{pack_id}'.",
                         "Each pack id must be unique within a file.")
        pack_ids_seen.add(pack_id)

        _require(result, pack, "id",          ctx, "Add: id: my-unique-pack-id")
        _require(result, pack, "name",        ctx, "Add: name: My Pack Display Name")
        _require(result, pack, "description", ctx, "Add: description: Short description of what's included.")
        _require(result, pack, "sources",     ctx, "Add: sources: [source-name-1, source-name-2]")

        _recommend(result, pack, "estimated_size", ctx,
                   "Add: estimated_size: 50MB  — shown in the download UI.")
        _recommend(result, pack, "info_links", ctx,
                   "Add info_links: with links to documentation or the source project.")
        _recommend(result, pack, "supported_by", ctx,
                   "Add: supported_by: [MiSTer, RetroBat]  — limits which clients show this pack.")

        # Check pack source references resolve
        pack_sources = pack.get("sources") or []
        if isinstance(pack_sources, list):
            for ref in pack_sources:
                if ref not in source_names:
                    result.error(f"{ctx}.sources",
                                 f"Pack references source '{ref}' which is not defined in this file.",
                                 f"Available sources: {', '.join(sorted(source_names)) or '<none>'}")

    return result


# ─────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────
def lint_all(config_dir: str, verbose: bool = False) -> bool:
    """Lint all config files under config_dir. Returns True if any errors found."""
    config_dir = os.path.abspath(config_dir)
    all_results: list[LintResult] = []
    error_count   = 0
    warning_count = 0

    # ── app.yaml ──────────────────────────────────────────────
    app_yaml = os.path.join(config_dir, "app.yaml")
    if os.path.exists(app_yaml):
        r = lint_app_yaml(app_yaml)
        all_results.append(r)
    else:
        print(f"{RED}ERROR{RESET}: app.yaml not found at {app_yaml}")
        return True

    # ── Client configs ────────────────────────────────────────
    clients_root = os.path.join(config_dir, "clients")
    if os.path.isdir(clients_root):
        for config_set in sorted(os.listdir(clients_root)):
            set_dir = os.path.join(clients_root, config_set)
            if not os.path.isdir(set_dir):
                continue
            for fname in sorted(os.listdir(set_dir)):
                if fname.endswith(".yaml"):
                    r = lint_client_yaml(os.path.join(set_dir, fname))
                    all_results.append(r)

    # ── Source configs ────────────────────────────────────────
    sources_root = os.path.join(config_dir, "sources")
    if os.path.isdir(sources_root):
        for config_set in sorted(os.listdir(sources_root)):
            set_dir = os.path.join(sources_root, config_set)
            if not os.path.isdir(set_dir):
                continue
            for manufacturer in sorted(os.listdir(set_dir)):
                mfr_dir = os.path.join(set_dir, manufacturer)
                if not os.path.isdir(mfr_dir):
                    continue
                for fname in sorted(os.listdir(mfr_dir)):
                    if fname.endswith(".yaml"):
                        r = lint_source_yaml(os.path.join(mfr_dir, fname))
                        all_results.append(r)

    # ── Print results ─────────────────────────────────────────
    clean_count = 0
    for r in all_results:
        r.print(verbose=verbose)
        if r.has_errors:
            error_count += sum(1 for i in r.issues if i.severity == Issue.ERROR)
        if r.has_warnings:
            warning_count += sum(1 for i in r.issues if i.severity == Issue.WARNING)
        if not r.issues:
            clean_count += 1

    # ── Summary ───────────────────────────────────────────────
    total = len(all_results)
    print(f"\n{'-'*60}")
    print(f"{BOLD}Summary:{RESET} {total} file(s) checked - "
          f"{GREEN}{clean_count} clean{RESET}, "
          f"{YELLOW}{warning_count} warning(s){RESET}, "
          f"{RED}{error_count} error(s){RESET}")
    if error_count == 0 and warning_count == 0:
        print(f"{GREEN}All configs look good!{RESET}")
    elif error_count == 0:
        print(f"{YELLOW}No errors, but there are warnings worth addressing.{RESET}")
    else:
        print(f"{RED}Fix the errors above before deploying.{RESET}")

    return error_count > 0


# ─────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="TransFS YAML config linter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config-dir", "-c",
        default=os.path.join(os.path.dirname(__file__), "..", "app", "config"),
        help="Path to the config directory (default: app/config next to tools/)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Also print files with no issues.",
    )
    parser.add_argument(
        "--file", "-f",
        metavar="FILE",
        help="Lint a single YAML file instead of the whole config tree. "
             "Type is inferred from path (app.yaml / clients/* / sources/*).",
    )
    args = parser.parse_args()

    if args.file:
        filepath = os.path.abspath(args.file)
        if not os.path.exists(filepath):
            print(f"{RED}File not found:{RESET} {filepath}")
            sys.exit(1)

        fname = os.path.basename(filepath)
        parts = Path(filepath).parts

        if fname == "app.yaml":
            r = lint_app_yaml(filepath)
        elif "clients" in parts:
            r = lint_client_yaml(filepath)
        elif "sources" in parts:
            r = lint_source_yaml(filepath)
        else:
            print(f"{YELLOW}Cannot determine config type from path — trying as source config.{RESET}")
            r = lint_source_yaml(filepath)

        r.print(verbose=True)
        sys.exit(1 if r.has_errors else 0)

    has_errors = lint_all(args.config_dir, verbose=args.verbose)
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
