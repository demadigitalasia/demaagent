#!/usr/bin/env python3
"""Unit test backend Mission Control (Fase C3) — stdlib SAJA (unittest + urllib).

Cara jalan:
    ./test_backend.py            # server harus hidup di 127.0.0.1:9120
    HERMES_DASHBOARD_BASIC_AUTH_USERNAME=... HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=... ./test_backend.py

Catatan: tes throttle (terakhir) mengunci IP 127.0.0.1 ±60 dtk — oleh karena itu
tes ini SELALU dieksekusi paling akhir.
"""
import http.cookiejar
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest
import urllib.error
import urllib.request

BASE = os.environ.get("MC_TEST_BASE", "http://127.0.0.1:9120")
USER = os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "")
PASS = os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "")


class Client:
    """Mini API client dengan cookie jar."""

    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.last_set_cookies = []

    def req(self, method, path, body=None, raw=False, headers=None):
        data = None
        request_headers = dict(headers or {})
        method = method.upper()
        if body is not None:
            data = json.dumps(body).encode()
            request_headers["Content-Type"] = "application/json"
        if method in {"POST", "PUT", "PATCH", "DELETE"} and "X-CSRF-Token" not in request_headers:
            csrf = next((c.value for c in self.jar if c.name == "mc_csrf"), None)
            if csrf:
                request_headers["X-CSRF-Token"] = csrf
        self.last_headers = {}
        self.last_set_cookies = []
        r = urllib.request.Request(BASE + path, data=data, headers=request_headers, method=method)
        try:
            with self.op.open(r, timeout=30) as resp:
                self.last_headers = dict(resp.headers.items())
                self.last_set_cookies = list(resp.headers.get_all("Set-Cookie") or [])
                payload = resp.read()
                return resp.status, (payload if raw else json.loads(payload))
        except urllib.error.HTTPError as e:
            self.last_headers = dict(e.headers.items())
            self.last_set_cookies = list(e.headers.get_all("Set-Cookie") or [])
            payload = e.read()
            try:
                return e.code, (payload if raw else json.loads(payload))
            except Exception:
                return e.code, {}

    def login(self, username=USER, password=PASS):
        st, body = self.req("POST", "/auth/login", {"username": username, "password": password})
        # urllib menghormati flag Secure -> cookie tidak dikirim lewat http lokal.
        # Untuk test lokal, lepas flag Secure (hanya pada jar test — server tetap aman).
        for c in self.jar:
            if c.name in {"mc_session", "mc_csrf"}:
                c.secure = False
        return st, body


client = None


