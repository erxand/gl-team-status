from __future__ import annotations

from textual.widgets import DataTable
from rich.text import Text

from models import MR, TeamMember
from pfzy.score import fzy_scorer

STATUS_ICONS = {
    "success": ("✓", "green"),
    "failed": ("✗", "red"),
    "running": ("●", "steel_blue"),
    "pending": ("○", "dim"),
    "canceled": ("⊘", "dim"),
    "skipped": ("⊘", "dim"),
    "manual": ("○", "dim"),
    "created": ("○", "dim"),
    "waiting_for_resource": ("○", "dim"),
}


def pipeline_status_text(status: str | None) -> Text:
    if status is None:
        return Text("—", style="dim")
    icon, style = STATUS_ICONS.get(status, ("?", "dim"))
    return Text(f"{icon} {status}", style=style)


def approval_text(mr: MR) -> Text:
    if mr.approvals is None:
        return Text("—", style="dim")
    a = mr.approvals
    label = f"{a.approved_count}/{a.required_count}"
    if a.required_count > 0 and a.approved_count >= a.required_count:
        return Text(label, style="green")
    elif a.approved_count > 0:
        return Text(label, style="yellow")
    return Text(label)


def thread_text(mr: MR) -> Text:
    if mr.threads is None:
        return Text("—", style="dim")
    t = mr.threads
    if t.total == 0:
        return Text("0", style="green")
    if t.ai > 0:
        label = f"{t.total} ({t.ai} AI)"
    else:
        label = str(t.total)
    return Text(label, style="yellow")


def reviewer_text(mr: MR) -> Text:
    if mr.reviewing:
        return Text("✓", style="cyan bold")
    return Text("")


def fuzzy_match(title: str, query: str) -> tuple[float | None, list[int]]:
    score, indices = fzy_scorer(query.lower(), title.lower())
    if indices is None:
        return None, []
    return score, indices


def _highlight_match(title: str, query: str) -> Text:
    if not query:
        return Text(title)
    score, indices = fuzzy_match(title, query)
    if score is None:
        return Text(title)
    idx_set = set(indices)
    t = Text()
    for i, char in enumerate(title):
        t.append(char, style="bold yellow" if i in idx_set else "")
    return t


class MRTable(DataTable):
    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.cursor_foreground_priority = "renderable"

    def populate(self, mrs: list[MR], search_query: str = "") -> None:
        self.clear(columns=True)

        # Pre-compute cell contents so we can measure widths
        rows: list[tuple] = []
        for mr in mrs:
            author = mr.author_username
            if len(author) > 14:
                author = author[:11] + "..."
            rows.append((
                Text(f"!{mr.iid}"),
                Text(f"@{author}", style="dim"),
                _highlight_match(mr.title, search_query),
                reviewer_text(mr),
                approval_text(mr),
                thread_text(mr),
                pipeline_status_text(mr.pipeline_status),
                str(mr.iid),
            ))

        # Measure max content width per column (excluding Title which fills remaining space)
        headers = ["MR", "Author", "Title", "Rev", "Apps", "Threads", "Pipeline"]
        mr_w = max((len(r[0].plain) for r in rows), default=2)
        mr_w = max(mr_w, len(headers[0]))
        author_w = max((len(r[1].plain) for r in rows), default=6)
        author_w = max(author_w, len(headers[1]))
        rev_w = max((len(r[3].plain) for r in rows), default=1)
        rev_w = max(rev_w, len(headers[3]))
        appr_w = max((len(r[4].plain) for r in rows), default=3)
        appr_w = max(appr_w, len(headers[4]))
        thr_w = max((len(r[5].plain) for r in rows), default=7)
        thr_w = max(thr_w, len(headers[5]))
        pipe_w = max((len(r[6].plain) for r in rows), default=8)
        pipe_w = max(pipe_w, len(headers[6]))

        # 2 chars padding per column × 7 columns
        cell_padding = 14
        fixed = mr_w + author_w + rev_w + appr_w + thr_w + pipe_w + cell_padding
        title_w = max(20, self.size.width - fixed) if self.size.width > 0 else 60

        self.add_column(headers[0], width=mr_w)
        self.add_column(headers[1], width=author_w)
        self.add_column(headers[2], width=title_w)
        self.add_column(headers[3], width=rev_w)
        self.add_column(headers[4], width=appr_w)
        self.add_column(headers[5], width=thr_w)
        self.add_column(headers[6], width=pipe_w)

        for mr_id, author, title, rev, appr, thr, pipe, key in rows:
            self.add_row(mr_id, author, title, rev, appr, thr, pipe, key=key)


class SettingsTable(DataTable):
    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.cursor_foreground_priority = "renderable"

    def populate(self, members: list[TeamMember], followed_ids: set[int], search_query: str = "") -> None:
        # Preserve cursor position across re-render
        selected_key = None
        if self.row_count > 0 and self.cursor_row is not None and self.cursor_row < self.row_count:
            selected_key = self.ordered_rows[self.cursor_row].key.value

        self.clear(columns=True)

        self.add_column("", width=5)
        self.add_column("Username", width=22)
        self.add_column("Name", width=30)

        filtered = members
        if search_query:
            scored = []
            for m in members:
                haystack = f"{m.username} {m.name}"
                score, _ = fuzzy_match(haystack, search_query)
                if score is not None:
                    scored.append((score, m))
            filtered = [m for _, m in sorted(scored, key=lambda x: x[0], reverse=True)]

        for m in filtered:
            if m.user_id in followed_ids:
                check = Text(" ✓ ", style="green bold")
            else:
                check = Text("   ")
            self.add_row(
                check,
                Text(f"@{m.username}"),
                Text(m.name, style="dim"),
                key=str(m.user_id),
            )

        # Restore cursor position
        if selected_key is not None:
            for idx, row in enumerate(self.ordered_rows):
                if row.key.value == selected_key:
                    self.move_cursor(row=idx)
                    break
