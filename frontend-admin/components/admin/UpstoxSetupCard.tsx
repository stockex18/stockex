"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, Copy, ExternalLink, KeyRound, Link2, Loader2, Unplug } from "lucide-react";
import { UpstoxAPI, type UpstoxStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * Upstox credentials for Check Trades.
 *
 * Check Trades judges a fill against OUR record of the market — the tick we
 * published at that second, the minute candle we built from those ticks. That
 * answers "did we fill where we said we were quoting", which is the question
 * that matters most, but it cannot answer "were we quoting the right price":
 * both sides of that comparison come from us. Upstox is the second opinion.
 *
 * Three things have to line up, and the third is the one that usually bites:
 * the API key, the secret, and a redirect URL registered on the Upstox app
 * byte-for-byte. So the URL is shown to be COPIED, never typed.
 */
export function UpstoxSetupCard() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["upstox", "settings"],
    queryFn: () => UpstoxAPI.status(),
  });

  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [copied, setCopied] = useState(false);

  // Seed the key once the row arrives. The secret is never sent back, so its
  // box stays empty and an empty box means "leave what is stored alone".
  useEffect(() => {
    if (data) setApiKey(data.api_key || "");
  }, [data?.api_key]);

  const refresh = () => qc.invalidateQueries({ queryKey: ["upstox", "settings"] });

  const save = useMutation({
    mutationFn: () =>
      UpstoxAPI.save({
        api_key: apiKey,
        ...(apiSecret ? { api_secret: apiSecret } : {}),
      }),
    onSuccess: () => {
      setApiSecret("");
      toast.success("Upstox credentials saved");
      refresh();
    },
    onError: (e: any) => toast.error(e?.message || "Could not save"),
  });

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => UpstoxAPI.save({ enabled }),
    onSuccess: (r) => {
      toast.success(r.enabled ? "Upstox checks ON" : "Upstox checks OFF");
      refresh();
    },
    onError: (e: any) => toast.error(e?.message || "Could not save"),
  });

  const connect = useMutation({
    mutationFn: () => UpstoxAPI.loginUrl(),
    onSuccess: (r) => {
      // A new tab, not this one: the operator loses nothing if they are
      // halfway through a trade check.
      window.open(r.url, "_blank", "noopener");
      toast.info("Finish the login on Upstox, then come back and refresh.");
    },
    onError: (e: any) => toast.error(e?.message || "Could not build the login URL"),
  });

  const disconnect = useMutation({
    mutationFn: () => UpstoxAPI.disconnect(),
    onSuccess: () => {
      toast.success("Disconnected — credentials kept");
      refresh();
    },
  });

  const s: Partial<UpstoxStatus> = data ?? {};

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
              <KeyRound className="size-4 text-primary" /> Upstox price source
            </CardTitle>
            <CardDescription>
              An outside second opinion. Check Trades compares a fill against our own
              tick; with this connected it can also hold that minute against Upstox&apos;s
              own candle.
            </CardDescription>
          </div>
          <span
            className={cn(
              "rounded px-2 py-0.5 text-[11px] font-bold",
              s.connected ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground",
            )}
          >
            {isLoading ? "…" : s.connected ? "CONNECTED" : "NOT CONNECTED"}
          </span>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Redirect URL first: it has to be registered on the Upstox app
            BEFORE the key and secret are of any use. */}
        <div>
          <label className="text-xs font-semibold text-muted-foreground">
            Redirect URL — paste this into your Upstox app
          </label>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            It must match byte-for-byte. Upstox refuses the login otherwise, and the
            error it gives does not say why.
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
            <label className="text-xs font-semibold text-muted-foreground">API key</label>
            <Input
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="From the Upstox developer console"
              className="mt-1 h-9 font-mono text-xs"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-muted-foreground">
              API secret {s.has_secret ? <span className="text-primary">· saved</span> : null}
            </label>
            <Input
              type="password"
              value={apiSecret}
              onChange={(e) => setApiSecret(e.target.value)}
              placeholder={s.has_secret ? "Leave blank to keep the saved one" : "Paste the secret"}
              className="mt-1 h-9 font-mono text-xs"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            onClick={() => save.mutate()}
            loading={save.isPending}
            disabled={!apiKey.trim()}
          >
            Save credentials
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="gap-1.5"
            onClick={() => connect.mutate()}
            loading={connect.isPending}
            disabled={!s.api_key || !s.has_secret}
          >
            <ExternalLink className="size-3.5" />
            {s.connected ? "Reconnect" : "Connect to Upstox"}
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
            {s.enabled ? "Turn checks OFF" : "Turn checks ON"}
          </Button>
        </div>

        {(!s.api_key || !s.has_secret) && (
          <p className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
            <Link2 className="mt-0.5 size-3 shrink-0" />
            Create an app at Upstox → Developer → Apps, paste the redirect URL above into
            it, then bring the key and secret back here.
          </p>
        )}

        {s.last_error && (
          <p className="rounded-md bg-destructive/10 px-3 py-2 text-[11px] text-destructive">
            Last error from Upstox: {s.last_error}
          </p>
        )}

        {s.connected && s.last_connected && (
          <p className="text-[11px] text-muted-foreground">
            Connected {new Date(s.last_connected).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}.
            Upstox tokens expire daily — reconnect when a check says the session is gone.
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
