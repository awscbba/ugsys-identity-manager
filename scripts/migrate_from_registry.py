#!/usr/bin/env python3
"""
Migration script: Registry PeopleTableV2 → ugsys-identity-manager-users-{env}

What it does:
  1. Scans PeopleTableV2 for all users
  2. Fetches roles from people-registry-roles for each user
  3. Transforms schema to the identity-manager format
  4. Writes to ugsys-identity-manager-users-{env} using pk=USER#{id}/sk=PROFILE

Role mapping:
  Registry          → Identity Manager
  user              → member
  admin             → admin
  super_admin       → super_admin
  moderator         → member  (no equivalent)
  auditor           → member  (no equivalent)
  guest             → member  (no equivalent)

Password hashes: bcrypt — compatible, copied as-is.

Usage:
  # Dry run (default) — prints what would be migrated, writes nothing
  uv run python scripts/migrate_from_registry.py

  # Live run
  uv run python scripts/migrate_from_registry.py --execute

  # Target a specific environment
  uv run python scripts/migrate_from_registry.py --env prod --execute

  # Override table names explicitly
  uv run python scripts/migrate_from_registry.py \\
    --source-table PeopleTableV2 \\
    --roles-table people-registry-roles \\
    --target-table ugsys-identity-manager-users-prod \\
    --execute
"""

import argparse
import sys
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

# ── Role mapping ──────────────────────────────────────────────────────────────

ROLE_MAP: dict[str, str] = {
    "user": "member",
    "member": "member",
    "moderator": "member",
    "auditor": "member",
    "guest": "member",
    "admin": "admin",
    "super_admin": "super_admin",
}

DEFAULT_ROLE = "member"


def map_roles(registry_roles: list[str], is_admin: bool) -> list[str]:
    """Map Registry role names to identity-manager role names."""
    mapped = {ROLE_MAP.get(r.lower(), DEFAULT_ROLE) for r in registry_roles}
    if is_admin and "admin" not in mapped and "super_admin" not in mapped:
        mapped.add("admin")
    if not mapped:
        mapped.add(DEFAULT_ROLE)
    return sorted(mapped)


# ── DynamoDB helpers ──────────────────────────────────────────────────────────


def scan_all(table: object) -> list[dict]:  # type: ignore[type-arg]
    """Full table scan, handles pagination."""
    items: list[dict] = []  # type: ignore[type-arg]
    kwargs: dict[str, Any] = {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return items


def get_user_roles_from_registry(
    roles_table: object,
    user_id: str,  # type: ignore[type-arg]
) -> list[str]:
    """Query people-registry-roles for a user's active roles."""
    try:
        resp = roles_table.query(
            KeyConditionExpression="user_id = :uid",
            ExpressionAttributeValues={":uid": user_id},
        )
        return [item["role_type"] for item in resp.get("Items", []) if item.get("is_active", True)]
    except ClientError as e:
        print(f"  [WARN] Could not fetch roles for {user_id}: {e}")
        return []


# ── Schema transform ──────────────────────────────────────────────────────────


def transform(person: dict, roles: list[str]) -> dict:  # type: ignore[type-arg]
    """Convert a Registry person item to identity-manager user item."""
    user_id = person["id"]
    is_admin = person.get("isAdmin", False)

    # Combine firstName + lastName into full_name
    first = person.get("firstName", "").strip()
    last = person.get("lastName", "").strip()
    full_name = f"{first} {last}".strip() or "Unknown"

    # Status mapping
    is_active = person.get("isActive", False)
    status = "active" if is_active else "inactive"

    # Timestamps — preserve originals, fall back to now
    now = datetime.now(UTC).isoformat()
    created_at = person.get("createdAt", now)
    updated_at = person.get("updatedAt", now)

    # Ensure ISO format with timezone
    for ts in [created_at, updated_at]:
        if ts and not ts.endswith("+00:00") and not ts.endswith("Z"):
            pass  # assume UTC if no tz info

    mapped_roles = map_roles(roles, is_admin)

    return {
        "pk": f"USER#{user_id}",
        "sk": "PROFILE",
        "id": user_id,
        "email": person.get("email", "").lower().strip(),
        "hashed_password": person.get("passwordHash", ""),
        "full_name": full_name,
        "status": status,
        "roles": mapped_roles,
        "created_at": created_at,
        "updated_at": updated_at,
        # Preserve extra fields for audit trail
        "_migrated_from": "registry",
        "_migrated_at": now,
    }


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate users from Registry to identity-manager")
    parser.add_argument("--env", default="prod", help="Target environment (default: prod)")
    parser.add_argument("--source-table", default="PeopleTableV2", help="Registry people table")
    parser.add_argument(
        "--roles-table", default="people-registry-roles", help="Registry roles table"
    )
    parser.add_argument("--target-table", default="", help="Override target table name")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument(
        "--execute", action="store_true", help="Actually write to DynamoDB (default: dry run)"
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip users already in target (default: True)",
    )
    args = parser.parse_args()

    target_table = args.target_table or f"ugsys-identity-manager-users-{args.env}"
    dry_run = not args.execute

    print("=" * 60)
    print("Registry → Identity Manager User Migration")
    print("=" * 60)
    print(f"  Source table : {args.source_table}")
    print(f"  Roles table  : {args.roles_table}")
    print(f"  Target table : {target_table}")
    print(f"  Region       : {args.region}")
    print(f"  Mode         : {'DRY RUN' if dry_run else '⚠️  LIVE WRITE'}")
    print()

    dynamodb = boto3.resource("dynamodb", region_name=args.region)
    source = dynamodb.Table(args.source_table)
    roles_tbl = dynamodb.Table(args.roles_table)
    target = dynamodb.Table(target_table)

    # Scan source
    print("Scanning source table...")
    people = scan_all(source)
    print(f"Found {len(people)} users in {args.source_table}")
    print()

    # Check existing in target (for skip-existing)
    existing_ids: set[str] = set()
    if args.skip_existing and not dry_run:
        print("Scanning target table for existing users...")
        existing = scan_all(target)
        existing_ids = {item.get("id", "") for item in existing}
        print(f"Found {len(existing_ids)} existing users in target — will skip them")
        print()

    # Migrate
    migrated = 0
    skipped = 0
    errors = 0
    no_password = 0

    for person in people:
        user_id = person.get("id", "")
        email = person.get("email", "").lower().strip()

        if not user_id or not email:
            print(f"  [SKIP] Missing id or email: {person}")
            skipped += 1
            continue

        if user_id in existing_ids:
            print(f"  [SKIP] Already exists: {email}")
            skipped += 1
            continue

        # Fetch roles
        roles = get_user_roles_from_registry(roles_tbl, user_id)

        # Transform
        item = transform(person, roles)

        # Warn on missing password hash
        if not item["hashed_password"]:
            print(f"  [WARN] No passwordHash for {email} — user won't be able to log in")
            no_password += 1

        if dry_run:
            print(
                f"  [DRY RUN] Would migrate: {email} | "
                f"status={item['status']} | roles={item['roles']}"
            )
            migrated += 1
        else:
            try:
                target.put_item(Item=item)
                print(f"  [OK] Migrated: {email} | status={item['status']} | roles={item['roles']}")
                migrated += 1
            except ClientError as e:
                print(f"  [ERROR] Failed to migrate {email}: {e}")
                errors += 1

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Migrated : {migrated}")
    print(f"  Skipped  : {skipped}")
    print(f"  Errors   : {errors}")
    print(f"  No pwd   : {no_password} (users without passwordHash)")
    if dry_run:
        print()
        print("This was a DRY RUN. Run with --execute to apply changes.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
