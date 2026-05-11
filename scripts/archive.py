#!/usr/bin/env python3
"""
compounded portable archive (export and import).

Export bundles into a single .tar.gz:
  - USER.md
  - All active skills (.verified/, .trusted/, .autonomous/)
  - The trust DB rows for those skills (without raw event logs by default)
  - A manifest with compounded version, timestamp, machine identifier hash

Excluded by default for privacy:
  - .proposed/, .rejected/ (work-in-progress, may contain incomplete drafts)
  - Raw event logs (`logs/`)
  - The trust.db file itself (we serialize the relevant rows into JSON)

Use --include-pending to also export .proposed/ and .rejected/.

Import merges:
  - USER.md: appended with a separator if both files have content
  - Skills: imported into matching tier directory; conflicts skipped (with warning)
  - Trust state rows: re-created in the local DB

Usage:
    archive.py export --output ~/Desktop/compounded-2026-05-11.tar.gz [--include-pending]
    archive.py import --input ~/Desktop/compounded-2026-05-11.tar.gz [--overwrite]
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import io
import json
import os
import platform
import socket
import sys
import tarfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _lib import (
    ACTIVE_STATES,
    PROPOSED,
    REJECTED,
    SKILLS_DIR,
    STATE_DIRS,
    USER_MD,
    db,
    ensure_layout,
    find_skill_dir,
    get_skill,
    log_event,
    now_ts,
    upsert_skill,
)

ARCHIVE_VERSION = 1
MANIFEST_NAME = "compounded-manifest.json"
USER_MD_NAME = "USER.md"
SKILLS_JSON_NAME = "skills.json"
SKILLS_DATA_DIR = "skills"


def machine_id() -> str:
    raw = f"{getpass.getuser()}@{socket.gethostname()}:{platform.platform()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def collect_skills_for_export(include_pending: bool) -> list[dict]:
    states = list(ACTIVE_STATES)
    if include_pending:
        states += [PROPOSED, REJECTED]

    out: list[dict] = []
    for state in states:
        base = STATE_DIRS[state]
        if not base.exists():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            if not skill_md.exists():
                continue
            entry = {
                "name": child.name,
                "state": state,
                "skill_md": skill_md.read_text(encoding="utf-8"),
                "verification_hint": None,
                "verification_verdict": None,
                "rejection_reason": None,
            }
            hint_path = child / ".verification_hint"
            if hint_path.exists():
                entry["verification_hint"] = hint_path.read_text(encoding="utf-8").strip()
            verdict_path = child / ".verification_verdict"
            if verdict_path.exists():
                try:
                    entry["verification_verdict"] = json.loads(verdict_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            rejection_path = child / ".rejection_reason"
            if rejection_path.exists():
                entry["rejection_reason"] = rejection_path.read_text(encoding="utf-8").strip()

            with db() as conn:
                row = get_skill(conn, child.name)
            if row is not None:
                entry["use_count"] = row["use_count"]
                entry["correction_count"] = row["correction_count"]
                entry["clean_uses_since_correction"] = row["clean_uses_since_correction"]
                entry["last_used_at"] = row["last_used_at"]

            out.append(entry)
    return out


def cmd_export(args: argparse.Namespace) -> int:
    ensure_layout()
    output_path = Path(args.output).expanduser().resolve()
    if output_path.exists() and not args.force:
        print(f"error: {output_path} already exists. Use --force to overwrite.", file=sys.stderr)
        return 2

    skills = collect_skills_for_export(include_pending=args.include_pending)

    user_md_text = USER_MD.read_text(encoding="utf-8") if USER_MD.exists() else ""

    manifest = {
        "archive_version": ARCHIVE_VERSION,
        "exported_at": now_ts(),
        "exported_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "machine_id": machine_id(),
        "include_pending": bool(args.include_pending),
        "skill_count": len(skills),
        "skill_states": {state: sum(1 for s in skills if s["state"] == state) for state in (*ACTIVE_STATES, PROPOSED, REJECTED)},
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(output_path, mode="w:gz") as tar:
        # Manifest
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        info = tarfile.TarInfo(name=MANIFEST_NAME)
        info.size = len(manifest_bytes)
        info.mtime = now_ts()
        tar.addfile(info, io.BytesIO(manifest_bytes))

        # USER.md
        user_bytes = user_md_text.encode("utf-8")
        info = tarfile.TarInfo(name=USER_MD_NAME)
        info.size = len(user_bytes)
        info.mtime = now_ts()
        tar.addfile(info, io.BytesIO(user_bytes))

        # Skills metadata in one JSON
        skills_bytes = json.dumps(skills, indent=2).encode("utf-8")
        info = tarfile.TarInfo(name=SKILLS_JSON_NAME)
        info.size = len(skills_bytes)
        info.mtime = now_ts()
        tar.addfile(info, io.BytesIO(skills_bytes))

        # And as actual SKILL.md files for human inspection
        for entry in skills:
            md_bytes = entry["skill_md"].encode("utf-8")
            arcname = f"{SKILLS_DATA_DIR}/{entry['state']}/{entry['name']}/SKILL.md"
            info = tarfile.TarInfo(name=arcname)
            info.size = len(md_bytes)
            info.mtime = now_ts()
            tar.addfile(info, io.BytesIO(md_bytes))

    print(f"exported: {output_path}")
    print(f"  user.md: {len(user_md_text)} chars")
    print(f"  skills:  {len(skills)} ({manifest['skill_states']})")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    ensure_layout()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"error: {input_path} does not exist", file=sys.stderr)
        return 2

    try:
        with tarfile.open(input_path, mode="r:gz") as tar:
            members = {m.name: m for m in tar.getmembers()}

            if MANIFEST_NAME not in members:
                print(f"error: archive missing {MANIFEST_NAME}", file=sys.stderr)
                return 2

            manifest_member = tar.extractfile(members[MANIFEST_NAME])
            if manifest_member is None:
                print("error: cannot read manifest", file=sys.stderr)
                return 2
            manifest = json.loads(manifest_member.read().decode("utf-8"))

            if manifest.get("archive_version") != ARCHIVE_VERSION:
                print(
                    f"warning: archive version is {manifest.get('archive_version')!r}, "
                    f"expected {ARCHIVE_VERSION}; proceeding but may be incompatible.",
                    file=sys.stderr,
                )

            print(f"importing archive from {manifest.get('exported_at_iso')} (machine {manifest.get('machine_id')})")

            # USER.md
            if USER_MD_NAME in members:
                user_member = tar.extractfile(members[USER_MD_NAME])
                if user_member is not None:
                    incoming = user_member.read().decode("utf-8")
                    existing = USER_MD.read_text(encoding="utf-8") if USER_MD.exists() else ""
                    if not existing.strip():
                        USER_MD.write_text(incoming, encoding="utf-8")
                        print(f"  USER.md: imported ({len(incoming)} chars)")
                    elif args.overwrite:
                        USER_MD.write_text(incoming, encoding="utf-8")
                        print(f"  USER.md: overwritten ({len(incoming)} chars)")
                    else:
                        merged = existing.rstrip() + "\n\n---\n[imported " + manifest.get("exported_at_iso", "") + "]\n" + incoming.lstrip()
                        USER_MD.write_text(merged, encoding="utf-8")
                        print(f"  USER.md: merged (now {len(merged)} chars)")

            # Skills
            if SKILLS_JSON_NAME in members:
                skills_member = tar.extractfile(members[SKILLS_JSON_NAME])
                if skills_member is None:
                    print("error: cannot read skills.json", file=sys.stderr)
                    return 2
                skills = json.loads(skills_member.read().decode("utf-8"))

                imported = 0
                skipped = 0
                for entry in skills:
                    name = entry["name"]
                    state = entry["state"]
                    if state not in STATE_DIRS:
                        continue
                    target_dir = STATE_DIRS[state] / name
                    if target_dir.exists() and not args.overwrite:
                        existing_check = find_skill_dir(name)
                        if existing_check is not None:
                            print(f"  skill {name!r}: skipped (exists at .{existing_check[0]})")
                            skipped += 1
                            continue
                    target_dir.mkdir(parents=True, exist_ok=True)
                    (target_dir / "SKILL.md").write_text(entry["skill_md"], encoding="utf-8")
                    if entry.get("verification_hint"):
                        (target_dir / ".verification_hint").write_text(entry["verification_hint"], encoding="utf-8")
                    if entry.get("verification_verdict"):
                        (target_dir / ".verification_verdict").write_text(
                            json.dumps(entry["verification_verdict"], indent=2),
                            encoding="utf-8",
                        )
                    if entry.get("rejection_reason"):
                        (target_dir / ".rejection_reason").write_text(entry["rejection_reason"], encoding="utf-8")

                    with db() as conn:
                        upsert_skill(conn, name=name, state=state, verification_hint=entry.get("verification_hint"))
                        # Counters
                        if "use_count" in entry:
                            conn.execute(
                                "UPDATE skills SET use_count = ?, correction_count = ?, "
                                "clean_uses_since_correction = ? WHERE name = ?",
                                (
                                    entry.get("use_count", 0),
                                    entry.get("correction_count", 0),
                                    entry.get("clean_uses_since_correction", 0),
                                    name,
                                ),
                            )
                        log_event(conn, name, "imported", {"source_machine": manifest.get("machine_id")})
                    imported += 1

                print(f"  skills: {imported} imported, {skipped} skipped")
    except tarfile.TarError as exc:
        print(f"error: cannot read archive: {exc}", file=sys.stderr)
        return 2

    print("done.")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_export = sub.add_parser("export")
    p_export.add_argument("--output", required=True)
    p_export.add_argument("--include-pending", action="store_true",
                          help="include .proposed/ and .rejected/ skills")
    p_export.add_argument("--force", action="store_true")
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser("import")
    p_import.add_argument("--input", required=True)
    p_import.add_argument("--overwrite", action="store_true",
                          help="overwrite local skills if names collide")
    p_import.set_defaults(func=cmd_import)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001
        print(f"error: archive: {exc}", file=sys.stderr)
        sys.exit(1)
