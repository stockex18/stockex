"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Network, RefreshCw, Search } from "lucide-react";

import { ManagementAPI } from "@/lib/api";
import { formatINR, signedINR } from "@/lib/utils";
import { useAdminAuthStore } from "@/stores/authStore";
import { PageHeader } from "@/components/common/PageHeader";
import { Card, CardContent } from "@/components/ui/card";

type Row = {
  id: string;
  user_code: string;
  full_name: string;
  email?: string;
  mobile?: string;
  status: string;
  is_demo: boolean;
  wallet_balance: string;
};
type AdminRow = Row;
type BrokerRow = Row & { parent_broker_id: string | null; admin_id: string | null };
type UserRow = Row & {
  broker_id: string | null;
  admin_id: string | null;
  realised_pnl: string;
  today_pnl: string;
  unrealised_pnl: string;
  net_pnl: string;
  open_positions: number;
};

type Kind = "ADMIN" | "SA" | "BROKER" | "SUB_BROKER" | "USER";

// Rolled-up totals for a node: its own wallet + everything beneath it.
type Totals = {
  brokers: number;
  users: number;
  userWallet: number;
  today: number;
  realised: number;
  unrealised: number;
  net: number;
};

type Node = {
  key: string;
  kind: Kind;
  row: Row | null; // null for the super-admin "direct pool" bucket
  children: Node[];
  totals: Totals;
  match: boolean; // self or any descendant matches the search
};

const SA_KEY = "SA";

function n(v: string | number | undefined) {
  return Number(v) || 0;
}

function Money({ v, bold }: { v: number; bold?: boolean }) {
  return (
    <span
      className={`tabular-nums ${bold ? "font-semibold" : ""} ${
        v < 0 ? "text-red-500" : v > 0 ? "text-emerald-500" : "text-muted-foreground"
      }`}
    >
      {signedINR(v)}
    </span>
  );
}

const KIND_LABEL: Record<Kind, string> = {
  ADMIN: "Admin",
  SA: "Super admin",
  BROKER: "Broker",
  SUB_BROKER: "Sub-broker",
  USER: "User",
};
const KIND_STYLE: Record<Kind, string> = {
  ADMIN: "bg-amber-500/15 text-amber-500",
  SA: "bg-amber-500/15 text-amber-500",
  BROKER: "bg-sky-500/15 text-sky-400",
  SUB_BROKER: "bg-violet-500/15 text-violet-400",
  USER: "bg-muted text-muted-foreground",
};

function detailHref(node: Node): string | null {
  if (!node.row) return null;
  if (node.kind === "ADMIN") return `/management/sub-admins/${node.row.id}`;
  if (node.kind === "BROKER" || node.kind === "SUB_BROKER") return `/management/brokers/${node.row.id}`;
  return `/users/${node.row.id}`;
}

function buildTree(
  admins: AdminRow[],
  brokers: BrokerRow[],
  users: UserRow[],
  q: string,
): Node[] {
  const needle = q.trim().toLowerCase();
  const hit = (r: Row | null) =>
    !needle ||
    (!!r &&
      [r.full_name, r.user_code, r.email, r.mobile].some((s) => (s || "").toLowerCase().includes(needle)));

  // Brokers keyed by their parent: a sub-broker under its broker id, a
  // top-level broker under "admin:<id>" (or "admin:SA" for the SA pool).
  const brokersBy = new Map<string, BrokerRow[]>();
  for (const b of brokers) {
    const k = b.parent_broker_id ?? `admin:${b.admin_id ?? SA_KEY}`;
    brokersBy.set(k, [...(brokersBy.get(k) || []), b]);
  }
  const usersBy = new Map<string, UserRow[]>();
  for (const u of users) {
    const k = u.broker_id ?? `admin:${u.admin_id ?? SA_KEY}`;
    usersBy.set(k, [...(usersBy.get(k) || []), u]);
  }

  const zero = (): Totals => ({ brokers: 0, users: 0, userWallet: 0, today: 0, realised: 0, unrealised: 0, net: 0 });

  const userNode = (u: UserRow): Node => ({
    key: `u:${u.id}`,
    kind: "USER",
    row: u,
    children: [],
    totals: {
      brokers: 0,
      users: 1,
      userWallet: n(u.wallet_balance),
      today: n(u.today_pnl),
      realised: n(u.realised_pnl),
      unrealised: n(u.unrealised_pnl),
      net: n(u.net_pnl),
    },
    match: hit(u),
  });

  const finish = (node: Node, parentMatched: boolean): Node => {
    const t = zero();
    for (const c of node.children) {
      t.brokers += c.totals.brokers + (c.kind === "BROKER" || c.kind === "SUB_BROKER" ? 1 : 0);
      t.users += c.totals.users;
      t.userWallet += c.totals.userWallet;
      t.today += c.totals.today;
      t.realised += c.totals.realised;
      t.unrealised += c.totals.unrealised;
      t.net += c.totals.net;
    }
    node.totals = t;
    const selfHit = hit(node.row);
    // When a parent matches, keep its whole subtree visible.
    if (selfHit || parentMatched) node.match = true;
    else node.match = node.children.some((c) => c.match);
    if (needle && !(selfHit || parentMatched)) node.children = node.children.filter((c) => c.match);
    return node;
  };

  const seen = new Set<string>();
  const brokerNode = (b: BrokerRow, depth: number, parentMatched: boolean): Node => {
    seen.add(b.id);
    const selfHit = !!needle && hit(b);
    const subs = (brokersBy.get(b.id) || [])
      .filter((s) => !seen.has(s.id))
      .map((s) => brokerNode(s, depth + 1, parentMatched || selfHit));
    const us = (usersBy.get(b.id) || []).map(userNode).map((u) => ({
      ...u,
      match: u.match || parentMatched || selfHit,
    }));
    return finish(
      {
        key: `b:${b.id}`,
        kind: depth === 0 ? "BROKER" : "SUB_BROKER",
        row: b,
        children: [...subs, ...us],
        totals: zero(),
        match: false,
      },
      parentMatched,
    );
  };

  const adminNode = (a: AdminRow | null): Node => {
    const k = `admin:${a ? a.id : SA_KEY}`;
    const selfHit = !!needle && !!a && hit(a);
    const bs = (brokersBy.get(k) || []).map((b) => brokerNode(b, 0, selfHit));
    const us = (usersBy.get(k) || []).map(userNode).map((u) => ({ ...u, match: u.match || selfHit }));
    return finish(
      { key: k, kind: a ? "ADMIN" : "SA", row: a, children: [...bs, ...us], totals: zero(), match: false },
      false,
    );
  };

  const roots = [adminNode(null), ...admins.map(adminNode)];
  return needle ? roots.filter((r) => r.match) : roots.filter((r) => r.kind !== "SA" || r.children.length);
}

