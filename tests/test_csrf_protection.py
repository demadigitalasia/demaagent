#!/usr/bin/env python3
"""Focused CSRF protection tests for the Mission Control owner plane."""
import http.cookiejar
import importlib.util
import json
import os
from pathlib import Path
import time
import unittest
import urllib.error
import urllib.request

BASE = os.environ.get("MC_TEST_BASE", "http://127.0.0.1:9120")
USER = os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "")
PASS = os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "")
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.last_headers = {}
        self.last_set_cookies = []

    def cookie(self, name):
        return next((c.value for c in self.jar if c.name == name), None)

    def strip_secure_for_local_http(self):
        for cookie in self.jar:
            if cookie.name in {"mc_session", "mc_csrf"}:
                cookie.secure = False

    def req(self, method, path, body=None, headers=None, raw=False):
        method = method.upper()
        request_headers = dict(headers or {})
        if body is not None:
            data = json.dumps(body).encode()
            request_headers.setdefault("Content-Type", "application/json")
        else:
            data = None
        request = urllib.request.Request(
            BASE + path, data=data, headers=request_headers, method=method
        )
        self.last_headers = {}
        self.last_set_cookies = []
        try:
            with self.op.open(request, timeout=30) as response:
                self.last_headers = dict(response.headers.items())
                self.last_set_cookies = list(response.headers.get_all("Set-Cookie") or [])
                payload = response.read()
                return response.status, payload if raw else json.loads(payload)
        except urllib.error.HTTPError as error:
            self.last_headers = dict(error.headers.items())
            self.last_set_cookies = list(error.headers.get_all("Set-Cookie") or [])
            payload = error.read()
            try:
                return error.code, payload if raw else json.loads(payload)
            except Exception:
                return error.code, {}

    def login(self):
        status, body = self.req(
            "POST", "/auth/login", {"username": USER, "password": PASS}
        )
        self.strip_secure_for_local_http()
        return status, body


def cookie_header(set_cookies, name):
    prefix = name + "="
    return next((value for value in set_cookies if value.startswith(prefix)), "")


