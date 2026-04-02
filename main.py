#!/usr/bin/env python3
from __future__ import annotations
import os
import sys
from pathlib import Path

def _maybe_reexec_into_venv():
    script_dir = Path(__file__).resolve().parent
    venv_python = script_dir / ".venv" / "bin" / "python"
    if venv_python.is_file() and os.environ.get("VENV_PREFERRED") != "1":
        os.environ["VENV_PREFERRED"] = "1"
        os.execv(str(venv_python), [str(venv_python)] + sys.argv)

_maybe_reexec_into_venv()

import asyncio
import shutil
import subprocess

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.events import Key
from textual.widgets import Static
from textual.timer import Timer
from textual.binding import Binding
from textual.widgets import DataTable
from rich.text import Text

import db
import gitlab
from models import MR, TeamMember
from widgets import MRTable, SettingsTable, fuzzy_match


REFRESH_INTERVAL = 30
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _preflight_check() -> None:
    if shutil.which("glab") is None:
        sys.exit(
            "Error: 'glab' CLI not found in PATH.\n"
            "Install it from: https://gitlab.com/gitlab-org/cli"
        )

    result = subprocess.run(["glab", "auth", "status"], capture_output=True)
    if result.returncode != 0:
        sys.exit(
            "Error: 'glab' is not authenticated.\n"
            "Run 'glab auth login' to authenticate."
        )

    result = subprocess.run(
        ["glab", "api", "projects/:fullpath"], capture_output=True
    )
    if result.returncode != 0:
        sys.exit(
            "Error: Not a GitLab repository.\n"
            "Run this tool from a directory that is a GitLab-backed git repository."
        )


