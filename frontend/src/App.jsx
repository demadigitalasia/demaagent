import React, { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { apiFetch, apiLogin, apiLogout, AuthError } from "./api.js";
import {
  LayoutDashboard, ListTodo, CalendarDays, FileText, Building2, Bot, Brain, BookOpen,
  MessageSquare, Wrench, Link2, Inbox, Folder, Table2, File, Package,
  Folders, Zap, Repeat, Loader2, Check, CheckCircle2, TriangleAlert,
  CircleAlert, Gauge, ExternalLink, Activity as ActivityIcon, Menu, X, LogOut,
  Cpu, RefreshCw, Download, Timer, Eye, Info, Server, Rocket,
  EllipsisVertical, Pencil, Star, Trash2, Plus, Save,
  Monitor, Sofa, Tv, Coffee, Wifi, Radio,
} from "lucide-react";

// Aplikasi mandiri: satu jalur fetch untuk semua request terautentikasi.
// 401 -> satu transisi AuthError -> Root menampilkan halaman login.
let onUnauthorized = null;
let unauthorizedNotified = false;
function safeFetchJSON(url, init) {
  return apiFetch(url, init).catch((err) => {
    notifyUnauthorized(err);
    throw err;
  });
}

export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
  if (fn) unauthorizedNotified = false;
}
function resetUnauthorizedNotice() {
  unauthorizedNotified = false;
}
function notifyUnauthorized(err) {
  if (err instanceof AuthError && onUnauthorized && !unauthorizedNotified) {
    unauthorizedNotified = true;
    onUnauthorized();
  }
}

const EP = "/api";
const POLL_OVERVIEW_MS = 10000;
const POLL_ACTIVITY_MS = 10000;
const POLL_AGENTS_MS = 15000;
const POLL_TASKS_MS = 15000;
const POLL_CALENDAR_MS = 30000;
const POLL_MEMORY_MS = 30000;
const POLL_OFFICE_MS = 10000;
const POLL_DOCS_MS = 30000;
const POLL_OBSIDIAN_MS = 30000;

// --- util kecil -------------------------------------------------------------
function fmtUptime(sec) {
  if (typeof sec !== "number") return "n/a";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0) return `${h}j ${m}m`;
  if (m > 0) return `${m}m ${s}dtk`;
  return `${s}dtk`;
}

function fmtNum(n) {
  if (typeof n !== "number") return "—";
  return n.toLocaleString("en-US");
}

function fmtAgo(epochSec) {
  if (typeof epochSec !== "number") return "—";
  const diff = Math.max(0, Date.now() / 1000 - epochSec);
  if (diff < 60) return `${Math.floor(diff)}dtk lalu`;
  if (diff < 3600) return `${Math.floor(diff / 60)}mnt lalu`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}jam lalu`;
  return `${Math.floor(diff / 86400)}hari lalu`;
}

function shortId(s) {
  if (!s) return "—";
  return s.length > 10 ? `…${s.slice(-8)}` : s;
}

function fmtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  const opts = { day: "2-digit", month: "short", year: "numeric" };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    opts.hour = "2-digit";
    opts.minute = "2-digit";
  }
  return d.toLocaleString("id-ID", opts);
}

function jsonErrorLocation(text, error) {
  const raw = String((error && error.message) || error || "JSON tidak valid");
  const match = raw.match(/position\s+(\d+)/i);
  if (!match) return raw;
  const position = Number(match[1]);
  const before = String(text || "").slice(0, position);
  const line = before.split("\n").length;
  const column = position - before.lastIndexOf("\n");
  return `${raw} (baris ${line}, kolom ${column})`;
}

function jsonObjectCount(text, fallback = 0) {
  try {
    const value = JSON.parse(text || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? Object.keys(value).length : fallback;
  } catch {
    return fallback;
  }
}

function modelProviderMap(models) {
  const raw = models && models.providers;
  if (Array.isArray(raw)) {
    return raw.reduce((out, row) => {
      if (!row || typeof row !== "object") return out;
      const provider = String(row.slug || row.provider || "").trim();
      const names = Array.isArray(row.models) ? row.models.filter((m) => typeof m === "string" && m.trim()) : [];
      if (provider) out[provider] = Array.from(new Set(names));
      return out;
    }, {});
  }
  if (!raw || typeof raw !== "object") return {};
  return Object.entries(raw).reduce((out, [provider, names]) => {
    if (!provider) return out;
    out[provider] = Array.isArray(names)
      ? names.filter((m) => typeof m === "string" && m.trim())
      : [];
    return out;
  }, {});
}

function modelProviderDetails(models) {
  const raw = models && models.provider_details;
  return raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
}

function modelCatalogDefault(models) {
  return models && typeof models.default === "string" ? models.default : "";
}

function fmtEvtRange(start, end) {
  if (!start) return "—";
  const s = fmtDateTime(start);
  if (!end) return s;
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/;
  if (dateOnly.test(start) && dateOnly.test(end)) return `${s} (sepanjang hari)`;
  return `${s} → ${fmtDateTime(end)}`;
}

// --- primitif UI (semua styling lewat Tailwind) ------------------------------
const BADGE_CLS = {
  ok: "mc-badge-ok",
  bad: "mc-badge-bad",
  warn: "mc-badge-warn",
  info: "mc-badge-info",
  neutral: "mc-badge-neutral",
};
const BAR_CLS = {
  ok: "bg-[#4ade80]",
  bad: "bg-[#f87171]",
  warn: "bg-[#fbbf24]",
  info: "bg-[#38bdf8]",
  neutral: "bg-[#a1a1aa]",
};

function Badge({ tone = "neutral", className = "", children }) {
  return <span className={`${BADGE_CLS[tone] || BADGE_CLS.neutral} ${className}`.trim()}>{children}</span>;
}

function Chip({ children }) {
  return <span className="mc-chip">{children}</span>;
}

function Feedback({ kind = "ok", className = "", id, children }) {
  const error = kind === "err" || kind === "error" || kind === "bad";
  return (
    <div
      id={id}
      className={`${error ? "mc-err" : "mc-ok"} ${className}`.trim()}
      role={error ? "alert" : "status"}
      aria-live={error ? "assertive" : "polite"}
    >
      {children}
    </div>
  );
}

function Loading({ label = "memuat…" }) {
  return (
    <div className="text-mc-muted text-[13px] py-2.5 flex items-center gap-2" role="status" aria-live="polite" aria-busy="true">
      <span className="mc-spinner" aria-hidden="true" /> {label}
    </div>
  );
}

function Empty({ msg }) {
  return <div className="mc-empty">Kosong — {msg}</div>;
}

function Unavailable({ msg }) {
  return <div className="mc-err" role="alert" aria-live="assertive"><CircleAlert size={13} className="inline mr-1 -mt-0.5" aria-hidden="true" />Tidak tersedia{msg ? `: ${msg}` : ""}</div>;
}

const MODAL_FOCUSABLE = "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex=\"-1\"])";
let modalSequence = 0;

function Modal({ title, subtitle, onClose, children, footer, wide = false, mode = "dialog", initialFocusRef, contentClassName = "", headerContent, busy = false, dialogId }) {
  const dialogRef = useRef(null);
  const titleIdRef = useRef(null);
  const subtitleIdRef = useRef(null);
  if (!titleIdRef.current) {
    modalSequence += 1;
    titleIdRef.current = `mc-modal-title-${modalSequence}`;
    subtitleIdRef.current = `mc-modal-subtitle-${modalSequence}`;
  }
  const titleId = titleIdRef.current;
  const subtitleId = subtitleIdRef.current;

  useEffect(() => {
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const shell = document.querySelector("[data-mc-app-shell]");
    const previousShell = shell ? { inert: shell.hasAttribute("inert"), ariaHidden: shell.getAttribute("aria-hidden") } : null;
    const previousOverflow = document.body.style.overflow;
    if (shell) {
      shell.setAttribute("inert", "");
      shell.setAttribute("aria-hidden", "true");
    }
    document.body.style.overflow = "hidden";
    const focusFrame = requestAnimationFrame(() => {
      const target = initialFocusRef && initialFocusRef.current
        ? initialFocusRef.current
        : dialogRef.current && dialogRef.current.querySelector(MODAL_FOCUSABLE);
      (target || dialogRef.current)?.focus();
    });
    return () => {
      cancelAnimationFrame(focusFrame);
      if (shell && previousShell) {
        if (previousShell.inert) shell.setAttribute("inert", "");
        else shell.removeAttribute("inert");
        if (previousShell.ariaHidden == null) shell.removeAttribute("aria-hidden");
        else shell.setAttribute("aria-hidden", previousShell.ariaHidden);
      }
      document.body.style.overflow = previousOverflow;
      if (trigger && trigger.isConnected) requestAnimationFrame(() => trigger.focus());
    };
  }, [initialFocusRef]);

  function handleKeyDown(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !dialogRef.current) return;
    const focusable = Array.from(dialogRef.current.querySelectorAll(MODAL_FOCUSABLE)).filter((el) => el.offsetParent !== null);
    if (!focusable.length) {
      e.preventDefault();
      dialogRef.current.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  if (typeof document === "undefined") return null;
  const isDrawer = mode === "drawer";
  const dialogClass = isDrawer
    ? "relative h-full w-[264px] max-w-[85vw] bg-gradient-to-b from-[#101014] to-mc-sidebar border-r border-mc-border shadow-lift flex flex-col"
    : `relative w-full ${wide ? "max-w-4xl" : "max-w-2xl"} rounded-2xl bg-mc-card border border-mc-border shadow-lift flex flex-col max-h-[90vh]`;
  const headerClass = isDrawer
    ? "flex items-center justify-between gap-3 px-3 pb-3.5 pt-3 border-b border-mc-border"
    : "flex items-start justify-between gap-3 border-b border-mc-border px-5 py-4";
  const bodyClass = isDrawer
    ? "flex flex-col gap-1 p-3 overflow-y-auto overscroll-contain flex-1 min-h-0"
    : `px-5 py-4 overflow-y-auto overscroll-contain flex-1 min-h-0 ${contentClassName}`;

  return createPortal(
    <div className={`fixed inset-0 z-[100] flex ${isDrawer ? "justify-start" : "items-center justify-center"} p-0 sm:p-4`}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onMouseDown={onClose} aria-hidden="true" />
      <div
        id={dialogId}
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={subtitle ? subtitleId : undefined}
        aria-busy={busy || undefined}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        className={dialogClass}
      >
        <div className={headerClass}>
          {headerContent ? (
            <>
              <h2 id={titleId} className="sr-only">{title}</h2>
              <div className="min-w-0 flex-1">{headerContent}</div>
            </>
          ) : (
            <div className="min-w-0 flex-1">
              <h2 id={titleId} className="m-0 text-[15px] font-semibold text-mc-text">{title}</h2>
              {subtitle ? <div id={subtitleId} className="text-[11px] text-mc-muted mt-px break-words">{subtitle}</div> : null}
            </div>
          )}
          <button type="button" onClick={onClose} aria-label="Tutup" className="w-8 h-8 rounded-lg flex items-center justify-center text-mc-muted hover:text-mc-text hover:bg-white/5 cursor-pointer shrink-0">
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        {headerContent && subtitle ? <div id={subtitleId} className="sr-only">{subtitle}</div> : null}
        <div className={bodyClass}>{children}</div>
        {footer ? <div className="flex justify-end gap-2 border-t border-mc-border px-5 py-3.5">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  );
}

function ConfirmModal({
  title,
  target,
  impact,
  onClose,
  onConfirm,
  busy = false,
  error = null,
  success = null,
  confirmLabel = "Hapus",
  busyLabel = "Menghapus…",
  confirmIcon: ConfirmIcon = Trash2,
  busyIcon: BusyIcon = Loader2,
  confirmClassName = "!text-rose-300 !border-rose-400/40",
}) {
  const cancelRef = useRef(null);
  const completed = Boolean(success);
  return (
    <Modal
      title={title}
      subtitle="Tindakan ini tidak dapat dibatalkan dari dashboard setelah berhasil."
      onClose={onClose}
      initialFocusRef={cancelRef}
      busy={busy}
      footer={(
        <>
          <button type="button" ref={cancelRef} className="mc-btn-ghost" onClick={onClose} disabled={busy}>{completed ? "Tutup" : "Batal"}</button>
          {!completed ? (
            <button type="button" className={`mc-btn-ghost ${confirmClassName}`.trim()} onClick={onConfirm} disabled={busy} aria-busy={busy}>
              {busy ? <><BusyIcon size={13} className="animate-spin" aria-hidden="true" /> {busyLabel}</> : <><ConfirmIcon size={13} aria-hidden="true" /> {confirmLabel}</>}
            </button>
          ) : null}
        </>
      )}
    >
      {completed ? (
        <Feedback kind="ok" className="rounded-xl border border-green-400/25 bg-green-400/[0.06] p-3.5 mt-0">{success}</Feedback>
      ) : (
        <div className="rounded-xl border border-rose-400/25 bg-rose-400/[0.06] p-3.5" role="alert">
          <div className="text-[13px] font-semibold text-rose-200 break-words">{target}</div>
          <p className="m-0 mt-1.5 text-[12px] leading-relaxed text-mc-muted">{impact}</p>
        </div>
      )}
      {error ? <Feedback kind="err" className="mt-2">{error}</Feedback> : null}
    </Modal>
  );
}

function Card({ title, right, children, busy = false, className = "" }) {
  return (
    <div className={`mc-card ${className}`.trim()} aria-busy={busy || undefined}>
      <div className="mc-card-head">
        <p className="mc-card-title">{title}</p>
        {right}
      </div>
      {children}
    </div>
  );
}

function Row({ k, v, mono = true }) {
  return (
    <div className="mc-row">
      <span className="mc-row-key">{k}</span>
      <span className={mono === false ? "text-right text-mc-text" : "mc-row-val"}>{v}</span>
    </div>
  );
}

function Block({ ok, error, emptyMsg, loading, children }) {
  if (loading) return <Loading />;
  if (!ok) return <Unavailable msg={error} />;
  if (children == null || (Array.isArray(children) && children.length === 0)) {
    return <Empty msg={emptyMsg || "tidak ada data"} />;
  }
  return children;
}

// --- polling hook (per-panel; interval dibersihkan saat unmount) -------------
// Param ketiga `tick` (opsional): saat berubah, polling langsung load ulang —
// dipakai panel Tasks setelah create/complete supaya list segar tanpa nunggu interval.
function usePolling(url, ms, tick) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    let cancelled = false;

    function load() {
      setRefreshing(true);
      safeFetchJSON(url)
        .then((json) => {
          if (cancelled) return;
          setData(json);
          setError(null);
        })
        .catch((e) => {
          if (cancelled) return;
          notifyUnauthorized(e);
          setError(String((e && e.message) || e));
          // data lama tetap ditampilkan saat refresh gagal
        })
        .finally(() => {
          if (!cancelled) setRefreshing(false);
        });
    }

    load();
    const timer = setInterval(load, ms);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [url, ms, tick]);

  return { data, error, refreshing };
}

// --- PANEL: Overview ---------------------------------------------------------
// --- Grafik aktivitas 7 hari (state.db) --------------------------------------
const DAY_NAMES = ["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"];

function ActivityChart() {
  const { data, error, refreshing } = usePolling(`${EP}/stats`, 30000);

  if (!data && !error) return <Loading />;
  if (error) {
    return (
      <Card title="Aktivitas 7 Hari">
        <Unavailable msg={error} />
      </Card>
    );
  }
  const st = data.stats || {};
  const ok = st.status === "ok";
  const days = ok ? st.days || [] : [];

  if (!ok) {
    return (
      <Card title="Aktivitas 7 Hari" right={<Badge tone="bad">unavailable</Badge>}>
        <Unavailable msg={(st && st.error) || ""} />
      </Card>
    );
  }

  const max = Math.max(1, ...days.map((d) => d.messages));
  const totalMsgs = days.reduce((a, d) => a + d.messages, 0);
  const totalTools = days.reduce((a, d) => a + d.tool_calls, 0);
  const totalSess = days.reduce((a, d) => a + d.sessions, 0);
  const W = 560, H = 150, PAD = 6, GAP = 10;
  const bw = (W - PAD * 2 - GAP * (days.length - 1)) / Math.max(1, days.length);

  return (
    <Card
      title="Aktivitas 7 Hari"
      right={
        <Badge tone={totalMsgs > 0 ? "ok" : "neutral"}>
          {totalMsgs} pesan · {totalTools} tool · {totalSess} sesi
        </Badge>
      }
    >
      <div style={{ overflowX: "auto", maxWidth: "100%" }}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Grafik aktivitas 7 hari" style={{ width: "100%", minWidth: "320px", height: "auto" }}>
          {days.map((d, i) => {
            const x = PAD + i * (bw + GAP);
            const bh = d.messages === 0 ? 2 : Math.max(4, (d.messages / max) * (H - 46));
            const y = H - 26 - bh;
            const dt = new Date(d.date + "T00:00:00Z");
            const label = `${DAY_NAMES[dt.getUTCDay()]}\n${dt.getUTCDate()}/${dt.getUTCMonth() + 1}`;
            return (
              <g key={d.date}>
                <rect
                  x={x}
                  y={y}
                  width={bw}
                  height={bh}
                  rx={4}
                  fill={d.messages > 0 ? "url(#mcBarGrad)" : "rgba(255,255,255,0.06)"}
                >
                  <title>{`${d.date}: ${d.messages} pesan · ${d.tool_calls} tool calls · ${d.sessions} sesi`}</title>
                </rect>
                <text x={x + bw / 2} y={H - 26 + 12} textAnchor="middle" fontSize="10" fill="#71717a">
                  {label.split("\n")[0]}
                </text>
                <text x={x + bw / 2} y={H - 26 + 24} textAnchor="middle" fontSize="9" fill="#52525b">
                  {label.split("\n")[1]}
                </text>
                {d.messages > 0 ? (
                  <text x={x + bw / 2} y={y - 5} textAnchor="middle" fontSize="9" fill="#a1a1aa">
                    {d.messages}
                  </text>
                ) : null}
              </g>
            );
          })}
          <defs>
            <linearGradient id="mcBarGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#38bdf8" />
              <stop offset="100%" stopColor="#a78bfa" />
            </linearGradient>
          </defs>
        </svg>
      </div>
      <div className="mc-footnote mt-2">
        Jumlah pesan per hari (state.db, read-only) · refresh 30 dtk · arahkan kursor ke batang untuk detail.
      </div>
    </Card>
  );
}

function OverviewPanel() {
  const { data, error, refreshing } = usePolling(`${EP}/overview`, POLL_OVERVIEW_MS);

  if (!data && !error) return <Loading />;
  if (error) {
    return (
      <Card title="Overview">
        <Unavailable msg={error} />
      </Card>
    );
  }

  const g = data.gateway || {};
  const db = data.db || {};
  const u = data.uptime || {};
  const gOk = g.status === "ok";
  const dOk = db.status === "ok";
  const uOk = u.status === "ok";

  return (
    <>
      {error ? <Card title="Refresh gagal"><Unavailable msg={error} /></Card> : null}
      <div className="mc-panel-grid">
        {/* Kartu 1: gateway */}
        <Card
          title="Gateway"
          right={
            <Badge tone={gOk ? "ok" : "bad"}>
              {gOk ? (g.state || "running") : "unavailable"}
            </Badge>
          }
        >
          <Row k="PID" v={g.pid ?? "—"} />
          <Row k="Versi" v={g.code_version ?? "—"} />
          <Row
            k="Uptime"
            v={uOk ? fmtUptime(u.uptime_s) : "—"}
            mono={false}
          />
          <Row k="Active agents" v={fmtNum(g.active_agents) + (g.active_work ? ` (${g.active_work})` : "")} />
          <Row k="Session store" v={((g.session_store || {}).status) ?? "—"} />
          <div className="mc-row items-start">
            <span className="mc-row-key">Platform</span>
            <span className="flex gap-1 flex-wrap justify-end">
              {Object.keys(g.platforms || {}).length === 0
                ? "—"
                : Object.entries(g.platforms).map(([name, p]) => (
                    <Chip key={name}>
                      {name}
                      {p && p.state ? `:${p.state}` : ""}
                      {p && p.needs_attention ? <TriangleAlert size={11} className="inline ml-0.5 text-amber-400" /> : null}
                    </Chip>
                  ))}
            </span>
          </div>
          {gOk ? null : <Feedback kind="err">{g.error}</Feedback>}
        </Card>

        {/* Kartu 2: aktivitas hari ini */}
        <Card
          title="Statistik hari ini (state.db)"
          right={<Badge tone={dOk ? "ok" : "bad"}>{dOk ? "ok" : "unavailable"}</Badge>}
        >
          <Row k="Sesi baru" v={fmtNum(db.sessions_today)} />
          <Row k="Pesan" v={fmtNum(db.messages_today)} />
          <Row k="Tool calls" v={fmtNum(db.tool_calls_today)} />
          <Row k="Delegasi async" v={fmtNum(db.async_delegations_today)} />
          <Row k="Sesi aktif (all-time)" v={fmtNum(db.active_sessions)} />
          {dOk ? null : <Feedback kind="err">{db.error}</Feedback>}
        </Card>

        {/* Kartu 3: total + terakhir */}
        <Card title="Total &amp; terakhir">
          <Row k="Total sesi" v={fmtNum(db.total_sessions)} />
          <Row k="Total pesan" v={fmtNum(db.total_messages)} />
          <Row k="Pesan terakhir" v={fmtAgo(db.latest_message_at)} mono={false} />
          <Row k="Update terakhir" v={data.generated_at || "—"} mono={false} />
        </Card>
      </div>
      <ActivityChart />
      <div className="mc-footnote">
        Token/cost tidak tersedia dari /overview (tidak ada field-nya) — ditampilkan yang tersedia saja.
        · {refreshing ? "auto-refresh 10 dtk…" : "auto-refresh 10 dtk"}
      </div>
    </>
  );
}

// --- PANEL: Activity ----------------------------------------------------------
const KIND_TONE = { tool_call: "info", api_call: "neutral", inbound: "ok", response: "warn" };
const KIND_LABEL = { tool_call: "tool_call", api_call: "api_call", inbound: "inbound", response: "response" };
const KIND_ICON = { tool_call: Wrench, api_call: Link2, inbound: Inbox, response: MessageSquare };

function KindIcon({ kind, size = 14 }) {
  const I = KIND_ICON[kind];
  return I ? <I size={size} className="text-mc-muted shrink-0" /> : <span className="text-mc-faint">•</span>;
}

function ActivityItem({ e }) {
  let main = null;
  let sub = null;

  if (e.kind === "tool_call") {
    main = (
      <span>
        Tool <b className="text-sky-400">{e.tool || "?"}</b>
        {" — "}
        <Badge tone={e.outcome === "completed" ? "ok" : "bad"}>{e.outcome || "?"}</Badge>
      </span>
    );
  } else if (e.kind === "api_call") {
    main = (
      <span>
        API call <b>{e.model || "?"}</b>
        <span className="text-mc-faint"> · {e.provider || "?"}</span>
      </span>
    );
    sub = `in ${fmtNum(e.in_tokens)} → out ${fmtNum(e.out_tokens)} tok · ${e.latency_s != null ? e.latency_s + "s" : "?"}`;
  } else if (e.kind === "inbound") {
    main = (
      <span>
        Inbound <b>{e.platform || "?"}</b>
        <span className="text-mc-faint"> · user={e.user || "?"} · chat={shortId(e.chat)}</span>
      </span>
    );
    sub = e.msg ? `“${e.msg}”` : null;
  } else if (e.kind === "response") {
    main = (
      <span>
        Response <b>{e.platform || "?"}</b>
        <span className="text-mc-faint"> · {e.time_s != null ? e.time_s + "s" : "?"}</span>
      </span>
    );
    sub = e.api_calls != null ? `${e.api_calls} api call · ${fmtNum(e.chars)} chars` : null;
  }

  return (
    <div className="mc-feed-item">
      <span className={`mc-feed-bar ${BAR_CLS[KIND_TONE[e.kind]] || BAR_CLS.neutral}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="shrink-0" aria-hidden><KindIcon kind={e.kind} /></span>
          <Badge tone={KIND_TONE[e.kind] || "neutral"}>{KIND_LABEL[e.kind] || e.kind}</Badge>
          <span className="font-mono text-[11px] text-mc-faint">{e.ts}</span>
          <span className="font-mono text-[11px] text-mc-faint ml-auto" title={e.session || ""}>sesi {shortId(e.session)}</span>
        </div>
        <div className="text-[13px] mt-1 break-words">{main}</div>
        {sub ? <div className="text-[11px] text-mc-muted mt-0.5 font-mono">{sub}</div> : null}
      </div>
    </div>
  );
}

function ActivityPanel() {
  const { data, error, refreshing } = usePolling(`${EP}/activity`, POLL_ACTIVITY_MS);

  if (!data && !error) return <Loading />;
  if (error) {
    return (
      <Card title="Activity">
        <Unavailable msg={error} />
      </Card>
    );
  }

  const a = data.activity || {};
  const ok = a.status === "ok";
  const entries = a.entries || [];
  const sources = a.sources || {};

  return (
    <>
      <Card
        title="Activity feed (live)"
        right={
          <span className={`mc-fresh ${refreshing ? "text-sky-400" : ""}`}>
            {refreshing ? "memuat…" : "auto-refresh 10 dtk"}
          </span>
        }
      >
        <div className="flex gap-1.5 flex-wrap">
          {Object.entries(sources).map(([name, s]) => (
            <Chip key={name}>
              {name}.log: {s && s.status === "ok" ? `${s.count} baru` : "n/a"}
            </Chip>
          ))}
        </div>
        <div className="h-2" />
        {!ok ? (
          <Unavailable msg={a.error || "kedua sumber log tidak tersedia"} />
        ) : entries.length === 0 ? (
          <Empty msg="belum ada aktivitas tercatat di log" />
        ) : (
          <div className="flex flex-col gap-2">
            {entries.map((e, i) => (
              <ActivityItem key={i} e={e} />
            ))}
          </div>
        )}
        {!ok
          ? Object.entries(sources)
              .filter(([, s]) => !s || s.status !== "ok")
              .map(([name, s]) => (
                <Feedback key={name} kind="err">
                  {name}.log: {(s && (s.error || s.file)) || "tidak tersedia"}
                </Feedback>
              ))
          : null}
      </Card>
      <div className="mc-footnote">
        {entries.length} entri ditampilkan (maks {a.max_entries ?? "?"}) · terbaru di atas · sumber dari {sources.agent && sources.agent.status === "ok" ? "agent.log" : ""}{" "}
        {sources.gateway && sources.gateway.status === "ok" ? "+ gateway.log" : ""}
      </div>
    </>
  );
}

