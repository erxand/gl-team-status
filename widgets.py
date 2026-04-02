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

        # Fixed columns: MR(7) + Author(15) + Approvals(10) + Threads(14) + Pipeline(13) = 59
        # Cell padding: ~2 per column × 6 = 12
        other_cols = 59
        cell_padding = 12
        title_width = max(20, self.size.width - other_cols - cell_padding) if self.size.width > 0 else 60

        self.add_column("MR", width=7)
        self.add_column("Author", width=15)
        self.add_column("Title", width=title_width)
        self.add_column("Approvals", width=10)
        self.add_column("Threads", width=14)
        self.add_column("Pipeline", width=13)

        for mr in mrs:
            author = mr.author_username
            if len(author) > 14:
                author = author[:11] + "..."
            self.add_row(
                Text(f"!{mr.iid}"),
                Text(f"@{author}", style="dim"),
                _highlight_match(mr.title, search_query),
                approval_text(mr),
                thread_text(mr),
                pipeline_status_text(mr.pipeline_status),
                key=str(mr.iid),
            )


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