class TeamStatusApp(App):
    TITLE = "GL Team Status"

    CSS = """
    #header-bar {
        dock: top;
        height: 1;
        background: $primary-background;
        padding: 0 1;
    }
    #filter-row {
        dock: top;
        height: 1;
        background: $surface;
    }
    #filter-bar {
        width: 1fr;
        padding: 0 1;
    }
    #hotkeys {
        width: auto;
        padding: 0 1;
        color: $text-muted;
    }
    #mr-table {
        height: 1fr;
    }
    #mr-table > .datatable--cursor {
        background: $surface;
        text-style: bold;
    }
    #mr-table > .datatable--hover {
        background: transparent;
        text-style: none;
    }
    #settings-table {
        height: 1fr;
        display: none;
    }
    #settings-table > .datatable--cursor {
        background: $surface;
        text-style: bold;
    }
    #settings-table > .datatable--hover {
        background: transparent;
        text-style: none;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "toggle_settings", "Settings", show=False),
        Binding("o", "open_mr", "Open", show=False),
        Binding("f", "force_refresh", "Refresh", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("slash", "start_search", "Search", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.mrs: list[MR] = []
        self.search_query: str = ""
        self._searching: bool = False
        self.seconds_until_refresh = REFRESH_INTERVAL
        self._countdown_timer: Timer | None = None
        self._refresh_task: asyncio.Task | None = None
        self._refreshing: bool = False
        self._spinner_frame: int = 0
        self._spinner_timer: Timer | None = None
        self._settings_visible: bool = False
        self._project_members: list[TeamMember] = []
        self._followed_ids: set[int] = set()

    def compose(self) -> ComposeResult:
        yield Static(id="header-bar")
        with Horizontal(id="filter-row"):
            yield Static(id="filter-bar")
            yield Static(id="hotkeys")
        yield MRTable(id="mr-table")
        yield SettingsTable(id="settings-table")

    def on_mount(self) -> None:
        db.init_db()
        followed = db.get_followed_users()
        self._followed_ids = {u.user_id for u in followed}

        self._update_header()
        self._update_hotkeys()

        if not followed:
            # No users followed yet — show settings
            self._settings_visible = True
            self._apply_view_visibility()
            self._update_filter_bar()
            asyncio.ensure_future(self._load_members())
        else:
            self._apply_view_visibility()
            self._update_filter_bar()
            self.query_one("#mr-table", MRTable).loading = True
            self._schedule_refresh()

        self._countdown_timer = self.set_interval(1, self._tick)
        self._spinner_timer = self.set_interval(0.15, self._spin, pause=True)

    def _apply_view_visibility(self) -> None:
        mr_table = self.query_one("#mr-table", MRTable)
        settings = self.query_one("#settings-table", SettingsTable)
        if self._settings_visible:
            mr_table.styles.display = "none"
            settings.styles.display = "block"
        else:
            mr_table.styles.display = "block"
            settings.styles.display = "none"

    def _schedule_refresh(self) -> None:
        if self._refreshing:
            return
        self._refresh_task = asyncio.ensure_future(self._do_refresh())

    def _update_header(self) -> None:
        if self._settings_visible:
            self.query_one("#header-bar", Static).update(
                "GL Team Status | Settings — select users to follow"
            )
        else:
            mins = self.seconds_until_refresh // 60
            secs = self.seconds_until_refresh % 60
            self.query_one("#header-bar", Static).update(
                f"GL Team Status | Next refresh: {mins}:{secs:02d}"
            )

    def _update_filter_bar(self) -> None:
        t = Text()
        if self._settings_visible:
            t.append(" s ", style="bold underline")
            t.append("Settings")
            t.append("  ")
            t.append(f"{len(self._followed_ids)} followed", style="dim")
        else:
            t.append(" s ", style="dim")
            t.append("Settings")
            t.append("  ")
            t.append(f"{len(self.mrs)} MRs", style="dim")

        t.append("  ")
        t.append(" / ", style="bold underline" if (self._searching or self.search_query) else "dim")
        if self._searching:
            t.append(self.search_query + "▊")
        elif self.search_query:
            t.append(self.search_query, style="dim")
        else:
            t.append("search...", style="dim")

        self.query_one("#filter-bar", Static).update(t)

    def _update_hotkeys(self) -> None:
        spinner = f" {_SPINNER_FRAMES[self._spinner_frame]}" if self._refreshing else ""
        if self._settings_visible:
            self.query_one("#hotkeys", Static).update(
                "↵ toggle · / filter · s back · q quit"
            )
        else:
            self.query_one("#hotkeys", Static).update(
                f"o open · f refresh{spinner} · s settings · / search · q quit"
            )

    def _spin(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(_SPINNER_FRAMES)
        self._update_hotkeys()

    def _tick(self) -> None:
        if self._settings_visible:
            return
        self.seconds_until_refresh -= 1
        if self.seconds_until_refresh <= 0:
            self.seconds_until_refresh = REFRESH_INTERVAL
            self._schedule_refresh()
        self._update_header()

    async def _do_refresh(self) -> None:
        self._refreshing = True
        if self._spinner_timer is not None:
            self._spinner_timer.resume()
        self._update_hotkeys()
        try:
            followed_usernames = db.get_followed_usernames()
            if not followed_usernames:
                self.mrs = []
                self._render_table()
                return

            mrs = await gitlab.fetch_open_mrs(followed_usernames)

            async def enrich(mr: MR) -> None:
                try:
                    mr.approvals = await gitlab.fetch_approvals(mr.iid)
                    mr.threads = await gitlab.fetch_threads(mr.iid)
                    mr.pipeline_status = await gitlab.fetch_pipeline_status(mr.iid)
                except Exception:
                    pass

            await asyncio.gather(*(enrich(mr) for mr in mrs))

            self.mrs = mrs
            self._render_table()
        finally:
            self._refreshing = False
            if self._spinner_timer is not None:
                self._spinner_timer.pause()
            self._update_hotkeys()

    def _visible_mrs(self) -> list[MR]:
        mrs = self.mrs
        if self.search_query:
            scored = []
            for mr in mrs:
                score, _ = fuzzy_match(mr.title, self.search_query)
                if score is not None:
                    scored.append((score, mr))
            mrs = [mr for _, mr in sorted(scored, key=lambda x: x[0], reverse=True)]
        return mrs

    def _render_table(self) -> None:
        table = self.query_one("#mr-table", MRTable)
        table.loading = False
        selected_key = None
        if table.row_count > 0 and table.cursor_row is not None and table.cursor_row < table.row_count:
            selected_key = table.ordered_rows[table.cursor_row].key.value
        table.populate(self._visible_mrs(), search_query=self.search_query)
        if selected_key is not None:
            for idx, row in enumerate(table.ordered_rows):
                if row.key.value == selected_key:
                    table.move_cursor(row=idx)
                    break
        self._update_filter_bar()

    def _render_settings(self) -> None:
        table = self.query_one("#settings-table", SettingsTable)
        table.populate(self._project_members, self._followed_ids, search_query=self.search_query)

    def _selected_mr(self) -> MR | None:
        table = self.query_one("#mr-table", MRTable)
        if table.cursor_row is None or table.cursor_row >= table.row_count:
            return None
        row_key = table.ordered_rows[table.cursor_row].key
        for mr in self.mrs:
            if str(mr.iid) == row_key.value:
                return mr
        return None

    async def _load_members(self) -> None:
        if not self._project_members:
            self.query_one("#settings-table", SettingsTable).loading = True
            self._project_members = await gitlab.fetch_project_members()
            self.query_one("#settings-table", SettingsTable).loading = False
        self._render_settings()

    # --- Key handling ---

    def on_key(self, event: Key) -> None:
        if not self._searching:
            return
        event.prevent_default()
        if event.key == "escape":
            self._searching = False
            self.search_query = ""
        elif event.key == "enter":
            self._searching = False
        elif event.key == "backspace":
            self.search_query = self.search_query[:-1]
        elif event.character and event.character.isprintable():
            self.search_query += event.character

        if self._settings_visible:
            self._render_settings()
        else:
            self._render_table()
        self._update_filter_bar()

    # --- Actions ---

    async def action_toggle_settings(self) -> None:
        self._settings_visible = not self._settings_visible
        self.search_query = ""
        self._searching = False
        self._apply_view_visibility()
        self._update_header()
        self._update_filter_bar()
        self._update_hotkeys()

        if self._settings_visible:
            await self._load_members()
        else:
            # Leaving settings — refresh MRs only if followed set changed
            new_ids = {u.user_id for u in db.get_followed_users()}
            changed = new_ids != self._followed_ids
            self._followed_ids = new_ids
            if self._followed_ids and changed:
                self.seconds_until_refresh = REFRESH_INTERVAL
                self._schedule_refresh()

    def action_start_search(self) -> None:
        self._searching = True
        self._update_filter_bar()

    async def action_open_mr(self) -> None:
        if self._settings_visible:
            return
        mr = self._selected_mr()
        if mr:
            await gitlab.open_mr_in_browser(mr.iid)

    def action_force_refresh(self) -> None:
        if self._settings_visible:
            return
        self.seconds_until_refresh = REFRESH_INTERVAL
        self._schedule_refresh()
        self._update_header()

    def action_cursor_down(self) -> None:
        if self._settings_visible:
            self.query_one("#settings-table", SettingsTable).action_cursor_down()
        else:
            self.query_one("#mr-table", MRTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        if self._settings_visible:
            self.query_one("#settings-table", SettingsTable).action_cursor_up()
        else:
            self.query_one("#mr-table", MRTable).action_cursor_up()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if not self._settings_visible:
            return
        row_key = event.row_key
        user_id = int(row_key.value)

        # Find the member
        member = None
        for m in self._project_members:
            if m.user_id == user_id:
                member = m
                break
        if member is None:
            return

        # Toggle follow
        if user_id in self._followed_ids:
            db.remove_followed_user(user_id)
            self._followed_ids.discard(user_id)
        else:
            db.add_followed_user(user_id, member.username, member.name)
            self._followed_ids.add(user_id)

        self._render_settings()
        self._update_filter_bar()


if __name__ == "__main__":
    _preflight_check()
    TeamStatusApp().run()
