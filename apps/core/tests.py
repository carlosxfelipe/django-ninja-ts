from copy import deepcopy

from django.test import Client, TestCase
from todos import api as todos_api


class GotaParityRoutesTests(TestCase):
    def setUp(self):
        self.client = Client()
        self._original_todos = deepcopy(todos_api._TODOS)
        self._original_next_id = todos_api._NEXT_ID

    def tearDown(self):
        todos_api._TODOS[:] = self._original_todos
        todos_api._NEXT_ID = self._original_next_id

    def test_root_redirects_to_docs(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/api/docs")

    def test_docs_uses_fastify_theme(self):
        response = self.client.get("/api/docs")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('"theme": "fastify"', html)
        self.assertIn('"layout": "classic"', html)

    def test_health_endpoint(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertIsInstance(data["uptimeSeconds"], int)
        self.assertGreaterEqual(data["uptimeSeconds"], 0)
        self.assertIsInstance(data["pythonVersion"], str)

    def test_ping_endpoint(self):
        response = self.client.get("/api/ping")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "text/plain; charset=utf-8")
        self.assertEqual(response.content.decode("utf-8"), "pong")

    def test_list_todos_and_filters(self):
        response = self.client.get("/api/todos")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {
                    "id": 1,
                    "title": "Update README badges",
                    "priority": "low",
                    "done": True,
                },
                {
                    "id": 2,
                    "title": "Review pull requests",
                    "priority": "normal",
                    "done": False,
                },
                {
                    "id": 3,
                    "title": "Deploy release v2.0",
                    "priority": "high",
                    "done": False,
                },
            ],
        )

        done_resp = self.client.get("/api/todos?done=true")
        self.assertEqual(done_resp.status_code, 200)
        self.assertEqual([t["id"] for t in done_resp.json()], [1])

        priority_resp = self.client.get("/api/todos?priority=high")
        self.assertEqual(priority_resp.status_code, 200)
        self.assertEqual([t["id"] for t in priority_resp.json()], [3])

        invalid_resp = self.client.get("/api/todos?priority=urgent")
        self.assertEqual(invalid_resp.status_code, 422)
        self.assertEqual(
            invalid_resp.json()["detail"][0]["msg"],
            "Priority must be low, normal, or high",
        )

    def test_get_todo_by_id(self):
        response = self.client.get("/api/todos/1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], 1)

        not_found = self.client.get("/api/todos/999")
        self.assertEqual(not_found.status_code, 404)
        self.assertEqual(not_found.json(), {"detail": "Todo not found"})

        invalid_id = self.client.get("/api/todos/0")
        self.assertEqual(invalid_id.status_code, 422)
        self.assertEqual(
            invalid_id.json()["detail"][0]["msg"],
            "Todo ID must be a positive integer",
        )

    def test_create_todo_and_validation(self):
        created = self.client.post(
            "/api/todos",
            data={"title": "Write tests"},
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(
            created.json(),
            {
                "id": 4,
                "title": "Write tests",
                "priority": "normal",
                "done": False,
            },
        )

        missing_title = self.client.post(
            "/api/todos",
            data={},
            content_type="application/json",
        )
        self.assertEqual(missing_title.status_code, 422)
        self.assertEqual(
            missing_title.json()["detail"][0]["msg"],
            "Title is required",
        )

        short_title = self.client.post(
            "/api/todos",
            data={"title": "ab"},
            content_type="application/json",
        )
        self.assertEqual(short_title.status_code, 422)
        self.assertEqual(
            short_title.json()["detail"][0]["msg"],
            "Title must be at least 3 characters",
        )

        bad_priority = self.client.post(
            "/api/todos",
            data={"title": "Valid title", "priority": "urgent"},
            content_type="application/json",
        )
        self.assertEqual(bad_priority.status_code, 422)
        self.assertEqual(
            bad_priority.json()["detail"][0]["msg"],
            "Priority must be low, normal, or high",
        )

    def test_put_todo(self):
        updated = self.client.put(
            "/api/todos/2",
            data={"title": "Reviewed PRs", "priority": "high", "done": True},
            content_type="application/json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(
            updated.json(),
            {
                "id": 2,
                "title": "Reviewed PRs",
                "priority": "high",
                "done": True,
            },
        )

        missing_priority = self.client.put(
            "/api/todos/2",
            data={"title": "Reviewed PRs"},
            content_type="application/json",
        )
        self.assertEqual(missing_priority.status_code, 422)
        self.assertEqual(
            missing_priority.json()["detail"][0]["msg"],
            "Priority is required",
        )

        not_found = self.client.put(
            "/api/todos/999",
            data={"title": "Reviewed PRs", "priority": "normal", "done": False},
            content_type="application/json",
        )
        self.assertEqual(not_found.status_code, 404)
        self.assertEqual(not_found.json(), {"detail": "Todo not found"})

    def test_patch_todo(self):
        patched = self.client.patch(
            "/api/todos/3",
            data={"done": True},
            content_type="application/json",
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(
            patched.json(),
            {
                "id": 3,
                "title": "Deploy release v2.0",
                "priority": "high",
                "done": True,
            },
        )

        short_title = self.client.patch(
            "/api/todos/3",
            data={"title": "ab"},
            content_type="application/json",
        )
        self.assertEqual(short_title.status_code, 422)
        self.assertEqual(
            short_title.json()["detail"][0]["msg"],
            "Title must be at least 3 characters",
        )

        not_found = self.client.patch(
            "/api/todos/999",
            data={"done": True},
            content_type="application/json",
        )
        self.assertEqual(not_found.status_code, 404)
        self.assertEqual(not_found.json(), {"detail": "Todo not found"})

    def test_delete_todo(self):
        deleted = self.client.delete("/api/todos/1")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(deleted.content, b"")

        not_found = self.client.delete("/api/todos/1")
        self.assertEqual(not_found.status_code, 404)
        self.assertEqual(not_found.json(), {"detail": "Todo not found"})