def cleanup_created_workspace(body):
    """Trash only the workspace folder returned by this test's POST response."""
    workspace = ((body or {}).get("agent") or {}).get("drive_workspace") or {}
    folder_id = workspace.get("folder_id")
    if not folder_id:
        return
    env = {
        **os.environ,
        "HOME": "/opt/data",
        "HERMES_HOME": "/opt/data",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin") + ":/opt/data/bin",
    }
    subprocess.run(
        [
            "/opt/data/bin/gws-google", "drive", "files", "update",
            "--params", json.dumps({"fileId": folder_id}),
            "--json", json.dumps({"trashed": True}),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def setUpModule():
    global client
    if not USER or not PASS:
        raise RuntimeError("env HERMES_DASHBOARD_BASIC_AUTH_USERNAME/PASSWORD belum diset")
    client = Client()


class TestAuth(unittest.TestCase):
    def test_healthz_public(self):
        st, body = client.req("GET", "/healthz")
        self.assertEqual(st, 200)
        self.assertEqual(body.get("status"), "ok")

    def test_login_salah_401_atau_429(self):
        # 429 muncul bila throttle 60 dtk masih aktif dari run sebelumnya — keduanya valid
        st, body = client.req("POST", "/auth/login", {"username": "x", "password": "y"})
        self.assertIn(st, (401, 429))

    def test_login_benar_200_cookie_aman(self):
        st, body = client.login(USER, PASS)
        self.assertEqual(st, 200)
        self.assertEqual(body.get("status"), "ok")
        # verifikasi flag cookie dari header RESPON server (bukan state jar)
        set_cookies = "\n".join(client.last_set_cookies)
        self.assertIn("mc_session=", set_cookies)
        self.assertIn("mc_csrf=", set_cookies)
        self.assertIn("Secure", set_cookies, "header Set-Cookie wajib ber-flag Secure")
        self.assertIn("HttpOnly", set_cookies)
        self.assertIn("SameSite=lax", set_cookies)
        set_cookie = None
        for c in client.jar:
            if c.name == "mc_session":
                set_cookie = c
        self.assertIsNotNone(set_cookie, "cookie mc_session harus ada")
        self.assertGreater(len(set_cookie.value), 16, "token harus acak dan cukup panjang")

    def test_api_tanpa_cookie_401(self):
        anon = Client()
        st, body = anon.req("GET", "/api/overview")
        self.assertEqual(st, 401)

    def test_session_info(self):
        st, body = client.req("GET", "/auth/session")
        self.assertEqual(st, 200)
        self.assertGreater(body.get("expires_in_s", 0), 0)

    def test_logout(self):
        c = Client()
        c.login()
        st, body = c.req("POST", "/auth/logout")
        self.assertEqual(st, 200)
        st2, _ = c.req("GET", "/auth/session")
        self.assertEqual(st2, 401, "sesi harus dicabut setelah logout")


class TestEndpoints(unittest.TestCase):
    def setUp(self):
        if not any(c.name == "mc_session" for c in client.jar):
            st, _ = client.login()
            if st != 200:
                self.fail(f"login gagal: {st}")

    def test_overview(self):
        st, body = client.req("GET", "/api/overview")
        self.assertEqual(st, 200)
        self.assertEqual(body.get("plugin"), "mission-control")
        self.assertIn("gateway", body)
        self.assertIn("db", body)
        self.assertEqual(body["db"].get("status"), "ok")

    def test_stats_7_hari(self):
        st, body = client.req("GET", "/api/stats")
        self.assertEqual(st, 200)
        days = body["stats"]["days"]
        self.assertEqual(len(days), 7, "harus persis 7 hari")
        for d in days:
            self.assertIn("date", d)
            self.assertIn("messages", d)
            self.assertIn("sessions", d)
            self.assertIn("tool_calls", d)

    def test_tasks_shape(self):
        st, body = client.req("GET", "/api/tasks")
        self.assertEqual(st, 200)
        self.assertIn("kanban", body)
        self.assertIsInstance(body["kanban"].get("total_tasks"), int)

    def test_models_nyata(self):
        st, body = client.req("GET", "/api/models")
        self.assertEqual(st, 200)
        m = body["models"]
        self.assertIn(m["status"], ("ok", "partial"))
        self.assertGreater(m["total"], 0, "harus ada model nyata dari katalog Hermes/OpenCode")
        self.assertIn("providers", m)
        self.assertIn("sources", m)
        self.assertIn("hermes", m["sources"])
        self.assertIn("opencode", m["sources"])
        self.assertIsInstance(m.get("provider_details"), dict)

    def test_models_refresh_read_only_shape(self):
        st, body = client.req("GET", "/api/models?refresh=1")
        self.assertEqual(st, 200)
        m = body.get("models") or {}
        self.assertIn(m.get("status"), ("ok", "partial"))
        self.assertIsInstance(m.get("providers"), dict)
        self.assertIsInstance(m.get("sources"), dict)
        self.assertGreaterEqual((m.get("sources", {}).get("opencode", {}).get("model_count") or 0), 1)

    def test_models_no_secret_bearing_fields(self):
        st, body = client.req("GET", "/api/models")
        self.assertEqual(st, 200)
        encoded = json.dumps(body, ensure_ascii=False).lower()
        for marker in ("api_key", "access_token", "client_secret", "password", "extra_headers"):
            self.assertNotIn(marker, encoded, marker)

    def test_unknown_api_404_json(self):
        st, body = client.req("GET", "/api/tidak-ada")
        self.assertEqual(st, 404)
        self.assertIsInstance(body, dict, "404 harus JSON, bukan SPA fallback")
        self.assertIn("error", body)

    def test_spa_fallback(self):
        st, body = client.req("GET", "/halaman/apa/saja", raw=True)
        self.assertEqual(st, 200)
        self.assertIsInstance(body, bytes)
        self.assertIn(b"Mission Control", body)

    def test_memory_manager_read_and_auth_no_secret(self):
        anon = Client()
        st0, body0 = anon.req("GET", "/api/skill-library")
        self.assertEqual(st0, 401)
        self.assertEqual(body0.get("error"), "unauthorized")
        st, body = client.req("GET", "/api/memory/files/MEMORY.md")
        self.assertEqual(st, 200)
        self.assertEqual(body.get("status"), "ok")
        self.assertIn("content", body)
        st2, library = client.req("GET", "/api/skill-library")
        self.assertEqual(st2, 200)
        self.assertEqual(library.get("status"), "ok")
        self.assertIsInstance(library.get("skills"), list)
        self.assertGreater(library.get("count", 0), 0)
        encoded = json.dumps({"memory": body, "library": library}, ensure_ascii=False).lower()
        for marker in ("api_key:", "access_token:", "client_secret:", "password:", "authorization:"):
            self.assertNotIn(marker, encoded, marker)

    def test_memory_skill_manager_rejects_path_traversal(self):
        st, _ = client.req("GET", "/api/memory/files/..%2FUSER.md")
        self.assertIn(st, (400, 404))
        st2, _ = client.req("GET", "/api/skill-library/..%2Fescape/name")
        self.assertIn(st2, (400, 404))

    def test_documents_atau_unavailable(self):
        st, body = client.req("GET", "/api/documents")
        self.assertEqual(st, 200)
        drive = body.get("drive", {})
        sts = drive.get("status")
        if sts is None and isinstance(drive.get("stats"), dict):
            sts = drive["stats"].get("status")
        self.assertIn(sts, ("ok", "unavailable"))

    def test_obsidian_read_only_shape_and_auth(self):
        anon = Client()
        st_anon, body_anon = anon.req("GET", "/api/obsidian")
        self.assertEqual(st_anon, 401)
        self.assertEqual(body_anon.get("error"), "unauthorized")

        st, body = client.req("GET", "/api/obsidian")
        self.assertEqual(st, 200)
        self.assertIn(body.get("status"), ("ok", "unavailable"))
        self.assertIn("vault_path", body)
        self.assertNotIn("/opt/data/", json.dumps(body, ensure_ascii=False))
        self.assertIsInstance(body.get("notes"), list)
        if body.get("status") == "ok":
            self.assertIsInstance(body.get("note_count"), int)
            self.assertIsInstance(body.get("folder_count"), int)
            self.assertLessEqual(len(body["notes"]), 100)
            st2, search = client.req("GET", "/api/obsidian/notes?limit=999")
            self.assertEqual(st2, 200)
            self.assertLessEqual(len(search.get("results", [])), 50)

    def test_obsidian_graph_write_require_auth(self):
        anon = Client()
        st_graph, body_graph = anon.req("GET", "/api/obsidian/graph?path=README.md")
        self.assertEqual(st_graph, 401)
        self.assertEqual(body_graph.get("error"), "unauthorized")
        st_write, body_write = anon.req(
            "POST", "/api/obsidian/notes",
            {"path": "tests/unauthorized.md", "content": "must not write"},
        )
        self.assertEqual(st_write, 401)
        self.assertEqual(body_write.get("error"), "unauthorized")

    def test_obsidian_phase2_routes_require_auth(self):
        anon = Client()
        checks = [
            ("POST", "/api/obsidian/ingest", {
                "title": "unauthorized", "source_url": "https://example.com/u",
                "source_type": "article", "content": "must not write",
            }),
            ("GET", "/api/obsidian/inbox"),
            ("GET", "/api/obsidian/inbox/40-Inbox/LLM-Wiki/missing.md"),
            ("POST", "/api/obsidian/inbox/approve", {
                "confirm": True, "proposal_path": "40-Inbox/LLM-Wiki/missing.md",
                "target_path": "10-Wiki/concepts/Nope.md",
            }),
            ("GET", "/api/obsidian/lint"),
        ]
        for method, path, *body in checks:
            st, response = anon.req(method, path, body[0] if body else None)
            self.assertEqual(st, 401, f"{method} {path}: {response}")
            self.assertEqual(response.get("error"), "unauthorized")

    def test_agent_workspace_routes_auth_scope_and_no_secret(self):
        anon = Client()
        checks = [
            ("GET", "/api/obsidian/agent-workspaces"),
            ("GET", "/api/obsidian/agent-workspaces/hermes-lead"),
            ("GET", "/api/obsidian/agent-workspaces/hermes-lead/graph?path=README.md"),
            ("GET", "/api/obsidian/agent-workspaces/hermes-lead/notes/README.md"),
            ("POST", "/api/obsidian/agent-workspaces/hermes-lead/notes", {
                "path": "notes/unauthorized.md", "content": "must not write"
            }),
        ]
        for method, path, *body in checks:
            st, response = anon.req(method, path, body[0] if body else None)
            self.assertEqual(st, 401, f"{method} {path}: {response}")
            self.assertEqual(response.get("error"), "unauthorized")

        st, body = client.req("GET", "/api/obsidian/agent-workspaces")
        self.assertEqual(st, 200)
        self.assertEqual(body.get("status"), "ok")
        self.assertGreaterEqual(body.get("count"), 1)
        ids = {row.get("agent_id") for row in body.get("workspaces", [])}
        current_roster_ids = {
            row.get("id") for row in json.loads(Path("/opt/data/mission-control/agents.json").read_text())
        }
        self.assertTrue(ids.issubset(current_roster_ids))
        self.assertNotIn("opencode", ids)
        self.assertEqual((body.get("policy") or {}).get("scope"), "owner_control_plane")
        self.assertEqual((body.get("policy") or {}).get("runtime_identity"), "not_implemented")

        st2, detail = client.req("GET", "/api/obsidian/agent-workspaces/hermes-lead")
        self.assertEqual(st2, 200)
        self.assertEqual(detail.get("scope", {}).get("shared"), "10-Wiki")
        self.assertTrue(any(row.get("workspace_relative_path") == "README.md" for row in (detail.get("workspace", {}).get("notes") or [])))
        self.assertIn("10-Wiki/index.md", {row.get("relative_path") for row in (detail.get("shared_context") or [])})
        encoded = json.dumps(detail, ensure_ascii=False).lower()
        for marker in ("api_key:", "access_token:", "client_secret:", "password:", "/opt/data/"):
            self.assertNotIn(marker, encoded, marker)

        st3, graph = client.req("GET", "/api/obsidian/agent-workspaces/hermes-lead/graph?path=README.md&depth=1&max_notes=40&max_bytes=60000")
        self.assertEqual(st3, 200)
        self.assertLessEqual(len(graph.get("notes", [])), 40)
        graph_paths = {row.get("relative_path") for row in graph.get("notes", [])}
        self.assertTrue(all(path.startswith("30-Agents/hermes-lead/") or path.startswith("10-Wiki/") for path in graph_paths))

        st4, readme = client.req("GET", "/api/obsidian/agent-workspaces/hermes-lead/notes/README.md")
        self.assertEqual(st4, 200)
        self.assertEqual(readme.get("scope"), "private_agent_namespace")

        st5, rejected = client.req("GET", "/api/obsidian/agent-workspaces/hermes-lead/notes/30-Agents/agent-engineer/README.md")
        self.assertEqual(st5, 400)
        self.assertEqual(rejected.get("status"), "error")

        st6, open_code = client.req("GET", "/api/obsidian/agent-workspaces/opencode")
        self.assertEqual(st6, 403)
        self.assertIn("executor-only", open_code.get("error", ""))

    def test_roster_workspace_metadata_dan_no_secret(self):
        st, body = client.req("GET", "/api/agents/roster")
        self.assertEqual(st, 200)
        agents = body.get("agents") or []
        self.assertGreaterEqual(len(agents), 3)
        encoded = json.dumps(body, ensure_ascii=False).lower()
        for marker in ("access_token", "client_secret", "api_key", "password", "authorization"):
            self.assertNotIn(marker, encoded, marker)
        for agent in agents:
            workspace = agent.get("drive_workspace") or {}
            self.assertIn(workspace.get("status"), ("ready", "pending", "unavailable"))
            self.assertTrue(workspace.get("name"))
            if workspace.get("status") == "ready":
                self.assertTrue(workspace.get("folder_id"))

    def test_command_center_shape_summary_status_separation_and_no_secret(self):
        st, body = client.req("GET", "/api/agents/command-center")
        self.assertEqual(st, 200)
        self.assertEqual(body.get("status"), "ok")
        self.assertIsInstance(body.get("generated_at"), str)
        self.assertIsInstance(body.get("summary"), dict)
        agents = body.get("agents") or []
        summary = body["summary"]
        self.assertEqual(summary.get("total"), len(agents))
        self.assertEqual(summary.get("configured_active"), sum(bool(a.get("configured_active")) for a in agents))
        allowed = {"online", "running", "standby", "offline", "blocked", "unknown"}
        live_counts = summary.get("live_status") or {}
        self.assertEqual(sum(live_counts.values()), len(agents))
        for agent in agents:
            self.assertIsInstance(agent.get("configured_active"), bool)
            self.assertIn(agent.get("live_status"), allowed)
            self.assertIn("live_detail", agent)
            self.assertIn("live_sessions", agent)
            self.assertIn("model", agent)
            self.assertIn("provider", agent)
            self.assertIn("workspace", agent)
            self.assertIn(agent["workspace"].get("status"), ("ready", "pending", "unavailable"))
            self.assertIn("created_at", agent)
            self.assertIn("updated_at", agent)
            self.assertIsInstance(agent.get("generated_at"), str)
            self.assertIsInstance(agent.get("source_freshness"), dict)
        encoded = json.dumps(body, ensure_ascii=False).lower()
        for marker in ("access_token", "client_secret", "api_key", "password", "authorization"):
            self.assertNotIn(f'"{marker}"', encoded, marker)

    def test_command_center_unauthorized(self):
        anon = Client()
        st, body = anon.req("GET", "/api/agents/command-center")
        self.assertEqual(st, 401)
        self.assertEqual(body.get("error"), "unauthorized")

    def test_command_center_summary_has_explicit_empty_buckets(self):
        st, body = client.req("GET", "/api/agents/command-center")
        self.assertEqual(st, 200)
        summary = body.get("summary") or {}
        configured = summary.get("configured_status") or {}
        live = summary.get("live_status") or {}
        self.assertIn("active", configured)
        self.assertIn("inactive", configured)
        for status in ("online", "running", "standby", "offline", "blocked", "unknown"):
            self.assertIn(status, live)

    def test_agent_workspace_listing_shape(self):
        st, roster = client.req("GET", "/api/agents/roster")
        self.assertEqual(st, 200)
        agent = (roster.get("agents") or [])[0]
        st2, body = client.req("GET", f"/api/agents/{agent['id']}/workspace")
        self.assertEqual(st2, 200)
        self.assertIn("workspace", body)
        self.assertIn("files", body)
        workspace = body["workspace"]
        self.assertIn(workspace.get("status"), ("ready", "pending", "unavailable"))
        files = body["files"]
        self.assertIn(files.get("status"), ("ok", "unavailable"))
        encoded = json.dumps(body, ensure_ascii=False).lower()
        for marker in ("access_token", "client_secret", "api_key", "password", "authorization"):
            self.assertNotIn(marker, encoded, marker)


class TestCommandCenterHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")
        spec = importlib.util.spec_from_file_location("mission_control_test_plugin_api", path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_unknown_live_status_is_normalized_without_fabrication(self):
        self.assertEqual(self.module._normalize_live_status(None), "unknown")
        self.assertEqual(self.module._normalize_live_status({"status": "future-state"}), "unknown")
        self.assertEqual(self.module._normalize_live_status({"status": "online"}), "running")

    def test_empty_live_payload_keeps_sessions_unknown(self):
        item = self.module._command_center_agent(
            {"id": "x", "name": "X", "model": "", "skills": [], "persona": "", "active": False},
            {"status": "unknown", "detail": "runtime source unavailable"},
            "2026-09-30T00:00:00Z",
        )
        self.assertEqual(item["live_status"], "unknown")
        self.assertIsNone(item["live_sessions"])

    def test_persona_profile_is_whitelisted_and_secret_free(self):
        profile = json.loads(Path("/opt/data/mission-control/agents.json").read_text())[0]["persona_profile"]
        safe = self.module._safe_persona_profile({**profile, "api_key": "must-not-escape"})
        self.assertEqual(set(safe), set(self.module.PERSONA_PROFILE_FIELDS))
        encoded = json.dumps(safe, ensure_ascii=False).lower()
        self.assertNotIn("api_key", encoded)
        self.assertIsNone(self.module._safe_persona_profile({"mission": "partial"}))

class TestValidation(unittest.TestCase):
    def setUp(self):
        # kelas ini bisa jalan tanpa TestAuth mendahului (urutan alfabetis unittest)
        if not any(c.name == "mc_session" for c in client.jar):
            st, _ = client.login()
            if st != 200:
                self.fail(f"login gagal: {st}")

    def test_create_title_kosong_400(self):
        st, body = client.req("POST", "/api/tasks/create", {"title": "  "})
        self.assertEqual(st, 400, "title kosong harus 400 — " + str(body))

    def test_create_priority_invalid_400(self):
        st, body = client.req("POST", "/api/tasks/create", {"title": "T", "priority": 9})
        self.assertEqual(st, 400)

    def test_complete_result_kosong_400(self):
        st, body = client.req("POST", "/api/tasks/create", {"title": "T-uji-400"})
        self.assertEqual(st, 200, "seeder task valid harus 200")
        tid = body["task_id"]
        st2, body2 = client.req("POST", f"/api/tasks/{tid}/complete", {"result": ""})
        self.assertEqual(st2, 400, "result kosong harus 400 — " + str(body2))

    def test_complete_id_injeksi_400(self):
        import urllib.parse
        st, body = client.req(
            "POST",
            "/api/tasks/" + urllib.parse.quote("' OR 1--") + "/complete",
            {"result": "x"},
        )
        self.assertEqual(st, 400, "id injeksi harus ditolak — " + str(body.get("message", "")))

    def test_coolify_status_atau_unavailable(self):
        """Endpooint baru: /api/coolify — 200 dengan shape, atau unavailable jujur (tanpa crash)."""
        st, body = client.req("GET", "/api/coolify")
        self.assertEqual(st, 200)
        if body.get("status") == "ok":
            self.assertIn("items", body)
            self.assertIn("total", body)
            self.assertIsInstance(body["items"], list)
        else:
            self.assertEqual(body.get("status"), "unavailable")
            self.assertIn("error", body)

    def test_coolify_deploy_validasi_uuid(self):
        st, body = client.req("POST", "/api/coolify/deploy", {"uuid": ""})
        self.assertEqual(st, 400, "uuid kosong harus 400")
        st2, body2 = client.req("POST", "/api/coolify/deploy", {"uuid": "a" * 100})
        self.assertEqual(st2, 400, "uuid >64 char harus 400")


class TestAgentRoster(unittest.TestCase):
    """Roster agent: seed nyata, CRUD tervalidasi ke daftar model/skill asli."""

    def setUp(self):
        # kelas ini bisa jalan sebelum TestAuth (urutan alfabetis unittest)
        if not any(c.name == "mc_session" for c in client.jar):
            st, _ = client.login()
            if st != 200:
                self.fail(f"login gagal: {st}")

    def test_roster_shape_dan_seed(self):
        st, body = client.req("GET", "/api/agents/roster")
        self.assertEqual(st, 200)
        self.assertEqual(body.get("status"), "ok")
        agents = body.get("agents") or []
        self.assertEqual(len(agents), 11, "Mission Control current roster harus memuat 11 approved entries")
        ids = {a["id"] for a in agents}
        self.assertEqual(ids, {
            "hermes-lead", "agent-engineer", "backend-data", "frontend-product-ui", "devops-sre",
            "personal-assistant", "finance-assistant", "document-knowledge", "social-research-trends",
            "content-planner-copywriter", "visual-ugc-designer",
        })
        self.assertNotIn("opencode", ids)
        st_mem, memory = client.req("GET", "/api/memory")
        self.assertEqual(st_mem, 200)
        skill_names = {
            item.get("name")
            for item in (memory.get("skills", {}).get("skills") or [])
            if isinstance(item, dict)
        }
        required_profile = {
            "mission", "authority", "operating_mode", "language",
            "allowed_actions", "forbidden_actions", "inputs", "outputs",
            "verification", "escalation",
        }
        encoded = json.dumps(body, ensure_ascii=False).lower()
        for marker in ("access_token", "client_secret", "api_key", "password", "authorization"):
            self.assertNotIn(marker, encoded, marker)
        for a in agents:
            self.assertGreater(a.get("persona_chars", 0), 0, a["id"])
            self.assertTrue((a.get("role") or "").strip(), a["id"])
            self.assertFalse((a.get("role") or "").rstrip().endswith(("resp", "konsiste")), a["id"])
            self.assertIn("model", a)
            self.assertIn("skills_count", a)
            self.assertIn("live", a)
            self.assertIn("persona_chars", a)
            self.assertEqual(a["skills_count"], len(a.get("skills") or []))
            self.assertTrue(set(a.get("skills") or []).issubset(skill_names), a["id"])
            profile = a.get("persona_profile")
            self.assertIsInstance(profile, dict, a["id"])
            self.assertEqual(set(profile), required_profile, a["id"])
            for key in ("mission", "authority", "operating_mode", "language", "verification", "escalation"):
                self.assertIsInstance(profile[key], str)
                self.assertTrue(profile[key].strip(), f"{a['id']}:{key}")
            for key in ("allowed_actions", "forbidden_actions", "inputs", "outputs"):
                self.assertIsInstance(profile[key], list)
                self.assertTrue(profile[key], f"{a['id']}:{key}")
                self.assertTrue(all(isinstance(item, str) and item.strip() for item in profile[key]))

    def test_roster_backward_compatible_and_requires_auth(self):
        anon = Client()
        st_anon, body_anon = anon.req("GET", "/api/agents/roster")
        self.assertEqual(st_anon, 401)
        self.assertEqual(body_anon.get("error"), "unauthorized")
        st, body = client.req("GET", "/api/agents/roster")
        self.assertEqual(st, 200)
        for agent in body.get("agents") or []:
            for legacy_key in ("id", "name", "role", "model", "skills", "skills_count", "persona_chars", "live"):
                self.assertIn(legacy_key, agent)

    def test_create_valid_dan_duplikat(self):
        st, body = client.req("POST", "/api/agents", {
            "name": "Roster-Test", "role": "uji",
            "model": "opencode-go/deepseek-v4-flash", "skills": ["agent-engineer"],
        })
        self.assertEqual(st, 200, str(body))
        aid = body["agent"]["id"]
        try:
            st2, _ = client.req("POST", "/api/agents", {
                "name": "roster-test", "model": "opencode-go/deepseek-v4-flash"})
            self.assertEqual(st2, 400, "duplikat (case-insensitive) harus 400")
        finally:
            client.req("DELETE", f"/api/agents/{aid}")
            cleanup_created_workspace(body)

    def test_create_model_palsu_400(self):
        st, body = client.req("POST", "/api/agents", {
            "name": "Palsu", "model": "nvidia/tidak-ada-model"})
        self.assertEqual(st, 400)

    def test_create_and_patch_model_from_hermes_catalog(self):
        st, catalog_body = client.req("GET", "/api/models")
        self.assertEqual(st, 200)
        models = catalog_body.get("models") or {}
        providers = models.get("providers") or {}
        details = models.get("provider_details") or {}
        candidate = next(
            (
                (provider, names)
                for provider, names in providers.items()
                if isinstance(names, list) and names
                and "hermes" in (details.get(provider) or {}).get("sources", [])
            ),
            None,
        )
        if candidate is None:
            self.skipTest("tidak ada provider Hermes tambahan pada runtime ini")
        provider, names = candidate
        model = f"{provider}/{names[0]}"
        name = "Roster-Hermes-Catalog-Test"
        st2, created = client.req("POST", "/api/agents", {
            "name": name, "role": "uji katalog Hermes", "model": model,
        })
        self.assertEqual(st2, 200, str(created))
        aid = created["agent"]["id"]
        try:
            st3, roster = client.req("GET", "/api/agents/roster")
            self.assertEqual(st3, 200)
            row = next(a for a in roster["agents"] if a["id"] == aid)
            self.assertEqual(row["model"], model)
            if len(names) > 1:
                updated_model = f"{provider}/{names[1]}"
                st4, updated = client.req("PATCH", f"/api/agents/{aid}", {"model": updated_model})
                self.assertEqual(st4, 200, str(updated))
                st5, roster2 = client.req("GET", "/api/agents/roster")
                self.assertEqual(st5, 200)
                row2 = next(a for a in roster2["agents"] if a["id"] == aid)
                self.assertEqual(row2["model"], updated_model)
        finally:
            client.req("DELETE", f"/api/agents/{aid}")
            cleanup_created_workspace(created)

    def test_create_skill_palsu_400(self):
        st, body = client.req("POST", "/api/agents", {
            "name": "Palsu2", "model": "opencode-go/deepseek-v4-flash",
            "skills": ["skill-yang-tidak-pernah-ada"]})
        self.assertEqual(st, 400)

    def test_patch_persona_dan_404(self):
        st, body = client.req("POST", "/api/agents", {
            "name": "Roster-Edit", "model": "opencode-go/deepseek-v4-flash"})
        aid = body["agent"]["id"]
        try:
            st2, _ = client.req("PATCH", f"/api/agents/{aid}", {"persona": "persona uji"})
            self.assertEqual(st2, 200)
            st3, pbody = client.req("GET", f"/api/agent-persona?id={aid}")
            self.assertEqual(st3, 200)
            self.assertEqual(pbody.get("persona"), "persona uji")
            st4, _ = client.req("PATCH", f"/api/agents/{aid}", {"active": True})
            self.assertEqual(st4, 200)
            st5, rbody = client.req("GET", "/api/agents/roster")
            active = [a for a in rbody["agents"] if a["active"]]
            self.assertEqual(len(active), 1, "hanya boleh satu agent aktif")
        finally:
            client.req("DELETE", f"/api/agents/{aid}")
            cleanup_created_workspace(body)
        st6, _ = client.req("PATCH", f"/api/agents/{aid}", {"persona": "x"})
        self.assertEqual(st6, 404, "agent terhapus harus 404")

    def test_governance_patch_authenticated_readback_and_validation(self):
        st, body = client.req("POST", "/api/agents", {
            "name": "Governance-Edit", "model": "opencode-go/deepseek-v4-flash"})
        self.assertEqual(st, 200, body)
        aid = body["agent"]["id"]
        profile = {
            "mission": "Menyelesaikan pekerjaan terukur.",
            "authority": "Boleh mengubah hasil dalam scope yang diberikan.",
            "operating_mode": "On-demand dan approval-gated.",
            "language": "Bahasa Indonesia; identifier teknis dipertahankan.",
            "allowed_actions": ["Inspeksi source.", "Menjalankan test."],
            "forbidden_actions": ["Mengarang hasil.", "Melakukan perubahan di luar scope."],
            "inputs": ["Requirement dan acceptance criteria."],
            "outputs": ["Patch dan evidence."],
            "verification": "Cocokkan source dengan hasil test.",
            "escalation": "Eskalasi blocker kepada Lead.",
        }
        try:
            st2, saved = client.req("PATCH", f"/api/agents/{aid}", {"persona_profile": profile})
            self.assertEqual(st2, 200, saved)
            st3, readback = client.req("GET", f"/api/agent-persona?id={aid}")
            self.assertEqual(st3, 200, readback)
            self.assertEqual(readback.get("persona_profile"), profile)

            incomplete = dict(profile)
            incomplete.pop("verification")
            st4, _ = client.req("PATCH", f"/api/agents/{aid}", {"persona_profile": incomplete})
            self.assertEqual(st4, 400)

            secret_marker = dict(profile)
            secret_marker["mission"] = "Use api_key only when needed."
            st5, _ = client.req("PATCH", f"/api/agents/{aid}", {"persona_profile": secret_marker})
            self.assertEqual(st5, 400)

            oversized = dict(profile)
            oversized["mission"] = "x" * 4001
            st6, _ = client.req("PATCH", f"/api/agents/{aid}", {"persona_profile": oversized})
            self.assertEqual(st6, 400)

            st7, unchanged = client.req("GET", f"/api/agent-persona?id={aid}")
            self.assertEqual(st7, 200)
            self.assertEqual(unchanged.get("persona_profile"), profile)
        finally:
            client.req("DELETE", f"/api/agents/{aid}")
            cleanup_created_workspace(body)


class TestZZThrottle(unittest.TestCase):
    def test_throttle_11_gagal_429(self):
        """WAJIB terakhir: 11 percobaan gagal -> 429 (10/60 dtk/IP)."""
        c = Client()
        last = None
        for _ in range(11):
            last = c.req("POST", "/auth/login", {"username": "spam", "password": "spam"})
        self.assertEqual(last[0], 429, "percobaan ke-11 sesudah 10 gagal harus 429")
        print("\n  (menunggu 62 dtk agar kunci throttle 127.0.0.1 lepas untuk run berikutnya)")
        import time
        time.sleep(62)


if __name__ == "__main__":
    unittest.main(verbosity=2)