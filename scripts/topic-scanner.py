#!/usr/bin/env python3
"""
TOPIC SCANNER - Builds a project/topic registry by scanning a workspace.
Maps every project name → all related paths, tags, key files.

Configure via environment variables:
  TOPIC_SCANNER_ROOT  — Root directory to scan (default: ~/projects)
  TOPIC_SCANNER_OUT   — Output directory (default: $ROOT/topics)

Output: $TOPIC_SCANNER_OUT/registry.json
"""

import os
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

SCAN_ROOT = os.environ.get("TOPIC_SCANNER_ROOT", os.path.expanduser("~/projects"))
OUTPUT_DIR = os.environ.get("TOPIC_SCANNER_OUT", os.path.join(SCAN_ROOT, "topics"))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "registry.json")

# User-configurable: add your own project name aliases here
# Maps variant names to canonical names
ALIASES = {
    # Example:
    # "my-project-v2": "my-project",
    # "old-api": "my-api",
}

# User-configurable: add your project names to scan for
# Leave empty to auto-discover from directory names
KNOWN_PROJECTS = [
    # Example:
    # "my-project",
    # "my-api",
]

# File extensions to scan for tags/keywords
SCANNABLE_EXTS = {".md", ".txt", ".json", ".yaml", ".yml", ".sh", ".py"}

# Directories to skip (large, irrelevant)
SKIP_DIRS = {
    "node_modules", ".git", ".next", "__pycache__", "dist",
    ".pnpm", ".pnpm-store", "cache", "lost+found", ".venv",
    "venv", "env", ".env", "build", "target",
}

# Tag extraction patterns
TAG_PATTERNS = [
    r"CVE-\d{4}-\d+",
    r"CWE-\d+",
    r"\b(XSS|SQLi|SSRF|IDOR|RCE|LFI|CSRF|XXE|SSTI)\b",
    r"\b(OAuth|JWT|API|CORS|CSP)\b",
    r"\b(bypass|injection|leak|exposed|misconfigur|vulnerab)\w*",
]


def normalize_project(name):
    """Normalize project name using aliases."""
    name_lower = name.lower().strip()
    if name_lower in ALIASES:
        return ALIASES[name_lower]
    return name_lower


def extract_tags(filepath, max_bytes=5000):
    """Extract relevant tags from a file."""
    tags = set()
    try:
        with open(filepath, "r", errors="ignore") as f:
            content = f.read(max_bytes)
        for pattern in TAG_PATTERNS:
            matches = re.findall(pattern, content, re.IGNORECASE)
            tags.update(m.upper() if len(m) <= 5 else m.lower() for m in matches)
    except Exception:
        pass
    return tags


def get_key_files(dirpath, max_files=10):
    """Get the most important files in a directory."""
    key_files = []
    try:
        for entry in sorted(os.scandir(dirpath), key=lambda e: e.name):
            if entry.is_file():
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in SCANNABLE_EXTS:
                    key_files.append(entry.name)
                    if len(key_files) >= max_files:
                        break
    except PermissionError:
        pass
    return key_files


def count_files(dirpath):
    """Count total files in a directory tree (fast, skip heavy dirs)."""
    count = 0
    try:
        for root, dirs, files in os.walk(dirpath):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            count += len(files)
            if count > 1000:
                return f"{count}+"
    except PermissionError:
        pass
    return count


def scan_directory(base_dir):
    """Scan a directory for project subdirectories."""
    projects = defaultdict(lambda: {
        "paths": [],
        "key_files": [],
        "tags": set(),
        "files_count": 0,
        "status": "unknown",
    })

    if not os.path.isdir(base_dir):
        return projects

    for item in os.listdir(base_dir):
        item_path = os.path.join(base_dir, item)
        if not os.path.isdir(item_path):
            continue

        canonical = normalize_project(item)
        entry = projects[canonical]
        entry["paths"].append(item_path)
        entry["key_files"].extend(get_key_files(item_path))
        entry["files_count"] = count_files(item_path)

        for kf in entry["key_files"]:
            tags = extract_tags(os.path.join(item_path, kf))
            entry["tags"].update(tags)

    return projects


def scan_for_known_projects(base_dir):
    """Scan files for references to known projects."""
    if not KNOWN_PROJECTS:
        return defaultdict(list)

    findings = defaultdict(list)
    if not os.path.isdir(base_dir):
        return findings

    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith((".md", ".txt")):
                filepath = os.path.join(root, f)
                try:
                    with open(filepath, "r", errors="ignore") as fh:
                        content = fh.read(10000).lower()
                    for proj_name in KNOWN_PROJECTS:
                        if proj_name.lower() in content:
                            findings[proj_name].append(filepath)
                except Exception:
                    pass

    return findings


def build_registry():
    """Build the full project registry."""
    print(f"[*] Scanning {SCAN_ROOT}...")
    projects = scan_directory(SCAN_ROOT)

    print("[*] Scanning for known project references...")
    refs = scan_for_known_projects(SCAN_ROOT)

    # Merge references
    for proj, paths in refs.items():
        canonical = normalize_project(proj)
        if canonical not in projects:
            projects[canonical] = {
                "paths": [],
                "key_files": [],
                "tags": set(),
                "files_count": 0,
                "status": "unknown",
            }
        existing = set(projects[canonical]["paths"])
        for p in paths:
            if p not in existing:
                projects[canonical]["paths"].append(p)
                existing.add(p)

    # Build JSON-serializable registry
    registry = {
        "meta": {
            "last_scan": datetime.now(timezone.utc).isoformat(),
            "scanner_version": "2.0",
            "scan_root": SCAN_ROOT,
            "total_projects": len(projects),
        },
        "projects": {}
    }

    for name, data in sorted(projects.items()):
        registry["projects"][name] = {
            "paths": sorted(set(data["paths"])),
            "path_count": len(set(data["paths"])),
            "key_files": list(set(data["key_files"]))[:15],
            "tags": sorted(data["tags"])[:20],
            "files_count": data["files_count"],
            "status": data.get("status", "unknown"),
        }

    return registry


def generate_summary(registry):
    """Generate a lightweight summary."""
    summary_lines = []
    for name, data in sorted(registry["projects"].items()):
        path_count = data["path_count"]
        tags_str = ", ".join(data["tags"][:5]) if data["tags"] else "no tags"
        summary_lines.append(f"  {name}: {path_count} locations | {tags_str}")

    summary = f"# Topic Registry ({registry['meta']['total_projects']} projects)\n"
    summary += f"# Last scan: {registry['meta']['last_scan']}\n"
    summary += "\n".join(summary_lines)
    return summary


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    registry = build_registry()

    with open(OUTPUT_FILE, "w") as f:
        json.dump(registry, f, indent=2)
    print(f"[+] Registry: {OUTPUT_FILE} ({len(registry['projects'])} projects)")

    summary = generate_summary(registry)
    summary_file = os.path.join(OUTPUT_DIR, "summary.txt")
    with open(summary_file, "w") as f:
        f.write(summary)
    print(f"[+] Summary: {summary_file}")

    print(f"\n[*] REGISTRY: {len(registry['projects'])} projects indexed")
    for name, data in sorted(registry["projects"].items()):
        print(f"    {name:25s} | {data['path_count']:2d} paths | {', '.join(data['tags'][:3])}")


if __name__ == "__main__":
    main()
