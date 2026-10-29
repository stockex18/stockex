"use client";

import { useEffect, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Loader2, Mail, Phone, Search } from "lucide-react";
import { LeadsAPI, type LeadRow, type LeadStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/common/PageHeader";
import { cn } from "@/lib/utils";

const STATUSES: { value: LeadStatus; label: string; tone: string }[] = [
  { value: "NEW", label: "New", tone: "bg-sky-500/15 text-sky-400" },
  { value: "CONTACTED", label: "Contacted", tone: "bg-amber-500/15 text-amber-400" },
  { value: "CONVERTED", label: "Converted", tone: "bg-emerald-500/15 text-emerald-400" },
  { value: "NOT_INTERESTED", label: "Not interested", tone: "bg-zinc-500/20 text-zinc-400" },
];
const toneOf = (s: LeadStatus) => STATUSES.find((x) => x.value === s)?.tone ?? "";

const PAGE_SIZE = 50;

function istDateTime(v: string | null) {
  if (!v) return "—";
  const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(v) ? v : `${v}Z`);
  return d.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function source(r: LeadRow) {
  const parts = [r.utm_source, r.utm_medium, r.utm_campaign].filter(Boolean);
  return parts.length ? parts.join(" / ") : "Direct";
}

function NoteCell({ row }: { row: LeadRow }) {
  const qc = useQueryClient();
  const [val, setVal] = useState(row.note);
  useEffect(() => setVal(row.note), [row.note]);
  const save = useMutation({
    mutationFn: (note: string) => LeadsAPI.update(row.id, { note }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leads"] }),
  });
  return (
    <Input
      value={val}
      placeholder="Add a note"
      className="h-8 min-w-[10rem] text-xs"
      onChange={(e) => setVal(e.target.value)}
      onBlur={() => val !== row.note && save.mutate(val)}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

export default function LeadsPage() {
  const qc = useQueryClient();
  const [status, setStatus] = useState<LeadStatus | "">("");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);

  // Search as the operator types, without a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(search.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(t);
  }, [search]);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["leads", status, q, page],
    queryFn: () => LeadsAPI.list({ status: status || undefined, q: q || undefined, page, limit: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });

  const setLeadStatus = useMutation({
    mutationFn: ({ id, s }: { id: string; s: LeadStatus }) => LeadsAPI.update(id, { status: s }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leads"] }),
  });

  async function exportCsv() {
    setExporting(true);
    try {
      const blob = await LeadsAPI.exportCsv({ status: status || undefined, q: q || undefined });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `leads-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  const counts = data?.counts;
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const all = counts ? Object.values(counts).reduce((a, b) => a + b, 0) : 0;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Leads"
        description="People who asked for a callback on the /start landing page. Every mobile is verified by SMS."
        actions={
          <Button variant="outline" onClick={exportCsv} disabled={exporting || total === 0}>
            {exporting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}
            Export CSV
          </Button>
        }
      />

      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => { setStatus(""); setPage(1); }}
          className={cn(
            "rounded-full border px-3 py-1.5 text-xs font-medium",
            status === "" ? "border-primary bg-primary/15 text-primary" : "border-border text-muted-foreground",
          )}
        >
          All · {all}
        </button>
        {STATUSES.map((s) => (
          <button
            key={s.value}
            onClick={() => { setStatus(s.value); setPage(1); }}
            className={cn(
              "rounded-full border px-3 py-1.5 text-xs font-medium",
              status === s.value ? "border-primary bg-primary/15 text-primary" : "border-border text-muted-foreground",
            )}
          >
            {s.label} · {counts?.[s.value] ?? 0}
          </button>
        ))}
      </div>

      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder="Search name, mobile, email, city, campaign, ref code"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center gap-2 p-10 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading leads…
            </div>
          ) : isError ? (
            <p className="p-6 text-sm text-red-400">{(error as Error)?.message || "Could not load leads."}</p>
          ) : !data?.rows.length ? (
            <p className="p-10 text-center text-sm text-muted-foreground">
              {q || status ? "No leads match this filter." : "No leads yet. They appear here as soon as someone submits the /start form."}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3">Received</th>
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3">Contact</th>
                    <th className="px-4 py-3">City</th>
                    <th className="px-4 py-3">Experience</th>
                    <th className="px-4 py-3">Question</th>
                    <th className="px-4 py-3">Source</th>
                    <th className="px-4 py-3">Ref</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Note</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {data.rows.map((r) => (
                    <tr key={r.id} className="align-middle">
                      <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                        {istDateTime(r.created_at)}
                        {r.submissions > 1 && (
                          <span className="ml-1 text-xs" title={`Last: ${istDateTime(r.last_submitted_at)}`}>
                            ×{r.submissions}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 font-medium">{r.full_name}</td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <a href={`tel:+91${r.mobile}`} className="inline-flex items-center gap-1.5 hover:text-primary">
                          <Phone className="h-3.5 w-3.5" /> {r.mobile}
                        </a>
                        {r.email && (
                          <a
                            href={`mailto:${r.email}`}
                            className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground hover:text-primary"
                          >
                            <Mail className="h-3 w-3" /> {r.email}
                          </a>
                        )}
                      </td>
                      <td className="px-4 py-3">{r.city}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs">{r.experience_label || "—"}</td>
                      <td className="px-4 py-3">
                        {r.question ? (
                          <p className="line-clamp-2 max-w-[16rem] text-xs text-muted-foreground" title={r.question}>
                            {r.question}
                          </p>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">{source(r)}</td>
                      <td className="px-4 py-3 font-mono text-xs">{r.ref_code || "—"}</td>
                      <td className="px-4 py-3">
                        <select
                          value={r.status}
                          disabled={setLeadStatus.isPending}
                          onChange={(e) => setLeadStatus.mutate({ id: r.id, s: e.target.value as LeadStatus })}
                          className={cn("rounded-md border-0 px-2 py-1 text-xs font-medium", toneOf(r.status))}
                        >
                          {STATUSES.map((s) => (
                            <option key={s.value} value={s.value} className="bg-background text-foreground">
                              {s.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-4 py-3">
                        <NoteCell row={r} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {pages > 1 && (
        <div className="flex items-center justify-end gap-3 text-sm">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <span className="text-muted-foreground">
            Page {page} of {pages}
          </span>
          <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
