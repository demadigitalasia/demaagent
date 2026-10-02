import http.cookiejar
import json
import os
import unittest
import urllib.error
import urllib.request


BASE = os.environ.get("MC_TEST_BASE", "http://127.0.0.1:9120")
USER = os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "")
PASSWORD = os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "")


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, method, path, body=None, headers=None, auto_csrf=True):
        headers = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
        if auto_csrf and method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            csrf = next((cookie.value for cookie in self.jar if cookie.name == "mc_csrf"), "")
            if csrf:
                headers.setdefault("X-CSRF-Token", csrf)
        request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read())
            except Exception:
                return error.code, {}

    def login(self):
        status, body = self.request("POST", "/auth/login", {"username": USER, "password": PASSWORD})
        for cookie in self.jar:
            if cookie.name in {"mc_session", "mc_csrf"}:
                cookie.secure = False
        return status, body


class RoutingApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not USER or not PASSWORD:
            raise unittest.SkipTest("owner auth env tidak tersedia")

    def test_routing_requires_owner_auth(self):
        status, body = Client().request("GET", "/api/routing")
        self.assertEqual(status, 401)
        self.assertEqual(body.get("error"), "unauthorized")

    def test_workflow_group_contract_read_only_and_no_secret(self):
        client = Client()
        status, _ = client.login()
        self.assertEqual(status, 200)
        status, body = client.request("GET", "/api/routing/workflow-groups")
        self.assertEqual(status, 200, body)
        self.assertEqual(body.get("status"), "ok")
        self.assertEqual(body.get("catalog_status"), "configured_read_only_catalog")
        self.assertFalse(body.get("autonomous_allowed"))
        self.assertEqual(body.get("provisioning"), "none")
        self.assertEqual(len(body.get("contracts") or []), 11)
        encoded = json.dumps(body, ensure_ascii=False).lower()
        for marker in ("api_key", "access_token", "password", "client_secret", "/opt/data/", "/home/"):
            self.assertNotIn(marker, encoded)
        for contract in body["contracts"]:
            self.assertTrue(contract.get("owner_agent_id"))
            self.assertTrue(contract.get("workflow_id"))
            self.assertTrue(contract.get("approval_boundary"))

        status, routing = client.request("GET", "/api/routing")
        self.assertEqual(status, 200, routing)
        self.assertEqual(routing["workflow_group_catalog"]["status"], "ok")
        self.assertEqual(
            routing["workflow_group_catalog"]["contracts"],
            body["contracts"],
        )

    def test_routing_read_preview_and_runtime_separation(self):
        client = Client()
        status, _ = client.login()
        self.assertEqual(status, 200)
        status, body = client.request("GET", "/api/routing")
        self.assertEqual(status, 200, body)
        with open("/opt/data/mission-control/agents.json", encoding="utf-8") as handle:
            roster_count = len(json.load(handle))
        self.assertEqual(len(body["agents"]), roster_count)
        self.assertEqual(body["runtime"]["runtime_ready"], False)
        self.assertEqual(body["runtime"]["live"], False)
        encoded = json.dumps(body).lower()
        for marker in ("api_key", "access_token", "password", "client_secret"):
            self.assertNotIn(marker, encoded)
        status, preview = client.request("POST", "/api/routing/preview", {
            "task_text": "Fix the backend API and add tests",
            "capability_hints": ["engineering-specialist"],
        })
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview["workflow"]["id"], "coding-pipeline")
        self.assertFalse(preview["execution"]["launched"])
        self.assertTrue(any(stage["id"] == "executor" for stage in preview["stages"]))

    def test_routing_mutations_require_csrf_and_validate_payload(self):
        client = Client()
        status, _ = client.login()
        self.assertEqual(status, 200)
        status, body = client.request(
            "PUT", "/api/routing", {"config": {"version": 1}},
            headers={"X-CSRF-Token": ""}, auto_csrf=False,
        )
        self.assertEqual(status, 403)
        self.assertEqual(body.get("error"), "csrf_failed")
        status, current = client.request("GET", "/api/routing")
        self.assertEqual(status, 200)
        bad_secret = json.loads(json.dumps(current["config"]))
        bad_secret["notes"] = "api_key=blocked"
        status, _ = client.request("PUT", "/api/routing", {"config": bad_secret})
        self.assertEqual(status, 400)
        status, _ = client.request("PATCH", "/api/routing/agents/unknown-agent", {"priority": 1})
        self.assertEqual(status, 404)
    def test_workflow_crud_and_agent_metadata_readback(self):
        client = Client()
        status, _ = client.login()
        self.assertEqual(status, 200)
        status, current = client.request("GET", "/api/routing")
        self.assertEqual(status, 200)
        workflow = {
            "id": "routing-test",
            "name": "Routing test",
            "keywords": ["routing-test"],
            "capabilities": ["assistant"],
            "priority": 1,
            "approval_gates": ["approval_required"],
            "stages": [{
                "id": "assist",
                "name": "Assist",
                "capabilities": ["assistant"],
                "approval": "approval_required",
                "depends_on": [],
            }],
        }
        try:
            status, _ = client.request("POST", "/api/routing/workflows", {"workflow": workflow})
            self.assertEqual(status, 200)
            status, _ = client.request("PATCH", "/api/routing/workflows/routing-test", {"name": "Routing test updated"})
            self.assertEqual(status, 200)
            status, current = client.request("GET", "/api/routing")
            self.assertEqual(status, 200)
            self.assertEqual(next(row for row in current["config"]["workflows"] if row["id"] == "routing-test")["name"], "Routing test updated")
            original_priority = next(row for row in current["agents"] if row["id"] == "backend-data")["routing"]["priority"]
            status, _ = client.request("PUT", "/api/routing", {
                "config": current["config"],
                "agent_metadata": {"backend-data": {"priority": original_priority + 1}},
            })
            self.assertEqual(status, 200)
            status, updated = client.request("GET", "/api/routing")
            self.assertEqual(status, 200)
            self.assertEqual(next(row for row in updated["agents"] if row["id"] == "backend-data")["routing"]["priority"], original_priority + 1)
        finally:
            client.request("DELETE", "/api/routing/workflows/routing-test")
            status, current = client.request("GET", "/api/routing")
            if status == 200:
                client.request("PUT", "/api/routing", {
                    "config": current["config"],
                    "agent_metadata": {"backend-data": {"priority": 80}},
                })


if __name__ == "__main__":
    unittest.main(verbosity=2)
