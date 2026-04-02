from __future__ import annotations

import asyncio
import json

from models import ApprovalInfo, MR, TeamMember, ThreadCount

_semaphore = asyncio.Semaphore(10)


async def _run(cmd: list[str]) -> str:
    async with _semaphore:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode()


async def _fetch_paginated(base_url: str) -> list[dict]:
    """Fetch all pages from a paginated glab API endpoint."""
    results: list[dict] = []
    page = 1
    while True:
        sep = "&" if "?" in base_url else "?"
        raw = await _run(
            ["glab", "api", f"{base_url}{sep}per_page=100&page={page}"]
        )
        if not raw.strip():
            break
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            break
        if not isinstance(data, list) or not data:
            break
        results.extend(data)
        if len(data) < 100:
            break
        page += 1
    return results


async def _fetch_group_path() -> str | None:
    """Get the namespace/group path for the current project."""
    raw = await _run(["glab", "api", "projects/:fullpath"])
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
        namespace = data.get("namespace", {})
        return namespace.get("full_path")
    except (json.JSONDecodeError, KeyError):
        return None


async def fetch_project_members() -> list[TeamMember]:
    seen: dict[int, TeamMember] = {}

    # First try project members/all (direct + inherited)
    data = await _fetch_paginated("projects/:fullpath/members/all")
    for m in data:
        if isinstance(m, dict) and "id" in m:
            seen[m["id"]] = TeamMember(user_id=m["id"], username=m["username"], name=m["name"])

    # Also fetch group members for broader coverage
    group_path = await _fetch_group_path()
    if group_path:
        encoded = group_path.replace("/", "%2F")
        group_data = await _fetch_paginated(f"groups/{encoded}/members/all")
        for m in group_data:
            if isinstance(m, dict) and "id" in m and m["id"] not in seen:
                seen[m["id"]] = TeamMember(user_id=m["id"], username=m["username"], name=m["name"])

    members = sorted(seen.values(), key=lambda m: m.username.lower())
    return members


async def fetch_open_mrs(followed_usernames: set[str]) -> list[MR]:
    raw = await _run(["glab", "mr", "list", "--per-page=100", "--output=json"])
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    mrs = []
    for item in data:
        if item.get("state") != "opened":
            continue
        if item.get("draft", False) or item.get("title", "").startswith("Draft:"):
            continue
        author = item.get("author") or {}
        username = author.get("username", "")
        if username not in followed_usernames:
            continue
        mrs.append(
            MR(
                iid=item["iid"],
                title=item["title"],
                author_username=username,
                web_url=item["web_url"],
            )
        )
    return mrs


async def fetch_approvals(mr_iid: int) -> ApprovalInfo:
    raw = await _run(
        ["glab", "api", f"projects/:fullpath/merge_requests/{mr_iid}/approvals"]
    )
    if not raw.strip():
        return ApprovalInfo()
    try:
        data = json.loads(raw)
        approved_by = data.get("approved_by") or []
        required = data.get("approvals_required", 0)
        return ApprovalInfo(approved_count=len(approved_by), required_count=required)
    except (json.JSONDecodeError, KeyError):
        return ApprovalInfo()


async def fetch_threads(mr_iid: int) -> ThreadCount:
    raw = await _run(
        ["glab", "api", f"projects/:fullpath/merge_requests/{mr_iid}/discussions?per_page=100"]
    )
    if not raw.strip():
        return ThreadCount()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ThreadCount()

    total = 0
    ai = 0
    for discussion in data:
        notes = discussion.get("notes", [])
        is_unresolved = any(
            n.get("resolvable") and not n.get("resolved") for n in notes
        )
        if not is_unresolved:
            continue
        total += 1
        # Classify by the first note's author
        first_author = notes[0].get("author", {}) if notes else {}
        if first_author.get("bot", False):
            ai += 1

    return ThreadCount(total=total, ai=ai)


async def fetch_pipeline_status(mr_iid: int) -> str | None:
    raw = await _run(
        ["glab", "api", f"projects/:fullpath/merge_requests/{mr_iid}/pipelines"]
    )
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
        if data:
            return data[0].get("status")
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    return None


async def open_mr_in_browser(mr_iid: int) -> None:
    await _run(["glab", "mr", "view", "--web", str(mr_iid)])
