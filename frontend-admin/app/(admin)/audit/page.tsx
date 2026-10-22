"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Search as SearchIcon } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { X as XIcon } from "lucide-react";
import { SettingsAPI, UsersAPI } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/common/PageHeader";
import { DataTable, type Column } from "@/components/common/DataTable";
import { StatusPill } from "@/components/common/StatusPill";

export default function AuditLogsPage() {
  return (
    <Suspense fallback={null}>
      <AuditLogsInner />
    </Suspense>
  );
}

/** Lightweight UA → "Chrome on macOS" style summariser. We deliberately
 *  avoid a `ua-parser-js` dep — the audit column just needs a glance-
 *  readable hint, not a perfect parse. Picks one of:
 *     Mobile-app → "iOS app" / "Android app" if the UA mentions our
 *     bundle name; otherwise falls back to browser-on-OS detection. */
function shortDevice(ua: string | null | undefined): string {
  if (!ua) return "—";
  const s = ua;
  if (/StockEx[-\s]?Mobile|stockex.+Capacitor|stockex.+Cordova/i.test(s)) {
    if (/iPhone|iPad|iOS/i.test(s)) return "iOS app";
    if (/Android/i.test(s)) return "Android app";
    return "Mobile app";
  }
  const browser =
    /Edg\//.test(s) ? "Edge" :
    /Chrome\//.test(s) && !/Chromium/.test(s) ? "Chrome" :
    /Firefox\//.test(s) ? "Firefox" :
    /Safari\//.test(s) ? "Safari" :
    /OPR\//.test(s) ? "Opera" :
    "Browser";
  const os =
    /iPhone|iPad/.test(s) ? "iOS" :
    /Android/.test(s) ? "Android" :
    /Mac OS X|Macintosh/.test(s) ? "macOS" :
    /Windows/.test(s) ? "Windows" :
    /Linux/.test(s) ? "Linux" :
    "";
  return os ? `${browser} on ${os}` : browser;
}

/** Two-line cell: full name on top, user_code in mono on the second
 *  line. Falls back to "system" / "—" when the row has no actor /
 *  target (e.g. boot-time migration audit rows have no actor). Click
 *  the cell to re-scope the entire audit page to that user. */
function UserCell({
  info,
  fallback,
}: {
  info?: { id?: string; name?: string | null; code?: string | null; role?: string | null } | null;
  fallback: string;
}) {
  if (!info || !info.id) {
    return <span className="text-xs text-muted-foreground">{fallback}</span>;
  }
  const name = info.name?.trim();
  const code = info.code?.trim();
  if (!name && !code) {
    return (
      <span className="font-mono text-[11px] text-muted-foreground">
        {info.id.slice(-8)}
      </span>
    );
  }
  return (
    <Link
      href={`/audit?involving_user_id=${info.id}`}
      className="group inline-flex flex-col leading-tight"
      title={`${name ?? ""} ${code ? `(${code})` : ""}`.trim()}
    >
      <span className="text-xs font-medium text-foreground group-hover:underline">
        {name || code || info.id.slice(-8)}
      </span>
      {code && (
        <span className="font-mono text-[10px] text-muted-foreground">
          {code}
        </span>
      )}
    </Link>
  );
}


/** Search-a-user box. Lets the admin type a name / user code / email /
 *  mobile, see live matches, and click one to re-scope the ENTIRE audit
 *  feed to that user (actor OR target) via `?involving_user_id=`. This is
 *  the "kis user ne kya kiya" entry point — once scoped, every row shows
 *  the order/position/login with its IP, device and exact timestamp, so a
 *  user can't claim "maine order place nahi kiya". Debounced 250 ms;
 *  queries the same `/admin/users?q=` endpoint the Users table uses (which
 *  matches full_name / user_code / email / mobile). */
