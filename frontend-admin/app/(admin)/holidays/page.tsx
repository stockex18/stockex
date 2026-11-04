"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { SettingsAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { PageHeader } from "@/components/common/PageHeader";
import { DataTable, type Column } from "@/components/common/DataTable";

export default function HolidaysPage() {
  const qc = useQueryClient();
  const [year, setYear] = useState<number | undefined>(new Date().getFullYear());
  const { data, isFetching } = useQuery({
    queryKey: ["admin", "holidays", year],
    queryFn: () => SettingsAPI.holidays(year),
  });

  const [adding, setAdding] = useState(false);
  const blank = { holiday_date: "", description: "", exchange: "NSE", is_muhurat: false, open_time: "", close_time: "" };
  const [form, setForm] = useState(blank);

  function edit(r: any) {
    setForm({
      holiday_date: r.holiday_date,
      description: r.description || "",
      exchange: r.exchange,
      is_muhurat: !!r.is_muhurat,
      open_time: r.open_time || "",
      close_time: r.close_time || "",
    });
    setAdding(true);
  }

  async function add() {
    if (form.is_muhurat && (!form.open_time || !form.close_time)) {
      toast.error("Set the session's start and end time");
      return;
    }
    try {
      // Saving the same date + exchange again edits that day.
      await SettingsAPI.createHoliday({ ...form, is_full_day: !form.is_muhurat });
      toast.success("Saved");
      setAdding(false);
      qc.invalidateQueries({ queryKey: ["admin", "holidays"] });
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function remove(id: string) {
    if (!confirm("Delete this holiday?")) return;
    try {
      await SettingsAPI.deleteHoliday(id);
      toast.success("Deleted");
      qc.invalidateQueries({ queryKey: ["admin", "holidays"] });
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  const cols: Column<any>[] = [
    { key: "holiday_date", header: "Date" },
    { key: "exchange", header: "Exchange" },
    { key: "description", header: "Description" },
    {
      key: "session",
      header: "Trading",
      render: (r) =>
        r.is_muhurat && r.open_time && r.close_time ? (
          <span className="font-semibold text-emerald-500">
            Muhurat · {r.open_time} – {r.close_time} IST
          </span>
        ) : r.is_full_day ? (
          <span className="text-muted-foreground">Closed all day</span>
        ) : (
          "—"
        ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (r) => (
        <div className="flex justify-end gap-1">
          <Button variant="ghost" size="icon" onClick={() => edit(r)} aria-label="Edit">
            <Pencil className="size-4" />
          </Button>
          <Button variant="ghost" size="icon" onClick={() => remove(r.id)} aria-label="Delete">
            <Trash2 className="size-4 text-destructive" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Trading holidays"
        actions={
          <div className="flex gap-2">
            <Input
              type="number"
              value={year ?? ""}
              onChange={(e) => setYear(e.target.value ? Number(e.target.value) : undefined)}
              className="h-10 w-24"
              placeholder="Year"
            />
            <Dialog
              open={adding}
              onOpenChange={(o) => {
                setAdding(o);
                if (!o) setForm(blank);
              }}
            >
              <DialogTrigger asChild>
                <Button>
                  <Plus className="size-4" /> Add holiday
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Holiday / Muhurat session</DialogTitle>
                </DialogHeader>
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <Label>Date</Label>
                    <Input type="date" value={form.holiday_date} onChange={(e) => setForm((f) => ({ ...f, holiday_date: e.target.value }))} />
                  </div>
                  <div className="space-y-1.5">
                    <Label>Exchange</Label>
                    <select
                      value={form.exchange}
                      onChange={(e) => setForm((f) => ({ ...f, exchange: e.target.value }))}
                      className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                    >
                      <option value="NSE">NSE</option>
                      <option value="BSE">BSE</option>
                      <option value="MCX">MCX</option>
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <Label>Description</Label>
                    <Input value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
                  </div>
                  <div className="space-y-1.5">
                    <Label>Type</Label>
                    <select
                      value={form.is_muhurat ? "MUHURAT" : "HOLIDAY"}
                      onChange={(e) => setForm((f) => ({ ...f, is_muhurat: e.target.value === "MUHURAT" }))}
                      className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                    >
                      <option value="HOLIDAY">Holiday: market closed all day</option>
                      <option value="MUHURAT">Muhurat / special session: open only between two times</option>
                    </select>
                  </div>
                  {form.is_muhurat && (
                    <div className="space-y-2 rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3">
                      <div className="grid grid-cols-2 gap-2">
                        <div className="space-y-1.5">
                          <Label>From (IST)</Label>
                          <Input
                            type="time"
                            value={form.open_time}
                            onChange={(e) => setForm((f) => ({ ...f, open_time: e.target.value }))}
                          />
                        </div>
                        <div className="space-y-1.5">
                          <Label>To (IST)</Label>
                          <Input
                            type="time"
                            value={form.close_time}
                            onChange={(e) => setForm((f) => ({ ...f, close_time: e.target.value }))}
                          />
                        </div>
                      </div>
                      <p className="text-[11px] text-muted-foreground">
                        That day {form.exchange === "MCX" ? "MCX" : "NSE, BSE and F&O"} trade only in this window,
                        even on a Saturday or Sunday: new orders, exits, pending limit / SL orders and SL / TP /
                        stop-out. Intraday carry runs after it closes.
                        {form.exchange !== "MCX" && " Add a separate MCX row if MCX also has a session."}
                      </p>
                    </div>
                  )}
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setAdding(false)}>
                    Cancel
                  </Button>
                  <Button onClick={add}>Save</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        }
      />
      <DataTable columns={cols} rows={data} keyExtractor={(r) => r.id} loading={isFetching && !data} />
    </div>
  );
}