export default function HierarchyPage() {
  const admin = useAdminAuthStore((s) => s.admin);
  const [q, setQ] = useState("");
  const [hideDemo, setHideDemo] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set());

  const query = useQuery({
    queryKey: ["management", "hierarchy"],
    queryFn: () => ManagementAPI.hierarchy(),
    enabled: admin?.role === "SUPER_ADMIN",
    refetchInterval: 15000,
  });

  const data = query.data as
    | { admins: AdminRow[]; brokers: BrokerRow[]; users: UserRow[]; generated_at: string }
    | undefined;

  const tree = useMemo(() => {
    if (!data) return [];
    const keep = <T extends Row>(rows: T[]) => (hideDemo ? rows.filter((r) => !r.is_demo) : rows);
    return buildTree(keep(data.admins), keep(data.brokers), keep(data.users), q);
  }, [data, q, hideDemo]);

  const summary = useMemo(() => {
    const users = (data?.users || []).filter((u) => !hideDemo || !u.is_demo);
    const brokers = (data?.brokers || []).filter((b) => !hideDemo || !b.is_demo);
    return {
      admins: (data?.admins || []).filter((a) => !hideDemo || !a.is_demo).length,
      brokers: brokers.filter((b) => !b.parent_broker_id).length,
      subBrokers: brokers.filter((b) => b.parent_broker_id).length,
      users: users.length,
      userWallet: users.reduce((s, u) => s + n(u.wallet_balance), 0),
      today: users.reduce((s, u) => s + n(u.today_pnl), 0),
      net: users.reduce((s, u) => s + n(u.net_pnl), 0),
    };
  }, [data, hideDemo]);

  if (admin?.role !== "SUPER_ADMIN") {
    return (
      <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground">
        Only the super admin can view the hierarchy.
      </div>
    );
  }

  const searching = q.trim().length > 0;
  const isOpen = (k: string) => searching || open.has(k);
  const toggle = (k: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });

  const allKeys = (nodes: Node[]): string[] =>
    nodes.flatMap((x) => (x.children.length ? [x.key, ...allKeys(x.children)] : []));

  const rows: { node: Node; depth: number }[] = [];
  const walk = (nodes: Node[], depth: number) => {
    for (const node of nodes) {
      rows.push({ node, depth });
      if (node.children.length && isOpen(node.key)) walk(node.children, depth + 1);
    }
  };
  walk(tree, 0);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Hierarchy"
        description="Every admin, broker, sub-broker and user on the platform, with wallet balance and P&L. Totals on admin / broker rows roll up everyone beneath them."
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        {[
          { label: "Admins", value: summary.admins },
          { label: "Brokers", value: summary.brokers },
          { label: "Sub-brokers", value: summary.subBrokers },
          { label: "Users", value: summary.users },
        ].map((t) => (
          <Card key={t.label}>
            <CardContent className="p-3">
              <div className="text-[11px] uppercase text-muted-foreground">{t.label}</div>
              <div className="text-xl font-semibold tabular-nums">{t.value}</div>
            </CardContent>
          </Card>
        ))}
        <Card>
          <CardContent className="p-3">
            <div className="text-[11px] uppercase text-muted-foreground">Users&apos; wallets</div>
            <div className="text-base font-semibold tabular-nums">{formatINR(summary.userWallet)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-3">
            <div className="text-[11px] uppercase text-muted-foreground">Today P&amp;L</div>
            <div className="text-base">
              <Money v={summary.today} bold />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-3">
            <div className="text-[11px] uppercase text-muted-foreground">Net P&amp;L (all time)</div>
            <div className="text-base">
              <Money v={summary.net} bold />
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 sm:max-w-sm">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search name, code, email, mobile"
            className="h-9 w-full rounded-md border border-border bg-background pl-8 pr-3 text-sm outline-none focus:border-primary"
          />
        </div>
        <button
          className="h-9 rounded-md border border-border px-3 text-sm hover:bg-muted"
          onClick={() => setOpen(new Set(allKeys(tree)))}
        >
          Expand all
        </button>
        <button className="h-9 rounded-md border border-border px-3 text-sm hover:bg-muted" onClick={() => setOpen(new Set())}>
          Collapse all
        </button>
        <label className="flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm">
          <input type="checkbox" checked={hideDemo} onChange={(e) => setHideDemo(e.target.checked)} />
          Hide demo
        </label>
        <button
          className="ml-auto flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm hover:bg-muted"
          onClick={() => query.refetch()}
          title="Refresh"
        >
          <RefreshCw className={`size-4 ${query.isFetching ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      <Card>
        <CardContent className="overflow-x-auto p-0">
          {query.isLoading && <div className="p-4 text-sm text-muted-foreground">Loading…</div>}
          {query.isError && <div className="p-4 text-sm text-red-500">Could not load the hierarchy.</div>}
          {data && rows.length === 0 && (
            <div className="p-4 text-sm text-muted-foreground">{searching ? "No matches." : "Nobody here yet."}</div>
          )}
          {rows.length > 0 && (
            <table className="w-full min-w-[1000px] text-sm">
              <thead className="text-left text-[11px] uppercase text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Type</th>
                  <th className="px-3 py-2 text-right">Brokers</th>
                  <th className="px-3 py-2 text-right">Users</th>
                  <th className="px-3 py-2 text-right">Own wallet</th>
                  <th className="px-3 py-2 text-right">Users&apos; wallets</th>
                  <th className="px-3 py-2 text-right">Today P&amp;L</th>
                  <th className="px-3 py-2 text-right">Realised</th>
                  <th className="px-3 py-2 text-right">Open P&amp;L</th>
                  <th className="px-3 py-2 text-right">Net P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ node, depth }) => {
                  const isUser = node.kind === "USER";
                  const href = detailHref(node);
                  const r = node.row;
                  const ur = isUser ? (r as UserRow) : null;
                  return (
                    <tr
                      key={node.key}
                      className={`border-b border-border/60 ${depth === 0 ? "bg-muted/30" : ""} hover:bg-muted/40`}
                    >
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1" style={{ paddingLeft: depth * 20 }}>
                          {node.children.length ? (
                            <button
                              onClick={() => toggle(node.key)}
                              className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                              aria-label={isOpen(node.key) ? "Collapse" : "Expand"}
                            >
                              {isOpen(node.key) ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                            </button>
                          ) : (
                            <span className="inline-block w-5" />
                          )}
                          <div className="min-w-0">
                            {r ? (
                              <>
                                <div className="flex items-center gap-1.5">
                                  {href ? (
                                    <Link href={href} className="truncate font-medium hover:text-primary hover:underline">
                                      {r.full_name || r.user_code}
                                    </Link>
                                  ) : (
                                    <span className="font-medium">{r.full_name}</span>
                                  )}
                                  {r.is_demo && (
                                    <span className="rounded bg-yellow-500/15 px-1 text-[10px] font-medium text-yellow-500">
                                      DEMO
                                    </span>
                                  )}
                                  {r.status !== "ACTIVE" && (
                                    <span className="rounded bg-red-500/15 px-1 text-[10px] font-medium text-red-500">
                                      {r.status}
                                    </span>
                                  )}
                                </div>
                                <div className="text-[11px] text-muted-foreground">{r.user_code}</div>
                              </>
                            ) : (
                              <>
                                <div className="font-medium">Super admin — direct</div>
                                <div className="text-[11px] text-muted-foreground">Not under any admin</div>
                              </>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${KIND_STYLE[node.kind]}`}>
                          {KIND_LABEL[node.kind]}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{isUser ? "" : node.totals.brokers}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{isUser ? "" : node.totals.users}</td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {r ? formatINR(r.wallet_balance) : "—"}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                        {isUser ? "" : formatINR(node.totals.userWallet)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <Money v={node.totals.today} />
                      </td>
                      <td className="px-3 py-2 text-right">
                        <Money v={node.totals.realised} />
                      </td>
                      <td className="px-3 py-2 text-right">
                        <Money v={node.totals.unrealised} />
                        {ur && ur.open_positions > 0 && (
                          <div className="text-[10px] text-muted-foreground">{ur.open_positions} open</div>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <Money v={node.totals.net} bold />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
      {data?.generated_at && (
        <div className="text-[11px] text-muted-foreground">
          <Network className="mr-1 inline size-3" />
          Updated {new Date(data.generated_at).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" })} IST · refreshes
          every 15 s. P&amp;L shown is the users&apos; trading P&amp;L (realised + open).
        </div>
      )}
    </div>
  );
}
