"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, Copy, ExternalLink, KeyRound, Link2, Loader2, Unplug } from "lucide-react";
import { FyersAPI, type FyersStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * Fyers credentials for the order price check.
 *
 * Same shape as the Upstox card: App ID, secret, and a redirect URL that has
 * to be saved on the Fyers app byte-for-byte — so it is shown to be COPIED,
 * never typed. Fyers tokens expire daily, so Connect is a once-a-morning click.
 */
export function FyersSetupCard() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["fyers", "settings"],
    queryFn: () => FyersAPI.status(),
  });

  const [appId, setAppId] = useState("");
  const [secret, setSecret] = useState("");
  const [copied, setCopied] = useState(false);

  // Seed the App ID once the row arrives. The secret is never sent back, so
  // its box stays empty and an empty box means "leave what is stored alone".
  useEffect(() => {
    if (data) setAppId(data.app_id || "");
  }, [data?.app_id]);

  const refresh = () => qc.invalidateQueries({ queryKey: ["fyers", "settings"] });

  const save = useMutation({
    mutationFn: () => FyersAPI.save({ app_id: appId, ...(secret ? { secret } : {}) }),
    onSuccess: () => {
      setSecret("");
      toast.success("Fyers credentials saved");
      refresh();
    },
    onError: (e: any) => toast.error(e?.message || "Could not save"),
  });

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => FyersAPI.save({ enabled }),
    onSuccess: (r) => {
      toast.success(r.enabled ? "Fyers price check ON" : "Fyers price check OFF");
      refresh();
    },
    onError: (e: any) => toast.error(e?.message || "Could not save"),
  });

  const connect = useMutation({
    mutationFn: () => FyersAPI.loginUrl(),
    onSuccess: (r) => {
      window.open(r.url, "_blank", "noopener");
      toast.info("Finish the login on Fyers, then come back and refresh.");
    },
    onError: (e: any) => toast.error(e?.message || "Could not build the login URL"),
  });

  const disconnect = useMutation({
    mutationFn: () => FyersAPI.disconnect(),
    onSuccess: () => {
      toast.success("Disconnected — credentials kept");
      refresh();
    },
  });

  const s: Partial<FyersStatus> = data ?? {};

  async function copyRedirect() {
    try {
      await navigator.clipboard.writeText(s.redirect_url || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Could not copy — select the text and copy it by hand.");
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <KeyRound className="size-4 text-primary" /> Fyers connection
            </CardTitle>
            <CardDescription>
              When a market order is placed, its Zerodha price is compared with Fyers&apos;
              price at that moment. Orders are never blocked or delayed by this check.
            </CardDescription>
          </div>
          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                "rounded px-2 py-0.5 text-[11px] font-bold",
                s.connected ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground",
              )}
            >
              {isLoading ? "…" : s.connected ? "CONNECTED" : "NOT CONNECTED"}
            </span>
            <span
              className={cn(
                "rounded px-2 py-0.5 text-[11px] font-bold",
                s.enabled ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground",
              )}
            >
              {isLoading ? "…" : s.enabled ? "CHECK ON" : "CHECK OFF"}
            </span>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div>
          <label className="text-xs font-semibold text-muted-foreground">
            Redirect URL — paste this into your Fyers app
          </label>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            It must match byte-for-byte, or Fyers refuses the login.
          </p>
          <div className="mt-1.5 flex items-center gap-2">
            <Input readOnly value={s.redirect_url || ""} className="h-9 font-mono text-xs" />
            <Button size="sm" variant="outline" onClick={copyRedirect} className="shrink-0 gap-1.5">
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="text-xs font-semibold text-muted-foreground">App ID</label>
            <Input
              value={appId}
              onChange={(e) => setAppId(e.target.value)}
              placeholder="e.g. XB12345-100"
              className="mt-1 h-9 font-mono text-xs"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-muted-foreground">
              Secret ID {s.has_secret ? <span className="text-primary">· saved</span> : null}
            </label>
            <Input
              type="password"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              placeholder={s.has_secret ? "Leave blank to keep the saved one" : "Paste the secret"}
              className="mt-1 h-9 font-mono text-xs"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => save.mutate()} loading={save.isPending} disabled={!appId.trim()}>
            Save credentials
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="gap-1.5"
            onClick={() => connect.mutate()}
            loading={connect.isPending}
            disabled={!s.app_id || !s.has_secret}
          >
            <ExternalLink className="size-3.5" />
            {s.connected ? "Reconnect" : "Connect to Fyers"}
          </Button>
          {s.connected && (
            <Button
              size="sm"
              variant="ghost"
              className="gap-1.5 text-muted-foreground"
              onClick={() => disconnect.mutate()}
              loading={disconnect.isPending}
            >
              <Unplug className="size-3.5" /> Disconnect
            </Button>
          )}
          <Button
            size="sm"
            variant={s.enabled ? "destructive" : "default"}
            onClick={() => toggle.mutate(!s.enabled)}
            loading={toggle.isPending}
            disabled={!s.connected && !s.enabled}
            className="ml-auto"
          >
            {s.enabled ? "Turn check OFF" : "Turn check ON"}
          </Button>
        </div>

        {(!s.app_id || !s.has_secret) && (
          <p className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
            <Link2 className="mt-0.5 size-3 shrink-0" />
            In the Fyers API dashboard (myapi.fyers.in), open the app, paste the redirect URL
            above into it, then bring the App ID and Secret ID back here.
          </p>
        )}

        {s.last_error && (
          <p className="rounded-md bg-destructive/10 px-3 py-2 text-[11px] text-destructive">
            Last error from Fyers: {s.last_error}
          </p>
        )}

        {s.connected && s.last_connected && (
          <p className="text-[11px] text-muted-foreground">
            Connected {new Date(s.last_connected).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}.
            Fyers tokens expire daily — click Reconnect each morning before market open.
          </p>
        )}

        {isLoading && (
          <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Loader2 className="size-3 animate-spin" /> Loading…
          </p>
        )}
      </CardContent>
    </Card>
  );
}
