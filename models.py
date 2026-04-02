from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApprovalInfo:
    approved_count: int = 0
    required_count: int = 0


@dataclass
class ThreadCount:
    total: int = 0    # total unresolved threads
    ai: int = 0       # unresolved threads from bots

    @property
    def human(self) -> int:
        return self.total - self.ai


@dataclass
class MR:
    iid: int
    title: str
    author_username: str
    web_url: str
    pipeline_status: str | None = None
    approvals: ApprovalInfo | None = None
    threads: ThreadCount | None = None

    @property
    def is_draft(self) -> bool:
        return self.title.startswith("Draft:")


@dataclass
class TeamMember:
    user_id: int
    username: str
    name: str