// --- PANEL: Agents -------------------------------------------------------------
function AgentSessionsCard({ title, blk, gatewayCount }) {
  const ok = blk && blk.status === "ok";
  const rows = (blk && blk.rows) || [];
  const activeInRows = rows.filter((r) => r.active).length;
  const last = rows[0];

  return (
    <Card title={title} right={<Badge tone={ok ? (rows.length ? "ok" : "neutral") : "bad"}>{ok ? "tersedia" : "unavailable"}</Badge>}>
      {!ok ? (
        <Unavailable msg={(blk && blk.error) || ""} />
      ) : rows.length === 0 ? (
        <Empty msg="belum ada sesi tercatat" />
      ) : (
        <>
          {gatewayCount != null ? (
            <Row k="Active agents (gateway)" v={fmtNum(gatewayCount)} />
          ) : null}
          <Row k="Sesi (10 terbaru)" v={`${rows.length}`} />
          <Row k="Sesi aktif di daftar" v={`${activeInRows}`} />
          {last ? (
            <div className="mt-1.5 p-2.5 rounded-lg bg-white/[0.03] border border-mc-border">
              <div className="text-xs font-semibold break-all text-mc-text">
                {last.title || last.display_name || shortId(last.id)}
              </div>
              <div className="text-[11px] text-mc-muted mt-0.5 font-mono">
                {last.model || "?"} · {last.started_at_iso || "?"} ·{" "}
                <Badge tone={last.active ? "ok" : "neutral"}>{last.active ? "aktif" : "selesai"}</Badge>
              </div>
            </div>
          ) : null}
          <div className="flex flex-col gap-1.5 mt-2">
            {rows.slice(1, 4).map((r) => (
              <div key={r.id} className="mc-feed-item">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[11px] font-mono text-mc-muted">{shortId(r.id)}</span>
                    <span className="text-[11px] text-mc-faint">· {r.model || "?"}</span>
                    <span className="font-mono text-[11px] text-mc-faint ml-auto">
                      <Badge tone={r.active ? "ok" : "neutral"}>{r.active ? "aktif" : "selesai"}</Badge>
                    </span>
                  </div>
                  <div className="text-[11px] text-mc-muted mt-0.5 font-mono">{r.started_at_iso || "?"}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}

function OpenCodeCard({ blk }) {
  const ok = blk && blk.status === "ok";

  return (
    <Card
      title="OpenCode workers"
      right={
        ok ? (
          <Badge tone={blk.active_sessions_recent ? "ok" : "neutral"}>
            {blk.active_sessions_recent ? `${blk.active_sessions_recent} aktif (15m)` : "idle"}
          </Badge>
        ) : (
          <Badge tone="bad">unavailable</Badge>
        )
      }
    >
      {!ok ? (
        <Unavailable msg={(blk && blk.error) || ""} />
      ) : !blk.sessions || blk.sessions.length === 0 ? (
        <Empty msg="belum ada sesi OpenCode" />
      ) : (
        <>
          <Row k="Sesi (10 terbaru)" v={`${blk.sessions.length}`} />
          <Row k="Aktif (update &lt; 15 mnt)" v={`${blk.active_sessions_recent ?? 0}`} />
          <div className="flex flex-col gap-1.5 mt-2">
            {blk.sessions.slice(0, 5).map((s) => (
              <div key={s.id} className="mc-feed-item">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-semibold text-mc-text">{shortId(s.title || s.id)}</span>
                    <span className="font-mono text-[11px] text-mc-faint ml-auto">
                      {s.recent ? <Badge tone="ok">aktif</Badge> : null}
                    </span>
                  </div>
                  <div className="text-[11px] text-mc-muted mt-0.5 font-mono">
                    {s.agent || "agent"} · {(s.model && (s.model.id || JSON.stringify(s.model))) || "?"} · {fmtNum(s.message_count)} msg · {s.time_updated_iso || "?"}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}

const DELEG_TONE = { running: "info", completed: "ok", error: "bad", failed: "bad", timed_out: "warn", blocked: "warn" };

function Avatar({ name, index }) {
  const initials = (name || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  return (
    <span aria-hidden className={`mc-avatar mc-avatar-h${(index || 0) % 7}`}>
      {initials}
    </span>
  );
}

function AgentCard({ idx, name, role, online, model, stats, meta, accent, onDetail }) {
  return (
    <div className="mc-agent-card">
      <div className="flex gap-2.5 items-center">
        <Avatar name={name} index={idx} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-mc-text">{name}</span>
            <span
              className={`w-2 h-2 rounded-full ${online ? "bg-green-400 shadow-[0_0_8px_#4ade80]" : "bg-mc-faint"}`}
              title={online ? "aktif" : "offline"}
            />
          </div>
          <div className="text-[11px] text-mc-muted mt-px">{role}</div>
        </div>
        <span className="mc-chip">{online ? "online" : "offline"}</span>
      </div>
      {model ? (
        <div className="mc-model-block">
          <Brain size={12} className="inline mr-1 -mt-0.5" /> {model}
        </div>
      ) : null}
      {stats && stats.length ? (
        <div className="flex gap-1.5 flex-wrap">
          {stats.map((s, i) => (
            <span key={i} className="mc-chip inline-flex items-center gap-1.5">{s.icon}{s.text}</span>
          ))}
        </div>
      ) : null}
      {meta ? (
        <div className="text-[11px] text-mc-faint font-mono border-t border-mc-border pt-2">
          {meta}
        </div>
      ) : null}
      {onDetail ? (
        <button
          onClick={onDetail}
          className="mt-2 w-full mc-btn-ghost inline-flex items-center justify-center gap-1.5 text-[12px]"
          aria-label={`Detail skill & memori ${name}`}
        >
          <Eye size={13} /> Detail skill & memori
        </button>
      ) : null}
    </div>
  );
}

function DelegationsBlock({ blk }) {
  const ok = blk && blk.status === "ok";
  const states = (blk && blk.states) || {};
  const recent = (blk && blk.recent) || [];

  return (
    <Card
      title="Delegasi terbaru"
      right={<Badge tone={ok ? "ok" : "bad"}>{ok ? "ok" : "unavailable"}</Badge>}
    >
      {!ok ? (
        <Unavailable msg={(blk && blk.error) || ""} />
      ) : (
        <>
          <div className="flex gap-1.5 flex-wrap mb-2.5">
            {Object.keys(states).length === 0 ? (
              <span className="mc-empty">Kosong — belum ada delegasi tercatat</span>
            ) : (
              Object.entries(states).map(([st, n]) => (
                <span key={st}>
                  <Badge tone={DELEG_TONE[st] || "neutral"}>
                    {st}: {n}
                  </Badge>
                </span>
              ))
            )}
          </div>
          {recent.length > 0 ? (
            <div className="overflow-x-auto max-w-full">
              <table className="mc-table">
                <thead>
                  <tr>
                    <th className="mc-th">ID</th>
                    <th className="mc-th">State</th>
                    <th className="mc-th">Parent sesi</th>
                    <th className="mc-th">Dispatched</th>
                    <th className="mc-th">Completed</th>
                  </tr>
                </thead>
                <tbody>
                  {recent.map((d) => (
                    <tr key={d.delegation_id} className="transition-colors hover:bg-white/[0.02]">
                      <td className="mc-td">{shortId(d.delegation_id)}</td>
                      <td className="mc-td">
                        <Badge tone={DELEG_TONE[d.state] || "neutral"}>{d.state || "?"}</Badge>
                      </td>
                      <td className="mc-td">{shortId(d.parent_session_id)}</td>
                      <td className="mc-td">{(d.dispatched_at_iso || "—").replace("T", " ")}</td>
                      <td className="mc-td">{(d.completed_at_iso || "—").replace("T", " ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}

function AgentsPanel() {
  const { data: agentsData } = usePolling(`${EP}/agents`, POLL_AGENTS_MS);
  const [roster, setRoster] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);
  const [edit, setEdit] = useState(null); // agent sedang diedit
  const [creating, setCreating] = useState(false);
  const [del, setDel] = useState(null); // { id, name }
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [menuFor, setMenuFor] = useState(null); // id kartu dengan menu terbuka
  const [msg, setMsg] = useState(null); // { kind, text }
  const [profileFor, setProfileFor] = useState(null); // roster agent yang dibuka di modal detail

  function load() {
    setLoading(true);
    safeFetchJSON(`${EP}/agents/roster`)
      .then((d) => {
        setRoster(d);
        setErr(null);
      })
      .catch((e) => {
        notifyUnauthorized(e);
        setErr(e.message || "gagal memuat roster");
      })
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function patchAgent(id, body) {
    try {
      const r = await safeFetchJSON(`${EP}/agents/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r && r.status === "ok") return true;
      setMsg({ kind: "err", text: (r && r.error) || "gagal menyimpan" });
      return false;
    } catch (e) {
      setMsg({ kind: "err", text: e.message || "gagal menyimpan" });
      return false;
    }
  }

  async function setActive(a) {
    if (await patchAgent(a.id, { active: true })) {
      setMsg({ kind: "ok", text: `"${a.name}" kini agent aktif ✓` });
      load();
    }
  }

  async function delAgent(a) {
    setDeleteBusy(true);
    setMsg(null);
    try {
      const r = await safeFetchJSON(`${EP}/agents/${a.id}`, { method: "DELETE" });
      if (r && r.status === "ok") {
        setMsg({ kind: "ok", text: `Agent "${a.name}" dihapus` });
        setDel(null);
        load();
      } else {
        setMsg({ kind: "err", text: (r && r.error) || "gagal menghapus" });
      }
    } catch (e) {
      notifyUnauthorized(e);
      setMsg({ kind: "err", text: e.message || "gagal menghapus" });
    } finally {
      setDeleteBusy(false);
    }
  }

  if (err && !roster) return <Unavailable msg={err} />;

  const agents = (roster && roster.agents) || [];
  const deleg = (agentsData && agentsData.agents && agentsData.agents.delegations) || {};

  return (
    <>
      <div className="mc-fresh mb-0.5 flex items-center justify-between flex-wrap gap-1.5">
        <span>
          {loading && !roster ? "memuat…" : `data: ${(roster && roster.generated_at) || ""} · ${(roster && roster.models_ref && roster.models_ref.total) || 0} model tersedia`}
        </span>
        <button
          onClick={() => setCreating(true)}
          className="mc-btn-ghost inline-flex items-center gap-1.5 text-[12px] px-2.5 py-1"
          aria-label="Buat agent baru"
        >
          <Plus size={13} /> Buat agent
        </button>
      </div>

      {msg ? <Feedback kind={msg.kind}>{msg.text}</Feedback> : null}

      {loading && !roster ? (
        <Loading />
      ) : !roster ? (
        <Unavailable msg={err || "roster tidak tersedia"} />
      ) : (
        <div className="mc-agent-grid">
          {agents.map((a, i) => {
            const live = a.live || {};
            const liveStatus = a.live_status || (live.status === "online" ? "running" : live.status || "unknown");
            const configuredActive = a.configured_active ?? a.active;
            const online = liveStatus === "running";
            const tone = online ? "ok" : liveStatus === "standby" ? "info" : liveStatus === "unknown" ? "warn" : "neutral";
            return (
              <div key={a.id} className="mc-agent-card relative">
                <div className="flex gap-2.5 items-center">
                  <Avatar name={a.name} index={i} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-semibold text-mc-text">{a.name}</span>
                      {configuredActive ? (
                        <span className="mc-chip text-[10px] inline-flex items-center gap-1 text-sky-300 border-sky-400/30">
                          <Star size={9} /> configured active
                        </span>
                      ) : null}
                      <span
                        className={`w-2 h-2 rounded-full ${online ? "bg-green-400 shadow-[0_0_8px_#4ade80]" : liveStatus === "standby" ? "bg-sky-400" : "bg-mc-faint"}`}
                        title={`live: ${liveStatus}`}
                      />
                    </div>
                    <div className="text-[11px] text-mc-muted mt-px">{a.role}</div>
                  </div>
                  <Badge tone={tone} className="text-[10.5px]">
                    {liveStatus === "running" ? "Running" : liveStatus === "standby" ? "Standby" : liveStatus === "offline" ? "Offline" : "Unknown"}
                  </Badge>
                  <div className="relative">
                    <button
                      onClick={() => setMenuFor(menuFor === a.id ? null : a.id)}
                      aria-label={`Menu ${a.name}`}
                      className="w-7 h-7 rounded-lg flex items-center justify-center text-mc-muted hover:text-mc-text hover:bg-white/5 cursor-pointer"
                    >
                      <EllipsisVertical size={15} />
                    </button>
                    {menuFor === a.id ? (
                      <>
                        <div className="fixed inset-0 z-30" onClick={() => setMenuFor(null)} aria-hidden />
                        <div className="absolute right-0 top-8 z-40 w-44 rounded-xl bg-mc-card border border-mc-border shadow-lift p-1.5 flex flex-col gap-0.5">
                          <button className="mc-btn-ghost justify-start text-[12px] px-2.5 py-1.5" onClick={() => { setEdit(a); setMenuFor(null); }}>
                            <Pencil size={12} /> Edit agent
                          </button>
                          <button className="mc-btn-ghost justify-start text-[12px] px-2.5 py-1.5" onClick={() => setActive(a)}>
                            <Star size={12} /> Set as active
                          </button>
                          <button
                            className="mc-btn-ghost justify-start text-[12px] px-2.5 py-1.5 !text-rose-300"
                            onClick={() => {
                              setMenuFor(null);
                              setDel({ id: a.id, name: a.name });
                            }}
                          >
                            <Trash2 size={12} /> Delete
                          </button>
                        </div>
                      </>
                    ) : null}
                  </div>
                </div>

                <div className="mc-model-block">
                  <Brain size={12} className="inline mr-1 -mt-0.5" />
                  {a.model_provider}/{a.model_id}
                  {!a.model_catalog_available ? (
                    <span className="ml-1.5 text-[10px] text-amber-300/80">(model missing from catalog)</span>
                  ) : a.provider_connected === false ? (
                    <span className="ml-1.5 text-[10px] text-amber-300/80">(provider not authenticated)</span>
                  ) : a.provider_connected == null ? (
                    <span className="ml-1.5 text-[10px] text-mc-muted">(provider auth unknown)</span>
                  ) : null}
                </div>

                <div className="flex gap-1.5 flex-wrap">
                  <span className="mc-chip inline-flex items-center gap-1">
                    <CheckCircle2 size={10} /> {a.skills_count} skill
                  </span>
                  <span className="mc-chip">Created {a.created_at}</span>
                  {live.detail ? <span className="mc-chip text-mc-muted">{live.detail}</span> : null}
                </div>

                <div className="text-[11px] text-mc-faint font-mono border-t border-mc-border pt-2">
                  persona {a.persona_chars} char
                  {live.sessions != null ? ` · ${live.sessions} sesi` : ""}
                </div>

                <button
                  onClick={() => setProfileFor(a)}
                  className="mt-2 w-full mc-btn-ghost inline-flex items-center justify-center gap-1.5 text-[12px]"
                  aria-label={`Detail persona & governance ${a.name}`}
                >
                  <Eye size={13} /> Detail persona & governance
                </button>
              </div>
            );
          })}
        </div>
      )}

      <DelegationsBlock blk={deleg} />

      {profileFor ? (
        <AgentProfileModal agent={profileFor} onClose={() => setProfileFor(null)} />
      ) : null}
      {creating ? (
        <AgentFormModal onClose={() => setCreating(false)} onSaved={() => { setCreating(false); load(); }} />
      ) : null}
      {edit ? (
        <AgentFormModal agent={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} />
      ) : null}
      {del ? (
        <ConfirmModal
          title="Hapus agent?"
          target={del.name}
          impact="Agent akan dihapus dari roster. Konfigurasi runtime yang sudah ada tidak diaktifkan atau dijalankan oleh tindakan ini. Pastikan target yang dipilih benar sebelum melanjutkan."
          busy={deleteBusy}
          error={msg && msg.kind === "err" ? msg.text : null}
          onClose={() => { if (!deleteBusy) { setDel(null); setMsg(null); } }}
          onConfirm={() => delAgent(del)}
        />
      ) : null}
    </>
  );
}

// --- form buat/edit agent (identity + persona + model + skills) -------------
function SkillChips({ skills, selected, onToggle }) {
  const cats = {};
  for (const s of skills) {
    (cats[s.category || "lainnya"] = cats[s.category || "lainnya"] || []).push(s.name);
  }
  if (!Object.keys(cats).length) return <div className="text-[12px] text-mc-muted">memuat skill…</div>;
  return (
    <div className="flex flex-col gap-3">
      {Object.entries(cats).sort((a, b) => a[0].localeCompare(b[0])).map(([cat, names]) => (
        <div key={cat}>
          <div className="text-[10.5px] uppercase tracking-wider text-mc-muted mb-1.5">{cat}</div>
          <div className="flex flex-wrap gap-1.5">
            {names.map((n) => {
              const on = selected.includes(n);
              return (
                <button
                  key={n}
                  type="button"
                  onClick={() => onToggle(n)}
                  className={`mc-chip cursor-pointer transition-colors duration-150 ${on ? "!text-sky-300 !border-sky-400/60 !bg-sky-400/15 shadow-[0_0_10px_-4px_rgba(56,189,248,0.5)]" : "text-mc-muted hover:text-mc-text hover:border-white/25"}`}
                  aria-pressed={on}
                >
                  {on ? "✓ " : ""}{n}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function GovernanceEditor({ profile, onChange }) {
  const scalarFields = [
    ["mission", "Mission"],
    ["authority", "Authority"],
    ["operating_mode", "Operating mode"],
    ["language", "Language"],
    ["verification", "Verification"],
    ["escalation", "Escalation"],
  ];
  const listFields = [
    ["allowed_actions", "Allowed actions"],
    ["forbidden_actions", "Forbidden actions"],
    ["inputs", "Inputs"],
    ["outputs", "Outputs"],
  ];
  const setScalar = (field, value) => onChange({ ...profile, [field]: value });
  const setListItem = (field, index, value) => {
    const values = [...profile[field]];
    values[index] = value;
    onChange({ ...profile, [field]: values });
  };
  const addListItem = (field) => onChange({ ...profile, [field]: [...profile[field], ""] });
  const removeListItem = (field, index) => {
    const values = profile[field].filter((_value, itemIndex) => itemIndex !== index);
    onChange({ ...profile, [field]: values });
  };
  return (
    <div className="flex flex-col gap-4">
      <div className="text-[11px] leading-relaxed text-mc-muted">
        Governance profile mengatur batas kerja agent. Isi semua field; perubahan ini hanya memperbarui konfigurasi roster dan tidak mengaktifkan runtime otonom.
      </div>
      {scalarFields.map(([field, label]) => (
        <label key={field} className="flex flex-col gap-1.5">
          <span className="text-[11px] font-semibold text-mc-muted">{label}</span>
          <textarea
            className="mc-input w-full resize-y text-[12px] leading-relaxed"
            rows={3}
            maxLength={4000}
            value={profile[field]}
            onChange={(e) => setScalar(field, e.target.value)}
            aria-label={`Governance ${label}`}
          />
        </label>
      ))}
      {listFields.map(([field, label]) => (
        <div key={field} className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-semibold text-mc-muted">{label}</span>
            <button
              type="button"
              className="mc-btn-ghost text-[11px] px-2 py-1 inline-flex items-center gap-1"
              onClick={() => addListItem(field)}
              disabled={profile[field].length >= 50}
            >
              <Plus size={11} /> Tambah
            </button>
          </div>
          <div className="flex flex-col gap-2">
            {profile[field].map((value, index) => (
              <div key={`${field}-${index}`} className="flex items-start gap-2">
                <textarea
                  className="mc-input w-full resize-y text-[12px] leading-relaxed"
                  rows={2}
                  maxLength={2000}
                  value={value}
                  onChange={(e) => setListItem(field, index, e.target.value)}
                  aria-label={`${label} ${index + 1}`}
                />
                <button
                  type="button"
                  className="mc-btn-ghost text-rose-300 px-2 py-2 shrink-0"
                  onClick={() => removeListItem(field, index)}
                  aria-label={`Hapus ${label} ${index + 1}`}
                  title="Hapus item"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

const GOVERNANCE_SCALAR_FIELDS = ["mission", "authority", "operating_mode", "language", "verification", "escalation"];
const GOVERNANCE_LIST_FIELDS = ["allowed_actions", "forbidden_actions", "inputs", "outputs"];
const GOVERNANCE_FIELD_ORDER = [
  "mission", "authority", "operating_mode", "language", "allowed_actions",
  "forbidden_actions", "inputs", "outputs", "verification", "escalation",
];

function blankGovernanceProfile() {
  return {
    mission: "",
    authority: "",
    operating_mode: "",
    language: "",
    allowed_actions: [""],
    forbidden_actions: [""],
    inputs: [""],
    outputs: [""],
    verification: "",
    escalation: "",
  };
}

function normalizeGovernanceProfile(profile) {
  if (!profile || typeof profile !== "object") return null;
  const next = {};
  for (const field of GOVERNANCE_SCALAR_FIELDS) next[field] = typeof profile[field] === "string" ? profile[field] : "";
  for (const field of GOVERNANCE_LIST_FIELDS) next[field] = Array.isArray(profile[field]) ? profile[field].map((item) => typeof item === "string" ? item : "") : [];
  return next;
}

function validateGovernanceProfile(profile) {
  if (!profile) return "";
  for (const field of GOVERNANCE_SCALAR_FIELDS) {
    if (!String(profile[field] || "").trim()) return `Governance ${field} wajib diisi.`;
  }
  for (const field of GOVERNANCE_LIST_FIELDS) {
    const values = profile[field];
    if (!Array.isArray(values) || !values.length || values.some((value) => !String(value || "").trim())) {
      return `Governance ${field} harus memiliki item yang tidak kosong.`;
    }
  }
  return "";
}

function cleanGovernanceProfile(profile) {
  if (!profile || typeof profile !== "object") return null;
  const next = {};
  for (const field of GOVERNANCE_FIELD_ORDER) {
    next[field] = GOVERNANCE_SCALAR_FIELDS.includes(field)
      ? String(profile[field] || "").trim()
      : profile[field].map((value) => String(value || "").trim());
  }
  return next;
}

function AgentFormModal({ agent, onClose, onSaved }) {
  const isEdit = !!agent;
  const [modelsData, setModelsData] = useState(null);
  const [skillList, setSkillList] = useState([]);
  const [name, setName] = useState((agent && agent.name) || "");
  const [role, setRole] = useState((agent && agent.role) || "");
  const [persona, setPersona] = useState("");
  const [provider, setProvider] = useState((agent && agent.model_provider) || "");
  const [modelId, setModelId] = useState((agent && agent.model_id) || "");
  const [skills, setSkills] = useState((agent && agent.skills) || []);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);
  const [governanceProfile, setGovernanceProfile] = useState(null);
  const [governanceLoading, setGovernanceLoading] = useState(isEdit);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState(null);
  const personaRef = useRef(null);

  // auto-grow textarea persona: tinggi mengikuti isi (maks 340px) supaya
  // tidak ada scrollbar ganda (textarea vs body modal) untuk persona normal
  useEffect(() => {
    const el = personaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 340) + "px";
  }, [persona]);

  useEffect(() => {
    let cancelled = false;
    setModelsLoading(true);
    setModelsError(null);
    safeFetchJSON(`${EP}/models`)
      .then((d) => {
        if (!cancelled) setModelsData(d && d.models ? d.models : null);
      })
      .catch((e) => {
        if (!cancelled) {
          setModelsData(null);
          setModelsError(String((e && e.message) || e));
          notifyUnauthorized(e);
        }
      })
      .finally(() => {
        if (!cancelled) setModelsLoading(false);
      });
    safeFetchJSON(`${EP}/memory`)
      .then((d) => setSkillList((d.skills && d.skills.skills) || []))
      .catch(() => setSkillList([]));
    if (agent) {
      setGovernanceLoading(true);
      safeFetchJSON(`${EP}/agent-persona?id=${encodeURIComponent(agent.id)}`)
        .then((d) => {
          setPersona((d && d.persona) || "");
          setGovernanceProfile(normalizeGovernanceProfile(d && d.persona_profile));
        })
        .catch((e) => {
          setPersona("");
          setGovernanceProfile(null);
          setErr(String((e && e.message) || "Governance profile tidak tersedia."));
        })
        .finally(() => setGovernanceLoading(false));
    } else {
      setGovernanceLoading(false);
      setGovernanceProfile(null);
    }
    return () => { cancelled = true; };
  }, [agent]);

  useEffect(() => {
    const catalog = modelProviderMap(modelsData);
    const provs = Object.keys(catalog);
    if (!provider && provs.length) {
      setProvider(provs[0]);
      setModelId(catalog[provs[0]][0] || "");
    }
    // Keep an existing roster assignment visible even if a later catalog refresh
    // no longer advertises that exact model; PATCH omits unchanged model fields.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelsData]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const catalogProviders = modelProviderMap(modelsData);
  if (isEdit && provider && modelId) {
    catalogProviders[provider] = Array.from(new Set([modelId, ...(catalogProviders[provider] || [])]));
  }
  const providers = Object.keys(catalogProviders);
  const modelOptions = (provider && catalogProviders[provider]) || [];

  function toggleSkill(n) {
    setSkills((prev) => (prev.includes(n) ? prev.filter((x) => x !== n) : [...prev, n]));
  }

  async function save(payloadOverride) {
    setSaving(true);
    setErr(null);
    let payload = payloadOverride;
    if (!payload) {
      const selectedModel = provider && modelId ? `${provider}/${modelId}` : "";
      const initialModel = agent && (agent.model || `${agent.model_provider || ""}/${agent.model_id || ""}`);
      if (!selectedModel && !isEdit) {
        setErr("Pilih provider dan model yang tersedia.");
        setSaving(false);
        return;
      }
      if (isEdit && governanceProfile) {
        const governanceError = validateGovernanceProfile(governanceProfile);
        if (governanceError) {
          setErr(governanceError);
          setSaving(false);
          return;
        }
      }
      payload = {
        name: name.trim(),
        role: role.trim(),
        persona,
        skills,
      };
      if (isEdit && governanceProfile) payload.persona_profile = cleanGovernanceProfile(governanceProfile);
      // Do not re-submit an unchanged legacy assignment that is no longer in the
      // live catalog; changing the model still requires exact backend validation.
      if (!isEdit || selectedModel !== initialModel) payload.model = selectedModel;
    }
    try {
      const r = await safeFetchJSON(isEdit ? `${EP}/agents/${agent.id}` : `${EP}/agents`, {
        method: isEdit ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (r && r.status === "ok") {
        let readback = null;
        if (isEdit) {
          readback = await safeFetchJSON(`${EP}/agent-persona?id=${encodeURIComponent(agent.id)}`);
          if (payload.persona_profile && JSON.stringify(cleanGovernanceProfile(readback.persona_profile)) !== JSON.stringify(cleanGovernanceProfile(payload.persona_profile))) {
            throw new Error("Readback governance profile tidak sama dengan nilai yang disimpan.");
          }
        }
        onSaved(readback);
      } else {
        setErr((r && r.error) || "gagal menyimpan");
        setSaving(false);
      }
    } catch (e) {
      setErr(e.message || "gagal menyimpan");
      setSaving(false);
    }
  }

  function savePersonaOnly() {
    save({ persona });
  }

  return (
    <Modal
      title={isEdit ? "Edit agent" : "Buat agent baru"}
      subtitle={isEdit ? `Agent: ${agent.name}` : "Role, persona, model & tools sendiri"}
      onClose={onClose}
      contentClassName="py-5 flex flex-col gap-6"
      footer={(
        <>
          <button type="button" className="mc-btn-ghost" onClick={onClose}>Batal</button>
          <button type="button" className="mc-btn-primary" disabled={saving || !name.trim()} onClick={() => save()} aria-busy={saving}>
            {saving ? "Menyimpan…" : isEdit ? "Simpan perubahan" : "Buat agent"}
          </button>
        </>
      )}
    >
      {err ? <Feedback kind="err">{err}</Feedback> : null}

            <div>
              <h4 className="m-0 text-[11px] font-semibold uppercase tracking-wider text-mc-muted mb-2.5">Identitas</h4>
              <div className="flex flex-col gap-2">
                <input className="mc-input" placeholder="Nama agent (mis. Afi)" value={name} maxLength={40}
                       onChange={(e) => setName(e.target.value)} aria-label="Nama agent" />
                <input className="mc-input" placeholder="Role / deskripsi (mis. Content Creator UGC affiliate)"
                       value={role} maxLength={120} onChange={(e) => setRole(e.target.value)} aria-label="Role agent" />
              </div>
            </div>

            <div>
              <h4 className="m-0 text-[11px] font-semibold uppercase tracking-wider text-mc-muted mb-2.5">Persona</h4>
              <textarea ref={personaRef} className="mc-input w-full resize-none text-[12px] leading-relaxed" rows={12}
                        placeholder="Instruksi & kepribadian agent ini…"
                        value={persona} onChange={(e) => setPersona(e.target.value)} aria-label="Persona" />
              <div className="flex justify-end mt-1.5">
                <button type="button" className="mc-btn-ghost text-[11.5px] px-3 py-1.5 inline-flex items-center gap-1.5" onClick={savePersonaOnly} disabled={saving}>
                  <Save size={12} /> {saving ? "Menyimpan…" : "Save persona"}
                </button>
              </div>
            </div>

            {isEdit ? (
              <div>
                <div className="flex items-center justify-between gap-2 mb-2.5">
                  <h4 className="m-0 text-[11px] font-semibold uppercase tracking-wider text-mc-muted">Governance profile</h4>
                  {governanceProfile ? <span className="text-[10px] text-mc-muted">10 field terstruktur</span> : null}
                </div>
                {governanceLoading ? <Loading /> : governanceProfile ? (
                  <GovernanceEditor profile={governanceProfile} onChange={setGovernanceProfile} />
                ) : (
                  <div className="rounded-xl border border-dashed border-mc-border p-3.5 text-[11.5px] leading-relaxed text-mc-muted">
                    Agent ini belum memiliki governance profile. Tambahkan profile lengkap bila ingin menyimpan aturan mission, authority, actions, inputs, outputs, verification, dan escalation.
                    <div className="mt-2.5">
                      <button type="button" className="mc-btn-ghost text-[11px] px-2.5 py-1.5 inline-flex items-center gap-1.5" onClick={() => setGovernanceProfile(blankGovernanceProfile())}>
                        <Plus size={12} /> Tambah governance profile
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ) : null}

            <div>
              <h4 className="m-0 text-[11px] font-semibold uppercase tracking-wider text-mc-muted mb-2.5">Model utama</h4>
              <div className="flex flex-col gap-2">
                {modelsLoading ? <Loading /> : null}
                {modelsError ? <Feedback kind="err">Daftar model tidak tersedia: {modelsError}</Feedback> : null}
                {!modelsLoading && !modelsError && !providers.length ? <Empty msg="belum ada provider/model yang bisa dipilih" /> : null}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 items-stretch">
                  <select
                    className="mc-input w-full min-w-0"
                    value={provider}
                    disabled={modelsLoading || !providers.length}
                    onChange={(e) => {
                      const next = e.target.value;
                      setProvider(next);
                      setModelId((catalogProviders[next] || [])[0] || "");
                    }}
                    aria-label="Provider"
                  >
                    {!providers.length ? <option value="">tidak ada provider</option> : null}
                    {providers.map((p) => <option key={p} value={p}>{p}</option>)}
                  </select>
                  <select
                    className="mc-input w-full min-w-0"
                    value={modelId}
                    disabled={modelsLoading || !modelOptions.length}
                    onChange={(e) => setModelId(e.target.value)}
                    aria-label="Model"
                  >
                    {!modelOptions.length ? <option value="">tidak ada model</option> : null}
                    {modelOptions.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
                <p className="m-0 text-[11.5px] leading-relaxed text-mc-muted">
                  {providers.length} provider · {providers.reduce((n, p) => n + (catalogProviders[p] || []).length, 0)} model tersedia · validasi server memakai katalog yang sama.
                  Helper models opsional — dapat ditambahkan lewat API/CLI nanti.
                </p>
              </div>
            </div>

            <div>
              <h4 className="m-0 text-[11px] font-semibold uppercase tracking-wider text-mc-muted mb-2.5">
                Tools & Skills ({skills.length} dipilih)
              </h4>
              <SkillChips skills={skillList} selected={skills} onToggle={toggleSkill} />
            </div>
    </Modal>
  );
}

function CoolifyPanel() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);
  const [deploying, setDeploying] = useState({ uuid: null, app: null, phase: "idle" }); // idle|confirm|busy|done|err
  const [msg, setMsg] = useState(null); // { kind, text }

  function load() {
    setLoading(true);
    safeFetchJSON(`${EP}/coolify`)
      .then((d) => {
        setData(d);
        setErr(null);
      })
      .catch((e) => {
        notifyUnauthorized(e);
        setErr(e.message || "gagal memuat status Coolify");
      })
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function doDeploy(app) {
    setDeploying({ uuid: app.uuid, app, phase: "busy" });
    setMsg(null);
    try {
      const r = await safeFetchJSON(`${EP}/coolify/deploy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ uuid: app.uuid }),
      });
      const ok = r && r.status === "queued";
      const nextMsg = ok
        ? { kind: "ok", text: `Deploy dikirim: ${app.name} ✓ — refresh untuk status baru` }
        : { kind: "err", text: (r && r.error) || "deploy ditolak" };
      setDeploying({ uuid: app.uuid, app, phase: ok ? "done" : "err" });
      setMsg(nextMsg);
      if (ok) setTimeout(load, 3000);
    } catch (e) {
      setDeploying({ uuid: app.uuid, app, phase: "err" });
      setMsg({ kind: "err", text: e.message || "gagal deploy" });
    }
  }

  if (err && !data) return <Unavailable msg={err} />;

  const st = (data && data.status) || null;
  const apps = (data && data.items) || [];
  const statusTone = (s) =>
    s === "running:healthy" ? "ok" : s === "running:unknown" || s === "running" ? "warn" : "bad";

  return (
    <Card title="Coolify — status aplikasi" busy={loading || deploying.phase === "busy"}>
      <div className="mc-fresh mb-0.5">
        {err ? (
          `sumber: ${err}`
        ) : loading ? (
          "memuat…"
        ) : (
          `data: ${data.generated_at || ""} · api Coolify v4`
        )}{" "}
        <button type="button" onClick={load} className="ml-1 mc-btn-ghost inline-flex items-center gap-1 text-[11px] px-2 py-0.5" aria-label="Muat ulang status" aria-busy={loading}>
          <RefreshCw size={11} className={loading ? "mc-spin" : ""} aria-hidden="true" /> muat ulang
        </button>
      </div>

      {msg && !deploying.app ? <Feedback kind={msg.kind}>{msg.text}</Feedback> : null}

      {st === "ok" ? (
        <>
          <div className="flex gap-1.5 flex-wrap mb-3">
            <span className="mc-chip">total: {data.total}</span>
            <span className="mc-chip inline-flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400" /> sehat: {data.healthy}
            </span>
            <span className="mc-chip inline-flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" /> berjalan*: {data.degraded}
            </span>
            <span className="mc-chip inline-flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-400" /> mati: {data.down}
            </span>
          </div>
          <div className="flex flex-col gap-2">
            {apps.map((a) => (
              <div key={a.uuid} className="rounded-xl bg-mc-sidebar/50 border border-mc-border p-3 flex flex-col gap-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className={`w-2 h-2 rounded-full ${a.status === "running:healthy" ? "bg-green-400 shadow-[0_0_8px_#4ade80]" : a.status.startsWith("running") ? "bg-amber-400" : "bg-rose-400"}`}
                    title={a.status}
                  />
                  <span className="text-[13px] font-semibold text-mc-text">{a.name}</span>
                  <Badge tone={statusTone(a.status)} className="text-[10.5px]">{a.status}</Badge>
                  {a.healthcheck ? (
                    <span className="mc-chip text-[10.5px] inline-flex items-center gap-1">
                      <CheckCircle2 size={10} /> healthcheck
                    </span>
                  ) : (
                    <span className="mc-chip text-[10.5px] text-mc-faint">tanpa healthcheck</span>
                  )}
                  {a.repo ? <span className="mc-chip text-[10.5px] font-mono text-mc-muted">{a.repo}</span> : null}
                </div>
                {a.fqdn ? (
                  <div className="flex items-center gap-1.5 flex-wrap text-[11.5px]">
                    {a.fqdn.split(",").slice(0, 3).filter(Boolean).map((f) => (
                      <a key={f} href={f} target="_blank" rel="noreferrer"
                         className="inline-flex items-center gap-1 text-sky-300 hover:text-sky-200 break-all">
                        <ExternalLink size={11} /> {f}
                      </a>
                    ))}
                  </div>
                ) : (
                  <div className="text-[11.5px] text-mc-faint">tanpa domain publik</div>
                )}
                <div className="flex items-center justify-between gap-2 flex-wrap text-[10.5px] text-mc-faint font-mono">
                  <span>port: {a.ports || "—"} · update: {a.updated_at || "—"}</span>
                  <button
                    onClick={() => { setMsg(null); setDeploying({ uuid: a.uuid, app: a, phase: "confirm" }); }}
                    disabled={deploying.phase === "busy" || deploying.phase === "done"}
                    className="mc-btn-ghost inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px]"
                    aria-label={`Redeploy ${a.name}`}
                  >
                    {deploying.uuid === a.uuid && deploying.phase === "done" ? (
                      <><Check size={11} /> terkirim</>
                    ) : (
                      <><Rocket size={11} /> redeploy</>
                    )}
                  </button>
                </div>
              </div>
            ))}
          </div>
          <div className="text-[10.5px] text-mc-faint mt-2.5">
            * berjalan tanpa status healthy (mis. running:unknown). Relasi proyek↔aplikasi tidak diekspos API Coolify — ditampilkan repo git sebagai pengganti.
          </div>
        </>
      ) : st === "unavailable" ? (
        <Unavailable msg={(data && data.error) || "status tidak tersedia"} />
      ) : (
        <Unavailable msg="belum ada data" />
      )}
      {deploying.app ? (
        <ConfirmModal
          title="Konfirmasi redeploy Coolify"
          target={deploying.app.name || deploying.app.uuid}
          impact="Deploy ulang akan mengirim aplikasi ini ke antrean Coolify dan dapat menyebabkan restart singkat. Pastikan target sudah benar sebelum mengonfirmasi."
          busy={deploying.phase === "busy"}
          error={deploying.phase === "err" ? (msg && msg.text) : null}
          success={deploying.phase === "done" ? (msg && msg.text) : null}
          confirmLabel={deploying.phase === "err" ? "Coba lagi" : "Konfirmasi redeploy"}
          busyLabel="Mengirim deploy…"
          confirmIcon={Rocket}
          confirmClassName="!text-amber-300 !border-amber-400/40"
          onClose={() => { if (deploying.phase !== "busy") { setDeploying({ uuid: null, app: null, phase: "idle" }); setMsg(null); } }}
          onConfirm={() => doDeploy(deploying.app)}
        />
      ) : null}
    </Card>
  );
}

function SectionLabel({ children }) {
  return (
    <h4 className="m-0 text-[11px] font-semibold uppercase tracking-wider text-mc-muted mb-1.5">
      {children}
    </h4>
  );
}

function Sub({ title, children }) {
  return (
    <div>
      <SectionLabel>{title}</SectionLabel>
      {children}
    </div>
  );
}

function AgentProfileModal({ agent, onClose }) {
  const [personaData, setPersonaData] = useState(null);
  const [legacyProfile, setLegacyProfile] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    setPersonaData(null);
    setLegacyProfile(null);
    setErr(null);
    safeFetchJSON(`${EP}/agent-persona?id=${encodeURIComponent(agent.id)}`)
      .then((d) => {
        if (alive) setPersonaData(d);
      })
      .catch((e) => {
        if (alive) setErr(e.message || "gagal memuat persona");
      });

    const runtimeAdapter = agent && agent.routing && agent.routing.runtime_adapter;
    const legacyKey = {
      hermes_lead: "lead_agent",
      agent_engineer: "agent_engineer",
      opencode: "opencode_workers",
    }[runtimeAdapter];
    if (legacyKey) {
      safeFetchJSON(`${EP}/agent-profile?agent=${encodeURIComponent(legacyKey)}`)
        .then((d) => {
          if (alive) setLegacyProfile((d && d.profile) || null);
        })
        .catch(() => {
          // General roster profile remains useful when legacy detail is unavailable.
        });
    }
    return () => {
      alive = false;
    };
  }, [agent.id]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const governance = agent.persona_profile && typeof agent.persona_profile === "object" ? agent.persona_profile : null;
  const skills = Array.isArray(agent.skills) ? agent.skills : [];
  const personaText = personaData && typeof personaData.persona === "string" ? personaData.persona : "";
  const live = agent.live || {};
  const workspace = agent.drive_workspace || {};
  const legacy = legacyProfile || {};
  const legacyMemory = legacy.memory || {};
  const legacyDelegations = legacy.delegations || {};
  const legacyModels = legacy.models || {};

  const listSection = (title, values) => (
    <Sub title={title}>
      {Array.isArray(values) && values.length ? (
        <div className="flex flex-col gap-1.5">
          {values.map((value, i) => (
            <div key={`${title}-${i}`} className="text-[12px] leading-relaxed text-mc-muted flex gap-2">
              <span className="text-sky-300 shrink-0">•</span>
              <span>{value}</span>
            </div>
          ))}
        </div>
      ) : (
        <Empty msg="belum ada data" />
      )}
    </Sub>
  );

  return (
    <Modal
      title={agent.name}
      subtitle={agent.role || "Role belum tersedia"}
      onClose={onClose}
      wide
      contentClassName="p-5"
      headerContent={(
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[15px] font-semibold text-mc-text">{agent.name}</span>
          <Badge tone={live.status === "online" ? "ok" : live.status === "standby" ? "info" : "neutral"}>{live.status || "unknown"}</Badge>
          {agent.active ? <span className="mc-chip text-[10.5px]">active</span> : null}
        </div>
      )}
    >
      <div className="flex flex-col gap-4">
            {err ? <Unavailable msg={err} /> : !personaData ? <Loading /> : null}

            <Card title="Governance profile" right={<Badge tone={governance ? "ok" : "neutral"}>{governance ? "tersedia" : "kosong"}</Badge>}>
              {!governance ? (
                <Empty msg="persona_profile belum disimpan untuk agent ini" />
              ) : (
                <div className="flex flex-col gap-4">
                  <Sub title="Mission"><p className="m-0 text-[12.5px] leading-relaxed text-mc-muted">{governance.mission}</p></Sub>
                  <Sub title="Authority"><p className="m-0 text-[12.5px] leading-relaxed text-mc-muted">{governance.authority}</p></Sub>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <Sub title="Operating mode"><p className="m-0 text-[12px] leading-relaxed text-mc-muted">{governance.operating_mode}</p></Sub>
                    <Sub title="Language"><p className="m-0 text-[12px] leading-relaxed text-mc-muted">{governance.language}</p></Sub>
                  </div>
                  {listSection("Allowed actions", governance.allowed_actions)}
                  {listSection("Forbidden actions", governance.forbidden_actions)}
                  {listSection("Inputs", governance.inputs)}
                  {listSection("Outputs", governance.outputs)}
                  <Sub title="Verification"><p className="m-0 text-[12.5px] leading-relaxed text-mc-muted">{governance.verification}</p></Sub>
                  <Sub title="Escalation"><p className="m-0 text-[12.5px] leading-relaxed text-mc-muted">{governance.escalation}</p></Sub>
                </div>
              )}
            </Card>

            <Card title={`Persona (${agent.persona_chars || personaText.length} char)`} right={<Badge tone={personaText ? "ok" : "neutral"}>{personaText ? "tersedia" : "kosong"}</Badge>}>
              {personaText ? (
                <pre className="mc-pre text-[12px] leading-relaxed whitespace-pre-wrap break-words">{personaText}</pre>
              ) : (
                <Empty msg="persona belum tersedia" />
              )}
            </Card>

            <Card title={`Skills (${skills.length})`} right={<Badge tone={agent.skills_valid === false ? "warn" : skills.length ? "ok" : "neutral"}>{agent.skills_valid === false ? "periksa" : `${skills.length} skill`}</Badge>}>
              {skills.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {skills.map((skill) => <span key={skill} className="mc-chip text-[10.5px]">{skill}</span>)}
                </div>
              ) : (
                <Empty msg="tidak ada skill yang ditugaskan" />
              )}
              {agent.skills_valid === false ? <div className="mc-err mt-2">Assignment skill tidak seluruhnya ditemukan: {(agent.invalid_skills || []).join(", ") || "Unknown"}</div> : null}
            </Card>

            <Card title="Konfigurasi & runtime">
              <Row k="Model" v={agent.model || "—"} />
              <Row k="Live" v={`${live.status || "unknown"}${live.detail ? ` · ${live.detail}` : ""}`} mono={false} />
              <Row k="Workspace" v={`${workspace.status || "pending"}${workspace.name ? ` · ${workspace.name}` : ""}`} mono={false} />
              <Row k="Dibuat" v={agent.created_at || "—"} />
              <Row k="Diubah" v={agent.updated_at || "—"} />
            </Card>

            {legacyMemory.MEMORY || legacyMemory.USER ? (
              <Card title="Memori global (read-only)">
                {legacyMemory.MEMORY ? (
                  <Sub title={`MEMORY.md (${legacyMemory.MEMORY.chars || "?"} char)`}>
                    <pre className="mc-pre text-[12px] leading-relaxed whitespace-pre-wrap break-words">{legacyMemory.MEMORY.content || "—"}{legacyMemory.MEMORY.truncated ? "\n… (dipotong)" : ""}</pre>
                  </Sub>
                ) : null}
                {legacyMemory.USER ? (
                  <Sub title={`USER.md (${legacyMemory.USER.chars || "?"} char)`}>
                    <pre className="mc-pre text-[12px] leading-relaxed whitespace-pre-wrap break-words">{legacyMemory.USER.content || "—"}{legacyMemory.USER.truncated ? "\n… (dipotong)" : ""}</pre>
                  </Sub>
                ) : null}
              </Card>
            ) : null}

            {legacyDelegations.states || legacyDelegations.recent ? (
              <Card title="Riwayat delegasi (read-only)">
                {legacyDelegations.states ? (
                  <div className="flex flex-wrap gap-1.5 mb-2">
                    {Object.entries(legacyDelegations.states).map(([key, value]) => <span key={key} className="mc-chip text-[11px]">{key}: {value}</span>)}
                  </div>
                ) : null}
                {Array.isArray(legacyDelegations.recent) && legacyDelegations.recent.length ? (
                  <div className="flex flex-col gap-1.5">
                    {legacyDelegations.recent.slice(0, 6).map((row, i) => <div key={row.delegation_id || row.id || i} className="text-[11px] font-mono text-mc-muted flex justify-between gap-2"><span className="truncate">{(row.delegation_id || row.id || "?").slice(0, 14)}</span><span className="mc-chip text-[10px]">{row.state || "?"}</span></div>)}
                  </div>
                ) : <Empty msg="belum ada delegasi tercatat" />}
              </Card>
            ) : null}

            {legacyModels && Object.keys(legacyModels).length ? (
              <Card title="Model gateway & sesi worker (read-only)">
                <Row k="Default" v={legacyModels.default || "—"} />
                <Row k="Model terdaftar" v={legacyModels.total ?? "—"} />
                <Row k="Provider" v={(legacyModels.provider_names || []).join(", ") || "—"} mono={false} />
                <Row k="Sesi tercatat" v={legacy.sessions_total ?? "—"} />
                <Row k="Aktif 15 mnt" v={legacy.active_sessions_recent ?? "—"} />
              </Card>
            ) : null}
      </div>
    </Modal>
  );
}

// --- PANEL: Tasks (kanban) -------------------------------------------------------
const TASK_TONE = {
  ready: "info", running: "ok", done: "ok", released: "info",
  blocked: "warn", timed_out: "warn",
  crashed: "bad", failed: "bad",
};

function TasksPanel() {
  // `tick` memicu polling langsung load ulang setelah create/complete
  const [tick, setTick] = useState(0);
  const { data, error, refreshing } = usePolling(`${EP}/tasks`, POLL_TASKS_MS, tick);

  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState("2");
  const [submitting, setSubmitting] = useState(false);
  const [completingId, setCompletingId] = useState(null);
  const [completeTarget, setCompleteTarget] = useState(null); // { id, title } saat modal terbuka
  const [resultText, setResultText] = useState("");
  const [resultErr, setResultErr] = useState(null);
  const resultRef = useRef(null);
  const [msg, setMsg] = useState(null); // { kind: "ok" | "err", text }

  async function handleCreate(e) {
    e.preventDefault();
    const t = title.trim();
    if (!t) {
      setMsg({ kind: "err", text: "Judul task wajib diisi." });
      return;
    }
    setSubmitting(true);
    setMsg(null);
    try {
      const json = await safeFetchJSON(`${EP}/tasks/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: t, priority: Number(priority) }),
      });
      if (json && json.status === "ok") {
        setTitle("");
        setMsg({ kind: "ok", text: `Task dibuat: ${json.task_id || "?"} ✓` });
        setTick((x) => x + 1);
      } else {
        setMsg({ kind: "err", text: (json && json.message) || "Gagal membuat task." });
      }
    } catch (err) {
      notifyUnauthorized(err);
      setMsg({ kind: "err", text: String((err && err.message) || err) });
    } finally {
      setSubmitting(false);
    }
  }

  async function handleComplete(taskId) {
    const r = resultText.trim();
    if (!r) {
      setResultErr("Ringkasan hasil wajib diisi — task tidak bisa diselesaikan tanpa bukti.");
      return;
    }
    setCompletingId(taskId);
    setResultErr(null);
    setMsg(null);
    try {
      const json = await safeFetchJSON(`${EP}/tasks/${encodeURIComponent(taskId)}/complete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ result: r }),
      });
      if (json && json.status === "ok") {
        setMsg({ kind: "ok", text: `Task ${taskId} selesai ✓` });
        setCompleteTarget(null);
        setResultText("");
        setTick((x) => x + 1);
      } else {
        setResultErr((json && json.message) || "Gagal menyelesaikan task.");
      }
    } catch (err) {
      notifyUnauthorized(err);
      const txt = String((err && err.message) || err);
      setResultErr(txt.startsWith("HTTP") ? "Gagal menyelesaikan task." : txt);
    } finally {
      setCompletingId(null);
    }
  }

  if (!data && !error) return <Loading />;
  if (error) {
    return (
      <Card title="Tasks">
        <Unavailable msg={error} />
      </Card>
    );
  }

  const kb = data.kanban || {};
  const ok = kb.status === "ok";
  const counts = { ...(kb.status_counts || {}), ...(kb.other_statuses || {}) };
  const latest = kb.latest || [];
  const runs = kb.task_runs || {};
  const hasAny = Object.values(counts).some((n) => n > 0);

  return (
    <>
      <Card
        title="Buat Task Baru"
        right={<Badge tone="info">tulis via CLI kanban</Badge>}
      >
        <form onSubmit={handleCreate} className="flex flex-col gap-2">
          <div className="flex gap-2 flex-wrap items-center">
            <input
              className="mc-input"
              placeholder="Judul task… (maks 200 karakter)"
              value={title}
              maxLength={200}
              onChange={(e) => setTitle(e.target.value)}
              aria-label="Judul task baru"
            />
            <select
              className="mc-select"
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              aria-label="Prioritas task baru"
            >
              <option value="1">P1 — tinggi</option>
              <option value="2">P2 — normal</option>
              <option value="3">P3 — rendah</option>
            </select>
            <button
              type="submit"
              className="mc-btn-primary"
              disabled={submitting}
              aria-busy={submitting}
            >
              {submitting ? "Membuat…" : "Buat Task"}
            </button>
          </div>
          {msg ? <Feedback kind={msg.kind}>{msg.text}</Feedback> : null}
        </form>
      </Card>

      <Card
        title="Tasks (kanban.db)"
        right={
          <div className="flex items-center gap-2">
            <button
              className="mc-btn-ghost"
              onClick={() => {
                const rows = latest.map((t) => ({
                  id: t.id,
                  title: t.title,
                  status: t.status,
                  priority: t.priority,
                  assignee: t.assignee || "",
                  started_at: t.started_at_iso || "",
                  result: t.result || "",
                }));
                const blob = new Blob([JSON.stringify(rows, null, 2)], {
                  type: "application/json",
                });
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = `mission-control-tasks-${new Date().toISOString().slice(0, 10)}.json`;
                a.click();
                URL.revokeObjectURL(a.href);
              }}
              aria-label="Ekspor task ke JSON"
            >
              <Download size={13} /> JSON
            </button>
            <button
              className="mc-btn-ghost"
              onClick={() => {
                const esc = (v) =>
                  `"${String(v ?? "").replace(/"/g, '""')}"`;
                const head = ["id", "title", "status", "priority", "assignee", "started_at", "result"];
                const rows = latest.map((t) =>
                  [t.id, t.title, t.status, t.priority, t.assignee || "", t.started_at_iso || "", t.result || ""]
                    .map(esc)
                    .join(",")
                );
                const csv = [head.join(","), ...rows].join("\n");
                const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = `mission-control-tasks-${new Date().toISOString().slice(0, 10)}.csv`;
                a.click();
                URL.revokeObjectURL(a.href);
              }}
              aria-label="Ekspor task ke CSV"
            >
              <Download size={13} /> CSV
            </button>
            <Badge tone={ok ? (hasAny ? "ok" : "neutral") : "bad"}>{ok ? `${kb.total_tasks ?? 0} task` : "unavailable"}</Badge>
          </div>
        }
      >
        {!ok ? (
          <Unavailable msg={kb.error || ""} />
        ) : (
          <>
            <div className="flex gap-1.5 flex-wrap mb-2.5">
              {Object.entries(counts).map(([st, n]) => (
                <span key={st}>
                  <Badge tone={TASK_TONE[st] || "neutral"}>
                    {st}: {n}
                  </Badge>
                </span>
              ))}
            </div>
            {runs && runs.total != null ? (
              <Row k="Task runs (task_runs)" v={`${runs.total}`} />
            ) : null}
            <div className="h-2" />
            {!hasAny ? (
              <Empty msg="Belum ada task. Buat lewat form di atas — task akan muncul di sini." />
            ) : (
              <div className="overflow-x-auto max-w-full">
                <table className="mc-table">
                  <thead>
                    <tr>
                      <th className="mc-th">Task</th>
                      <th className="mc-th">Status</th>
                      <th className="mc-th">Prioritas</th>
                      <th className="mc-th">Assignee</th>
                      <th className="mc-th">Mulai</th>
                      <th className="mc-th">Aksi</th>
                    </tr>
                  </thead>
                  <tbody>
                    {latest.map((t) => (
                      <tr key={t.id} className="transition-colors hover:bg-white/[0.02]">
                        <td className="mc-td">{t.title || shortId(t.id)}</td>
                        <td className="mc-td">
                          <Badge tone={TASK_TONE[t.status] || "neutral"}>{t.status || "?"}</Badge>
                        </td>
                        <td className="mc-td">{t.priority || "—"}</td>
                        <td className="mc-td">{t.assignee || "—"}</td>
                        <td className="mc-td">{fmtDateTime(t.started_at_iso)}</td>
                        <td className="mc-td">
                          {t.status === "ready" ? (
                            <button
                              className="mc-btn-ghost"
                              disabled={completingId === t.id}
                              onClick={() => {
                                setCompleteTarget({ id: t.id, title: t.title });
                                setResultText("");
                                setResultErr(null);
                              }}
                            >
                              {completingId === t.id ? (
                                <><Loader2 size={13} className="animate-spin" /> Menyimpan…</>
                              ) : (
                                <><Check size={13} /> Selesai</>
                              )}
                            </button>
                          ) : (
                            <span className="text-mc-faint text-[11px]">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Card>
      <div className="mc-footnote">
        {latest.length} task terbaru di tabel (maks 20, urut mulai terbaru) · status: ready/running/done/blocked/crashed/timed_out/failed/released ·{" "}
        {refreshing ? "memuat…" : "auto-refresh 15 dtk"} · buat/selesai = validasi backend + CLI `hermes kanban`
      </div>

      {completeTarget ? (
        <Modal
          title="Selesaikan task"
          subtitle={completeTarget.title || completeTarget.id}
          onClose={() => { if (!completingId) setCompleteTarget(null); }}
          initialFocusRef={resultRef}
          busy={!!completingId}
          footer={(
            <>
              <button type="button" className="mc-btn-ghost" disabled={!!completingId} onClick={() => setCompleteTarget(null)}>Batal</button>
              <button type="button" className="mc-btn-primary" disabled={!!completingId} onClick={() => handleComplete(completeTarget.id)} aria-busy={!!completingId}>
                {completingId ? <><Loader2 size={13} className="animate-spin" aria-hidden="true" /> Menyimpan…</> : <><Check size={13} aria-hidden="true" /> Selesaikan</>}
              </button>
            </>
          )}
        >
          <textarea
            ref={resultRef}
            value={resultText}
            onChange={(e) => setResultText(e.target.value)}
            rows={3}
            placeholder="Ringkasan hasil penyelesaian (bukti/summary wajib diisi)…"
            className="mc-input resize-none w-full"
            aria-label="Ringkasan hasil"
            aria-invalid={Boolean(resultErr)}
            aria-describedby={resultErr ? "task-result-error" : undefined}
          />
          {resultErr ? <Feedback kind="err" className="mt-2" ><span id="task-result-error">{resultErr}</span></Feedback> : null}
        </Modal>
      ) : null}
    </>
  );
}

// --- PANEL: Calendar (Google Calendar) --------------------------------------------
function CalendarPanel() {
  const { data, error, refreshing } = usePolling(`${EP}/calendar`, POLL_CALENDAR_MS);

  if (!data && !error) return <Loading />;
  if (error) {
    return (
      <Card title="Calendar">
        <Unavailable msg={error} />
      </Card>
    );
  }

  const cal = data.calendar || {};
  const ok = cal.status === "ok";
  const items = cal.items || [];

  return (
    <>
      <Card
        title="Calendar (Google Calendar)"
        right={<Badge tone={ok ? "ok" : "bad"}>{ok ? `${cal.count ?? items.length} event` : "unavailable"}</Badge>}
      >
        {!ok ? (
          <>
            <Unavailable msg={cal.error || ""} />
            <div className="mc-footnote">
              Kalender tidak terbaca dari wrapper gws-google — cek koneksi/kredensial Google Workspace, lalu muat ulang.
            </div>
          </>
        ) : (
          <>
            <Row k="Kalender" v={cal.calendar_id || "primary"} />
            <Row k="Zona waktu" v={cal.timezone || "—"} />
            <div className="h-2" />
            {items.length === 0 ? (
              <Empty msg="Kalender kosong — tambahkan event di Google Calendar." />
            ) : (
              <div className="flex flex-col gap-2">
                {items.map((ev, i) => (
                  <div key={i} className="flex gap-2.5 p-2.5 rounded-xl bg-white/[0.02] border border-mc-border">
                    <span className="mc-feed-bar bg-[#38bdf8]" />
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-semibold text-mc-text break-words"><CalendarDays size={13} className="inline mr-1.5 -mt-0.5 text-mc-muted" />{ev.summary || "(tanpa judul)"}</div>
                      <div className="text-[11px] text-mc-muted mt-0.5 font-mono">{fmtEvtRange(ev.start, ev.end)}</div>
                      {ev.htmlLink ? (
                        <a className="text-[11px] text-sky-400 no-underline mt-1 inline-block hover:text-sky-300" href={ev.htmlLink} target="_blank" rel="noreferrer">
                          Buka di Google <ExternalLink size={10} className="inline ml-0.5" />
                        </a>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </Card>
      <div className="mc-footnote">
        {items.length} event terdekat (maks 10, orderBy startTime, singleEvents) · {refreshing ? "memuat…" : "auto-refresh 30 dtk"}
      </div>
    </>
  );
}

// --- PANEL: Memory & Skill Library ---------------------------------------------
function ManagedModal({ title, subtitle, onClose, children, footer, wide = false, contentClassName = "" }) {
  return <Modal title={title} subtitle={subtitle} onClose={onClose} wide={wide} contentClassName={contentClassName} footer={footer}>{children}</Modal>;
}

function ManagedTextModal({ file, onClose }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    safeFetchJSON(`${EP}/memory/files/${encodeURIComponent(file)}`)
      .then(setData)
      .catch((e) => { notifyUnauthorized(e); setErr(e.message || "gagal memuat file"); });
  }, [file]);
  async function copyContent() {
    if (!data || typeof data.content !== "string") return;
    try {
      await navigator.clipboard.writeText(data.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setErr("Clipboard tidak tersedia di browser ini.");
    }
  }
  return (
    <ManagedModal title={file} subtitle="Isi penuh dari backend; nilai yang tampak seperti credential diredáksi." onClose={onClose} wide
      footer={<><button className="mc-btn-ghost" onClick={copyContent} disabled={!data}>{copied ? "Tersalin ✓" : "Salin isi"}</button><button className="mc-btn-primary" onClick={onClose}>Tutup</button></>}>
      {err ? <Feedback kind="err">{err}</Feedback> : null}
      {!data && !err ? <Loading /> : data ? <pre className="mc-mem-pre !max-h-none min-h-[220px]">{data.content || "(kosong)"}</pre> : null}
    </ManagedModal>
  );
}

function MemoryEditModal({ file, mode = "edit", onClose, onSaved }) {
  const [content, setContent] = useState("");
  const [title, setTitle] = useState("");
  const [section, setSection] = useState("");
  const [loading, setLoading] = useState(mode === "edit");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);
  const [redacted, setRedacted] = useState(false);
  const [redactionAcknowledged, setRedactionAcknowledged] = useState(false);
  useEffect(() => {
    if (mode !== "edit") {
      setRedacted(false);
      setRedactionAcknowledged(true);
      return;
    }
    safeFetchJSON(`${EP}/memory/files/${encodeURIComponent(file)}`)
      .then((d) => {
        setContent(d.content || "");
        const responseWasRedacted = Boolean(d && d.redacted);
        setRedacted(responseWasRedacted);
        setRedactionAcknowledged(!responseWasRedacted);
      })
      .catch((e) => { notifyUnauthorized(e); setErr(e.message || "gagal memuat file"); })
      .finally(() => setLoading(false));
  }, [file, mode]);
  async function save() {
    if (mode === "edit" && redacted && !redactionAcknowledged) {
      setErr("Konfirmasi diperlukan: isi yang memuat nilai sensitif telah disamarkan oleh backend.");
      return;
    }
    setSaving(true); setErr(null);
    try {
      const url = mode === "append" ? `${EP}/memory/files/${encodeURIComponent(file)}/sections` : `${EP}/memory/files/${encodeURIComponent(file)}`;
      const body = mode === "append" ? { title: title.trim(), content: section } : { content };
      const method = mode === "append" ? "POST" : "PUT";
      const d = await safeFetchJSON(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (d && d.status === "ok") onSaved(); else setErr((d && d.error) || "gagal menyimpan");
    } catch (e) { notifyUnauthorized(e); setErr(e.message || "gagal menyimpan"); }
    finally { setSaving(false); }
  }
  return (
    <ManagedModal title={mode === "append" ? `Tambah section · ${file}` : `Edit · ${file}`} subtitle="Perubahan ditulis atomik dan backup lama dibuat bila file sudah ada." onClose={onClose} wide
      footer={<><button className="mc-btn-ghost" onClick={onClose}>Batal</button><button className="mc-btn-primary" disabled={saving || loading || (mode === "append" ? !title.trim() || !section.trim() : (redacted && !redactionAcknowledged))} onClick={save}>{saving ? "Menyimpan…" : "Simpan"}</button></>}>
      {err ? <Feedback kind="err">{err}</Feedback> : null}
      {redacted ? (
        <div className="text-[12px] text-amber-200 bg-amber-400/10 border border-amber-400/30 rounded-lg px-3 py-2.5 mb-3" role="alert">
          <div className="flex items-start gap-2"><TriangleAlert size={14} className="shrink-0 mt-0.5" /><span>Backend menyamarkan nilai sensitif pada isi yang dimuat. Nilai asli tidak dikirim ke browser; menyimpan isi ini dapat menggantinya dengan <code>[redacted]</code>.</span></div>
          <label className="mt-2 flex items-start gap-2 text-[11.5px] text-amber-100 cursor-pointer"><input type="checkbox" className="mt-0.5" checked={redactionAcknowledged} onChange={(e) => setRedactionAcknowledged(e.target.checked)} />Saya mengerti dan ingin menyimpan perubahan ini secara eksplisit.</label>
        </div>
      ) : null}
      {loading ? <Loading /> : mode === "append" ? (
        <div className="flex flex-col gap-3">
          <label className="text-[12px] text-mc-muted">Judul section<input className="mc-input w-full mt-1" value={title} maxLength={160} onChange={(e) => setTitle(e.target.value)} aria-label="Judul section" /></label>
          <label className="text-[12px] text-mc-muted">Isi section<textarea className="mc-input w-full mt-1 min-h-[240px] font-mono text-[12px]" value={section} onChange={(e) => setSection(e.target.value)} aria-label="Isi section" /></label>
        </div>
      ) : (
        <label className="text-[12px] text-mc-muted">Isi {file}<textarea className="mc-input w-full mt-1 min-h-[420px] font-mono text-[12px] leading-relaxed" value={content} onChange={(e) => setContent(e.target.value)} aria-label={`Isi ${file}`} /></label>
      )}
    </ManagedModal>
  );
}

function MemoryFileCard({ name, blk, limit, onView, onEdit, onAppend, onDelete }) {
  const ok = blk && blk.status === "ok";
  return (
    <Card title={name} right={<Badge tone={ok ? "ok" : "bad"}>{ok ? `${blk.chars ?? 0} chars` : "unavailable"}</Badge>}>
      {!ok ? <Unavailable msg={(blk && blk.error) || ""} /> : (
        <>
          {blk.truncated ? <div className="text-[11px] text-amber-400 bg-amber-400/10 border border-amber-400/30 rounded-lg px-2.5 py-1.5 mb-2" role="status"><TriangleAlert size={12} className="inline mr-1 -mt-0.5" />Preview {limit ?? blk.chars} dari {blk.chars ?? "?"} karakter. Buka isi penuh untuk membaca file lengkap.</div> : null}
          <pre className="mc-mem-pre">{blk.content || "(kosong)"}</pre>
          <div className="flex flex-wrap gap-1.5 mt-2.5">
            <button className="mc-btn-ghost" onClick={onView}><Eye size={12} /> Lihat penuh</button>
            <button className="mc-btn-ghost" onClick={onEdit}><Pencil size={12} /> Edit</button>
            <button className="mc-btn-ghost" onClick={onAppend}><Plus size={12} /> Tambah section</button>
            <button className="mc-btn-ghost !text-rose-300" onClick={onDelete}><Trash2 size={12} /> Hapus</button>
          </div>
        </>
      )}
    </Card>
  );
}

function SkillLibraryBlock({ blk, legacyBlk, onSelect, onCreate }) {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [assignment, setAssignment] = useState("all");
  const [collapsed, setCollapsed] = useState({});
  const rawSource = blk && blk.status === "ok"
    ? blk.skills || []
    : (legacyBlk && legacyBlk.status === "ok" ? (legacyBlk.skills || []) : []);
  const assignmentMetadataAvailable = Boolean(
    blk && blk.status === "ok" && rawSource.every((s) => Object.prototype.hasOwnProperty.call(s || {}, "assigned_count"))
  );
  const source = rawSource.map((s) => ({
    ...s,
    assignment_status: assignmentMetadataAvailable
      ? (Number(s.assigned_count || 0) > 0 ? "assigned" : "available")
      : "unknown",
  }));
  const categories = Array.from(new Set(source.map((s) => s.category || "lainnya"))).sort();
  const ql = q.trim().toLowerCase();
  const filtered = source.filter((s) => {
    const text = `${s.name || ""} ${s.category || ""} ${s.description || ""}`.toLowerCase();
    const assigned = s.assignment_status === "assigned";
    const assignmentMatch = !assignmentMetadataAvailable || assignment === "all"
      || (assignment === "assigned" ? assigned : s.assignment_status === "available");
    return (!ql || text.includes(ql)) && (!category || s.category === category) && assignmentMatch;
  });
  const grouped = filtered.reduce((out, s) => { const c = s.category || "lainnya"; (out[c] ||= []).push(s); return out; }, {});
  return (
    <Card title="Library skill" right={<div className="flex items-center gap-2"><Badge tone={blk && blk.status === "ok" ? "ok" : "warn"}>{source.length} skill</Badge><button className="mc-btn-primary !px-2.5 !py-1.5 text-[11px]" onClick={onCreate}><Plus size={12} /> Buat skill</button></div>}>
      <p className="m-0 text-[12px] text-mc-muted leading-relaxed">Library skill adalah isi <code>SKILL.md</code>. Assignment agent dikelola terpisah di panel Team; label di bawah hanya menunjukkan dampaknya.{assignmentMetadataAvailable ? "" : " Metadata assignment tidak tersedia, jadi status assignment ditampilkan netral."}</p>
      {blk && blk.status !== "ok" ? <Unavailable msg={blk.error || "skill library tidak tersedia"} /> : null}
      <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_180px_160px] gap-2 mt-3">
        <input className="mc-input w-full" placeholder="Cari skill, kategori, deskripsi…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Cari skill library" />
        <select className="mc-select w-full" value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Filter kategori skill"><option value="">Semua kategori</option>{categories.map((c) => <option key={c} value={c}>{c}</option>)}</select>
        <select className="mc-select w-full" value={assignment} onChange={(e) => setAssignment(e.target.value)} aria-label="Filter assignment" disabled={!assignmentMetadataAvailable}><option value="all">{assignmentMetadataAvailable ? "Semua status" : "Assignment tidak tersedia"}</option><option value="assigned">Ditugaskan</option><option value="available">Tersedia</option></select>
      </div>
      {!filtered.length ? <Empty msg={source.length ? "tidak ada skill yang cocok dengan filter" : "belum ada skill di library"} /> : <div className="flex flex-col gap-2 mt-3">
        {Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)).map(([cat, rows]) => {
          const isOpen = collapsed[cat] !== true;
          return <div key={cat} className="border border-mc-border rounded-xl overflow-hidden">
            <button className="w-full flex items-center justify-between gap-2 px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-violet-300 bg-white/[0.02]" onClick={() => setCollapsed((old) => ({ ...old, [cat]: isOpen }))} aria-expanded={isOpen}>
              <span>{isOpen ? "▾" : "▸"} {cat} · {rows.length}</span><span className="text-mc-faint normal-case tracking-normal">kategori</span>
            </button>
            {isOpen ? <div className="p-2 flex flex-col gap-1.5">{rows.map((s) => {
              const assigned = s.assignment_status === "assigned";
              return <button key={`${s.category}/${s.name}`} className="mc-feed-item text-left hover:border-sky-400/40" onClick={() => onSelect(s)} aria-label={`Detail skill ${s.name}`}>
                <div className="min-w-0 flex-1"><div className="flex items-center gap-2 flex-wrap"><span className="text-[12px] font-semibold text-mc-text break-all">{s.name}</span><Badge tone={assigned ? "info" : "neutral"}>{assigned ? `ditugaskan · ${s.assigned_count}` : s.assignment_status === "unknown" ? "assignment tidak tersedia" : "tersedia"}</Badge>{s.valid === false ? <Badge tone="warn">frontmatter perlu diperiksa</Badge> : null}</div><div className="text-[11px] text-mc-muted mt-0.5 break-words">{s.description || "Deskripsi belum tersedia"}</div>{assigned ? <div className="text-[10.5px] text-sky-300/80 mt-1">Agent: {(s.assigned_agents || []).map((a) => a.name).join(", ") || "metadata assignment tidak tersedia"}</div> : null}</div><Eye size={14} className="text-mc-muted shrink-0" />
              </button>;
            })}</div> : null}
          </div>;
        })}
      </div>}
    </Card>
  );
}

function SkillEditorModal({ skill, onClose, onSaved }) {
  const editing = !!skill;
  const [category, setCategory] = useState(skill ? skill.category : "");
  const [name, setName] = useState(skill ? skill.name : "");
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(editing);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);
  const [redacted, setRedacted] = useState(Boolean(skill && skill.redacted));
  const [redactionAcknowledged, setRedactionAcknowledged] = useState(!Boolean(skill && skill.redacted));
  useEffect(() => {
    if (!editing) return;
    safeFetchJSON(`${EP}/skill-library/${encodeURIComponent(skill.category)}/${encodeURIComponent(skill.name)}`)
      .then((d) => {
        setContent(d.content || "");
        const responseWasRedacted = Boolean(d && d.redacted);
        setRedacted(responseWasRedacted);
        setRedactionAcknowledged(!responseWasRedacted);
      })
      .catch((e) => { notifyUnauthorized(e); setErr(e.message || "gagal memuat skill"); })
      .finally(() => setLoading(false));
  }, [editing, skill]);
  async function save() {
    if (editing && redacted && !redactionAcknowledged) {
      setErr("Konfirmasi diperlukan: isi skill yang memuat nilai sensitif telah disamarkan oleh backend.");
      return;
    }
    setSaving(true); setErr(null);
    try {
      const url = editing ? `${EP}/skill-library/${encodeURIComponent(skill.category)}/${encodeURIComponent(skill.name)}` : `${EP}/skill-library`;
      const d = await safeFetchJSON(url, { method: editing ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ category, name, content }) });
      if (d && d.status === "ok") onSaved(); else setErr((d && d.error) || "gagal menyimpan skill");
    } catch (e) { notifyUnauthorized(e); setErr(e.message || "gagal menyimpan skill"); }
    finally { setSaving(false); }
  }
  return <ManagedModal title={editing ? `Edit skill · ${skill.name}` : "Buat skill library"} subtitle="Nama/category aman dan frontmatter name + description wajib ada." onClose={onClose} wide
    footer={<><button className="mc-btn-ghost" onClick={onClose}>Batal</button><button className="mc-btn-primary" disabled={saving || loading || !category.trim() || !name.trim() || !content.trim() || (redacted && !redactionAcknowledged)} onClick={save}>{saving ? "Menyimpan…" : "Simpan"}</button></>}>
    {err ? <Feedback kind="err">{err}</Feedback> : null}
    {redacted ? <div className="text-[12px] text-amber-200 bg-amber-400/10 border border-amber-400/30 rounded-lg px-3 py-2.5 mb-3" role="alert"><div className="flex items-start gap-2"><TriangleAlert size={14} className="shrink-0 mt-0.5" /><span>Backend menyamarkan nilai sensitif pada isi skill yang dimuat. Nilai asli tidak dikirim ke browser; menyimpan isi ini dapat menggantinya dengan <code>[redacted]</code>.</span></div><label className="mt-2 flex items-start gap-2 text-[11.5px] text-amber-100 cursor-pointer"><input type="checkbox" className="mt-0.5" checked={redactionAcknowledged} onChange={(e) => setRedactionAcknowledged(e.target.checked)} />Saya mengerti dan ingin menyimpan perubahan ini secara eksplisit.</label></div> : null}
    {loading ? <Loading /> : <div className="flex flex-col gap-3"><div className="grid grid-cols-1 sm:grid-cols-2 gap-2"><label className="text-[12px] text-mc-muted">Category<input className="mc-input w-full mt-1" value={category} disabled={editing} onChange={(e) => setCategory(e.target.value)} aria-label="Category skill" /></label><label className="text-[12px] text-mc-muted">Name<input className="mc-input w-full mt-1" value={name} disabled={editing} onChange={(e) => setName(e.target.value)} aria-label="Nama skill" /></label></div><label className="text-[12px] text-mc-muted">Isi SKILL.md<textarea className="mc-input w-full mt-1 min-h-[460px] font-mono text-[12px] leading-relaxed" value={content} onChange={(e) => setContent(e.target.value)} aria-label="Isi SKILL.md" /></label></div>}
  </ManagedModal>;
}

function SkillDetailModal({ skill, onClose, onEdit, onDeleted }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  useEffect(() => {
    safeFetchJSON(`${EP}/skill-library/${encodeURIComponent(skill.category)}/${encodeURIComponent(skill.name)}`)
      .then(setData)
      .catch((e) => { notifyUnauthorized(e); setErr(e.message || "gagal memuat skill"); });
  }, [skill]);
  async function remove() {
    setDeleting(true);
    setErr(null);
    try {
      const r = await safeFetchJSON(`${EP}/skill-library/${encodeURIComponent(skill.category)}/${encodeURIComponent(skill.name)}`, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: true }) });
      if (r && r.status === "ok") onDeleted(); else setErr((r && r.error) || "skill tidak dihapus");
    } catch (e) { notifyUnauthorized(e); setErr(e.message || "skill tidak dihapus"); }
    finally { setDeleting(false); }
  }
  const assignedAgents = (data && data.assigned_agents) || skill.assigned_agents || [];
  const impact = assignedAgents.length
    ? `Skill masih ditugaskan ke: ${assignedAgents.map((a) => a.name).join(", ")}. Assignment tidak akan dihapus otomatis.`
    : "SKILL.md akan tidak tersedia lagi dari library.";
  return <ManagedModal title={`${skill.category}/${skill.name}`} subtitle="Skill library terpisah dari assignment agent." onClose={onClose} wide
    footer={confirmingDelete ? <><button className="mc-btn-ghost" onClick={() => { if (!deleting) { setConfirmingDelete(false); setErr(null); } }} disabled={deleting}>Batal</button><button className="mc-btn-ghost !text-rose-300 !border-rose-400/40" onClick={remove} disabled={deleting} aria-busy={deleting}>{deleting ? <><Loader2 size={12} className="animate-spin" /> Menghapus…</> : <><Trash2 size={12} /> Hapus permanen</>}</button></> : <><button className="mc-btn-ghost" onClick={() => onEdit(data || skill)}><Pencil size={12} /> Edit</button><button className="mc-btn-ghost !text-rose-300" onClick={() => { setErr(null); setConfirmingDelete(true); }}><Trash2 size={12} /> Hapus</button><button className="mc-btn-primary" onClick={onClose}>Tutup</button></>}>
    {confirmingDelete ? <div className="rounded-xl border border-rose-400/25 bg-rose-400/[0.06] p-3.5" role="alert"><div className="text-[13px] font-semibold text-rose-200">Hapus {skill.name}?</div><p className="m-0 mt-1.5 text-[12px] leading-relaxed text-mc-muted">{impact}</p></div> : null}
    {err ? <Feedback kind="err">{err}</Feedback> : null}
    {!data && !err ? <Loading /> : data ? <div className="flex flex-col gap-3"><div className="grid grid-cols-2 sm:grid-cols-4 gap-2"><div className="mc-agent-card !p-2.5"><div className="text-[18px] font-bold text-sky-300">{data.chars || 0}</div><div className="text-[10px] text-mc-muted">karakter</div></div><div className="mc-agent-card !p-2.5"><div className="text-[18px] font-bold text-violet-300">{data.assigned_count || 0}</div><div className="text-[10px] text-mc-muted">agent ditugaskan</div></div><div className="mc-agent-card !p-2.5 col-span-2"><div className="text-[11px] font-semibold text-mc-text break-words">{data.description || "Deskripsi belum tersedia"}</div><div className="text-[10px] text-mc-muted">metadata frontmatter</div></div></div><div><SectionLabel>Agent terdampak</SectionLabel>{data.assigned_agents && data.assigned_agents.length ? <div className="flex flex-wrap gap-1.5">{data.assigned_agents.map((a) => <span key={a.id} className="mc-chip text-sky-300">{a.name}</span>)}</div> : <Empty msg="skill belum ditugaskan ke agent" />}</div><div><SectionLabel>Preview SKILL.md</SectionLabel><pre className="mc-mem-pre !max-h-[420px]">{data.content || "(kosong)"}</pre></div></div> : null}
  </ManagedModal>;
}

function MemoryPanel() {
  const [tick, setTick] = useState(0);
  const { data, error, refreshing } = usePolling(`${EP}/memory`, POLL_MEMORY_MS, tick);
  const { data: library, error: libraryError } = usePolling(`${EP}/skill-library`, POLL_MEMORY_MS, tick);
  const [viewer, setViewer] = useState(null);
  const [memoryEditor, setMemoryEditor] = useState(null);
  const [skillEditor, setSkillEditor] = useState(null);
  const [skillDetail, setSkillDetail] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null); // memory file awaiting confirmation
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState(null);
  const [msg, setMsg] = useState(null);
  const mem = (data && data.memory) || {};
  const memOk = mem.status === "ok";
  const limit = mem.limit_chars || 2000;
  const refresh = () => { setMsg({ kind: "ok", text: "Perubahan tersimpan ✓" }); setTick((n) => n + 1); };
  async function deleteMemory() {
    if (!deleteTarget) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      const r = await safeFetchJSON(`${EP}/memory/files/${encodeURIComponent(deleteTarget)}`, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: true }) });
      if (r && r.status === "ok") {
        setDeleteTarget(null);
        refresh();
      } else {
        setDeleteError((r && r.error) || "file tidak dihapus");
      }
    } catch (e) {
      notifyUnauthorized(e);
      setDeleteError(e.message || "file tidak dihapus");
    } finally {
      setDeleteBusy(false);
    }
  }
  if (!data && !error) return <Loading />;
  if (error) return <Card title="Skills & Memory"><Unavailable msg={error} /></Card>;
  return <>
    <header className="mc-card !p-5"><div className="flex items-start justify-between gap-3 flex-wrap"><div><h2 className="m-0 text-xl font-semibold text-mc-text">Skills & Memory</h2><p className="m-0 mt-1.5 text-[13px] leading-relaxed text-mc-muted max-w-3xl">Kelola memori global dan library <code>SKILL.md</code> dengan aman. Isi memory bisa diedit di sini; assignment skill per agent tetap berada di panel Team.</p></div><Badge tone="info">manager terautentikasi</Badge></div><div className="mc-fresh mt-3">{refreshing ? "memuat…" : "auto-refresh 30 dtk"} · data: {data.generated_at || ""}</div></header>
    {msg ? <Feedback kind={msg.kind}>{msg.text}</Feedback> : null}
    <section aria-labelledby="memory-heading"><div className="flex items-center justify-between gap-2 flex-wrap mb-2"><div><h3 id="memory-heading" className="m-0 text-[14px] font-semibold text-mc-text">Memory global</h3><p className="m-0 mt-0.5 text-[11px] text-mc-muted">MEMORY.md dan USER.md · preview jujur bila terpotong</p></div><Badge tone={memOk ? "ok" : "bad"}>{memOk ? "tersedia" : "unavailable"}</Badge></div><div className="mc-panel-grid"><MemoryFileCard name="MEMORY.md" blk={memOk ? mem["MEMORY.md"] : null} limit={limit} onView={() => setViewer("MEMORY.md")} onEdit={() => setMemoryEditor({ file: "MEMORY.md", mode: "edit" })} onAppend={() => setMemoryEditor({ file: "MEMORY.md", mode: "append" })} onDelete={() => { setDeleteError(null); setDeleteTarget("MEMORY.md"); }} /><MemoryFileCard name="USER.md" blk={memOk ? mem["USER.md"] : null} limit={limit} onView={() => setViewer("USER.md")} onEdit={() => setMemoryEditor({ file: "USER.md", mode: "edit" })} onAppend={() => setMemoryEditor({ file: "USER.md", mode: "append" })} onDelete={() => { setDeleteError(null); setDeleteTarget("USER.md"); }} /></div></section>
    <section aria-labelledby="library-heading"><div className="flex items-center justify-between gap-2 flex-wrap mb-2"><div><h3 id="library-heading" className="m-0 text-[14px] font-semibold text-mc-text">Library skill</h3><p className="m-0 mt-0.5 text-[11px] text-mc-muted">CRUD isi skill terpisah dari assignment pada agent.</p></div><span className="text-[11px] text-mc-faint">{libraryError ? "Library tidak tersedia" : "Filter tidak mereset saat auto-refresh"}</span></div><SkillLibraryBlock blk={library} legacyBlk={data.skills} onSelect={setSkillDetail} onCreate={() => setSkillEditor({})} /></section>
    {viewer ? <ManagedTextModal file={viewer} onClose={() => setViewer(null)} /> : null}
    {memoryEditor ? <MemoryEditModal file={memoryEditor.file} mode={memoryEditor.mode} onClose={() => setMemoryEditor(null)} onSaved={() => { setMemoryEditor(null); refresh(); }} /> : null}
    {skillEditor ? <SkillEditorModal skill={skillEditor.name ? skillEditor : null} onClose={() => setSkillEditor(null)} onSaved={() => { setSkillEditor(null); refresh(); }} /> : null}
    {skillDetail ? <SkillDetailModal skill={skillDetail} onClose={() => setSkillDetail(null)} onEdit={(s) => { setSkillDetail(null); setSkillEditor(s); }} onDeleted={() => { setSkillDetail(null); refresh(); }} /> : null}
    {deleteTarget ? (
      <ConfirmModal
        title="Hapus file memory?"
        target={deleteTarget}
        impact="File akan dihapus setelah backup dibuat oleh backend, lalu dashboard akan menampilkan status tidak tersedia. Tidak ada agent runtime yang akan dijalankan oleh tindakan ini."
        busy={deleteBusy}
        error={deleteError}
        onClose={() => { if (!deleteBusy) { setDeleteTarget(null); setDeleteError(null); } }}
        onConfirm={deleteMemory}
      />
    ) : null}
  </>;
}

// --- PANEL: Visual Office (pixel-art retro) — SEMUA state dari data nyata ------
// Sumber state per agent:
//   - /api/agents/roster  -> live.status (online / standby / offline) = base state
//   - /api/office         -> sinyal KERJA eksplisit:
//       * active_sessions[].source==="subagent" && active  -> Hermes mengawasi sub-agent
//       * gateway_active_agents.active_work                -> Hermes sedang ada work
//       * running_delegations.count>0                      -> Agent Engineer (delegasi coding)
//       * opencode_workers.active (probe 15 mnt)           -> OpenCode
//   - Tidak ada sinyal kerja / status tak dikenal -> "unknown" (ditampilkan jujur,
//     zona netral berlabel). TIDAK ADA simulasi.
const OFFICE_TONE_COLORS = { ok: "#4ade80", neutral: "#8b8b94", bad: "#f87171" };

function officeStatus(o) {
  const desk = (src) => {
    if (!src || src.status !== "ok") return { tone: "bad", label: "Tidak tersedia", detail: (src && src.error) || "" };
    return null; // caller fills ok-branch
  };

  const leadSrc = o.gateway_active_agents || {};
  const engSrc = o.running_delegations || {};
  const ocSrc = o.opencode_workers || {};
  const wrSrc = o.active_sessions || {};

  const lead = desk(leadSrc) || (leadSrc.count > 0
    ? { tone: "ok", label: "AKTIF", detail: `${leadSrc.count} agent aktif${leadSrc.active_work ? ` (work: ${leadSrc.active_work})` : ""}` }
    : { tone: "neutral", label: "Idle", detail: "tidak ada agent aktif di gateway" });

  const eng = desk(engSrc) || (engSrc.count > 0
    ? { tone: "ok", label: "Bekerja", detail: `${engSrc.count} delegasi running${(engSrc.running_ids || []).length ? ` · ${engSrc.running_ids.map(shortId).join(", ")}` : ""}` }
    : { tone: "neutral", label: "Idle", detail: "tidak ada delegasi running" });

  const oc = desk(ocSrc) || (ocSrc.active
    ? { tone: "ok", label: "Aktif", detail: `${ocSrc.recent_sessions ?? 0} sesi update < ${Math.round((ocSrc.recent_window_s || 900) / 60)} mnt` }
    : { tone: "neutral", label: "Idle", detail: `${ocSrc.total_sessions ?? 0} sesi total, ${ocSrc.recent_sessions ?? 0} recent (15 mnt)` });

  const wr = desk(wrSrc) || (wrSrc.count > 0
    ? { tone: "ok", label: `${wrSrc.count} sesi aktif`, detail: "sesi state.db yang belum selesai (ended_at IS NULL)" }
    : { tone: "neutral", label: "Tidak ada sesi", detail: "state.db: tidak ada sesi aktif" });

  return { lead, eng, oc, wr, leadSrc, engSrc, ocSrc, wrSrc };
}

// Palet sprite pixel [kepala, badan] — urut indeks roster, senada mc-avatar-h*
const PIX_PAL = [
  ["#38bdf8", "#6366f1"], ["#a78bfa", "#7c3aed"], ["#f472b6", "#db2777"],
  ["#4ade80", "#16a34a"], ["#fbbf24", "#d97706"], ["#fb7185", "#e11d48"],
  ["#34d399", "#059669"],
];
const STATE_META = {
  working: { label: "Bekerja", tone: "ok", color: "#4ade80", room: "workspace" },
  idle: { label: "Idle", tone: "neutral", color: "#a1a1aa", room: "lounge" },
  offline: { label: "Offline", tone: "bad", color: "#f87171", room: "lounge" },
  unknown: { label: "Unknown", tone: "warn", color: "#fbbf24", room: "lounge" },
};
const PIX_FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

// Karakter pixel: char -> warna ('H' kepala, 'B' badan, 'S' kulit/tangan, 'E' mata)
const SPRITE_STAND = [
  "..HHHH..",
  ".HHHHHH.",
  ".HHHHHH.",
  "..HEEH..",
  "...BB...",
  "..BBBB..",
  ".BBBBBB.",
  ".BBBBBB.",
  "..B..B..",
  ".SB..BS.",
  ".SS..SS.",
];
const SPRITE_SIT = [
  "..HHHH..",
  ".HHHHHH.",
  ".HHHHHH.",
  "..HEEH..",
  "...BB...",
  "..BBBB..",
  ".BBBBBB.",
  ".BBBBBB.",
  "..S..S..",
];

function PixelSprite({ x, y, cell = 6, colors, sit = false, sel = false, onClick, title }) {
  const rows = sit ? SPRITE_SIT : SPRITE_STAND;
  const rects = [];
  rows.forEach((row, ry) => {
    for (let rx = 0; rx < row.length; rx++) {
      const ch = row[rx];
      if (ch === ".") continue;
      const c = ch === "H" ? colors[0] : ch === "B" ? colors[1] : ch === "S" ? "#f5d0a9" : "#101828";
      rects.push(<rect key={`${ry}-${rx}`} x={x + rx * cell} y={y + ry * cell} width={cell} height={cell} fill={c} />);
    }
  });
  const w = rows[0].length * cell;
  const h = rows.length * cell;
  return (
    <g
      className={onClick ? "mc-pixel-sprite" : undefined}
      style={{ cursor: onClick ? "pointer" : "default" }}
      onClick={onClick}
      onKeyDown={(e) => {
        if (onClick && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          onClick();
        }
      }}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      aria-label={title}
      aria-pressed={onClick ? sel : undefined}
    >
      {title ? <title>{title}</title> : null}
      {sel ? <rect x={x - 4} y={y - 4} width={w + 8} height={h + 8} fill="none" stroke="#fbbf24" strokeWidth="1.5" strokeDasharray="3 3" /> : null}
      {onClick ? <rect className="mc-sprite-focus-ring" x={x - 5} y={y - 5} width={w + 10} height={h + 10} fill="none" stroke="#7dd3fc" strokeWidth="2" rx="2" pointerEvents="none" /> : null}
      {rects}
    </g>
  );
}

function PixelPlant({ x, y, cell = 5, mirror = false }) {
  const rows = [
    "..GG...",
    ".GgGG..",
    "GGGGGG.",
    ".GGGg..",
    "..GG...",
  ];
  const rects = [];
  rows.forEach((row, ry) => {
    for (let rx = 0; rx < row.length; rx++) {
      const ch = row[rx];
      if (ch === ".") continue;
      const px = mirror ? x + (row.length - 1 - rx) * cell : x + rx * cell;
      rects.push(<rect key={`${ry}-${rx}`} x={px} y={y + ry * cell} width={cell} height={cell} fill={ch === "g" ? "#2d7a44" : "#3fae5f"} />);
    }
  });
  return <g>{rects}</g>;
}

function PixBubble({ cx, cy, w, text }) {
  return (
    <g>
      <rect x={cx - w / 2} y={cy - 18} width={w} height={36} rx="10" fill="#16161d" stroke="#2f2f3a" strokeWidth="1.2" />
      <text x={cx} y={cy + 4} fontSize="11" fill="#d4d4d8" textAnchor="middle" fontFamily={PIX_FONT}>{text}</text>
    </g>
  );
}

// Derive state per agent dari data nyata; tak bisa ditentukan -> unknown + alasan.
function deriveOfficeData(office, roster, ag) {
  const o = (office && office.office) || {};
  const wrs = o.gateway_active_agents || {};
  const engs = o.running_delegations || {};
  const ocs = o.opencode_workers || {};
  const sessOk = !!(o.active_sessions && o.active_sessions.status === "ok");
  const sessArr = sessOk && Array.isArray(o.active_sessions.sessions) ? o.active_sessions.sessions : [];
  const rosterOk = !!(roster && Array.isArray(roster.agents));
  const list = rosterOk ? roster.agents : [];
  const agAg = (ag && ag.agents) || {};
  const delegRecent = ((agAg.delegations && agAg.delegations.recent) || []);
  const leadRows = ((agAg.lead_agent && agAg.lead_agent.rows) || []);
  const engRows = ((agAg.agent_engineer && agAg.agent_engineer.rows) || []);
  const ocSess = ((agAg.opencode_workers && agAg.opencode_workers.sessions) || []);
  const sortedBy = (arr, k) => [...arr].sort((x, y) => String(y[k] || "").localeCompare(String(x[k] || "")));

  const stateOf = (a) => {
    const live = a.live || {};
    const base = a.live_status || (live.status === "online" ? "running" : live.status || "unknown");
    const sourceStatus = a.live_source_status || live.source_status || "unknown";
    const runtimeAdapter = (a.routing && a.routing.runtime_adapter) || live.runtime_adapter || "";
    const reasons = [];
    const need = (name, src) => {
      if (!src || src.status !== "ok") { reasons.push(`sumber ${name} tidak tersedia`); return false; }
      return true;
    };
    if (base === "running" || base === "online") {
      if (runtimeAdapter === "hermes_lead") {
        const wOk = need("gateway_active_agents", wrs);
        const sOk = need("active_sessions", o.active_sessions);
        if (sOk && sessArr.some((s) => s.source === "subagent" && s.active)) {
          return { st: "working", reasons: reasons.concat(["active_sessions: ada sesi sub-agent aktif (Hermes mengawasi)"]) };
        }
        if (wOk && wrs.active_work) return { st: "working", reasons: reasons.concat(["gateway_active_agents.active_work terisi"]) };
        if (wOk || sOk) return { st: "idle", reasons: reasons.concat(["runtime adapter aktif — tanpa kerja berjalan di /office"]) };
        return { st: "unknown", reasons };
      }
      if (runtimeAdapter === "agent_engineer") {
        const eOk = need("running_delegations", engs);
        if (!eOk) return { st: "unknown", reasons };
        if (engs.count > 0) return { st: "working", reasons: reasons.concat(["running_delegations.count>0 → delegasi coding berjalan"]) };
        return { st: "idle", reasons: reasons.concat(["runtime adapter aktif — running_delegations=0"]) };
      }
      if (runtimeAdapter === "opencode") {
        const cOk = need("opencode_workers", ocs);
        if (!cOk) return { st: "unknown", reasons };
        if (ocs.active) return { st: "working", reasons: reasons.concat(["opencode_workers.active (sesi ≤15 mnt di opencode.db)"]) };
        return { st: "idle", reasons: reasons.concat(["runtime adapter aktif — probe 15 mnt = 0"]) };
      }
      return { st: "working", reasons: ["backend live_status=running"] };
    }
    if (base === "standby") return { st: "unknown", reasons: [sourceStatus === "not_configured" ? "runtime belum dikonfigurasi" : "backend live_status=standby"] };
    if (base === "offline") return { st: "offline", reasons: ["backend live_status=offline"] };
    if (base === "blocked") return { st: "unknown", reasons: ["backend live_status=blocked"] };
    return { st: "unknown", reasons: ["backend live_status=unknown atau sumber tidak tersedia"] };
  };

  const agents = list.map((a, ridx) => {
    const { st, reasons } = stateOf(a);
    const runtimeAdapter = (a.routing && a.routing.runtime_adapter) || (a.live && a.live.runtime_adapter) || "";
    let taskNow = null, lastAct = null;
    if (runtimeAdapter === "hermes_lead") {
      const sub = sessArr.filter((s) => s.source === "subagent" && s.active);
      if (sub.length) taskNow = `Mengawasi sub-agent · ${shortId(sub[0].id)} (mulai ${fmtTime(sub[0].started_at_iso)})`;
      const r0 = sortedBy(leadRows, "started_at_iso")[0];
      if (r0) lastAct = r0.active ? `Sesi ${r0.source} aktif sejak ${fmtTime(r0.started_at_iso)}` : `Sesi ${r0.source} selesai ${fmtTime(r0.ended_at_iso)}`;
    } else if (runtimeAdapter === "agent_engineer") {
      const run = engs.status === "ok" ? engs.running_ids || [] : [];
      if (run.length) {
        const d0 = delegRecent.find((dd) => dd.delegation_id === run[0]);
        taskNow = `Delegasi ${shortId(run[0])} berjalan${d0 ? ` sejak ${fmtTime(d0.dispatched_at_iso)}` : ""}`;
      }
      const r0 = sortedBy(engRows, "started_at_iso")[0];
      if (r0) lastAct = r0.active ? `Sesi sub-agent aktif sejak ${fmtTime(r0.started_at_iso)}` : `Sub-agent selesai ${fmtTime(r0.ended_at_iso)} (${r0.end_reason || "?"})`;
    } else if (runtimeAdapter === "opencode") {
      if (ocs.status === "ok" && ocs.active) taskNow = `Sesi opencode dalam ${Math.round((ocs.recent_window_s || 900) / 60)} mnt terakhir`;
      const r0 = sortedBy(ocSess, "time_updated_iso")[0];
      if (r0) lastAct = `Sesi terakhir ${fmtAgo(new Date(r0.time_updated_iso).getTime() / 1000)} · ${shortId(r0.id)}`;
    }
    return { a, ridx, st, reasons, taskNow, lastAct };
  });

  const counts = { working: 0, idle: 0, offline: 0, unknown: 0 };
  agents.forEach((x) => { counts[x.st] = (counts[x.st] || 0) + 1; });

  return { agents, counts, rosterOk, sourceReady: { sessOk, wrs: wrs.status === "ok", engs: engs.status === "ok", ocs: ocs.status === "ok" } };
}

// Event NYATA hasil diff antar-polling /api/office (bukan simulasi).
function useOfficeEvents(office) {
  const prevRef = useRef(null);
  const [events, setEvents] = useState([]);
  useEffect(() => {
    if (!office || !office.office) return;
    const prev = prevRef.current;
    if (prev && prev.office) {
      const pSess = prev.office.active_sessions && Array.isArray(prev.office.active_sessions.sessions) ? prev.office.active_sessions.sessions : [];
      const cSess = office.office.active_sessions && Array.isArray(office.office.active_sessions.sessions) ? office.office.active_sessions.sessions : [];
      const pD = prev.office.running_delegations && Array.isArray(prev.office.running_delegations.running_ids) ? prev.office.running_delegations.running_ids : [];
      const cD = office.office.running_delegations && Array.isArray(office.office.running_delegations.running_ids) ? office.office.running_delegations.running_ids : [];
      const ev = [];
      const pSet = new Set(pSess.map((s) => s.id)), cSet = new Set(cSess.map((s) => s.id));
      cSess.forEach((s) => { if (!pSet.has(s.id)) ev.push(`Sesi ${s.source || "?"} dimulai · ${shortId(s.id)}`); });
      pSess.forEach((s) => { if (!cSet.has(s.id)) ev.push(`Sesi ${shortId(s.id)} berakhir`); });
      const pdSet = new Set(pD), cdSet = new Set(cD);
      cD.forEach((d) => { if (!pdSet.has(d)) ev.push(`Delegasi ${shortId(d)} berjalan (baru)`); });
      pD.forEach((d) => { if (!cdSet.has(d)) ev.push(`Delegasi ${shortId(d)} selesai/berhenti`); });
      const po = prev.office.opencode_workers, co = office.office.opencode_workers;
      if (po && co && po.status === "ok" && co.status === "ok" && po.active !== co.active) {
        ev.push(`OpenCode ${co.active ? "aktif" : "berhenti"} (probe 15 mnt)`);
      }
      if (ev.length) setEvents((old) => [...ev.map((e) => ({ t: office.generated_at || "", e })), ...old].slice(0, 8));
    }
    prevRef.current = office;
  }, [office]);
  return events;
}

// --- Ruangan: definisi + render. Tambah ruang baru = tambah entry di sini + case render. ---
const ROOM_DEFS = [
  { key: "workspace", label: "Workspace", icon: Monitor },
  { key: "lounge", label: "Lounge", icon: Sofa },
];

const DESK_XS = [140, 280, 420, 560, 700];   // 5 workstation (slot = urutan roster)
const SEAT_XS = [104, 170, 236, 302];        // sofa (4 dudukan)
const SEAT_RUG_XS = [486, 540];              // dudukan karpet tambahan
const UNK_XS = [658, 712, 766];              // zona unknown (di Lounge)

function RoomShell({ children }) {
  return (
    <g>
      {/* dinding & lantai */}
      <rect x="0" y="0" width="860" height="150" fill="#15151b" />
      <rect x="0" y="142" width="860" height="8" fill="#0e0e12" />
      <rect x="0" y="150" width="860" height="270" fill="#29180f" />
      {[178, 206, 234, 262, 290, 318, 346, 374, 402].map((y) => (
        <rect key={y} x="0" y={y} width="860" height="2" fill="#1e1109" />
      ))}
      {[97, 397, 715].map((x) => (
        <rect key={x} x={x} y="150" width="2" height="270" fill="#1e1109" />
      ))}
      {/* jendela */}
      <rect x="100" y="28" width="104" height="76" fill="#3a3a44" />
      <rect x="106" y="34" width="92" height="64" fill="#7dd3fc" opacity="0.16" />
      <rect x="150" y="34" width="2" height="64" fill="#3a3a44" />
      <rect x="106" y="64" width="92" height="2" fill="#3a3a44" />
      <rect x="480" y="28" width="104" height="76" fill="#3a3a44" />
      <rect x="486" y="34" width="92" height="64" fill="#7dd3fc" opacity="0.16" />
      <rect x="530" y="34" width="2" height="64" fill="#3a3a44" />
      <rect x="486" y="64" width="92" height="2" fill="#3a3a44" />
      {/* pintu + jam */}
      <rect x="394" y="50" width="72" height="104" fill="none" stroke="#2a2a33" strokeWidth="3" />
      <rect x="398" y="56" width="64" height="96" fill="#5c3317" />
      <rect x="408" y="66" width="44" height="76" fill="#4a2812" />
      <circle cx="452" cy="104" r="3" fill="#fbbf24" />
      <circle cx="420" cy="36" r="9" fill="#e4e4e7" />
      <line x1="420" y1="36" x2="420" y2="30" stroke="#334155" strokeWidth="2" />
      <line x1="420" y1="36" x2="425" y2="36" stroke="#334155" strokeWidth="2" />
      {/* rak buku */}
      <rect x="10" y="26" width="76" height="124" fill="#23232b" />
      <rect x="14" y="30" width="68" height="116" fill="#1b1b22" />
      {[62, 96, 130].map((y) => <rect key={y} x="14" y={y} width="68" height="4" fill="#14141b" />)}
      {[
        [18, 42, "#38bdf8"], [28, 44, "#a78bfa"], [38, 42, "#fbbf24"], [48, 45, "#f472b6"], [58, 42, "#4ade80"], [68, 44, "#fb7185"],
        [18, 78, "#f472b6"], [28, 78, "#38bdf8"], [38, 80, "#fb7185"], [48, 78, "#fbbf24"], [58, 82, "#a78bfa"], [68, 78, "#4ade80"],
        [18, 116, "#4ade80"], [28, 114, "#fbbf24"], [38, 116, "#38bdf8"], [48, 114, "#fb7185"], [58, 116, "#a78bfa"], [68, 118, "#f472b6"],
      ].map(([bx, by, c]) => <rect key={`${bx}-${by}`} x={bx} y={by} width="8" height="20" fill={c} />)}
      {/* tanaman */}
      <PixelPlant x={6} y={306} />
      <rect x="12" y="344" width="28" height="18" fill="#6b3d1f" />
      <rect x="8" y="336" width="36" height="8" fill="#7a4a24" />
      <PixelPlant x={818} y={306} mirror />
      <rect x="820" y="344" width="28" height="18" fill="#6b3d1f" />
      <rect x="816" y="336" width="36" height="8" fill="#7a4a24" />
      {children}
      {/* scanline CRT */}
      <rect x="0" y="0" width="860" height="420" fill="url(#pxscan)" pointerEvents="none" />
    </g>
  );
}

function WorkspaceFurniture({ d, selId, onSelect, gwOk }) {
  const working = d.agents.filter((x) => x.st === "working");
  const desks = [];
  for (let i = 0; i < DESK_XS.length; i++) {
    const agent = d.agents[i];
    const dx = DESK_XS[i];
    const busy = !!(agent && agent.st === "working");
    const pal = agent ? PIX_PAL[agent.ridx % PIX_PAL.length] : PIX_PAL[0];
    desks.push(
      <g key={`desk-${i}`}>
        {busy ? (
          <PixelSprite
            x={dx + 31} y={168} colors={pal}
            sel={selId === agent.a.id}
            onClick={() => onSelect(selId === agent.a.id ? null : agent.a.id)}
            title={`${agent.a.name} — ${STATE_META.working.label} (klik untuk detail)`}
          />
        ) : null}
        {/* furnitur dekoratif tak boleh menelan klik sprite (sprite di bawah di z-order) */}
        <g pointerEvents="none">
        <rect x={dx + 28} y={214} width="64" height="32" fill="#0d1117" />
        <rect x={dx + 32} y={218} width="56" height="24" fill={busy ? "#16283a" : "#0a0e14"} />
        {busy ? (
          <g>
            <rect x={dx + 36} y={222} width="16" height="3" fill="#4ade80" />
            <rect x={dx + 36} y={228} width="10" height="3" fill="#4ade80" opacity="0.8" />
          </g>
        ) : (
          <text x={dx + 60} y={235} fontSize="8" fill="#3f4655" textAnchor="middle" fontFamily={PIX_FONT}>—</text>
        )}
        <rect x={dx + 52} y={246} width="16" height="6" fill="#26262e" />
        <rect x={dx + 40} y={252} width="40" height="8" fill="#26262e" />
        <rect x={dx + 8} y={250} width="104" height="10" fill="#6b4423" />
        <rect x={dx + 14} y={260} width="12" height="70" fill="#4a2e16" />
        <rect x={dx + 94} y={260} width="12" height="70" fill="#4a2e16" />
        <rect x={dx + 36} y={262} width="48" height="20" fill="#23232b" />
        <rect x={dx + 24} y={282} width="72" height="12" fill="#2b2b34" />
        <rect x={dx + 58} y={294} width="4" height="14" fill="#1a1a21" />
        <rect x={dx + 34} y={308} width="52" height="6" fill="#26262e" />
        <circle cx={dx + 28} cy={327} r="3" fill={agent ? STATE_META[agent.st].color : "#3f3f46"} />
        <text x={dx + 38} y={331} fontSize="10" fill="#a1a1aa" fontFamily={PIX_FONT}>{agent ? agent.a.name : "kosong"}</text>
        {agent && !busy ? (
          <text x={dx + 56} y={346} fontSize="8" fill={STATE_META[agent.st].color} textAnchor="middle" fontFamily={PIX_FONT}>
            {agent.st === "unknown" ? "→ Zona Unknown" : "→ Lounge"}
          </text>
        ) : null}
        </g>
      </g>
    );
  }
  return (
    <g>
      {/* whiteboard — isi data nyata */}
      <rect x="616" y="26" width="188" height="108" fill="#31333f" />
      <rect x="620" y="30" width="180" height="100" fill="#1d2029" />
      <text x="630" y="46" fontSize="9" fill="#8b8f9e" fontFamily={PIX_FONT}>PAPAN STATUS — DATA NYATA</text>
      <text x="630" y="62" fontSize="10" fill="#a5b4fc" fontFamily={PIX_FONT}>
        CREW: {d.counts.working} bekerja · {d.counts.idle} idle · {d.counts.offline} offline · {d.counts.unknown} unknown
      </text>
      <text x="630" y="78" fontSize="10" fill="#7dd3fc" fontFamily={PIX_FONT}>{gwOk}</text>
      <text x="630" y="94" fontSize="8.5" fill="#5b6070" fontFamily={PIX_FONT}>sumber: /office · roster · overview</text>
      {desks}
      {working.length === 0 ? (
        <PixBubble cx={430} cy={380} w={330} text="Tidak ada agent di workstation saat ini" />
      ) : (
        <PixBubble cx={430} cy={380} w={430} text={`${working.length} agent bekerja di Workspace`} />
      )}
    </g>
  );
}

function LoungeFurniture({ d, selId, onSelect, tvLines }) {
  const seated = d.agents.filter((x) => x.st === "idle" || x.st === "offline");
  const unk = d.agents.filter((x) => x.st === "unknown");
  const seatedSprite = [];
  const unkSprite = [];
  seated.slice(0, 6).forEach((x, i) => {
    if (i < SEAT_XS.length) {
      seatedSprite.push(
        <PixelSprite
          key={x.a.id} x={SEAT_XS[i] - 24} y={244} sit colors={PIX_PAL[x.ridx % PIX_PAL.length]}
          sel={selId === x.a.id}
          onClick={() => onSelect(selId === x.a.id ? null : x.a.id)}
          title={`${x.a.name} — ${STATE_META[x.st].label} di Lounge (klik untuk detail)`}
        />
      );
    } else {
      seatedSprite.push(
        <PixelSprite
          key={x.a.id} x={SEAT_RUG_XS[i - SEAT_XS.length] - 24} y={336} sit colors={PIX_PAL[x.ridx % PIX_PAL.length]}
          sel={selId === x.a.id}
          onClick={() => onSelect(selId === x.a.id ? null : x.a.id)}
          title={`${x.a.name} — ${STATE_META[x.st].label} di karpet (klik untuk detail)`}
        />
      );
    }
  });
  unk.slice(0, UNK_XS.length).forEach((x, i) => {
    unkSprite.push(
      <g key={x.a.id}>
        <text x={UNK_XS[i] + 24} y={344} fontSize="13" fill="#fbbf24" textAnchor="middle" fontWeight="bold" fontFamily={PIX_FONT}>?</text>
        <PixelSprite
          x={UNK_XS[i] - 24} y={348} sit colors={PIX_PAL[x.ridx % PIX_PAL.length]}
          sel={selId === x.a.id}
          onClick={() => onSelect(selId === x.a.id ? null : x.a.id)}
          title={`${x.a.name} — ${STATE_META.unknown.label}: tidak ada data runtime (klik untuk detail)`}
        />
      </g>
    );
  });
  return (
    <g>
      {/* TV — isi data nyata */}
      <rect x="348" y="34" width="164" height="98" fill="#1b2233" />
      <rect x="358" y="44" width="144" height="78" fill="#0b1020" />
      <text x="368" y="60" fontSize="9" fill="#64748b" fontFamily={PIX_FONT}>MC TV — DATA NYATA</text>
      {[78, 90, 102, 114].map((y, i) => (
        <text key={y} x="368" y={y} fontSize="10" fill="#7dd3fc" fontFamily={PIX_FONT}>{tvLines[i] || "—"}</text>
      ))}
      <rect x="420" y="132" width="20" height="10" fill="#141821" />
      <rect x="404" y="142" width="52" height="8" fill="#141821" />
      {/* sofa */}
      <rect x="84" y="252" width="248" height="36" fill="#3e4d78" />
      <rect x="58" y="250" width="26" height="82" fill="#35426a" />
      <rect x="336" y="250" width="26" height="82" fill="#35426a" />
      {seatedSprite}
      <rect x="88" y="284" width="80" height="48" fill="#4d5e94" />
      <rect x="172" y="284" width="76" height="48" fill="#46568a" />
      <rect x="252" y="284" width="80" height="48" fill="#4d5e94" />
      <rect x="72" y="332" width="8" height="10" fill="#1b2030" />
      <rect x="340" y="332" width="8" height="10" fill="#1b2030" />
      {/* karpet + meja kopi */}
      <ellipse cx="460" cy="352" rx="150" ry="26" fill="#2d2a52" opacity="0.55" />
      <rect x="416" y="330" width="56" height="14" fill="#6b3d1f" />
      <rect x="422" y="344" width="6" height="14" fill="#4a2e16" />
      <rect x="460" y="344" width="6" height="14" fill="#4a2e16" />
      <rect x="426" y="322" width="12" height="10" fill="#e2e8f0" />
      <rect x="446" y="324" width="12" height="8" fill="#dbe3ee" />
      {/* area kopi */}
      <rect x="700" y="306" width="110" height="6" fill="#2e2e38" />
      <rect x="700" y="312" width="110" height="24" fill="#26262e" />
      <rect x="726" y="254" width="58" height="50" fill="#1f2733" />
      <rect x="732" y="258" width="46" height="12" fill="#0d1117" />
      <rect x="768" y="262" width="4" height="4" fill={d.sourceReady.ocs ? "#4ade80" : "#f87171"} />
      <text x="755" y="340" fontSize="9" fill="#8b8f9e" textAnchor="middle" fontFamily={PIX_FONT}>KOPI</text>
      {/* zona unknown (netral, berlabel) */}
      <rect x="642" y="322" width="186" height="86" fill="rgba(251,191,36,0.04)" stroke="#fbbf24" strokeWidth="1.2" strokeDasharray="5 3" />
      <text x="652" y="338" fontSize="9" fill="#fbbf24" fontFamily={PIX_FONT}>ZONA UNKNOWN — belum ada data runtime</text>
      {unkSprite}
      {seated.length === 0 && unk.length === 0 ? (
        <PixBubble cx={430} cy={192} w={330} text="Lounge kosong — semua agent bekerja" />
      ) : null}
    </g>
  );
}

function VisualOfficeSVG({ room, d, selId, onSelect, gwLine, tvLines }) {
  return (
    <svg
      viewBox="0 0 860 420" width="100%" role="img"
      aria-label={room === "workspace" ? "Ruangan Workspace — pixel art" : "Ruangan Lounge — pixel art"}
      className="block" style={{ imageRendering: "pixelated", minWidth: "560px" }}
    >
      <defs>
        <pattern id="pxscan" width="4" height="4" patternUnits="userSpaceOnUse">
          <rect width="4" height="2" fill="rgba(0,0,0,0.16)" />
        </pattern>
      </defs>
      <rect x="0" y="0" width="860" height="420" rx="12" fill="#0b0b0d" />
      <RoomShell>
        {room === "workspace" ? (
          <WorkspaceFurniture d={d} selId={selId} onSelect={onSelect} gwOk={gwLine} />
        ) : (
          <LoungeFurniture d={d} selId={selId} onSelect={onSelect} tvLines={tvLines} />
        )}
      </RoomShell>
    </svg>
  );
}

function AgentDetailCard({ x, onClose }) {
  if (!x) return null;
  const meta = STATE_META[x.st];
  return (
    <Card
      title={`Agent: ${x.a.name}`}
      right={
        <button className="mc-btn-ghost" onClick={onClose} aria-label="Tutup panel agent">
          <X size={14} />
        </button>
      }
    >
      <Row k="Role" v={x.a.role || "—"} mono={false} />
      <Row k="Model" v={x.a.model || "—"} />
      <div className="mc-row">
        <span className="mc-row-key">State saat ini</span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full" style={{ background: meta.color }} />
          <Badge tone={meta.tone}>{meta.label}</Badge>
          <span className="text-[11px] text-mc-muted">{meta.room === "workspace" ? "Workspace" : x.st === "unknown" ? "Zona Unknown (Lounge)" : "Lounge"}</span>
        </span>
      </div>
      <Row k="Task saat ini" v={x.taskNow || "—"} mono={false} />
      <Row k="Aktivitas terakhir" v={x.lastAct || "—"} mono={false} />
      <div className="mc-row">
        <span className="mc-row-key">Live (roster)</span>
        <span className="mc-row-val">{(x.a.live && x.a.live.status) || "?"}{(x.a.live && x.a.live.detail) ? ` · ${x.a.live.detail}` : ""}</span>
      </div>
      <div className="mc-footnote">
        {x.reasons.length ? `Alasan state: ${x.reasons.join("; ")}.` : "State dari data nyata."}
        {" "}Data tidak tersedia → “—”.
      </div>
    </Card>
  );
}

function OfficePanel() {
  const { data, error, refreshing } = usePolling(`${EP}/office`, POLL_OFFICE_MS);
  const { data: roster, error: rosterErr } = usePolling(`${EP}/agents/roster`, POLL_AGENTS_MS);
  const { data: ag } = usePolling(`${EP}/agents`, POLL_AGENTS_MS);
  const { data: ov } = usePolling(`${EP}/overview`, POLL_OVERVIEW_MS);
  const { data: st } = usePolling(`${EP}/stats`, 30000);
  const events = useOfficeEvents(data);
  const [room, setRoom] = useState("workspace");
  const [selId, setSelId] = useState(null);

  if (!data && !error) return <Loading />;
  if (error) {
    return (
      <Card title="Visual Office">
        <Unavailable msg={error} />
      </Card>
    );
  }

  const o = data.office || {};
  const st8 = officeStatus(o);
  const d = deriveOfficeData(data, roster, ag);
  const sel = d.agents.find((x) => x.a.id === selId) || null;

  const gw = ov && ov.gateway && ov.gateway.status === "ok" ? ov.gateway : null;
  const platforms = (gw && gw.platforms) || null;
  const gwLine = gw
    ? `GATEWAY ${String(gw.state || "?").toUpperCase()} · aktif ${gw.active_agents ?? "?"}`
    : "GATEWAY: tidak tersedia (overview)";

  const days = (st && st.stats && st.stats.status === "ok" && Array.isArray(st.stats.days)) ? st.stats.days : [];
  const today = days.length ? days[days.length - 1] : null;
  const tvLines = today
    ? ["HARI INI — " + today.date, `${today.messages} pesan`, `${today.tool_calls} tool · ${today.sessions} sesi`, "sumber: /api/stats"]
    : ["tidak tersedia", "—", "—", "sumber: /api/stats"];

  const snap = [];
  if (o.running_delegations && o.running_delegations.status === "ok") {
    (o.running_delegations.running_ids || []).forEach((id) => {
      const dd = ((ag && ag.agents && ag.agents.delegations && ag.agents.delegations.recent) || []).find((r) => r.delegation_id === id);
      snap.push(`[office] Delegasi ${shortId(id)} berjalan${dd ? ` sejak ${fmtTime(dd.dispatched_at_iso)}` : ""}`);
    });
  }
  if (o.active_sessions && o.active_sessions.status === "ok") {
    (o.active_sessions.sessions || []).slice(0, 3).forEach((s) => {
      snap.push(`[office] ${s.source === "subagent" ? "Sub-agent" : "Sesi"} ${shortId(s.id)}${s.model ? ` · ${s.model}` : ""} · mulai ${fmtTime(s.started_at_iso)}${s.active ? "" : " (selesai)"}`);
    });
  }
  if (o.opencode_workers && o.opencode_workers.status === "ok") {
    snap.push(`[office] OpenCode: ${o.opencode_workers.recent_sessions ?? 0} sesi dalam ${Math.round((o.opencode_workers.recent_window_s || 900) / 60)} mnt · ${o.opencode_workers.total_sessions ?? 0} total${o.opencode_workers.active ? " · AKTIF" : ""}`);
  }

  const workingNames = d.agents.filter((x) => x.st === "working").map((x) => x.a.name).join(", ");

  return (
    <>
      <div className="mc-fresh mb-0.5">
        {refreshing ? "memuat…" : "auto-refresh 10 dtk"} · data: {data.generated_at || ""}
      </div>
      <Card
        title="Visual Office"
        right={<Badge tone="info">read-only</Badge>}
      >
        <div className="flex items-center gap-1.5 mb-2.5 flex-wrap" role="group" aria-label="Pilih ruangan Visual Office">
          {ROOM_DEFS.map((r) => (
            <button
              key={r.key}
              type="button"
              aria-pressed={room === r.key}
              onClick={() => setRoom(r.key)}
              className={`mc-btn-ghost inline-flex items-center gap-1.5 text-[12px] px-3 py-1.5 ${room === r.key ? "!text-sky-300 !border-sky-400/50 !bg-sky-400/10" : ""}`}
            >
              <r.icon size={14} /> {r.label}
            </button>
          ))}
          <span className="ml-auto text-[11px] text-mc-muted flex items-center gap-3">
            <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full inline-block" style={{ background: STATE_META.working.color }} /> bekerja</span>
            <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full inline-block" style={{ background: STATE_META.idle.color }} /> idle</span>
            <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full inline-block" style={{ background: STATE_META.offline.color }} /> offline</span>
            <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full inline-block" style={{ background: STATE_META.unknown.color }} /> unknown</span>
          </span>
        </div>
        <p className="sm:hidden m-0 mb-2 text-[11px] text-sky-300/90">↔ Geser horizontal untuk melihat seluruh ruangan.</p>
        <div style={{ overflowX: "auto", maxWidth: "100%" }}>
          <VisualOfficeSVG room={room} d={d} selId={selId} onSelect={setSelId} gwLine={gwLine} tvLines={tvLines} />
        </div>
        <div className="sm:hidden mt-3" aria-label="Daftar agent Visual Office">
          <div className="mc-section-label !p-0 mb-1.5">Daftar agent (alternatif akses)</div>
          {d.agents.length ? <div className="flex flex-col gap-1.5">{d.agents.map((x) => (
            <button type="button" key={x.a.id} onClick={() => setSelId(x.a.id)} aria-pressed={selId === x.a.id} className={`mc-feed-item text-left ${selId === x.a.id ? "border-sky-400/60 bg-sky-400/10" : ""}`}>
              <div className="min-w-0 flex-1"><div className="text-[12px] font-semibold text-mc-text break-words">{x.a.name}</div><div className="text-[10.5px] text-mc-muted mt-0.5">{x.a.role || "—"}</div></div><Badge tone={x.st === "working" ? "ok" : x.st === "unknown" ? "warn" : "neutral"}>{STATE_META[x.st]?.label || x.st}</Badge>
            </button>
          ))}</div> : <Empty msg="agent belum tersedia" />}
        </div>
        <div className="mc-footnote">
          Klik karakter agent untuk detail. Bekerja → Workspace (dekat workstation sendiri); Idle/Offline → Lounge; tak dapat ditentukan → Zona Unknown (berlabel).
        </div>
      </Card>

      <Card title="Ringkasan crew" right={<Badge tone={d.rosterOk ? "ok" : rosterErr ? "bad" : "neutral"}>{d.rosterOk ? "dari data nyata" : rosterErr ? "roster gagal" : "memuat…"}</Badge>}>
        {!d.rosterOk ? (
          rosterErr ? (
            <Unavailable msg="roster tidak tersedia — hitungan tidak dihitung (hindari angka palsu)" />
          ) : (
            <Loading />
          )
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {["working", "idle", "offline", "unknown"].map((k) => (
                <div key={k} className="mc-agent-card !p-3">
                  <div className="text-[22px] font-bold" style={{ color: STATE_META[k].color }}>{d.counts[k]}</div>
                  <div className="text-[11px] text-mc-muted uppercase tracking-wider">{STATE_META[k].label}</div>
                  <div className="text-[10.5px] text-mc-faint mt-1 break-words">
                    {d.agents.filter((x) => x.st === k).map((x) => x.a.name).join(", ") || "—"}
                  </div>
                </div>
              ))}
            </div>
            <div className="mc-footnote">
              Hitungan hanya dari data nyata: /api/office + /api/agents/roster. Agent tanpa sinyal kerja → Unknown, bukan tebakan.
            </div>
          </>
        )}
      </Card>

      {sel ? <AgentDetailCard x={sel} onClose={() => setSelId(null)} /> : null}

      <Card title="Live Activity" right={<Badge tone={events.length ? "info" : "neutral"}>{events.length ? `${events.length} perubahan` : "tidak ada perubahan"}</Badge>}>
        {events.length ? (
          <div className="flex flex-col gap-1 mb-2">
            {events.map((ev, i) => (
              <div key={i} className="mc-feed-item">
                <ActivityIcon size={12} className="text-sky-400 shrink-0 mt-0.5" />
                <div className="min-w-0">
                  <div className="text-[12px] text-mc-text">{ev.e}</div>
                  <div className="text-[10px] text-mc-faint font-mono">deteksi antar-polling /office · {ev.t}</div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mc-empty">Tidak ada perubahan status sejak polling sebelumnya · {data.generated_at || ""}</div>
        )}
        <div className="mc-section-label mt-1">Status saat ini (snapshot nyata)</div>
        {snap.length ? (
          <div className="flex flex-col gap-1">
            {snap.map((s, i) => (
              <div key={i} className="text-[11.5px] text-mc-muted font-mono">{s}</div>
            ))}
          </div>
        ) : (
          <div className="mc-empty">Tidak ada item aktif</div>
        )}
      </Card>

      <Card title="Status sumber & channel" right={<Badge tone="info">live</Badge>}>
        <div className="flex items-center gap-2 text-[13px] py-1">
          <span className="mc-row-key">Gateway / War Room</span>
          <Badge tone={st8.wr.tone}>{st8.wr.label}</Badge>
          <span className="text-[11px] text-mc-muted mt-0.5 font-mono ml-auto">{st8.wr.detail}</span>
        </div>
        <div className="flex items-center gap-2 text-[13px] py-1">
          <span className="mc-row-key">Meja Lead Agent (Hermes)</span>
          <Badge tone={st8.lead.tone}>{st8.lead.label}</Badge>
          <span className="text-[11px] text-mc-muted mt-0.5 font-mono ml-auto">{st8.lead.detail}</span>
        </div>
        <div className="flex items-center gap-2 text-[13px] py-1">
          <span className="mc-row-key">Meja Agent Engineer</span>
          <Badge tone={st8.eng.tone}>{st8.eng.label}</Badge>
          <span className="text-[11px] text-mc-muted mt-0.5 font-mono ml-auto">{st8.eng.detail}</span>
        </div>
        <div className="flex items-center gap-2 text-[13px] py-1">
          <span className="mc-row-key">Meja OpenCode Worker</span>
          <Badge tone={st8.oc.tone}>{st8.oc.label}</Badge>
          <span className="text-[11px] text-mc-muted mt-0.5 font-mono ml-auto">{st8.oc.detail}</span>
        </div>
        {[[ "gateway_active_agents", st8.leadSrc ], [ "active_sessions", st8.wrSrc ], [ "running_delegations", st8.engSrc ], [ "opencode_workers", st8.ocSrc ]]
          .filter(([, s]) => !s || s.status !== "ok")
          .map(([name, s]) => (
            <Feedback key={name} kind="err">
              {name}: {(s && (s.error || "tidak tersedia")) || "tidak tersedia"}
            </Feedback>
          ))}
        <div className="mc-section-label mt-2">Channel (dari /api/overview → gateway.platforms)</div>
        {platforms ? (
          Object.entries(platforms).map(([id, p]) => {
            const okc = p.state === "connected";
            const label = id === "telegram" ? "Telegram (gateway)" : id === "api_server" ? "API Server (gateway)" : id;
            return (
              <div key={id} className="flex items-center gap-2 text-[13px] py-1">
                <span className="mc-row-key">{label}</span>
                <Badge tone={okc ? "ok" : p.state === "error" ? "bad" : "warn"}>{String(p.state || "?").toUpperCase()}</Badge>
                {p.needs_attention ? <TriangleAlert size={12} className="text-amber-400" /> : null}
                {p.error_message ? <span className="text-[11px] text-mc-muted font-mono ml-auto">{p.error_message}</span> : null}
              </div>
            );
          })
        ) : (
          <Unavailable msg="gateway/platforms tidak tersedia" />
        )}
        {ov && ov.gateway && ov.gateway.status !== "ok" ? (
          <Feedback kind="err">gateway: {(ov.gateway.error) || "tidak tersedia"}</Feedback>
        ) : null}
      </Card>

      {workingNames ? <div className="mc-footnote">Bekerja sekarang: {workingNames || "—"}</div> : null}
    </>
  );
}

// --- PANEL: Agent Knowledge Workspace (scoped private + shared context) -------------
function AgentWorkspacePanel() {
  const { data, error, refreshing } = usePolling(`${EP}/obsidian/agent-workspaces`, POLL_OBSIDIAN_MS);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [graph, setGraph] = useState(null);
  const [graphError, setGraphError] = useState(null);
  const [proposalOpen, setProposalOpen] = useState(false);
  const [proposalBusy, setProposalBusy] = useState(false);
  const [proposalMessage, setProposalMessage] = useState(null);
  const [proposalForm, setProposalForm] = useState({ path: "", title: "", content: "" });

  const workspaces = data && Array.isArray(data.workspaces) ? data.workspaces : [];
  useEffect(() => {
    if (!selectedAgentId && workspaces.length) setSelectedAgentId(workspaces[0].agent_id || "");
    if (selectedAgentId && workspaces.length && !workspaces.some((row) => row.agent_id === selectedAgentId)) {
      setSelectedAgentId(workspaces[0].agent_id || "");
    }
  }, [selectedAgentId, workspaces]);

  useEffect(() => {
    let cancelled = false;
    if (!selectedAgentId) {
      setDetail(null);
      setGraph(null);
      setDetailError(null);
      setGraphError(null);
      return undefined;
    }
    setDetailLoading(true);
    setDetailError(null);
    setGraphError(null);
    const encoded = encodeURIComponent(selectedAgentId);
    safeFetchJSON(`${EP}/obsidian/agent-workspaces/${encoded}`)
      .then((json) => {
        if (!cancelled) setDetail(json);
      })
      .catch((e) => {
        if (!cancelled) {
          notifyUnauthorized(e);
          setDetailError(String((e && e.message) || e));
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    safeFetchJSON(`${EP}/obsidian/agent-workspaces/${encoded}/graph?path=README.md&depth=1&max_notes=20&max_bytes=60000`)
      .then((json) => {
        if (!cancelled) setGraph(json);
      })
      .catch((e) => {
        if (!cancelled) {
          notifyUnauthorized(e);
          setGraphError(String((e && e.message) || e));
        }
      });
    return () => { cancelled = true; };
  }, [selectedAgentId]);

  async function submitProposal(e) {
    e.preventDefault();
    setProposalBusy(true);
    setProposalMessage(null);
    try {
      const json = await safeFetchJSON(`${EP}/obsidian/agent-workspaces/${encodeURIComponent(selectedAgentId)}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path: proposalForm.path.trim(),
          title: proposalForm.title.trim(),
          content: proposalForm.content,
        }),
      });
      setProposalMessage({ kind: "ok", text: `Proposal pending: ${(json && json.proposal && json.proposal.relative_path) || "—"}. Private page belum ditulis.` });
      setProposalForm({ path: "", title: "", content: "" });
      setProposalOpen(false);
    } catch (e2) {
      notifyUnauthorized(e2);
      setProposalMessage({ kind: "err", text: String((e2 && e2.message) || e2) });
    } finally {
      setProposalBusy(false);
    }
  }

  if (!data && !error) return <Loading />;
  if (error) return <Card title="Agent Knowledge Workspace"><Unavailable msg={error} /></Card>;

  const policy = (data && data.policy) || {};
  const workspace = (detail && detail.workspace) || {};
  const privateNotes = Array.isArray(workspace.notes) ? workspace.notes : [];
  const sharedContext = detail && Array.isArray(detail.shared_context) ? detail.shared_context : [];
  const graphNotes = graph && Array.isArray(graph.notes) ? graph.notes : [];
  const graphContext = graph && graph.context ? graph.context : {};
  const selected = workspaces.find((row) => row.agent_id === selectedAgentId) || {};

  return (
    <Card
      title="Agent Knowledge Workspace"
      right={
        <div className="flex items-center gap-2 flex-wrap justify-end">
          <Badge tone="info">owner control-plane</Badge>
          <Badge tone="warn">proposal-only writes</Badge>
          <select
            className="mc-input !w-auto max-w-[260px] text-[12px] py-1"
            value={selectedAgentId}
            onChange={(e) => { setSelectedAgentId(e.target.value); setProposalMessage(null); }}
            aria-label="Pilih agent knowledge workspace"
            disabled={!workspaces.length}
          >
            {!workspaces.length ? <option value="">{refreshing ? "Memuat workspace…" : "Workspace tidak tersedia"}</option> : null}
            {workspaces.map((row) => <option key={row.agent_id} value={row.agent_id}>{row.name || row.agent_id}</option>)}
          </select>
        </div>
      }
    >
      {data && data.status !== "ok" ? <Unavailable msg={data.error || "workspace tidak tersedia"} /> : null}
      {detailError ? <Feedback kind="err" className="mb-2">Workspace gagal dimuat: {detailError}</Feedback> : null}
      {proposalMessage ? <Feedback kind={proposalMessage.kind} className="mb-2">{proposalMessage.text}</Feedback> : null}
      <div className="text-[10.5px] text-mc-faint mb-3">
        Scope private: <code>30-Agents/{selectedAgentId || "<agent-id>"}</code> · shared read: <code>10-Wiki</code> · owner session: {policy.scope || "owner_control_plane"} · runtime API: <code>verified_service_token / enforced</code>
      </div>
      {!selectedAgentId ? <Empty msg="belum ada agent knowledge workspace" /> : detailLoading && !detail ? <Loading /> : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 min-w-0">
          <div className="min-w-0">
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <div className="mc-section-label !p-0">Private notes · {privateNotes.length}</div>
              <button type="button" className="mc-btn-ghost inline-flex items-center gap-1 text-[11px] px-2 py-1" onClick={() => { setProposalOpen((v) => !v); setProposalMessage(null); }}><Plus size={12} /> {proposalOpen ? "Tutup proposal" : "Ajukan note"}</button>
            </div>
            <div className="text-[10.5px] text-mc-muted mb-2">{workspace.name || selected.name || selectedAgentId} · {workspace.status || "—"} · canonical path only</div>
            {proposalOpen ? (
              <form onSubmit={submitProposal} className="border border-amber-400/20 bg-amber-400/[0.04] rounded-xl p-3 mb-3 flex flex-col gap-2">
                <div className="text-[11px] font-semibold text-amber-100">Proposal private note</div>
                <div className="text-[10.5px] text-amber-200/80">Path relatif terhadap namespace, misalnya <code>notes/decision.md</code>. Backend menulis pending proposal saja; halaman private accepted tidak disentuh.</div>
                <label className="text-[11px] text-mc-muted">Target path<input className="mc-input w-full mt-1 font-mono" required maxLength={480} value={proposalForm.path} onChange={(e) => setProposalForm({ ...proposalForm, path: e.target.value })} placeholder="notes/decision.md" /></label>
                <label className="text-[11px] text-mc-muted">Judul<input className="mc-input w-full mt-1" maxLength={160} value={proposalForm.title} onChange={(e) => setProposalForm({ ...proposalForm, title: e.target.value })} placeholder="Keputusan atau runbook" /></label>
                <label className="text-[11px] text-mc-muted">Isi<textarea className="mc-input w-full mt-1 min-h-[120px] font-mono text-[12px]" required maxLength={131072} value={proposalForm.content} onChange={(e) => setProposalForm({ ...proposalForm, content: e.target.value })} /></label>
                <button type="submit" className="mc-btn-primary inline-flex items-center gap-1.5 self-start" disabled={proposalBusy || !proposalForm.path.trim() || !proposalForm.content.trim()}><Save size={13} /> {proposalBusy ? "Membuat proposal…" : "Buat proposal"}</button>
              </form>
            ) : null}
            {privateNotes.length === 0 ? <Empty msg="namespace belum memiliki note" /> : <div className="flex flex-col gap-1.5 max-h-[300px] overflow-y-auto pr-0.5">{privateNotes.map((note) => <div key={note.relative_path} className="border border-mc-border rounded-lg p-2"><div className="text-[12px] font-semibold break-words">{note.title || note.relative_path}</div><div className="text-[10.5px] text-mc-muted font-mono break-all mt-0.5">{note.workspace_relative_path || note.relative_path} · {fmtSize(note.size)}</div></div>)}</div>}
          </div>
          <div className="min-w-0">
            <div className="mc-section-label !p-0 mb-1.5">Shared 10-Wiki context</div>
            {sharedContext.length === 0 ? <Empty msg="shared context tidak tersedia" /> : <div className="flex flex-col gap-1.5 max-h-[260px] overflow-y-auto pr-0.5">{sharedContext.map((note) => <div key={note.relative_path} className="border border-mc-border rounded-lg p-2"><div className="text-[12px] font-semibold break-words">{note.title || note.relative_path}</div><div className="text-[10.5px] text-sky-300 font-mono break-all mt-0.5">{note.relative_path}</div><div className="text-[11px] text-mc-faint mt-1 line-clamp-3 whitespace-pre-wrap">{note.content || "(kosong)"}</div></div>)}</div>}
            <div className="border border-violet-400/20 bg-violet-400/[0.04] rounded-lg p-2 mt-3">
              <div className="flex items-center justify-between gap-2 mb-1"><div className="text-[10px] uppercase tracking-wider text-violet-200/80">Scoped graph</div><span className="text-[10px] text-mc-faint">{graphContext.note_count || 0} notes · {graphContext.depth ?? "—"} hop</span></div>
              {graphError ? <Unavailable msg={graphError} /> : graphNotes.length === 0 ? <Empty msg="graph context kosong" /> : <div className="flex flex-wrap gap-1">{graphNotes.map((note) => <span key={note.relative_path} className={`mc-chip text-[10px] ${note.relative_path.startsWith("10-Wiki/") ? "text-sky-300" : "text-violet-300"}`}>{note.relative_path}</span>)}</div>}
              <div className="text-[10.5px] text-mc-faint mt-2">Graph hanya mencakup namespace agent terpilih dan shared <code>10-Wiki</code>; hasil dibatasi note/byte budget.</div>
            </div>
          </div>
        </div>
      )}
      <div className="mc-footnote mt-3">Policy: {policy.scope || "owner_control_plane"} · caller-supplied agent ID bukan runtime authentication · OpenCode executor-only tanpa namespace private.</div>
    </Card>
  );
}

// --- PANEL: Knowledge Base (VPS-only headless Obsidian) -----------------------------
function ObsidianPanel() {
  const { data, error, refreshing } = usePolling(`${EP}/obsidian`, POLL_OBSIDIAN_MS);
  const [query, setQuery] = useState("");
  const [folder, setFolder] = useState("");
  const [searchData, setSearchData] = useState(null);
  const [searchError, setSearchError] = useState(null);
  const [searching, setSearching] = useState(false);
  const [searchTick, setSearchTick] = useState(0);
  const [selectedPath, setSelectedPath] = useState("");
  const [noteData, setNoteData] = useState(null);
  const [noteError, setNoteError] = useState(null);
  const [noteLoading, setNoteLoading] = useState(false);
  const [graphData, setGraphData] = useState(null);
  const [graphError, setGraphError] = useState(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [composerOpen, setComposerOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [writeMessage, setWriteMessage] = useState(null);
  const [form, setForm] = useState({ path: "", title: "", tags: "", related: "", content: "" });
  const [ingestOpen, setIngestOpen] = useState(false);
  const [ingestSaving, setIngestSaving] = useState(false);
  const [ingestMessage, setIngestMessage] = useState(null);
  const [ingestForm, setIngestForm] = useState({ title: "", source_url: "", source_type: "article", tags: "", summary: "", content: "" });
  const [proposalsData, setProposalsData] = useState(null);
  const [proposalsError, setProposalsError] = useState(null);
  const [proposalsLoading, setProposalsLoading] = useState(false);
  const [selectedProposal, setSelectedProposal] = useState(null);
  const [proposalError, setProposalError] = useState(null);
  const [proposalLoading, setProposalLoading] = useState(false);
  const [approvalTarget, setApprovalTarget] = useState("");
  const [approvalType, setApprovalType] = useState("concept");
  const [approvalConfirm, setApprovalConfirm] = useState(false);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [approvalMessage, setApprovalMessage] = useState(null);
  const [lintData, setLintData] = useState(null);
  const [lintError, setLintError] = useState(null);
  const [lintLoading, setLintLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ query, folder, limit: "50" });
      setSearching(true);
      safeFetchJSON(`${EP}/obsidian/notes?${params.toString()}`)
        .then((json) => {
          if (!cancelled) {
            setSearchData(json);
            setSearchError(null);
          }
        })
        .catch((e) => {
          if (!cancelled) {
            notifyUnauthorized(e);
            setSearchError(String((e && e.message) || e));
          }
        })
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, folder, searchTick]);

  useEffect(() => {
    let cancelled = false;
    if (!selectedPath) {
      setNoteData(null);
      setNoteError(null);
      setGraphData(null);
      setGraphError(null);
      setNoteLoading(false);
      setGraphLoading(false);
      return undefined;
    }
    const encodedPath = selectedPath.split("/").map((part) => encodeURIComponent(part)).join("/");
    setNoteLoading(true);
    setGraphLoading(true);
    setGraphError(null);
    safeFetchJSON(`${EP}/obsidian/notes/${encodedPath}`)
      .then((json) => {
        if (!cancelled) {
          setNoteData(json);
          setNoteError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          notifyUnauthorized(e);
          setNoteError(String((e && e.message) || e));
        }
      })
      .finally(() => {
        if (!cancelled) setNoteLoading(false);
      });
    const params = new URLSearchParams({ path: selectedPath, depth: "2", max_notes: "20", max_bytes: "120000" });
    safeFetchJSON(`${EP}/obsidian/graph?${params.toString()}`)
      .then((json) => {
        if (!cancelled) {
          setGraphData(json);
          setGraphError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          notifyUnauthorized(e);
          setGraphError(String((e && e.message) || e));
        }
      })
      .finally(() => {
        if (!cancelled) setGraphLoading(false);
      });
    return () => { cancelled = true; };
  }, [selectedPath]);

  async function loadProposals() {
    setProposalsLoading(true);
    try {
      const json = await safeFetchJSON(`${EP}/obsidian/inbox?limit=50`);
      setProposalsData(json);
      setProposalsError(null);
    } catch (e) {
      notifyUnauthorized(e);
      setProposalsError(String((e && e.message) || e));
    } finally {
      setProposalsLoading(false);
    }
  }

  async function loadProposal(path) {
    if (!path) return;
    setProposalLoading(true);
    setProposalError(null);
    setApprovalMessage(null);
    try {
      const encoded = path.split("/").map((part) => encodeURIComponent(part)).join("/");
      const json = await safeFetchJSON(`${EP}/obsidian/inbox/${encoded}`);
      setSelectedProposal(json && json.proposal ? json.proposal : null);
      setApprovalConfirm(false);
      setApprovalTarget("");
    } catch (e) {
      notifyUnauthorized(e);
      setProposalError(String((e && e.message) || e));
    } finally {
      setProposalLoading(false);
    }
  }

  async function loadLint() {
    setLintLoading(true);
    try {
      const json = await safeFetchJSON(`${EP}/obsidian/lint?limit=200`);
      setLintData(json);
      setLintError(null);
    } catch (e) {
      notifyUnauthorized(e);
      setLintError(String((e && e.message) || e));
    } finally {
      setLintLoading(false);
    }
  }

  useEffect(() => {
    loadProposals();
    loadLint();
  }, []);

  async function ingestSource(e) {
    e.preventDefault();
    setIngestSaving(true);
    setIngestMessage(null);
    try {
      const json = await safeFetchJSON(`${EP}/obsidian/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: ingestForm.title.trim(),
          source_url: ingestForm.source_url.trim(),
          source_type: ingestForm.source_type,
          tags: ingestForm.tags.split(",").map((x) => x.trim()).filter(Boolean),
          summary: ingestForm.summary,
          content: ingestForm.content,
        }),
      });
      const proposal = json && json.proposal;
      setIngestMessage({ kind: "ok", text: json && json.deduplicated ? "Sumber sudah memiliki proposal; raw capture tetap immutable." : `Proposal dibuat: ${(proposal && proposal.relative_path) || "—"}` });
      setIngestOpen(false);
      setIngestForm({ title: "", source_url: "", source_type: "article", tags: "", summary: "", content: "" });
      await loadProposals();
      if (proposal && proposal.relative_path) loadProposal(proposal.relative_path);
    } catch (e2) {
      notifyUnauthorized(e2);
      setIngestMessage({ kind: "err", text: String((e2 && e2.message) || e2) });
    } finally {
      setIngestSaving(false);
    }
  }

  async function approveProposal(e) {
    e.preventDefault();
    if (!selectedProposal || !approvalTarget.trim() || !approvalConfirm) return;
    setApprovalBusy(true);
    setApprovalMessage(null);
    try {
      const json = await safeFetchJSON(`${EP}/obsidian/inbox/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          confirm: true,
          proposal_path: selectedProposal.relative_path,
          target_path: approvalTarget.trim(),
          type: approvalType,
        }),
      });
      setApprovalMessage({ kind: "ok", text: `Approved ke ${json && json.accepted ? json.accepted.relative_path : approvalTarget.trim()}` });
      setApprovalConfirm(false);
      await loadProposals();
      await loadProposal(selectedProposal.relative_path);
      setSearchTick((n) => n + 1);
      loadLint();
    } catch (e2) {
      notifyUnauthorized(e2);
      setApprovalMessage({ kind: "err", text: String((e2 && e2.message) || e2) });
    } finally {
      setApprovalBusy(false);
    }
  }

  async function createNote(e) {
    e.preventDefault();
    setSaving(true);
    setWriteMessage(null);
    const payload = {
      path: form.path.trim(),
      title: form.title.trim(),
      content: form.content,
      tags: form.tags.split(",").map((x) => x.trim()).filter(Boolean),
      related: form.related.split(",").map((x) => x.trim()).filter(Boolean),
    };
    try {
      const json = await safeFetchJSON(`${EP}/obsidian/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const createdPath = json && json.note && json.note.relative_path;
      setWriteMessage({ kind: "ok", text: `Catatan dibuat: ${createdPath || payload.path}` });
      setComposerOpen(false);
      setForm({ path: "", title: "", tags: "", related: "", content: "" });
      setSearchTick((n) => n + 1);
      if (createdPath) setSelectedPath(createdPath);
    } catch (e2) {
      notifyUnauthorized(e2);
      setWriteMessage({ kind: "err", text: String((e2 && e2.message) || e2) });
    } finally {
      setSaving(false);
    }
  }

  const vault = data || {};
  const statusOk = vault.status === "ok";
  const rows = (searchData && Array.isArray(searchData.results)) ? searchData.results : [];
  const folders = Array.from(new Set([
    ...(((data && data.folders) || []).filter(Boolean)),
    ...(((data && data.notes) || []).map((note) => note && note.folder).filter(Boolean)),
  ])).sort((a, b) => a.localeCompare(b));
  const statusTone = statusOk ? "ok" : vault.status === "unavailable" ? "warn" : "bad";
  const graphNotes = graphData && Array.isArray(graphData.notes) ? graphData.notes : [];
  const graphSeed = graphData && graphData.seed ? graphData.seed : null;
  const graphBacklinks = graphData && Array.isArray(graphData.backlinks) ? graphData.backlinks : [];
  const unresolved = graphData && Array.isArray(graphData.unresolved_links) ? graphData.unresolved_links : [];

  return (
    <>
      <AgentWorkspacePanel />
      <div className="mc-fresh mb-0.5 flex items-center justify-between gap-2 flex-wrap" aria-live="polite">
        <span>{refreshing || searching ? "memuat…" : "auto-refresh 30 dtk"} · data: {vault.generated_at || "—"}</span>
        <button type="button" className="mc-btn-ghost inline-flex items-center gap-1.5 text-[12px] px-2.5 py-1" onClick={() => { setComposerOpen((v) => !v); setWriteMessage(null); }}>
          <Plus size={13} /> {composerOpen ? "Tutup form" : "Buat catatan"}
        </button>
      </div>
      {writeMessage ? <Feedback kind={writeMessage.kind} className="mb-2">{writeMessage.text}</Feedback> : null}
      <Card
        title="Knowledge Base — Obsidian"
        right={<div className="flex items-center gap-2 flex-wrap justify-end"><Badge tone={statusTone}>{statusOk ? "tersedia" : (vault.status || "unavailable")}</Badge><Badge tone="info">VPS-only · auth write</Badge></div>}
      >
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
          <div className="mc-agent-card !p-2.5"><div className="text-[18px] font-bold text-sky-300">{statusOk ? fmtNum(vault.note_count) : "—"}</div><div className="text-[10px] text-mc-muted">catatan Markdown</div></div>
          <div className="mc-agent-card !p-2.5"><div className="text-[18px] font-bold text-violet-300">{statusOk ? fmtNum(vault.folder_count) : "—"}</div><div className="text-[10px] text-mc-muted">folder</div></div>
          <div className="mc-agent-card !p-2.5 col-span-2 sm:col-span-2"><div className="text-[12px] font-mono text-mc-text break-words">{vault.vault_path || "—"}</div><div className="text-[10px] text-mc-muted">lokasi tampilan aman · tanpa GUI / sync</div></div>
        </div>
        {!statusOk ? <Unavailable msg={vault.error || error || "vault tidak tersedia"} /> : null}
        {error && statusOk ? <Feedback kind="err" className="mb-2">Refresh status gagal: {error}</Feedback> : null}
        {composerOpen ? (
          <form onSubmit={createNote} className="border border-sky-400/20 bg-sky-400/[0.04] rounded-xl p-3 mb-3 flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2"><div className="mc-section-label !p-0">Catatan durable baru</div><Badge tone="warn">core MEMORY.md/USER.md tidak disentuh</Badge></div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <label className="text-[11px] text-mc-muted">Path relatif (.md)<input className="mc-input w-full mt-1" required maxLength={480} value={form.path} onChange={(e) => setForm({ ...form, path: e.target.value })} placeholder="Decisions/deploy.md" /></label>
              <label className="text-[11px] text-mc-muted">Judul<input className="mc-input w-full mt-1" maxLength={160} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Keputusan deploy" /></label>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <label className="text-[11px] text-mc-muted">Tags, pisahkan koma<input className="mc-input w-full mt-1" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} placeholder="decision, deploy" /></label>
              <label className="text-[11px] text-mc-muted">Related notes, pisahkan koma<input className="mc-input w-full mt-1" value={form.related} onChange={(e) => setForm({ ...form, related: e.target.value })} placeholder="Projects/Roadmap.md" /></label>
            </div>
            <label className="text-[11px] text-mc-muted">Isi ringkas<textarea className="mc-input w-full mt-1 min-h-[150px] font-mono text-[12px] leading-relaxed" required maxLength={131072} value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} placeholder="Keputusan, alasan, outcome, atau runbook ringkas…" /></label>
            <div className="flex items-center justify-between gap-2 flex-wrap"><span className="text-[10.5px] text-mc-faint">Wikilink aman akan dinormalisasi; backlink dihitung otomatis dari link maju.</span><button type="submit" className="mc-btn-primary inline-flex items-center gap-1.5" disabled={saving || !form.path.trim() || !form.content.trim()}><Save size={13} /> {saving ? "Menyimpan…" : "Simpan catatan"}</button></div>
          </form>
        ) : null}
        <div className="flex flex-col sm:flex-row gap-2 mb-3">
          <input className="mc-input !min-w-0 w-full sm:flex-1" value={query} maxLength={120} onChange={(e) => setQuery(e.target.value)} placeholder="Cari nama file atau isi catatan…" aria-label="Cari catatan Obsidian" />
          <select className="mc-select w-full sm:w-auto sm:min-w-[170px]" value={folder} onChange={(e) => setFolder(e.target.value)} aria-label="Filter folder Obsidian"><option value="">Semua folder</option>{folders.map((name) => <option key={name} value={name}>{name}</option>)}</select>
        </div>
        {searchError ? <Feedback kind="err" className="mb-2">Pencarian gagal: {searchError}</Feedback> : null}
        {searching && !searchData ? <Loading /> : searchData && searchData.status !== "ok" ? <Unavailable msg={searchData.error || "vault tidak tersedia"} /> : null}
        {searchData && searchData.status === "ok" ? (
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.4fr)] gap-3 min-w-0">
            <div className="min-w-0">
              <div className="flex items-center justify-between gap-2 mb-1.5"><div className="mc-section-label !p-0">Catatan · {searchData.count || 0}</div><span className="text-[10.5px] text-mc-faint" aria-live="polite">maks. 50 hasil</span></div>
              {rows.length === 0 ? <Empty msg={query || folder ? "tidak ada catatan yang cocok" : "vault belum memiliki catatan Markdown"} /> : (
                <div className="flex flex-col gap-1.5 max-h-[520px] overflow-y-auto pr-0.5">
                  {rows.map((note) => (
                    <button type="button" key={note.relative_path} onClick={() => setSelectedPath(note.relative_path)} aria-pressed={selectedPath === note.relative_path} className={`text-left rounded-lg border p-2.5 min-w-0 transition-colors ${selectedPath === note.relative_path ? "border-sky-400/60 bg-sky-400/10" : "border-mc-border bg-white/[0.02] hover:bg-white/[0.05]"}`}>
                      <div className="flex items-start gap-2 min-w-0"><FileText size={14} className="text-sky-300 shrink-0 mt-0.5" aria-hidden /><div className="min-w-0 flex-1"><div className="text-[12.5px] font-semibold text-mc-text break-words">{note.title || note.relative_path}</div><div className="text-[10.5px] text-mc-muted font-mono break-all mt-0.5">{note.relative_path} · {fmtSize(note.size)}</div>{note.snippet ? <div className="text-[11px] text-mc-faint mt-1 line-clamp-3 break-words">{note.snippet}</div> : null}</div></div>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="min-w-0">
              <div className="mc-section-label !p-0 mb-1.5">Pembaca & graph context</div>
              {!selectedPath ? <Empty msg="pilih catatan untuk membaca" /> : noteLoading && !noteData ? <Loading /> : noteError ? <Unavailable msg={noteError} /> : noteData && noteData.status === "ok" ? (
                <div className="min-w-0">
                  <div className="flex items-start gap-2 flex-wrap mb-2"><div className="min-w-0 flex-1"><div className="text-[14px] font-semibold break-words">{noteData.title || selectedPath}</div><div className="text-[10.5px] text-mc-muted font-mono break-all">{noteData.relative_path} · {fmtSize(noteData.size)} · {fmtTime(noteData.updated)}</div></div><Badge tone="info">graph read</Badge></div>
                  {noteData.redacted ? <div className="text-[11px] text-amber-300/90 mb-2" role="status">Nilai kredensial di isi catatan disamarkan.</div> : null}
                  <pre className="mc-mem-pre !max-h-[360px] overflow-auto">{noteData.content || "(catatan kosong)"}</pre>
                  {graphLoading && !graphData ? <Loading /> : graphError ? <Unavailable msg={graphError} /> : graphData && graphData.status === "ok" ? (
                    <div className="mt-3 flex flex-col gap-2">
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        <div className="border border-mc-border rounded-lg p-2"><div className="text-[10px] uppercase tracking-wider text-mc-muted mb-1">Linked notes</div>{graphSeed && graphSeed.links && graphSeed.links.length ? <div className="flex flex-wrap gap-1">{graphSeed.links.map((p) => <button key={p} type="button" className="mc-chip text-[10px] text-sky-300 hover:border-sky-300/50" onClick={() => setSelectedPath(p)}>{p}</button>)}</div> : <div className="text-[11px] text-mc-faint">Tidak ada forward link.</div>}</div>
                        <div className="border border-mc-border rounded-lg p-2"><div className="text-[10px] uppercase tracking-wider text-mc-muted mb-1">Backlinks</div>{graphBacklinks.length ? <div className="flex flex-wrap gap-1">{graphBacklinks.map((p) => <button key={p} type="button" className="mc-chip text-[10px] text-violet-300 hover:border-violet-300/50" onClick={() => setSelectedPath(p)}>{p}</button>)}</div> : <div className="text-[11px] text-mc-faint">Belum ada backlink.</div>}</div>
                      </div>
                      <div className="border border-amber-400/20 bg-amber-400/[0.04] rounded-lg p-2"><div className="text-[10px] uppercase tracking-wider text-amber-200/80 mb-1">Unresolved links</div>{unresolved.length ? <div className="flex flex-col gap-1">{unresolved.slice(0, 10).map((row, i) => <div key={`${row.from}-${row.target}-${i}`} className="text-[11px] text-amber-100/80 font-mono break-all">{row.from} → [[{row.target}]]</div>)}</div> : <div className="text-[11px] text-mc-faint">Tidak ada link rusak pada chain ini.</div>}</div>
                      <div className="border border-mc-border rounded-lg p-2"><div className="flex items-center justify-between gap-2 mb-1"><div className="text-[10px] uppercase tracking-wider text-mc-muted">Context chain</div><span className="text-[10px] text-mc-faint">{graphData.context && graphData.context.note_count} notes · {graphData.context && graphData.context.depth} hop</span></div>{graphData.context && graphData.context.chain ? <div className="flex flex-col gap-1">{graphData.context.chain.map((row) => <div key={row.depth} className="text-[11px]"><span className="text-mc-muted mr-1">hop {row.depth}:</span>{row.notes.map((p) => <button key={p} type="button" className="mc-chip text-[10px] mr-1 mb-1" onClick={() => setSelectedPath(p)}>{p}</button>)}</div>)}</div> : null}{graphData.context && graphData.context.truncated ? <div className="text-[10.5px] text-amber-300 mt-1">Context dibatasi oleh budget note/byte.</div> : null}</div>
                      {graphNotes.length > 1 ? <div className="text-[10.5px] text-mc-faint">Backlink dihitung otomatis dari forward wikilink; target note tidak diedit massal.</div> : null}
                    </div>
                  ) : null}
                </div>
              ) : <Unavailable msg="catatan tidak tersedia" />}
            </div>
          </div>
        ) : null}
      </Card>
      <div className="mc-footnote">Knowledge Base membaca Markdown langsung dari vault VPS. Pembuatan note memakai sesi dashboard, atomic write, validasi path, redaksi secret, dan tidak pernah menulis MEMORY.md/USER.md.</div>

      {ingestMessage ? <Feedback kind={ingestMessage.kind}>{ingestMessage.text}</Feedback> : null}
      <Card
        title="Reviewed ingestion"
        right={<div className="flex items-center gap-2"><Badge tone="info">raw immutable</Badge><button type="button" className="mc-btn-ghost inline-flex items-center gap-1.5 text-[12px] px-2.5 py-1" onClick={() => { setIngestOpen((v) => !v); setIngestMessage(null); }}><Plus size={13} /> {ingestOpen ? "Tutup" : "Ajukan sumber"}</button></div>}
      >
        <div className="text-[11.5px] text-mc-muted mb-2">Kirim capture yang sudah direview di luar API. Backend hanya membuat raw capture immutable dan proposal inbox; tidak ada fetch URL dan tidak ada auto-approve.</div>
        {ingestOpen ? (
          <form onSubmit={ingestSource} className="border border-sky-400/20 bg-sky-400/[0.04] rounded-xl p-3 flex flex-col gap-2">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <label className="text-[11px] text-mc-muted">Judul<input className="mc-input w-full mt-1" required maxLength={160} value={ingestForm.title} onChange={(e) => setIngestForm({ ...ingestForm, title: e.target.value })} /></label>
              <label className="text-[11px] text-mc-muted">Source URL<input className="mc-input w-full mt-1" required maxLength={2048} type="url" value={ingestForm.source_url} onChange={(e) => setIngestForm({ ...ingestForm, source_url: e.target.value })} placeholder="https://example.com/article" /></label>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <label className="text-[11px] text-mc-muted">Source type<select className="mc-select w-full mt-1" value={ingestForm.source_type} onChange={(e) => setIngestForm({ ...ingestForm, source_type: e.target.value })}><option value="article">Article / web</option><option value="paper">Paper</option><option value="transcript">Transcript</option><option value="other">Other</option></select></label>
              <label className="text-[11px] text-mc-muted">Tags, pisahkan koma<input className="mc-input w-full mt-1" value={ingestForm.tags} onChange={(e) => setIngestForm({ ...ingestForm, tags: e.target.value })} placeholder="llm, research" /></label>
            </div>
            <label className="text-[11px] text-mc-muted">Summary opsional<textarea className="mc-input w-full mt-1 min-h-[70px]" maxLength={4000} value={ingestForm.summary} onChange={(e) => setIngestForm({ ...ingestForm, summary: e.target.value })} /></label>
            <label className="text-[11px] text-mc-muted">Reviewed capture<textarea className="mc-input w-full mt-1 min-h-[160px] font-mono text-[12px] leading-relaxed" required maxLength={131072} value={ingestForm.content} onChange={(e) => setIngestForm({ ...ingestForm, content: e.target.value })} placeholder="Paste capture yang sudah direview; secret akan ditolak." /></label>
            <div className="flex items-center justify-between gap-2 flex-wrap"><span className="text-[10.5px] text-mc-faint">URL hanya metadata. API tidak melakukan server-side fetching.</span><button type="submit" className="mc-btn-primary inline-flex items-center gap-1.5" disabled={ingestSaving || !ingestForm.title.trim() || !ingestForm.source_url.trim() || !ingestForm.content.trim()}><Save size={13} /> {ingestSaving ? "Menyimpan…" : "Buat proposal"}</button></div>
          </form>
        ) : <div className="mc-empty">Form tertutup — ajukan sumber hanya saat capture siap direview.</div>}
      </Card>

      <Card
        title="Inbox proposals"
        right={<div className="flex items-center gap-2"><Badge tone={proposalsData && proposalsData.count ? "warn" : "neutral"}>{proposalsData ? `${proposalsData.count || 0} proposal` : "—"}</Badge><button type="button" className="mc-btn-ghost inline-flex items-center gap-1 text-[11px] px-2 py-1" onClick={loadProposals} disabled={proposalsLoading} aria-busy={proposalsLoading}><RefreshCw size={12} className={proposalsLoading ? "mc-spin" : ""} aria-hidden="true" /> Refresh</button></div>}
      >
        {proposalsError ? <Unavailable msg={proposalsError} /> : proposalsLoading && !proposalsData ? <Loading /> : !proposalsData || !Array.isArray(proposalsData.proposals) || proposalsData.proposals.length === 0 ? <Empty msg="belum ada proposal reviewed" /> : (
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.4fr)] gap-3 min-w-0">
            <div className="flex flex-col gap-1.5 min-w-0 max-h-[430px] overflow-y-auto pr-0.5">
              {proposalsData.proposals.map((proposal) => (
                <button type="button" key={proposal.relative_path} onClick={() => loadProposal(proposal.relative_path)} className={`text-left rounded-lg border p-2.5 min-w-0 transition-colors ${selectedProposal && selectedProposal.relative_path === proposal.relative_path ? "border-violet-400/60 bg-violet-400/10" : "border-mc-border bg-white/[0.02] hover:bg-white/[0.05]"}`}>
                  <div className="flex items-start justify-between gap-2"><div className="min-w-0"><div className="text-[12.5px] font-semibold break-words">{proposal.title || proposal.relative_path}</div><div className="text-[10.5px] text-mc-muted font-mono break-all mt-0.5">{proposal.relative_path}</div></div><Badge tone={proposal.status === "pending" ? "warn" : "ok"}>{proposal.status || "?"}</Badge></div>
                  <div className="text-[10.5px] text-mc-faint mt-1 break-all">{proposal.source_type || "source"} · {proposal.source_url || "URL n/a"}</div>
                </button>
              ))}
            </div>
            <div className="min-w-0">
              {proposalLoading && !selectedProposal ? <Loading /> : proposalError ? <Unavailable msg={proposalError} /> : !selectedProposal ? <Empty msg="pilih proposal untuk review" /> : (
                <div className="border border-mc-border rounded-xl p-3 min-w-0">
                  <div className="flex items-start justify-between gap-2 flex-wrap"><div className="min-w-0"><div className="text-[14px] font-semibold break-words">{selectedProposal.title || "Proposal"}</div><div className="text-[10.5px] text-mc-muted font-mono break-all">{selectedProposal.relative_path}</div></div><Badge tone={selectedProposal.status === "pending" ? "warn" : "ok"}>{selectedProposal.status || "?"}</Badge></div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2 text-[11px]"><div className="mc-agent-card !p-2"><div className="text-mc-muted">Source</div><div className="font-mono break-all mt-1">{selectedProposal.source_url || "—"}</div></div><div className="mc-agent-card !p-2"><div className="text-mc-muted">Raw capture</div><div className="font-mono break-all mt-1">{selectedProposal.raw_capture || "—"}</div></div></div>
                  {selectedProposal.summary ? <div className="text-[11.5px] text-mc-muted mt-2">{selectedProposal.summary}</div> : null}
                  <pre className="mc-mem-pre !max-h-[260px] overflow-auto mt-2">{selectedProposal.content || "(proposal kosong)"}</pre>
                  {selectedProposal.status === "pending" ? (
                    <form onSubmit={approveProposal} className="border border-amber-400/25 bg-amber-400/[0.04] rounded-lg p-2.5 mt-3 flex flex-col gap-2">
                      <div className="text-[11px] font-semibold text-amber-100">Approval eksplisit</div>
                      <div className="text-[10.5px] text-amber-200/80">Target accepted page akan ditulis tepat ke path ini; tidak ada update massal note lain.</div>
                      <div className="grid grid-cols-1 sm:grid-cols-[minmax(0,1fr)_150px] gap-2"><label className="text-[11px] text-mc-muted">Target path<input className="mc-input w-full mt-1 font-mono" required maxLength={480} value={approvalTarget} onChange={(e) => setApprovalTarget(e.target.value)} placeholder="10-Wiki/concepts/topic.md" /></label><label className="text-[11px] text-mc-muted">Type<select className="mc-select w-full mt-1" value={approvalType} onChange={(e) => setApprovalType(e.target.value)}><option value="entity">entity</option><option value="concept">concept</option><option value="comparison">comparison</option><option value="query">query</option><option value="source">source</option><option value="decision">decision</option></select></label></div>
                      <label className="flex items-start gap-2 text-[11px] text-amber-100 cursor-pointer"><input type="checkbox" className="mt-0.5" checked={approvalConfirm} onChange={(e) => setApprovalConfirm(e.target.checked)} />Saya sudah meninjau proposal dan menyetujui penulisan ke <code className="break-all">{approvalTarget || "target path"}</code>.</label>
                      <button type="submit" className="mc-btn-primary inline-flex items-center gap-1.5 self-start" disabled={approvalBusy || !approvalTarget.trim() || !approvalConfirm}><CheckCircle2 size={13} /> {approvalBusy ? "Approving…" : "Approve proposal"}</button>
                    </form>
                  ) : <Feedback kind="ok" className="mt-3">Proposal sudah diproses; approval tidak diulang.</Feedback>}
                  {approvalMessage ? <Feedback kind={approvalMessage.kind} className="mt-2">{approvalMessage.text}</Feedback> : null}
                </div>
              )}
            </div>
          </div>
        )}
      </Card>

      <Card
        title="Wiki lint"
        right={<div className="flex items-center gap-2"><Badge tone={lintData && lintData.counts && lintData.counts.total ? "warn" : "ok"}>{lintData && lintData.counts ? `${lintData.counts.total} issue` : "—"}</Badge><button type="button" className="mc-btn-ghost inline-flex items-center gap-1 text-[11px] px-2 py-1" onClick={loadLint} disabled={lintLoading} aria-busy={lintLoading}><RefreshCw size={12} className={lintLoading ? "mc-spin" : ""} aria-hidden="true" /> Lint ulang</button></div>}
      >
        {lintError ? <Unavailable msg={lintError} /> : lintLoading && !lintData ? <Loading /> : !lintData ? <Empty msg="lint belum dijalankan" /> : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3"><div className="mc-agent-card !p-2.5"><div className="text-[18px] font-bold text-red-300">{lintData.counts && lintData.counts.error || 0}</div><div className="text-[10px] text-mc-muted">error</div></div><div className="mc-agent-card !p-2.5"><div className="text-[18px] font-bold text-amber-300">{lintData.counts && lintData.counts.warning || 0}</div><div className="text-[10px] text-mc-muted">warning</div></div><div className="mc-agent-card !p-2.5"><div className="text-[18px] font-bold text-sky-300">{lintData.counts && lintData.counts.info || 0}</div><div className="text-[10px] text-mc-muted">info</div></div><div className="mc-agent-card !p-2.5"><div className="text-[18px] font-bold text-violet-300">{lintData.counts && lintData.counts.total || 0}</div><div className="text-[10px] text-mc-muted">total</div></div></div>
            {!lintData.issues || lintData.issues.length === 0 ? <Feedback kind="ok">Wiki lint bersih untuk scope accepted pages.</Feedback> : <div className="flex flex-col gap-1.5 max-h-[430px] overflow-y-auto pr-0.5">{lintData.issues.map((issue, i) => <div key={`${issue.path}-${issue.rule}-${i}`} className="border border-mc-border rounded-lg p-2"><div className="flex items-start gap-2 flex-wrap"><Badge tone={issue.severity === "error" ? "bad" : issue.severity === "warning" ? "warn" : "info"}>{issue.severity}</Badge><span className="text-[11px] font-mono text-mc-text break-all">{issue.path}</span><span className="text-[10.5px] text-mc-muted font-mono">{issue.rule}</span></div><div className="text-[11px] text-mc-faint mt-1">{issue.message}</div></div>)}</div>}
          </>
        )}
      </Card>
    </>
  );
}

// --- PANEL: Documents (Google Drive) -----------------------------------------------
const DOC_ICON = { folder: Folder, doc: FileText, sheet: Table2, pdf: File, other: Package };

function DocIcon({ kind, size = 16 }) {
  const I = DOC_ICON[kind];
  return I ? <I size={size} className="text-mc-muted shrink-0" /> : <Package size={size} className="text-mc-muted shrink-0" />;
}

function fmtSize(s) {
  if (s == null) return "";
  const n = Number(s);
  if (!Number.isFinite(n)) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("id-ID", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function DocumentsPanel() {
  const { data, error, refreshing } = usePolling(`${EP}/documents`, POLL_DOCS_MS);
  const { data: rosterData, refreshing: rosterRefreshing } = usePolling(`${EP}/agents/roster`, POLL_AGENTS_MS);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [workspaceData, setWorkspaceData] = useState(null);
  const [workspaceError, setWorkspaceError] = useState(null);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);

  const rosterAgents = (rosterData && Array.isArray(rosterData.agents)) ? rosterData.agents : [];
  useEffect(() => {
    if (!selectedAgentId && rosterAgents.length) setSelectedAgentId(rosterAgents[0].id || "");
    if (selectedAgentId && rosterAgents.length && !rosterAgents.some((a) => a.id === selectedAgentId)) {
      setSelectedAgentId(rosterAgents[0].id || "");
    }
  }, [rosterAgents, selectedAgentId]);

  useEffect(() => {
    let cancelled = false;
    if (!selectedAgentId) {
      setWorkspaceData(null);
      setWorkspaceError(null);
      setWorkspaceLoading(false);
      return undefined;
    }
    setWorkspaceData(null);
    setWorkspaceError(null);
    const load = () => {
      setWorkspaceLoading(true);
      safeFetchJSON(`${EP}/agents/${encodeURIComponent(selectedAgentId)}/workspace`)
        .then((json) => {
          if (!cancelled) {
            setWorkspaceData(json);
            setWorkspaceError(null);
          }
        })
        .catch((e) => {
          if (!cancelled) {
            notifyUnauthorized(e);
            setWorkspaceError(String((e && e.message) || e));
          }
        })
        .finally(() => {
          if (!cancelled) setWorkspaceLoading(false);
        });
    };
    load();
    const timer = setInterval(load, POLL_DOCS_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [selectedAgentId]);

  if (!data && !error) return <Loading />;
  if (error) {
    return (
      <Card title="Documents">
        <Unavailable msg={error} />
      </Card>
    );
  }

  const dr = data.drive || {};
  const ok = dr.status === "ok";
  const files = ok ? dr.files || [] : [];
  const root = dr.root || {};
  const workspace = (workspaceData && workspaceData.workspace) || {};
  const workspaceFiles = (workspaceData && workspaceData.files) || {};
  const workspaceFileItems = Array.isArray(workspaceFiles.files) ? workspaceFiles.files : [];
  const workspaceAgent = (workspaceData && workspaceData.agent) || {};
  const workspaceStatusTone = workspace.status === "ready" ? "ok" : workspace.status === "pending" ? "warn" : "bad";

  const renderFile = (f) => (
    <div key={f.id} className="mc-feed-item">
      <span className="shrink-0 text-mc-muted" aria-hidden><DocIcon kind={f.kind} /></span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[13px] font-semibold text-mc-text break-words">{f.name || "(tanpa nama)"}</span>
        </div>
        <div className="text-[11px] text-mc-muted mt-0.5 font-mono">
          {f.kind === "folder" ? "folder" : f.mimeType || "berkas"} · {fmtTime(f.modifiedTime)} · {fmtSize(f.size)}
          {f.webViewLink ? (
            <a href={f.webViewLink} target="_blank" rel="noreferrer" className="text-[11px] text-sky-400 no-underline mt-1 inline-block hover:text-sky-300">
              {" "}· Buka <ExternalLink size={10} className="inline ml-0.5" />
            </a>
          ) : null}
        </div>
      </div>
    </div>
  );

  return (
    <>
      <div className="mc-fresh mb-0.5">
        {refreshing ? "memuat…" : "auto-refresh 30 dtk"} · data: {data.generated_at || ""}
      </div>
      <Card
        title="Global Documents — Google Drive"
        right={<Badge tone={ok ? (files.length ? "ok" : "neutral") : "bad"}>{ok ? `${dr.count ?? files.length} berkas` : "unavailable"}</Badge>}
      >
        {!ok ? (
          <Unavailable msg={(dr && dr.error) || ""} />
        ) : files.length === 0 ? (
          <Empty msg="Drive global kosong — belum ada berkas" />
        ) : (
          <div className="flex flex-col gap-1.5">{files.map(renderFile)}</div>
        )}
        <div className="mc-row mt-3">
          <span className="mc-row-key">Root workspace</span>
          <span className="flex items-center gap-1.5 text-right">
            <Badge tone={root.status === "ready" ? "ok" : root.status === "missing" ? "warn" : "bad"}>{root.status || "—"}</Badge>
            {root.webViewLink ? <a href={root.webViewLink} target="_blank" rel="noreferrer" className="text-sky-400 hover:text-sky-300"><ExternalLink size={12} /></a> : null}
          </span>
        </div>
      </Card>

      <Card
        title="Agent Workspace"
        right={
          <select
            className="mc-input !w-auto max-w-[260px] text-[12px] py-1"
            value={selectedAgentId}
            onChange={(e) => setSelectedAgentId(e.target.value)}
            aria-label="Pilih agent workspace"
            disabled={!rosterAgents.length}
          >
            {!rosterAgents.length ? <option value="">{rosterRefreshing ? "Memuat roster…" : "Roster tidak tersedia"}</option> : null}
            {rosterAgents.map((a) => <option key={a.id} value={a.id}>{a.name} · {(a.drive_workspace && a.drive_workspace.status) || "pending"}</option>)}
          </select>
        }
      >
        {workspaceError ? <Unavailable msg={workspaceError} /> : workspaceLoading && !workspaceData ? <Loading /> : !selectedAgentId ? <Empty msg="pilih agent untuk melihat workspace" /> : (
          <>
            <div className="flex items-center gap-2 flex-wrap mb-2.5">
              <Badge tone={workspaceStatusTone}>{workspace.status || "pending"}</Badge>
              <span className="text-[13px] font-semibold text-mc-text">{workspaceAgent.name || selectedAgentId}</span>
              {workspace.name ? <span className="mc-chip font-mono text-[10.5px]">{workspace.name}</span> : null}
              {workspace.webViewLink ? <a href={workspace.webViewLink} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[11px] text-sky-400 hover:text-sky-300">Buka folder <ExternalLink size={10} /></a> : null}
            </div>
            {workspace.status !== "ready" ? <Unavailable msg={workspace.error || "folder workspace belum tersedia"} /> : workspaceFiles.status !== "ok" ? <Unavailable msg={workspaceFiles.error || "isi workspace tidak tersedia"} /> : workspaceFileItems.length === 0 ? <Empty msg="workspace agent belum memiliki dokumen" /> : <div className="flex flex-col gap-1.5">{workspaceFileItems.map(renderFile)}</div>}
          </>
        )}
      </Card>
      <div className="mc-footnote">
        Sumber: Google Drive melalui wrapper gws-google. Global Documents dan workspace agent dipisahkan; hanya metadata aman yang ditampilkan.
      </div>
    </>
  );
}

// --- ErrorBoundary: 1 panel crash tidak boleh mematikan seluruh app -------------
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { err: null };
  }
  static getDerivedStateFromError(err) {
    return { err };
  }
  render() {
    if (this.state.err) {
      const msg = String((this.state.err && this.state.err.message) || this.state.err).slice(0, 220);
      return (
        <Card title="Panel gagal dimuat">
          <Feedback kind="err">{msg || "error tak diketahui"}</Feedback>
          <button
            className="mc-btn-ghost mt-2"
            onClick={() => this.setState({ err: null })}
          >
            Coba lagi
          </button>
        </Card>
      );
    }
    return this.props.children;
  }
}

// --- ModelsPanel: merged Hermes dashboard + OpenCode catalog -------------------
function ModelsPanel() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);

  const load = (force = false) => {
    setBusy(true);
    const suffix = force ? "?refresh=1" : "";
    safeFetchJSON(`${EP}/models${suffix}`)
      .then((json) => {
        setData(json);
        setError(null);
      })
      .catch((e) => {
        notifyUnauthorized(e);
        setError(String((e && e.message) || e));
      })
      .finally(() => setBusy(false));
  };

  useEffect(() => { load(false); }, []);

  if (!data && !error) return <Loading />;

  const m = (data && data.models) || {};
  const status = typeof m.status === "string" ? m.status : "error";
  const usable = status === "ok" || status === "partial";
  const providerMap = usable ? modelProviderMap(m) : {};
  const details = modelProviderDetails(m);
  const total = typeof m.total === "number"
    ? m.total
    : Object.values(providerMap).reduce((sum, names) => sum + names.length, 0);
  const providerCount = typeof m.provider_count === "number"
    ? m.provider_count
    : Object.keys(providerMap).length;
  const ql = q.trim().toLowerCase();
  const filtered = Object.entries(providerMap)
    .map(([prov, names]) => {
      const detail = details[prov] && typeof details[prov] === "object" ? details[prov] : {};
      const label = String(detail.name || prov);
      const list = ql
        ? names.filter((n) => n.toLowerCase().includes(ql) || prov.toLowerCase().includes(ql) || label.toLowerCase().includes(ql))
        : names;
      return [prov, list];
    })
    .filter(([, list]) => list.length > 0);
  const emptyProviders = Object.entries(details).filter(([prov, detail]) => {
    const d = detail && typeof detail === "object" ? detail : {};
    return !(providerMap[prov] || []).length && (!ql || `${prov} ${d.name || ""} ${d.warning || ""}`.toLowerCase().includes(ql));
  });
  const sourceRows = m.sources && typeof m.sources === "object" ? Object.entries(m.sources) : [];
  const badgeTone = status === "ok" ? "ok" : status === "partial" ? "warn" : "bad";

  return (
    <>
      <Card
        title="Models"
        right={
          <div className="flex items-center gap-2">
            <Badge tone={badgeTone}>
              {usable ? `${total} model · ${providerCount} provider` : "unavailable"}
            </Badge>
            <button
              className="mc-btn-ghost"
              onClick={() => load(true)}
              disabled={busy}
              aria-busy={busy}
              aria-label="Muat ulang daftar model dari Hermes"
              title="Refresh katalog Hermes + OpenCode"
            >
              <RefreshCw size={14} className={busy ? "mc-spin" : ""} />
            </button>
          </div>
        }
      >
        {error && !data ? (
          <Unavailable msg={error} />
        ) : (
          <>
            {error ? <Feedback kind="err" className="mb-2">Refresh gagal: {error}</Feedback> : null}
            <div className="mc-row items-center">
              <span className="mc-row-key">Default (Hermes)</span>
              <Chip>{modelCatalogDefault(m) || "—"}</Chip>
            </div>
            <div className="flex gap-1.5 flex-wrap mt-2">
              <Chip>{providerCount} provider</Chip>
              <Chip>{total} model</Chip>
              {sourceRows.map(([source, info]) => {
                const s = info && typeof info === "object" ? info : {};
                const tone = s.status === "ok" ? "ok" : s.status === "error" ? "bad" : "warn";
                return <Badge key={source} tone={tone}>{source}: {s.status || "n/a"}</Badge>;
              })}
            </div>
            <input
              className="mc-input mt-3"
              placeholder="Cari model / provider…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              aria-label="Cari model"
            />
            {filtered.length === 0 && emptyProviders.length === 0 ? (
              <div className="mc-empty mt-3">
                {ql ? `Tidak ada model cocok dengan "${q}".` : "Tidak ada model tersedia."}
              </div>
            ) : (
              <div className="flex flex-col gap-4 mt-3">
                {filtered.map(([prov, names]) => {
                  const detail = details[prov] && typeof details[prov] === "object" ? details[prov] : {};
                  const label = detail.name && detail.name !== prov ? `${detail.name} · ${prov}` : prov;
                  return (
                    <div key={prov} className="flex flex-col gap-1.5">
                      <div className="mc-section-label flex items-center gap-2 flex-wrap">
                        <span>{label} · {names.length}</span>
                        {Array.isArray(detail.sources) ? <span className="text-mc-faint">[{detail.sources.join("+")}]</span> : null}
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {names.map((n) => <Chip key={`${prov}/${n}`}>{n}</Chip>)}
                      </div>
                      {detail.warning ? <div className="text-[11px] text-amber-300/80">{detail.warning}</div> : null}
                    </div>
                  );
                })}
                {emptyProviders.length ? (
                  <div className="border-t border-mc-border pt-3 flex flex-col gap-1.5">
                    <div className="mc-section-label">Provider terdaftar tanpa model tersedia</div>
                    {emptyProviders.map(([prov, detail]) => {
                      const d = detail && typeof detail === "object" ? detail : {};
                      return (
                        <div key={prov} className="text-[11.5px] text-mc-muted">
                          <span className="font-mono text-mc-text">{prov}</span>{d.name && d.name !== prov ? ` · ${d.name}` : ""}
                          {d.warning ? ` — ${d.warning}` : " — catalog kosong / belum tersambung"}
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            )}
          </>
        )}
      </Card>
      <div className="mc-footnote">
        Hermes dashboard inventory + OpenCode catalog · cache Mission Control 5 menit · refresh manual hanya membaca ulang sumber.
      </div>
    </>
  );
}

// --- SessionChip: sisa waktu sesi login (indikator footer) -----------------------
function SessionChip() {
  const [sec, setSec] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      // /auth/session adalah route server (di luar mount /api) dan TIDAK butuh EP
      safeFetchJSON("/auth/session")
        .then((j) => {
          if (!cancelled && j && typeof j.expires_in_s === "number") {
            setSec(j.expires_in_s);
          }
        })
        .catch(() => {});
    };
    load();
    const t = setInterval(load, 60000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  if (sec === null) return null;
  const warn = sec < 600;
  return (
    <span
      className={`mc-chip inline-flex items-center gap-1 ${warn ? "mc-badge-warn" : ""}`}
      title="Sesi login berakhir otomatis (cookie 12 jam)"
    >
      <Timer size={12} />
      {fmtUptime(sec)} tersisa
    </span>
  );
}

// --- Routing & workflow control plane -----------------------------------------
function RoutingPanel({ onDirtyChange }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [configText, setConfigText] = useState("");
  const [metadataText, setMetadataText] = useState("");
  const [savedConfigText, setSavedConfigText] = useState("");
  const [savedMetadataText, setSavedMetadataText] = useState("");
  const [parseErrors, setParseErrors] = useState({});
  const [taskText, setTaskText] = useState("");
  const [hintsText, setHintsText] = useState("");
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const dirty = Boolean(data) && (configText !== savedConfigText || metadataText !== savedMetadataText);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  function metadataFromResponse(json) {
    return (json.agents || []).reduce((out, agent) => {
      if (agent && agent.id) out[agent.id] = agent.routing || {};
      return out;
    }, {});
  }

  async function load(force = false) {
    if (!force && dirty) {
      setMessage({ kind: "err", text: "Perubahan Routing belum disimpan. Simpan atau batalkan sebelum memuat ulang." });
      return;
    }
    try {
      const json = await safeFetchJSON(`${EP}/routing`);
      const nextConfig = JSON.stringify(json.config || {}, null, 2);
      const nextMetadata = JSON.stringify(metadataFromResponse(json), null, 2);
      setData(json);
      setConfigText(nextConfig);
      setMetadataText(nextMetadata);
      setSavedConfigText(nextConfig);
      setSavedMetadataText(nextMetadata);
      setParseErrors({});
      setError(null);
      setMessage(null);
    } catch (e) {
      notifyUnauthorized(e);
      setError(String((e && e.message) || e));
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const beforeUnload = (event) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);

  function formatJson(field) {
    const text = field === "config" ? configText : metadataText;
    try {
      const formatted = JSON.stringify(JSON.parse(text || (field === "config" ? "{}" : "{}")), null, 2);
      if (field === "config") setConfigText(formatted);
      else setMetadataText(formatted);
      setParseErrors((old) => ({ ...old, [field]: null }));
      setMessage({ kind: "ok", text: `${field === "config" ? "Workflow" : "Metadata agent"} JSON diformat.` });
    } catch (e) {
      const detail = e instanceof SyntaxError ? jsonErrorLocation(text, e).replace(/^JSON\.parse: /, "") : "JSON tidak valid";
      setParseErrors((old) => ({ ...old, [field]: detail }));
      setMessage({ kind: "err", text: `${field === "config" ? "Workflow" : "Metadata agent"}: JSON tidak valid.` });
    }
  }

  function discardChanges() {
    setConfigText(savedConfigText);
    setMetadataText(savedMetadataText);
    setParseErrors({});
    setMessage({ kind: "ok", text: "Draft Routing dikembalikan ke readback tersimpan." });
    setPreview(null);
  }

  async function save() {
    let config;
    let agent_metadata;
    setParseErrors({});
    try {
      config = JSON.parse(configText);
    } catch (e) {
      const detail = e instanceof SyntaxError ? jsonErrorLocation(configText, e) : "JSON tidak valid";
      setParseErrors({ config: detail });
      setMessage({ kind: "err", text: "Workflow JSON tidak valid; perbaiki error pada field tersebut sebelum menyimpan." });
      return;
    }
    try {
      agent_metadata = JSON.parse(metadataText || "{}");
    } catch (e) {
      const detail = e instanceof SyntaxError ? jsonErrorLocation(metadataText, e) : "JSON tidak valid";
      setParseErrors({ metadata: detail });
      setMessage({ kind: "err", text: "Agent routing metadata JSON tidak valid; perbaiki error pada field tersebut sebelum menyimpan." });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const json = await safeFetchJSON(`${EP}/routing`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config, agent_metadata }),
      });
      setData(json);
      const nextConfig = JSON.stringify(json.config || {}, null, 2);
      const nextMetadata = JSON.stringify(metadataFromResponse(json), null, 2);
      setConfigText(nextConfig);
      setMetadataText(nextMetadata);
      setSavedConfigText(nextConfig);
      setSavedMetadataText(nextMetadata);
      setParseErrors({});
      setMessage({ kind: "ok", text: "Routing config dan metadata tersimpan atomik." });
    } catch (e) {
      notifyUnauthorized(e);
      setMessage({ kind: "err", text: String((e && e.message) || e) });
    } finally {
      setBusy(false);
    }
  }

  async function runPreview(e) {
    e.preventDefault();
    if (dirty) {
      setMessage({ kind: "err", text: "Preview memakai konfigurasi tersimpan terakhir. Simpan atau kembalikan draft sebelum preview." });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const json = await safeFetchJSON(`${EP}/routing/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_text: taskText,
          capability_hints: hintsText.split(",").map((item) => item.trim()).filter(Boolean),
        }),
      });
      setPreview(json);
    } catch (e2) {
      notifyUnauthorized(e2);
      setMessage({ kind: "err", text: String((e2 && e2.message) || e2) });
    } finally {
      setBusy(false);
    }
  }

  if (error && !data) return <Unavailable msg={error} />;
  if (!data) return <Loading />;
  const config = data.config || {};
  const persistedRevision = data.revision || data.updated_at || data.generated_at || "backend tidak mengekspos revisi";
  return (
    <>
      <header className="mc-card !p-5">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <h2 className="m-0 text-xl font-semibold text-mc-text">Routing & Workflows</h2>
            <p className="m-0 mt-1.5 text-[13px] leading-relaxed text-mc-muted max-w-3xl">Konfigurasi owner untuk routing berbasis capability. Preview deterministik; tidak meluncurkan agent dan tidak menulis ke layanan eksternal.</p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {dirty ? <Badge tone="warn">unsaved changes</Badge> : <Badge tone="ok">readback tersimpan</Badge>}
            {dirty ? <button type="button" className="mc-btn-ghost inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1.5" onClick={discardChanges} disabled={busy}><X size={12} aria-hidden="true" /> Kembalikan draft</button> : null}
            <button type="button" className="mc-btn-ghost inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1.5" onClick={() => load()} disabled={busy} aria-busy={busy}>
              <RefreshCw size={12} className={busy ? "mc-spin" : ""} aria-hidden="true" /> Muat ulang
            </button>
            <Badge tone="info">{data.runtime && data.runtime.configured ? "configured" : "unavailable"}</Badge>
          </div>
        </div>
        {message ? <Feedback kind={message.kind} className="mt-3">{message.text}</Feedback> : null}
      </header>
      <div className="mc-panel-grid">
        <Card title="Workflow definitions & capability rules" busy={busy} right={<div className="flex items-center gap-1.5"><button type="button" className="mc-btn-ghost !px-2 !py-1 text-[11px]" onClick={() => formatJson("config")} disabled={busy}>Format</button><button type="button" className="mc-btn-primary !px-2.5 !py-1.5 text-[11px]" onClick={save} disabled={busy} aria-busy={busy}><Save size={12} /> Simpan</button></div>}>
          <p className="m-0 text-[11px] text-mc-muted">File durable: <code>workflows.json</code> · backup rollback: <code>workflows.json.bak</code> · validasi schema tetap dilakukan backend.</p>
          <details className="mt-2 text-[11px] text-mc-muted"><summary className="cursor-pointer text-sky-300">Petunjuk schema</summary><div className="mt-1.5 leading-relaxed">Object utama memuat <code>version</code>, <code>default_workflow</code>, <code>workflows[]</code>, dan <code>routing_rules[]</code>. ID/capability, stage, approval gate, dan keyword tetap divalidasi backend.</div></details>
          <textarea className={`mc-input w-full min-h-[360px] mt-3 font-mono text-[11px] leading-relaxed ${parseErrors.config ? "!border-rose-400/70" : ""}`} value={configText} onChange={(e) => { setConfigText(e.target.value); setParseErrors((old) => ({ ...old, config: null })); }} aria-label="Workflow configuration JSON" aria-invalid={Boolean(parseErrors.config)} aria-describedby={parseErrors.config ? "routing-config-error" : undefined} />
          {parseErrors.config ? <Feedback id="routing-config-error" kind="err">Workflow JSON parse error: {parseErrors.config}</Feedback> : null}
        </Card>
        <Card busy={busy} title="Agent routing metadata" right={<div className="flex items-center gap-1.5"><button type="button" className="mc-btn-ghost !px-2 !py-1 text-[11px]" onClick={() => formatJson("metadata")} disabled={busy}>Format</button><Badge tone="neutral">{jsonObjectCount(savedMetadataText, 11)} roster records</Badge></div>}>
          <p className="m-0 text-[11px] text-mc-muted">Capabilities, tags, accepts/outputs, parent, runtime owner/mode, approval, priority, availability. Status live tidak disimpulkan dari konfigurasi.</p>
          <details className="mt-2 text-[11px] text-mc-muted"><summary className="cursor-pointer text-sky-300">Petunjuk field agent</summary><div className="mt-1.5 leading-relaxed">Setiap key agent dapat memuat <code>capabilities</code>, <code>tags</code>, <code>accepts</code>, <code>outputs</code>, <code>parent_id</code>, <code>runtime_owner</code>, <code>runtime_mode</code>, <code>approval_policy</code>, <code>priority</code>, dan <code>availability</code>.</div></details>
          <textarea className={`mc-input w-full min-h-[360px] mt-3 font-mono text-[11px] leading-relaxed ${parseErrors.metadata ? "!border-rose-400/70" : ""}`} value={metadataText} onChange={(e) => { setMetadataText(e.target.value); setParseErrors((old) => ({ ...old, metadata: null })); }} aria-label="Agent routing metadata JSON" aria-invalid={Boolean(parseErrors.metadata)} aria-describedby={parseErrors.metadata ? "routing-metadata-error" : undefined} />
          {parseErrors.metadata ? <Feedback id="routing-metadata-error" kind="err">Agent metadata JSON parse error: {parseErrors.metadata}</Feedback> : null}
        </Card>
      </div>
      <Card title="Route preview / simulation" busy={busy} right={<div className="flex items-center gap-1.5"><Badge tone="neutral">no launch</Badge><Badge tone={dirty ? "warn" : "info"}>{dirty ? "simpan/kembalikan dulu" : "preview config tersimpan"}</Badge></div>}>
        <p className="m-0 mb-2 text-[11px] leading-relaxed text-mc-muted">Preview ini memakai konfigurasi persisted terakhir dari backend, bukan draft textarea. Revision/readback: <code>{persistedRevision}</code>. Saat ada perubahan lokal, simpan atau kembalikan draft sebelum menjalankan preview.</p>
        <form onSubmit={runPreview} className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_240px_auto] gap-2 items-end">
          <label className="text-[11px] text-mc-muted">Task text<input className="mc-input w-full mt-1" value={taskText} onChange={(e) => setTaskText(e.target.value)} placeholder="Contoh: perbaiki backend API dan tambahkan test" aria-label="Task text" /></label>
          <label className="text-[11px] text-mc-muted">Capability hints<input className="mc-input w-full mt-1" value={hintsText} onChange={(e) => setHintsText(e.target.value)} placeholder="backend, testing" aria-label="Capability hints" /></label>
          <button className="mc-btn-primary" type="submit" disabled={busy || dirty || !taskText.trim()} aria-busy={busy}><Eye size={13} /> {busy ? "Memproses…" : "Preview"}</button>
        </form>
        {preview ? <pre className="mt-3 p-3 rounded-xl bg-black/20 border border-mc-border overflow-x-auto text-[11px] leading-relaxed text-mc-muted">{JSON.stringify(preview, null, 2)}</pre> : <Empty msg="masukkan task untuk melihat workflow, kandidat, alasan, dan approval gates" />}
      </Card>
      <Card title="Configured workflows" right={<Badge tone="neutral">{(config.workflows || []).length}</Badge>}>
        <div className="flex flex-col gap-2">
          {(config.workflows || []).map((workflow) => (
            <div key={workflow.id} className="rounded-xl border border-mc-border bg-black/10 p-3">
              <div className="flex items-center justify-between gap-2 flex-wrap"><strong className="text-[13px] text-mc-text">{workflow.name || workflow.id}</strong><span className="mc-chip font-mono text-[10px]">{workflow.id}</span></div>
              <div className="mt-1 text-[11px] text-mc-muted">{(workflow.stages || []).length} stages · capabilities: {(workflow.capabilities || []).join(", ") || "—"} · gates: {(workflow.approval_gates || []).join(", ") || "none"}</div>
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}

// --- ROOT ------------------------------------------------------------------------
const TAB_GROUPS = [
  {
    section: "Workspace",
    items: [
      { key: "overview", label: "Dashboard", icon: LayoutDashboard },
      { key: "tasks", label: "Kanban", icon: ListTodo },
      { key: "calendar", label: "Schedule", icon: CalendarDays },
      { key: "documents", label: "Documents", icon: FileText },
      { key: "obsidian", label: "Knowledge Base", icon: BookOpen },
      { key: "office", label: "Visual Office", icon: Building2 },
    ],
  },
  {
    section: "Agents",
    items: [
      { key: "agents", label: "Team", icon: Bot },
      { key: "routing", label: "Routing", icon: Repeat },
      { key: "models", label: "Models", icon: Cpu },
      { key: "memory", label: "Skills & Memory", icon: Brain },
      { key: "activity", label: "Chat Logs", icon: MessageSquare },
    ],
  },
  {
    section: "Infra",
    items: [
      { key: "coolify", label: "Coolify", icon: Server },
    ],
  },
];
const TABS = TAB_GROUPS.flatMap((g) => g.items);
const TAB_KEYS = new Set(TABS.map((tab) => tab.key));
const tabLabel = (key) => (TABS.find((t) => t.key === key) || {}).label || key;
function tabFromLocation() {
  if (typeof window === "undefined") return "overview";
  const candidate = new URLSearchParams(window.location.search).get("panel");
  return TAB_KEYS.has(candidate) ? candidate : "overview";
}
function writeTabLocation(tab, replace = false) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.set("panel", TAB_KEYS.has(tab) ? tab : "overview");
  window.history[replace ? "replaceState" : "pushState"]({ panel: tab }, "", `${url.pathname}${url.search}${url.hash}`);
}

function BrandLogo({ size = "sm" }) {
  // logo box gradien sky→violet, dipakai sidebar & header mobile
  const cls = size === "sm"
    ? "w-8 h-8 rounded-[10px] text-[15px]"
    : "w-7 h-7 rounded-lg text-sm";
  return (
    <span className={`${cls} shrink-0 bg-gradient-to-br from-sky-400 to-violet-500 flex items-center justify-center shadow-glow`} aria-hidden>
      <Gauge size={15} />
    </span>
  );
}

export function MissionControlApp({ onLogout }) {
  const [tab, setTab] = useState(tabFromLocation);
  const [drawer, setDrawer] = useState(false);
  const [pendingTab, setPendingTab] = useState(null);
  const [wide, setWide] = useState(typeof window !== "undefined" && window.innerWidth >= 820);
  const routingDirtyRef = useRef(false);
  const currentTabRef = useRef(tab);
  currentTabRef.current = tab;

  useEffect(() => {
    const h = () => setWide(window.innerWidth >= 820);
    window.addEventListener("resize", h);
    return () => window.removeEventListener("resize", h);
  }, []);

  useEffect(() => {
    const initial = tabFromLocation();
    if (initial !== tab) setTab(initial);
    const current = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("panel") : null;
    if (current !== initial) writeTabLocation(initial, true);
    const onPopState = () => {
      const next = tabFromLocation();
      if (currentTabRef.current === "routing" && next !== "routing" && routingDirtyRef.current) {
        writeTabLocation("routing", true);
        setPendingTab(next);
        return;
      }
      setPendingTab(null);
      setTab(next);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
    // URL is the source of truth only for initial load and browser history events.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function selectTab(next, { force = false } = {}) {
    const safeTab = TAB_KEYS.has(next) ? next : "overview";
    if (!force && tab === "routing" && safeTab !== "routing" && routingDirtyRef.current) {
      setPendingTab(safeTab);
      return;
    }
    if (tab === "routing" && safeTab !== "routing") routingDirtyRef.current = false;
    setPendingTab(null);
    setTab(safeTab);
    writeTabLocation(safeTab);
    setDrawer(false);
  }

  let body;
  if (tab === "overview") body = <OverviewPanel />;
  else if (tab === "activity") body = <ActivityPanel />;
  else if (tab === "agents") body = <AgentsPanel />;
  else if (tab === "routing") body = <RoutingPanel onDirtyChange={(dirty) => { routingDirtyRef.current = dirty; }} />;
  else if (tab === "tasks") body = <TasksPanel />;
  else if (tab === "calendar") body = <CalendarPanel />;
  else if (tab === "memory") body = <MemoryPanel />;
  else if (tab === "office") body = <OfficePanel />;
  else if (tab === "documents") body = <DocumentsPanel />;
  else if (tab === "obsidian") body = <ObsidianPanel />;
  else if (tab === "models") body = <ModelsPanel />;
  else if (tab === "coolify") body = <CoolifyPanel />;
  else body = null;

  const activeLabel = tabLabel(tab);

  useEffect(() => {
    document.title = `${activeLabel} · Mission Control`;
  }, [activeLabel]);

  const navSection = (g) => (
    <div key={g.section}>
      <div className="mc-section-label">
        {g.section}
      </div>
      {g.items.map((t) => (
        <button
          key={t.key}
          type="button"
          aria-current={tab === t.key ? "page" : undefined}
          onClick={() => selectTab(t.key)}
          className={`mc-nav-btn ${tab === t.key ? "mc-nav-btn-active" : ""}`}
        >
          <span className="shrink-0" aria-hidden>{t.icon ? <t.icon size={15} /> : null}</span>
          {t.label}
        </button>
      ))}
    </div>
  );

  return (
    <div data-mc-app-shell className="flex min-h-screen bg-mc-bg text-mc-text">
      {wide ? (
        <aside className="w-[216px] shrink-0 bg-gradient-to-b from-[#101014] to-mc-sidebar border-r border-mc-border flex flex-col gap-1 p-3 sticky top-0 h-screen">
          <div className="flex items-center gap-2.5 px-2 pb-3.5 mb-2.5 border-b border-mc-border">
            <BrandLogo />
            <span className="text-[15px] font-bold tracking-tight bg-gradient-to-r from-sky-300 to-violet-300 bg-clip-text text-transparent">
              Mission Control
            </span>
          </div>
          <nav className="flex flex-col gap-0.5 flex-1" aria-label="Panel">
            {TAB_GROUPS.map(navSection)}
          </nav>
          <div className="flex flex-col gap-2.5 border-t border-mc-border pt-3">
            <span className="mc-fresh">Panel: {activeLabel}</span>
            {onLogout ? (
              <button onClick={onLogout} className="mc-btn-ghost" aria-label="Logout">
                Keluar
              </button>
            ) : null}
          </div>
        </aside>
      ) : null}
      {!wide && drawer ? (
        <Modal
          title="Menu navigasi"
          mode="drawer"
          dialogId="mc-drawer"
          onClose={() => setDrawer(false)}
          headerContent={(
            <div className="flex items-center gap-2.5">
              <BrandLogo />
              <span className="text-[15px] font-bold tracking-tight bg-gradient-to-r from-sky-300 to-violet-300 bg-clip-text text-transparent">Mission Control</span>
            </div>
          )}
        >
          <nav className="flex flex-col gap-0.5 flex-1 overflow-y-auto" aria-label="Panel">
            {TAB_GROUPS.map(navSection)}
          </nav>
          <div className="flex flex-col gap-2.5 border-t border-mc-border pt-3 mt-auto">
            <span className="mc-fresh">Panel: {activeLabel}</span>
            {onLogout ? (
              <button type="button" onClick={onLogout} className="mc-btn-ghost" aria-label="Logout">
                <LogOut size={13} className="inline mr-1" aria-hidden="true" />
                Keluar
              </button>
            ) : null}
          </div>
        </Modal>
      ) : null}
      <main className="flex-1 min-w-0" aria-label="Konten">
        <div className="flex flex-col gap-3.5 p-4 sm:p-5 pb-8 max-w-[1100px] w-full mx-auto">
          {!wide ? (
            <>
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setDrawer(true)}
                    aria-label="Buka menu"
                    aria-expanded={drawer}
                    aria-controls="mc-drawer"
                    className="w-10 h-10 rounded-xl flex items-center justify-center text-mc-text bg-mc-card border border-mc-border cursor-pointer transition-colors duration-150 hover:bg-white/5 active:scale-95"
                  >
                    <Menu size={19} />
                  </button>
                  <div className="text-[17px] font-semibold tracking-tight flex items-center gap-2">
                    <BrandLogo size="sm" />
                    Mission Control
                  </div>
                </div>
                {onLogout ? (
                  <button
                    onClick={onLogout}
                    className="mc-btn-ghost !px-3 !py-2"
                    aria-label="Logout"
                  >
                    <LogOut size={13} className="inline mr-1" />
                    Keluar
                  </button>
                ) : null}
              </div>
              <div className="mc-fresh -mt-1">Panel aktif: {activeLabel}</div>
            </>
          ) : null}
          <h1 className="m-0 text-xl sm:text-2xl font-semibold tracking-tight text-mc-text">{activeLabel}</h1>
          {body ? <ErrorBoundary key={tab}>{body}</ErrorBoundary> : null}
          <div className="mc-footnote">
            Sumber data: /opt/data/gateway_state.json · /opt/data/state.db · /opt/data/logs/*.log · opencode.db — semuanya read-only, cache 3–5 dtk di backend. · <SessionChip />
          </div>
        </div>
      </main>
      {pendingTab ? (
        <ConfirmModal
          title="Tinggalkan Routing?"
          target={tabLabel(pendingTab)}
          impact="Perubahan JSON yang belum disimpan akan hilang. Pilih Batal untuk kembali dan simpan atau format data terlebih dahulu."
          confirmLabel="Tinggalkan"
          confirmIcon={TriangleAlert}
          confirmClassName="!text-amber-300 !border-amber-400/40"
          onClose={() => setPendingTab(null)}
          onConfirm={() => selectTab(pendingTab, { force: true })}
        />
      ) : null}
    </div>
  );
}

// --- Login + Root (aplikasi mandiri) ------------------------------------------
function LoginPage({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitted(true);
    setErr(null);
    if (!username.trim() || !password) {
      return;
    }
    setBusy(true);
    try {
      await apiLogin(username.trim(), password);
      setPassword("");
      onLogin();
    } catch (ex) {
      setErr(String((ex && ex.message) || ex));
    } finally {
      setBusy(false);
    }
  }

  const usernameError = submitted && !username.trim() ? "Username wajib diisi." : null;
  const passwordError = submitted && !password ? "Password wajib diisi." : null;
  const describedBy = (fieldErrorId) => [fieldErrorId, err ? "login-error" : null].filter(Boolean).join(" ") || undefined;

  return (
    <div className="min-h-screen flex items-center justify-center bg-mc-bg text-mc-text p-4">
      <div className="w-full max-w-[380px] mx-auto">
        <div className="rounded-2xl bg-gradient-to-br from-sky-400/50 via-mc-card to-violet-400/40 p-px shadow-glow">
          <div className="rounded-[15px] bg-mc-card px-7 py-8 shadow-lift">
            <div className="flex items-center gap-3 mb-1">
              <span className="w-11 h-11 rounded-xl bg-gradient-to-br from-sky-400 to-violet-500 flex items-center justify-center text-xl shadow-glow" aria-hidden>
                <Gauge size={20} />
              </span>
              <div>
                <h1 className="m-0 text-xl font-bold tracking-tight bg-gradient-to-r from-sky-300 to-violet-300 bg-clip-text text-transparent">
                  Mission Control
                </h1>
              </div>
            </div>
            <p className="text-xs text-mc-muted mt-2 mb-5">
              Aplikasi mandiri · server :9120 · sesi 12 jam
            </p>
            <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-2.5" aria-busy={busy}>
              <label className="text-[11px] text-mc-muted">
                Username
                <input
                  className="mc-input w-full mt-1"
                  placeholder="Username"
                  value={username}
                  autoComplete="username"
                  onChange={(e) => setUsername(e.target.value)}
                  aria-label="Username"
                  aria-invalid={Boolean(usernameError)}
                  aria-describedby={describedBy(usernameError ? "login-username-error" : null)}
                />
                {usernameError ? <Feedback id="login-username-error" kind="err" className="mt-1">{usernameError}</Feedback> : null}
              </label>
              <label className="text-[11px] text-mc-muted">
                Password
                <input
                  className="mc-input w-full mt-1"
                  type="password"
                  placeholder="Password"
                  value={password}
                  autoComplete="current-password"
                  onChange={(e) => setPassword(e.target.value)}
                  aria-label="Password"
                  aria-invalid={Boolean(passwordError)}
                  aria-describedby={describedBy(passwordError ? "login-password-error" : null)}
                />
                {passwordError ? <Feedback id="login-password-error" kind="err" className="mt-1">{passwordError}</Feedback> : null}
              </label>
              <button
                type="submit"
                className="mc-btn-primary mt-1 w-full"
                disabled={busy}
                aria-busy={busy}
              >
                {busy ? "Memeriksa…" : "Masuk"}
              </button>
            </form>
            {err ? <Feedback id="login-error" kind="err">{err}</Feedback> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function CheckingScreen() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-mc-bg text-mc-muted text-[13px] gap-2">
      <span className="mc-spinner" /> menunggu sesi…
    </div>
  );
}

export default function Root() {
  const [auth, setAuth] = useState("checking"); // checking | in | out

  useEffect(() => {
    setUnauthorizedHandler(() => setAuth("out"));
    safeFetchJSON("/api/overview")
      .then(() => setAuth("in"))
      .catch((e) => {
        // 401 -> halaman login; error lain (mis. server down) -> tetap buka dashboard
        setAuth(e instanceof AuthError ? "out" : "in");
      });
    return () => setUnauthorizedHandler(null);
  }, []);

  if (auth === "checking") return <CheckingScreen />;
  if (auth === "out") return <LoginPage onLogin={() => { resetUnauthorizedNotice(); setAuth("in"); }} />;
  return (
    <MissionControlApp
      onLogout={async () => {
        try {
          await apiLogout();
        } catch {
          /* cookie dihapus server saat request sampai */
        }
        setAuth("out");
      }}
    />
  );
}