function UserSearchBox() {
  const [term, setTerm] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(term.trim()), 250);
    return () => clearTimeout(t);
  }, [term]);

  const { data, isFetching } = useQuery({
    queryKey: ["admin", "audit", "user-search", debounced],
    queryFn: () => UsersAPI.list({ q: debounced, page_size: 8 }),
    enabled: debounced.length >= 2,
    staleTime: 60_000,
  });
  const results = ((data as any)?.items ?? []) as any[];

  return (
    <div data-tour="au-search" className="relative w-full max-w-md">
      <div className="relative">
        <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={term}
          onChange={(e) => {
            setTerm(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          // Delay close so a click on a result registers before blur.
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Search a user by name, code, email or mobile…"
          className="h-9 pl-8"
        />
      </div>
      {open && debounced.length >= 2 && (
        <div className="absolute z-20 mt-1 max-h-80 w-full overflow-auto rounded-md border border-border bg-background shadow-lg">
          {isFetching && results.length === 0 ? (
            <div className="px-3 py-2 text-xs text-muted-foreground">Searching…</div>
          ) : results.length === 0 ? (
            <div className="px-3 py-2 text-xs text-muted-foreground">No users found</div>
          ) : (
            results.map((u) => (
              <Link
                key={u.id}
                href={`/audit?involving_user_id=${u.id}`}
                onClick={() => {
                  setOpen(false);
                  setTerm("");
                }}
                className="flex flex-col gap-0.5 border-b border-border/50 px-3 py-2 text-xs last:border-0 hover:bg-muted/50"
              >
                <span className="font-medium text-foreground">
                  {u.full_name || u.user_code || String(u.id).slice(-8)}
                </span>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {[u.user_code, u.email, u.mobile].filter(Boolean).join(" · ") || String(u.id)}
                </span>
              </Link>
            ))
          )}
        </div>
      )}
    </div>
  );
}


/** Preset filter chips for the audit page. Each chip maps to a
 *  semantic category that the admin actually thinks in (Edit trade,
 *  Reopen, Deposit, etc.) — internally we hand a comma-separated list
 *  of action codes + an optional entity_type whitelist to the backend.
 *  Keeping the mapping table here (not on the backend) lets the
 *  category set evolve without a deploy.
 */
const PRESETS: {
  id: string;
  label: string;
  actions?: string[];        // matches AuditAction enum values
  entity_types?: string[];   // matches the entity_type strings the
                             // log_event helpers stamp (e.g. "Position",
                             // "DepositRequest", "WithdrawalRequest")
}[] = [
  { id: "all", label: "All" },
  {
    id: "edit_trade",
    label: "Edit trade",
    actions: ["POSITION_EDIT"],
    entity_types: ["Position"],
  },
  {
    id: "close_admin",
    label: "Close by admin",
    actions: ["SQUAREOFF", "SQUAREOFF_FORCE"],
    entity_types: ["Position"],
  },
  {
    id: "reopen",
    label: "Reopen",
    actions: ["POSITION_REOPEN"],
    entity_types: ["Position"],
  },
  {
    id: "position_delete",
    label: "Position delete",
    actions: ["POSITION_DELETE"],
    entity_types: ["Position"],
  },
  {
    id: "deposit",
    label: "Deposit",
    actions: ["APPROVE", "REJECT"],
    entity_types: ["DepositRequest"],
  },
  {
    id: "withdrawal",
    label: "Withdrawal",
    actions: ["APPROVE", "REJECT"],
    entity_types: ["WithdrawalRequest"],
  },
  {
    id: "settlement",
    label: "Settlement",
    actions: ["APPROVE", "REJECT"],
    entity_types: ["SettlementRequest"],
  },
  {
    id: "kyc",
    label: "KYC",
    actions: ["APPROVE", "REJECT", "CREATE", "UPDATE"],
    entity_types: ["KycSubmission"],
  },
  {
    id: "wallet_adjust",
    label: "Wallet adjust",
    actions: ["WALLET_ADJUST"],
  },
  {
    id: "block",
    label: "Block / Unblock",
    actions: ["BLOCK", "UNBLOCK"],
  },
  {
    id: "login",
    label: "Login",
    actions: ["LOGIN", "LOGOUT", "LOGIN_FAILED"],
  },
  {
    id: "settings",
    label: "Settings change",
    actions: ["SETTING_CHANGE"],
  },
];


function AuditLogsInner() {
  const searchParams = useSearchParams();
  // `involving_user_id` is the new "events involving this user as actor
  // OR target" filter — used by the user-detail Activity link so admin
  // sees user-initiated events too. `target_user_id` kept for backward
  // compat with any existing deep links.
  const queryInvolvingUserId = searchParams?.get("involving_user_id") ?? null;
  const queryTargetUserId = searchParams?.get("target_user_id") ?? null;
  const scopedUserId = queryInvolvingUserId ?? queryTargetUserId;
  const [preset, setPreset] = useState<string>("all");
  // Free-text fields stay as the "advanced" tier of the filter — when
  // a preset is active they're ignored on the server side (server
  // honours `action` over `actions`), so the UI hides them behind a
  // toggle to avoid the appearance of dead inputs.
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [action, setAction] = useState("");
  const [entityType, setEntityType] = useState("");
  const [fromDate, setFromDate] = useState<string>("");
  const [toDate, setToDate] = useState<string>("");
  const [page, setPage] = useState(1);

  // Resolve the active preset → backend params. Empty preset = no
  // category filter; advanced single-action `action` value (if any)
  // takes precedence so the back-compat path still works.
  const activePreset = PRESETS.find((p) => p.id === preset);
  const presetActions =
    !action && activePreset?.actions && activePreset.actions.length > 0
      ? activePreset.actions.join(",")
      : undefined;
  const presetEntityTypes =
    !entityType && activePreset?.entity_types && activePreset.entity_types.length > 0
      ? activePreset.entity_types.join(",")
      : undefined;

  function selectPreset(id: string) {
    setPreset(id);
    setPage(1);
  }

  const { data: scopedUser } = useQuery({
    queryKey: ["admin", "user", scopedUserId],
    queryFn: () => UsersAPI.detail(scopedUserId!),
    enabled: !!scopedUserId,
    staleTime: 5 * 60_000,
  });

  const { data, isFetching } = useQuery({
    queryKey: [
      "admin",
      "audit",
      {
        preset,
        action,
        entityType,
        fromDate,
        toDate,
        page,
        queryInvolvingUserId,
        queryTargetUserId,
      },
    ],
    queryFn: () =>
      SettingsAPI.audit({
        action: action || undefined,
        actions: presetActions,
        entity_type: entityType || undefined,
        entity_types: presetEntityTypes,
        from_date: fromDate ? new Date(fromDate).toISOString() : undefined,
        to_date: toDate
          ? new Date(`${toDate}T23:59:59.999`).toISOString()
          : undefined,
        involving_user_id: queryInvolvingUserId || undefined,
        target_user_id: queryTargetUserId || undefined,
        page,
        page_size: 50,
      }),
  });

  const cols: Column<any>[] = [
    { key: "created_at", header: "When", render: (r) => new Date(r.created_at).toLocaleString() },
    { key: "action", header: "Action", render: (r) => <StatusPill status={r.action} /> },
    { key: "entity_type", header: "Entity" },
    { key: "entity_id", header: "ID", render: (r) => <span className="font-mono text-[11px]">{r.entity_id?.slice(-12) || "—"}</span> },
    {
      // Actor — the user who initiated the action. Backend now ships
      // an `actor` object with `name` + `code` + `role`, so render the
      // friendly name with the user_code on a muted second line
      // instead of the last-8-of-ObjectId blob that used to be there.
      key: "actor",
      header: "Actor",
      render: (r) => <UserCell info={r.actor} fallback="system" />,
    },
    {
      // Target — who the action was performed on. Same enrichment as
      // Actor. Many rows have actor == target (e.g. user logs in:
      // actor=user, target=user) which is fine — both cells render
      // the same name.
      key: "target",
      header: "Target",
      render: (r) => <UserCell info={r.target} fallback="—" />,
    },
    {
      key: "metadata",
      header: "Detail",
      // Fixed width + override the DataTable's default `whitespace-nowrap`
      // so the inner truncate actually clips instead of forcing the cell
      // wider into the IP column. The bullets line gets per-line truncate;
      // the user can hover for the full title attribute and click "Raw"
      // for the unabbreviated JSON.
      className: "w-[320px] min-w-[320px] max-w-[320px] whitespace-normal align-top",
      render: (r) => <AuditDetailCell row={r} />,
    },
    {
      key: "ip_address",
      header: "IP",
      render: (r) => (
        <span className="font-tabular text-[11px]" title={r.ip_address ?? ""}>
          {r.ip_address || "—"}
        </span>
      ),
    },
    {
      key: "user_agent",
      header: "Device",
      render: (r) => (
        <span
          className="text-[11px]"
          // Full UA available on hover/long-press for the curious.
          title={r.user_agent ?? ""}
        >
          {shortDevice(r.user_agent)}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader title="Audit logs" description={`${data?.meta?.total ?? 0} events`} />

      {/* Search a user by name / code / email / mobile and jump straight
          to their full activity (orders, positions, logins) with IP +
          device + exact time — the "kis user ne kaunsa order place kiya"
          lookup. Selecting a result scopes the feed via involving_user_id. */}
      <UserSearchBox />

      {scopedUserId && (
        <div className="inline-flex items-center gap-2 rounded-md border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs">
          <span className="text-muted-foreground">
            {queryInvolvingUserId ? "Filtered by user (actor or target):" : "Filtered by target user:"}
          </span>
          <span className="font-semibold text-primary">
            {(scopedUser as any)?.user_code ?? scopedUserId.slice(-8)}
            {(scopedUser as any)?.full_name ? ` · ${(scopedUser as any).full_name}` : ""}
          </span>
          <Link
            href="/audit"
            className="grid size-5 place-items-center rounded text-muted-foreground hover:bg-muted/40 hover:text-foreground"
            aria-label="Clear user filter"
          >
            <XIcon className="size-3" />
          </Link>
        </div>
      )}

      {/* Preset filter chips — each chip maps to a backend
          `actions=...` + `entity_types=...` combo so the operator
          picks "Edit trade" / "Reopen" / "Deposit" / etc. without
          having to remember enum names. The "All" chip clears
          everything to the unfiltered view. */}
      <div data-tour="au-presets" className="flex flex-wrap items-center gap-1.5">
        {PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => selectPreset(p.id)}
            className={
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors " +
              (preset === p.id
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-background text-muted-foreground hover:bg-muted/40 hover:text-foreground")
            }
          >
            {p.label}
          </button>
        ))}
        <span className="mx-1 hidden h-6 w-px bg-border sm:inline-block" />
        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="rounded-full border border-dashed border-border bg-background px-3 py-1 text-[11px] text-muted-foreground hover:bg-muted/40"
        >
          {showAdvanced ? "Hide advanced" : "Advanced"}
        </button>
      </div>

      {/* Date range — always visible since it's a common filter for
          "today's events" / "yesterday only" investigations. Inputs
          are HTML5 date pickers so no extra dep is needed. Empty
          either bound = open-ended. */}
      <div data-tour="au-dates" className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <label className="block text-[10px] uppercase tracking-wider text-muted-foreground">
            From
          </label>
          <Input
            type="date"
            value={fromDate}
            onChange={(e) => {
              setPage(1);
              setFromDate(e.target.value);
            }}
            className="h-9 w-[150px]"
          />
        </div>
        <div className="space-y-1">
          <label className="block text-[10px] uppercase tracking-wider text-muted-foreground">
            To
          </label>
          <Input
            type="date"
            value={toDate}
            onChange={(e) => {
              setPage(1);
              setToDate(e.target.value);
            }}
            className="h-9 w-[150px]"
          />
        </div>
        {(fromDate || toDate) && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setFromDate("");
              setToDate("");
              setPage(1);
            }}
            className="h-9"
          >
            <XIcon className="size-3" /> Clear dates
          </Button>
        )}
      </div>

      {/* Advanced free-text filters — hidden by default to keep the
          chip row clean. When a preset is active these inputs take
          precedence on the backend (single `action` beats `actions`
          CSV) so the operator can drill into a specific action code
          that the chip set doesn't cover. */}
      {showAdvanced && (
        <div className="flex flex-wrap gap-2">
          <Input
            value={action}
            onChange={(e) => {
              setPage(1);
              setAction(e.target.value);
            }}
            placeholder="Action code (e.g. ORDER_PLACE)"
            className="h-9 max-w-xs"
          />
          <Input
            value={entityType}
            onChange={(e) => {
              setPage(1);
              setEntityType(e.target.value);
            }}
            placeholder="Entity type (e.g. User)"
            className="h-9 max-w-xs"
          />
        </div>
      )}

      <div data-tour="au-list">
        <DataTable columns={cols} rows={data?.items} keyExtractor={(r) => r.id} loading={isFetching && !data} />
      </div>

      {(data?.meta?.total_pages ?? 1) > 1 && (
        <div className="flex justify-end gap-2 text-xs">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Prev
          </Button>
          <span className="self-center text-muted-foreground">
            {page} / {data?.meta?.total_pages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= (data?.meta?.total_pages ?? 1)}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}

// ── Human-readable Detail cell ───────────────────────────────────────
//
// Operator 22-May: the Audit Logs page showed metadata as raw JSON —
// `{"symbol":"CRUDEOIL26JUNFUT","action":"BUY","ord...` — hard to scan
// at a glance. This renders the same data as plain English, grouped by
// the action type the row represents. Falls back to the JSON view via
// "Raw" toggle so nothing is hidden — admins can always pop the raw
// dict for fields the formatter doesn't know about.

const ACTION_LABELS: Record<string, string> = {
  ORDER_PLACE: "New order",
  ORDER_CANCEL: "Order cancelled",
  ORDER_MODIFY: "Order modified",
  SQUAREOFF: "Position squared off",
  SQUAREOFF_FORCE: "Force squareoff",
  POSITION_EDIT: "Position edited",
  POSITION_REOPEN: "Position reopened",
  POSITION_DELETE: "Position deleted",
  UPDATE: "Updated",
  WALLET_ADJUST: "Wallet adjusted",
  SETTING_CHANGE: "Setting changed",
  BLOCK: "User blocked",
  UNBLOCK: "User unblocked",
  IMPERSONATE: "Impersonated user",
  LOGIN: "Logged in",
  LOGOUT: "Logged out",
  LOGIN_FAILED: "Failed login",
  CREATE: "Created",
  DELETE: "Deleted",
  APPROVE: "Approved",
  REJECT: "Rejected",
};

// `kind` discriminator on Position UPDATE rows — sub-actions live here.
const KIND_LABELS: Record<string, string> = {
  INTRADAY_TO_CARRY_CONVERSION: "MIS → NRML carry-forward",
};

function fmtMoney(v: any): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v ?? "");
  return "🪙" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** "Name (CODE)" for a row's actor/target. Falls back to the code, the
 *  name alone, or a supplied placeholder when the backend couldn't
 *  resolve the user (e.g. system/boot rows). */
function personLabel(info: any, fallback: string): string {
  if (!info) return fallback;
  const name = (info.name || "").trim();
  const code = (info.code || "").trim();
  if (name && code) return `${name} (${code})`;
  return name || code || fallback;
}

// Sensitive actions an admin should never miss in a scan — these get an
// amber left-border + coloured text in the Detail cell. Impersonation,
// money moves, hand-edits to positions, and block/unblock all qualify.
const WARN_ACTIONS = new Set<string>([
  "IMPERSONATE",
  "SQUAREOFF_FORCE",
  "WALLET_ADJUST",
  "POSITION_EDIT",
  "POSITION_REOPEN",
  "POSITION_DELETE",
  "BLOCK",
  "UNBLOCK",
  "DELETE",
]);

/** Build a plain-English, full-sentence description of an audit row that
 *  names WHO did WHAT to WHOM — written so a non-technical operator gets
 *  it at a glance. The structured `bullets` underneath keep the exact
 *  numbers (price, qty, margins) for anyone who wants the detail. */
function fmtAuditMetadata(row: any): {
  summary: string;
  bullets: string[];
  tone: "normal" | "warn";
} {
  const m = row.metadata ?? {};
  const action = String(row.action ?? "");
  const actor = personLabel(row.actor, "System");
  const target = personLabel(row.target, "");
  const sym = m.symbol ? String(m.symbol) : "";
  const bullets: string[] = [];
  const tone: "normal" | "warn" = WARN_ACTIONS.has(action) ? "warn" : "normal";

  // ── Trading-log helpers — render order/trade rows in the clean broker
  // style: "Order Execution : amarjeet(VM1197) sell 35 Qty Of NIFTY…CE At
  // 187.04" / "Limit Order Created : ..." / "Pending Order Modified : ...".
  const ownerInfo =
    row.target && (row.target.name || row.target.code) ? row.target : row.actor;
  const ownerTight = (() => {
    const n = (ownerInfo?.name || "").trim();
    const c = (ownerInfo?.code || "").trim();
    return n && c ? `${n}(${c})` : n || c || actor;
  })();
  const sideTxt = m.action ? String(m.action).toLowerCase() : "";
  const qtyTxt =
    m.quantity != null ? String(m.quantity) : m.closed_qty != null ? String(m.closed_qty) : "";
  const pxTxt =
    m.price != null && m.price !== "0"
      ? Number(m.price).toLocaleString("en-IN", { maximumFractionDigits: 4 })
      : "";
  const otype = String(m.order_type || "").toUpperCase();
  const otypeLabel =
    otype === "LIMIT" ? "Limit" : otype === "SL_M" || otype === "SL" ? "SL-M" : "Market";
  const ofSym = sym ? ` Qty Of ${sym}` : "";
  const atPx = pxTxt ? ` At ${pxTxt}` : "";

  let summary: string;
  switch (action) {
    case "IMPERSONATE": {
      const role = m.as_role ? String(m.as_role).toLowerCase() : "user";
      const tgt = target || "another account";
      // Spell out the implication — this is the line operators most often
      // misread ("Impersonated user / As role: CLIENT" told them nothing).
      summary =
        `${actor} logged into ${tgt}'s account and can now act as them (${role}). ` +
        `Anything done after this — orders, closes, edits — is really ${actor}, ` +
        `even though it shows under ${tgt}'s name.`;
      break;
    }
    case "SQUAREOFF":
    case "SQUAREOFF_FORCE": {
      summary =
        `Square-off : ${ownerTight}${sym ? ` ${sym}` : ""}` +
        (qtyTxt ? ` ${qtyTxt} Qty` : "") +
        atPx +
        (action === "SQUAREOFF_FORCE" ? " (forced)" : "");
      break;
    }
    case "ORDER_PLACE": {
      // Market = immediate fill → "Order Execution". Limit / SL-M create a
      // pending order that fills later → "<Type> Order Created".
      summary =
        otype === "MARKET" || otype === ""
          ? `Order Execution : ${ownerTight} ${sideTxt} ${qtyTxt}${ofSym}${atPx}`
          : `${otypeLabel} Order Created : ${ownerTight} ${sideTxt} ${qtyTxt}${ofSym}${atPx}`;
      break;
    }
    case "ORDER_CANCEL":
      summary = `Pending Order Cancelled : ${ownerTight} ${sideTxt} ${qtyTxt}${ofSym}${atPx}`;
      break;
    case "ORDER_MODIFY":
      summary =
        `Pending Order Modified : ${otypeLabel} of ${sym || "order"} ` +
        `B/S: ${sideTxt} Qty: ${qtyTxt} Rate: ${pxTxt}`;
      break;
    case "ORDER_REJECT":
      summary = `Order Rejected : ${ownerTight} ${sideTxt} ${qtyTxt}${ofSym}${atPx}`;
      break;
    case "POSITION_EDIT":
      summary = `${actor} hand-edited ${target ? `${target}'s` : "a"} ${sym || "position"}`;
      break;
    case "POSITION_REOPEN":
      summary = `${actor} re-opened ${target ? `${target}'s` : "a"} closed ${sym || "position"}`;
      break;
    case "POSITION_DELETE":
      summary = `${actor} deleted ${target ? `${target}'s` : "a"} ${sym || "position"} record`;
      break;
    case "WALLET_ADJUST": {
      const amt = m.amount != null ? ` by ${fmtMoney(m.amount)}` : "";
      const kind = m.type ? ` (${m.type})` : "";
      summary = `${actor} changed ${target ? `${target}'s` : "a user's"} wallet balance${amt}${kind}`;
      break;
    }
    case "BLOCK":
      summary = `${actor} blocked ${target || "a user"} from the platform`;
      break;
    case "UNBLOCK":
      summary = `${actor} unblocked ${target || "a user"}`;
      break;
    case "APPROVE":
      summary = `${actor} approved ${row.entity_type || "a request"}${target && target !== actor ? ` for ${target}` : ""}`;
      break;
    case "REJECT":
      summary = `${actor} rejected ${row.entity_type || "a request"}${target && target !== actor ? ` for ${target}` : ""}`;
      break;
    case "LOGIN":
      summary = `${actor} logged in`;
      break;
    case "LOGOUT":
      summary = `${actor} logged out`;
      break;
    case "LOGIN_FAILED":
      summary = `Failed login attempt for ${target || actor}`;
      break;
    case "SETTING_CHANGE":
      summary = `${actor} changed a setting${m.tier ? ` (${m.tier})` : ""}`;
      break;
    case "UPDATE":
      summary =
        m.kind && KIND_LABELS[m.kind]
          ? `${actor} — ${KIND_LABELS[m.kind]}${target && target !== actor ? ` on ${target}'s position` : ""}`
          : `${actor} updated ${target && target !== actor ? `${target}'s record` : (row.entity_type || "a record")}`;
      break;
    default: {
      const label = ACTION_LABELS[action] ?? action;
      summary =
        target && target !== actor
          ? `${actor} — ${label} → ${target}`
          : `${actor} — ${label}`;
    }
  }

  // ── Supporting numbers (unchanged — kept under the sentence) ─────────
  // Symbol always on top if present
  if (m.symbol) bullets.push(`Symbol: ${m.symbol}`);

  // Order-shape fields
  if (m.action) bullets.push(`Side: ${m.action}`);
  if (m.order_type) bullets.push(`Type: ${m.order_type}`);
  if (m.product_type) bullets.push(`Product: ${m.product_type}`);
  if (m.quantity != null) bullets.push(`Qty: ${m.quantity}`);
  if (m.price != null && m.price !== "0") bullets.push(`Price: ${fmtMoney(m.price)}`);

  // Squareoff shape
  if (m.closed_lots != null) bullets.push(`Closed lots: ${m.closed_lots}`);
  if (m.closed_qty != null) bullets.push(`Closed qty: ${m.closed_qty}`);

  // Intraday→carry conversion shape
  if (m.old_margin != null) bullets.push(`Old margin: ${fmtMoney(m.old_margin)}`);
  if (m.new_margin != null) bullets.push(`New margin: ${fmtMoney(m.new_margin)}`);
  if (m.delta != null) bullets.push(`Margin Δ: ${fmtMoney(m.delta)}`);

  // Reopen shape
  if (m.reversed_realized_pnl != null) bullets.push(`Reversed P&L: ${fmtMoney(m.reversed_realized_pnl)}`);
  if (m.restored_quantity != null) bullets.push(`Restored qty: ${m.restored_quantity}`);

  // Wallet adjust shape
  if (m.amount != null && m.type) bullets.push(`Amount: ${fmtMoney(m.amount)} (${m.type})`);

  // Impersonate / role
  if (m.as_role) bullets.push(`Acting as: ${m.as_role}`);

  // Settings changes
  if (m.tier) bullets.push(`Tier: ${m.tier}`);
  if (m.rule_type) bullets.push(`Rule: ${m.rule_type}`);
  if (m.kind && !KIND_LABELS[m.kind]) bullets.push(`Kind: ${m.kind}`);

  return { summary, bullets, tone };
}

function AuditDetailCell({ row }: { row: any }) {
  const m = row.metadata ?? {};
  const [showRaw, setShowRaw] = useState(false);
  const hasMeta = m && Object.keys(m).length > 0;

  if (showRaw && hasMeta) {
    return (
      <div className="w-full max-w-[300px] space-y-1 overflow-hidden">
        <code
          className="block whitespace-pre-wrap break-all rounded bg-muted/40 p-1.5 text-[10px]"
          title={JSON.stringify(m, null, 2)}
        >
          {JSON.stringify(m, null, 2)}
        </code>
        <button
          type="button"
          onClick={() => setShowRaw(false)}
          className="text-[10px] text-primary hover:underline"
        >
          Hide technical data
        </button>
      </div>
    );
  }

  const { summary, bullets, tone } = fmtAuditMetadata(row);
  const bulletText = bullets.join(" · ");
  const warn = tone === "warn";

  return (
    <div
      className={
        "w-full max-w-[300px] space-y-0.5 overflow-hidden" +
        (warn ? " border-l-2 border-amber-500/70 pl-2" : "")
      }
    >
      {/* Full sentence — wraps (no truncate) so the whole "who did what to
          whom" line is readable. Sensitive actions render amber. */}
      <div
        className={
          "whitespace-normal break-words text-xs font-medium leading-snug " +
          (warn ? "text-amber-600 dark:text-amber-400" : "text-foreground")
        }
      >
        {summary}
      </div>
      {bullets.length > 0 && (
        <div
          className="truncate text-[11px] text-muted-foreground"
          title={bulletText}
        >
          {bulletText}
        </div>
      )}
      {hasMeta && (
        <button
          type="button"
          onClick={() => setShowRaw(true)}
          className="text-[10px] text-muted-foreground/70 hover:text-primary hover:underline"
        >
          Show technical data
        </button>
      )}
    </div>
  );
}