class TestCsrfProtection(unittest.TestCase):
    def setUp(self):
        if not USER or not PASS:
            self.fail("auth environment is not configured")
        self.client = Client()
        status, body = self.client.login()
        self.assertEqual(status, 200, body)
        self.csrf = self.client.cookie("mc_csrf")
        self.assertTrue(self.csrf)

    def test_login_sets_distinct_secure_cookie_pair_with_expected_flags(self):
        client = Client()
        status, body = client.login()
        self.assertEqual(status, 200, body)
        self.assertEqual(body.get("status"), "ok")
        session_cookie = cookie_header(client.last_set_cookies, "mc_session")
        csrf_cookie = cookie_header(client.last_set_cookies, "mc_csrf")
        self.assertTrue(session_cookie)
        self.assertTrue(csrf_cookie)
        self.assertIn("Secure", session_cookie)
        self.assertIn("HttpOnly", session_cookie)
        self.assertIn("SameSite=lax", session_cookie)
        self.assertIn("Path=/", session_cookie)
        self.assertIn("Secure", csrf_cookie)
        self.assertNotIn("HttpOnly", csrf_cookie)
        self.assertIn("SameSite=lax", csrf_cookie)
        self.assertIn("Path=/", csrf_cookie)
        self.assertNotEqual(client.cookie("mc_session"), client.cookie("mc_csrf"))
        self.assertNotIn(client.cookie("mc_csrf"), json.dumps(body))

    def test_safe_get_with_session_does_not_need_csrf_header(self):
        status, body = self.client.req("GET", "/api/overview")
        self.assertEqual(status, 200, body)
        self.assertEqual(body.get("plugin"), "mission-control")

    def test_missing_and_wrong_csrf_reject_post_patch_delete_without_mutation(self):
        persona_status, persona = self.client.req(
            "GET", "/api/agent-persona?id=hermes-lead"
        )
        self.assertEqual(persona_status, 200, persona)
        original = persona.get("persona")
        marker = "csrf-rejected-mutation-marker"

        status, body = self.client.req(
            "POST", "/api/agents", {"name": "csrf-rejected", "model": "invalid"}
        )
        self.assertEqual(status, 403, body)
        self.assertEqual(body.get("error"), "csrf_failed")

        status, body = self.client.req(
            "PATCH",
            "/api/agents/hermes-lead",
            {"persona": marker},
            headers={"X-CSRF-Token": "wrong-token"},
        )
        self.assertEqual(status, 403, body)
        self.assertEqual(body.get("error"), "csrf_failed")

        status, body = self.client.req(
            "DELETE",
            "/api/agents/does-not-exist",
            headers={"X-CSRF-Token": "wrong-token"},
        )
        self.assertEqual(status, 403, body)
        self.assertEqual(body.get("error"), "csrf_failed")

        read_status, readback = self.client.req(
            "GET", "/api/agent-persona?id=hermes-lead"
        )
        self.assertEqual(read_status, 200, readback)
        self.assertEqual(readback.get("persona"), original)

    def test_correct_csrf_allows_owner_mutation_and_readback(self):
        status, persona = self.client.req("GET", "/api/agent-persona?id=hermes-lead")
        self.assertEqual(status, 200, persona)
        original = persona.get("persona")
        marker = "csrf-accepted-mutation-marker"
        try:
            status, body = self.client.req(
                "PATCH",
                "/api/agents/hermes-lead",
                {"persona": marker},
                headers={"X-CSRF-Token": self.csrf},
            )
            self.assertEqual(status, 200, body)
            status, readback = self.client.req(
                "GET", "/api/agent-persona?id=hermes-lead"
            )
            self.assertEqual(status, 200, readback)
            self.assertEqual(readback.get("persona"), marker)
        finally:
            status, body = self.client.req(
                "PATCH",
                "/api/agents/hermes-lead",
                {"persona": original},
                headers={"X-CSRF-Token": self.csrf},
            )
            self.assertEqual(status, 200, body)

    def test_logout_requires_csrf_and_success_revokes_and_clears_both_cookies(self):
        for headers in ({}, {"X-CSRF-Token": "wrong-token"}):
            client = Client()
            status, body = client.login()
            self.assertEqual(status, 200, body)
            client.strip_secure_for_local_http()
            status, body = client.req("POST", "/auth/logout", headers=headers)
            self.assertEqual(status, 403, body)
            self.assertEqual(body.get("error"), "csrf_failed")
            session_status, _ = client.req("GET", "/auth/session")
            self.assertEqual(session_status, 200)

        client = Client()
        status, body = client.login()
        self.assertEqual(status, 200, body)
        client.strip_secure_for_local_http()
        csrf = client.cookie("mc_csrf")
        status, body = client.req(
            "POST", "/auth/logout", headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body.get("status"), "ok")
        deletion_headers = "\n".join(client.last_set_cookies)
        session_status, _ = client.req("GET", "/auth/session")
        self.assertEqual(session_status, 401)
        self.assertIn("mc_session=", deletion_headers)
        self.assertIn("mc_csrf=", deletion_headers)
        self.assertIn("Max-Age=0", deletion_headers)

    def test_stale_csrf_token_from_prior_login_session_is_rejected(self):
        old_csrf = self.csrf
        status, body = self.client.login()
        self.assertEqual(status, 200, body)
        new_csrf = self.client.cookie("mc_csrf")
        self.assertTrue(new_csrf)
        self.assertNotEqual(old_csrf, new_csrf)
        status, body = self.client.req(
            "PATCH",
            "/api/agents/hermes-lead",
            {"persona": "stale-token-must-fail"},
            headers={"X-CSRF-Token": old_csrf},
        )
        self.assertEqual(status, 403, body)
        self.assertEqual(body.get("error"), "csrf_failed")

    def test_runtime_bearer_route_is_independent_of_cookie_csrf(self):
        status, body = self.client.req(
            "POST",
            "/api/obsidian/runtime-tokens",
            {"agent_id": "agent-engineer", "ttl_s": 300},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(status, 200, body)
        runtime_token = body.get("token")
        self.assertTrue(runtime_token)
        runtime_client = Client()
        status, workspace = runtime_client.req(
            "GET",
            "/runtime-api/obsidian/workspace",
            headers={"Authorization": f"Bearer {runtime_token}"},
        )
        self.assertEqual(status, 200, workspace)
        self.assertEqual(
            workspace.get("runtime_identity", {}).get("agent_id"), "agent-engineer"
        )

    def test_csrf_never_appears_in_json_logs_or_unsafe_source_locations(self):
        csrf = self.csrf
        for method, path, body in (
            ("GET", "/auth/session", None),
            ("GET", "/api/overview", None),
        ):
            status, payload = self.client.req(method, path, body)
            self.assertEqual(status, 200, payload)
            self.assertNotIn(csrf, json.dumps(payload, ensure_ascii=False))

        log_path = Path("/opt/data/logs/mission-control.log")
        if log_path.exists():
            self.assertNotIn(csrf, log_path.read_text(errors="replace"))

        api_source = Path("/opt/data/mission-control/frontend/src/api.js").read_text()
        self.assertNotIn("localStorage", api_source)
        self.assertNotIn("sessionStorage", api_source)
        self.assertNotRegex(api_source, r"[?&][^\n]*csrf")
        self.assertNotRegex(api_source, r"console\.log[^\n]*csrf")

    def test_anonymous_health_and_login_remain_functional(self):
        anonymous = Client()
        status, body = anonymous.req("GET", "/healthz")
        self.assertEqual(status, 200, body)
        self.assertEqual(body.get("status"), "ok")
        status, body = anonymous.login()
        self.assertEqual(status, 200, body)
        self.assertTrue(anonymous.cookie("mc_session"))
        self.assertTrue(anonymous.cookie("mc_csrf"))


class TestCsrfSessionPruning(unittest.TestCase):
    def test_pruning_removes_expired_csrf_binding(self):
        path = Path("/opt/data/mission-control/server.py")
        spec = importlib.util.spec_from_file_location("mission_control_csrf_server", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(
            hasattr(module, "_session_csrf_tokens"),
            "server must keep a session-bound CSRF mapping",
        )
        with module._lock:
            module._sessions["expired-session"] = time.time() - 1
            module._session_csrf_tokens["expired-session"] = "expired-csrf"
            module._prune_sessions()
            self.assertNotIn("expired-session", module._sessions)
            self.assertNotIn("expired-session", module._session_csrf_tokens)


if __name__ == "__main__":
    unittest.main(verbosity=2)
