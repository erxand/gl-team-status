"""Unit tests for gl-team-status components."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from models import MR, ApprovalInfo, TeamMember, ThreadCount
from widgets import approval_text, thread_text, pipeline_status_text, reviewer_text, fuzzy_match


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

class TestModels(unittest.TestCase):
    def test_thread_count_human_property(self):
        t = ThreadCount(total=5, ai=2)
        self.assertEqual(t.human, 3)

    def test_thread_count_all_ai(self):
        t = ThreadCount(total=3, ai=3)
        self.assertEqual(t.human, 0)

    def test_thread_count_zero(self):
        t = ThreadCount()
        self.assertEqual(t.total, 0)
        self.assertEqual(t.ai, 0)
        self.assertEqual(t.human, 0)

    def test_mr_is_draft(self):
        mr = MR(iid=1, title="Draft: wip", author_username="u", web_url="")
        self.assertTrue(mr.is_draft)

    def test_mr_not_draft(self):
        mr = MR(iid=1, title="Fix bug", author_username="u", web_url="")
        self.assertFalse(mr.is_draft)


# ---------------------------------------------------------------------------
# widgets helpers
# ---------------------------------------------------------------------------

class TestWidgetHelpers(unittest.TestCase):
    def test_approval_text_met(self):
        mr = MR(iid=1, title="t", author_username="u", web_url="",
                approvals=ApprovalInfo(approved_count=2, required_count=2))
        t = approval_text(mr)
        self.assertEqual(t.plain, "2/2")
        self.assertIn("green", str(t.style))

    def test_approval_text_partial(self):
        mr = MR(iid=1, title="t", author_username="u", web_url="",
                approvals=ApprovalInfo(approved_count=1, required_count=2))
        t = approval_text(mr)
        self.assertEqual(t.plain, "1/2")

    def test_approval_text_none(self):
        mr = MR(iid=1, title="t", author_username="u", web_url="")
        t = approval_text(mr)
        self.assertEqual(t.plain, "—")

    def test_approval_text_zero_required(self):
        mr = MR(iid=1, title="t", author_username="u", web_url="",
                approvals=ApprovalInfo(approved_count=1, required_count=0))
        t = approval_text(mr)
        self.assertEqual(t.plain, "1/0")

    def test_thread_text_with_ai(self):
        mr = MR(iid=1, title="t", author_username="u", web_url="",
                threads=ThreadCount(total=4, ai=1))
        t = thread_text(mr)
        self.assertEqual(t.plain, "4 (1 AI)")

    def test_thread_text_no_ai(self):
        mr = MR(iid=1, title="t", author_username="u", web_url="",
                threads=ThreadCount(total=3, ai=0))
        t = thread_text(mr)
        self.assertEqual(t.plain, "3")

    def test_thread_text_zero(self):
        mr = MR(iid=1, title="t", author_username="u", web_url="",
                threads=ThreadCount(total=0, ai=0))
        t = thread_text(mr)
        self.assertEqual(t.plain, "0")
        self.assertIn("green", str(t.style))

    def test_thread_text_none(self):
        mr = MR(iid=1, title="t", author_username="u", web_url="")
        t = thread_text(mr)
        self.assertEqual(t.plain, "—")

    def test_pipeline_status_success(self):
        t = pipeline_status_text("success")
        self.assertIn("✓", t.plain)
        self.assertIn("success", t.plain)

    def test_pipeline_status_failed(self):
        t = pipeline_status_text("failed")
        self.assertIn("✗", t.plain)

    def test_pipeline_status_none(self):
        t = pipeline_status_text(None)
        self.assertEqual(t.plain, "—")

    def test_pipeline_status_unknown(self):
        t = pipeline_status_text("something_weird")
        self.assertIn("?", t.plain)

    def test_fuzzy_match_hit(self):
        score, indices = fuzzy_match("Fix authentication bug", "auth")
        self.assertIsNotNone(score)
        self.assertTrue(len(indices) > 0)

    def test_fuzzy_match_miss(self):
        score, indices = fuzzy_match("Fix authentication bug", "zzzzz")
        self.assertIsNone(score)
        self.assertEqual(indices, [])

    def test_reviewer_text_assigned(self):
        mr = MR(iid=1, title="t", author_username="u", web_url="", reviewing=True)
        t = reviewer_text(mr)
        self.assertEqual(t.plain, "✓")

    def test_reviewer_text_not_assigned(self):
        mr = MR(iid=1, title="t", author_username="u", web_url="", reviewing=False)
        t = reviewer_text(mr)
        self.assertEqual(t.plain, "")

    def test_fuzzy_match_case_insensitive(self):
        score, _ = fuzzy_match("FIX AUTH", "fix")
        self.assertIsNotNone(score)


# ---------------------------------------------------------------------------
# db
# ---------------------------------------------------------------------------

class TestDB(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        # Patch the DB path
        import db as db_mod
        self._orig_path = db_mod._DB_PATH
        db_mod._DB_PATH = type(db_mod._DB_PATH)(self._tmp.name)
        self.db = db_mod
        self.db.init_db()

    def tearDown(self):
        self.db._DB_PATH = self._orig_path
        os.unlink(self._tmp.name)

    def test_init_creates_table(self):
        conn = sqlite3.connect(self._tmp.name)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        self.assertIn(("followed_users",), tables)

    def test_add_and_get(self):
        self.db.add_followed_user(42, "alice", "Alice A")
        users = self.db.get_followed_users()
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0].user_id, 42)
        self.assertEqual(users[0].username, "alice")

    def test_remove(self):
        self.db.add_followed_user(42, "alice", "Alice A")
        self.db.remove_followed_user(42)
        self.assertEqual(len(self.db.get_followed_users()), 0)

    def test_is_following(self):
        self.assertFalse(self.db.is_following(42))
        self.db.add_followed_user(42, "alice", "Alice A")
        self.assertTrue(self.db.is_following(42))

    def test_get_followed_usernames(self):
        self.db.add_followed_user(1, "alice", "Alice")
        self.db.add_followed_user(2, "bob", "Bob")
        names = self.db.get_followed_usernames()
        self.assertEqual(names, {"alice", "bob"})

    def test_add_duplicate_replaces(self):
        self.db.add_followed_user(42, "alice", "Alice A")
        self.db.add_followed_user(42, "alice", "Alice Updated")
        users = self.db.get_followed_users()
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0].name, "Alice Updated")

    def test_remove_nonexistent_is_noop(self):
        self.db.remove_followed_user(999)
        self.assertEqual(len(self.db.get_followed_users()), 0)

    def test_init_db_idempotent(self):
        self.db.init_db()
        self.db.init_db()
        self.db.add_followed_user(1, "a", "A")
        self.assertEqual(len(self.db.get_followed_users()), 1)


# ---------------------------------------------------------------------------
# gitlab (mocked)
# ---------------------------------------------------------------------------

class TestGitlabParsing(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_approvals_parses(self):
        import gitlab as gl
        mock_response = json.dumps({
            "approved_by": [{"user": {"id": 1}}, {"user": {"id": 2}}],
            "approvals_required": 2,
        })
        with patch.object(gl, "_run", new_callable=AsyncMock, return_value=mock_response):
            result = await gl.fetch_approvals(123)
        self.assertEqual(result.approved_count, 2)
        self.assertEqual(result.required_count, 2)

    async def test_fetch_approvals_empty(self):
        import gitlab as gl
        with patch.object(gl, "_run", new_callable=AsyncMock, return_value=""):
            result = await gl.fetch_approvals(123)
        self.assertEqual(result.approved_count, 0)
        self.assertEqual(result.required_count, 0)

    async def test_fetch_approvals_bad_json(self):
        import gitlab as gl
        with patch.object(gl, "_run", new_callable=AsyncMock, return_value="not json"):
            result = await gl.fetch_approvals(123)
        self.assertEqual(result.approved_count, 0)

    async def test_fetch_threads_counts_correctly(self):
        import gitlab as gl
        discussions = [
            # Unresolved human thread
            {"notes": [{"resolvable": True, "resolved": False, "author": {"bot": False}}]},
            # Unresolved AI thread
            {"notes": [{"resolvable": True, "resolved": False, "author": {"bot": True}}]},
            # Resolved thread (should be ignored)
            {"notes": [{"resolvable": True, "resolved": True, "author": {"bot": False}}]},
            # Non-resolvable (e.g. system note, should be ignored)
            {"notes": [{"resolvable": False, "author": {"bot": False}}]},
        ]
        with patch.object(gl, "_run", new_callable=AsyncMock, return_value=json.dumps(discussions)):
            result = await gl.fetch_threads(123)
        self.assertEqual(result.total, 2)
        self.assertEqual(result.ai, 1)
        self.assertEqual(result.human, 1)

    async def test_fetch_threads_empty(self):
        import gitlab as gl
        with patch.object(gl, "_run", new_callable=AsyncMock, return_value=""):
            result = await gl.fetch_threads(123)
        self.assertEqual(result.total, 0)

    async def test_fetch_threads_all_resolved(self):
        import gitlab as gl
        discussions = [
            {"notes": [{"resolvable": True, "resolved": True, "author": {"bot": False}}]},
        ]
        with patch.object(gl, "_run", new_callable=AsyncMock, return_value=json.dumps(discussions)):
            result = await gl.fetch_threads(123)
        self.assertEqual(result.total, 0)

    async def test_fetch_pipeline_status(self):
        import gitlab as gl
        pipelines = [{"status": "success"}, {"status": "failed"}]
        with patch.object(gl, "_run", new_callable=AsyncMock, return_value=json.dumps(pipelines)):
            result = await gl.fetch_pipeline_status(123)
        self.assertEqual(result, "success")  # takes first (latest)

    async def test_fetch_pipeline_status_empty(self):
        import gitlab as gl
        with patch.object(gl, "_run", new_callable=AsyncMock, return_value=""):
            result = await gl.fetch_pipeline_status(123)
        self.assertIsNone(result)

    async def test_fetch_pipeline_status_empty_list(self):
        import gitlab as gl
        with patch.object(gl, "_run", new_callable=AsyncMock, return_value="[]"):
            result = await gl.fetch_pipeline_status(123)
        self.assertIsNone(result)

    async def test_fetch_open_mrs_filters(self):
        import gitlab as gl
        data = [
            {"iid": 1, "title": "Good MR", "state": "opened", "draft": False,
             "author": {"username": "alice"}, "web_url": "http://x/1"},
            {"iid": 2, "title": "Draft: WIP", "state": "opened", "draft": True,
             "author": {"username": "alice"}, "web_url": "http://x/2"},
            {"iid": 3, "title": "Not followed", "state": "opened", "draft": False,
             "author": {"username": "charlie"}, "web_url": "http://x/3"},
            {"iid": 4, "title": "Closed", "state": "closed", "draft": False,
             "author": {"username": "alice"}, "web_url": "http://x/4"},
            {"iid": 5, "title": "Also good", "state": "opened", "draft": False,
             "author": {"username": "bob"}, "web_url": "http://x/5"},
        ]
        with patch.object(gl, "_run", new_callable=AsyncMock, return_value=json.dumps(data)):
            mrs = await gl.fetch_open_mrs({"alice", "bob"})
        iids = [mr.iid for mr in mrs]
        self.assertEqual(iids, [1, 5])

    async def test_fetch_open_mrs_empty(self):
        import gitlab as gl
        with patch.object(gl, "_run", new_callable=AsyncMock, return_value=""):
            mrs = await gl.fetch_open_mrs({"alice"})
        self.assertEqual(mrs, [])

    async def test_fetch_open_mrs_includes_reviewer_mrs(self):
        """MRs where current user is a reviewer should be included even if author not followed."""
        import gitlab as gl
        data = [
            {"iid": 1, "title": "Team MR", "state": "opened", "draft": False,
             "author": {"username": "alice"}, "web_url": "http://x/1",
             "reviewers": []},
            {"iid": 2, "title": "Review requested", "state": "opened", "draft": False,
             "author": {"username": "charlie"}, "web_url": "http://x/2",
             "reviewers": [{"id": 99}]},
            {"iid": 3, "title": "Not mine", "state": "opened", "draft": False,
             "author": {"username": "charlie"}, "web_url": "http://x/3",
             "reviewers": [{"id": 50}]},
        ]
        with patch.object(gl, "_run", new_callable=AsyncMock, return_value=json.dumps(data)):
            mrs = await gl.fetch_open_mrs({"alice"}, current_user_id=99)
        iids = [mr.iid for mr in mrs]
        self.assertIn(1, iids)   # followed author
        self.assertIn(2, iids)   # current user is reviewer
        self.assertNotIn(3, iids)  # neither followed nor reviewing
        # Check reviewing flag
        mr2 = next(mr for mr in mrs if mr.iid == 2)
        self.assertTrue(mr2.reviewing)
        mr1 = next(mr for mr in mrs if mr.iid == 1)
        self.assertFalse(mr1.reviewing)

    async def test_fetch_current_user_id(self):
        import gitlab as gl
        with patch.object(gl, "_run", new_callable=AsyncMock, return_value='{"id": 42, "username": "me"}'):
            uid = await gl.fetch_current_user_id()
        self.assertEqual(uid, 42)

    async def test_fetch_current_user_id_empty(self):
        import gitlab as gl
        with patch.object(gl, "_run", new_callable=AsyncMock, return_value=""):
            uid = await gl.fetch_current_user_id()
        self.assertIsNone(uid)

    async def test_assign_reviewer_success(self):
        import gitlab as gl
        call_count = 0
        async def mock_run(cmd):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # GET existing MR data
                return json.dumps({"reviewers": [{"id": 10}]})
            else:
                # PUT response
                return json.dumps({"iid": 123})
        with patch.object(gl, "_run", new_callable=AsyncMock, side_effect=mock_run):
            ok = await gl.assign_reviewer(123, 42)
        self.assertTrue(ok)

    async def test_assign_reviewer_already_assigned(self):
        import gitlab as gl
        async def mock_run(cmd):
            return json.dumps({"reviewers": [{"id": 42}]})
        with patch.object(gl, "_run", new_callable=AsyncMock, side_effect=mock_run):
            ok = await gl.assign_reviewer(123, 42)
        self.assertTrue(ok)

    async def test_fetch_project_members_handles_missing_fields(self):
        import gitlab as gl
        data = [
            {"id": 1, "username": "alice", "name": "Alice"},
            {"id": 2},  # missing username — should be skipped
            {"id": 3, "username": "bob", "name": "Bob"},
        ]

        async def mock_paginated(url):
            return data

        with patch.object(gl, "_fetch_paginated", new_callable=AsyncMock, side_effect=mock_paginated):
            with patch.object(gl, "_fetch_group_path", new_callable=AsyncMock, return_value=None):
                members = await gl.fetch_project_members()
        usernames = [m.username for m in members]
        self.assertIn("alice", usernames)
        self.assertIn("bob", usernames)
        self.assertEqual(len(members), 2)  # the one missing username is skipped


if __name__ == "__main__":
    unittest.main()
