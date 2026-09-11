"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { ShieldCheck } from "lucide-react";
import { useAdminAuthStore } from "@/stores/authStore";
import { ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { BrandLogo } from "@/components/layout/BrandLogo";
import { InstallPWAButton } from "@/components/pwa/InstallPWAButton";

const schema = z.object({
  identifier: z.string().min(3, "Enter your admin email or user code"),
  password: z.string().min(8, "Minimum 8 characters"),
});
type FormValues = z.infer<typeof schema>;

export default function AdminLoginPage() {
  const router = useRouter();
  const login = useAdminAuthStore((s) => s.login);
  // `?install=1` used to mean the broker app, which now has its own page.
  // Forward any old link (a cached website, a shared message) there.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("install") === "1") {
      router.replace("/broker/login?install=1");
    }
  }, [router]);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { identifier: "", password: "" },
  });

  async function onSubmit(values: FormValues) {
    try {
      // `portal: "admin"` — brokers are refused here server-side and pointed
      // to the broker login, which is a separate page and a separate app.
      await login(values.identifier, values.password, undefined, "admin");
      toast.success("Authenticated");
      router.push("/dashboard");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Login failed");
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-background p-6">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-3">
          <BrandLogo href={null} size="md" showAdminBadge={false} />
          <div className="inline-flex w-fit items-center gap-2 rounded-md bg-destructive/10 px-2 py-1 text-xs uppercase tracking-wider text-destructive">
            <ShieldCheck className="size-3" />
            Restricted access · Admins only
          </div>
          <CardTitle className="text-2xl">Admin Login</CardTitle>
          <CardDescription>
            StockEx control panel — sign in with your admin credentials.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="identifier">Admin email or user code</Label>
              <Input id="identifier" autoComplete="username" {...form.register("identifier")} />
              {form.formState.errors.identifier && (
                <p className="text-xs text-destructive">{form.formState.errors.identifier.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" autoComplete="current-password" {...form.register("password")} />
              {form.formState.errors.password && (
                <p className="text-xs text-destructive">{form.formState.errors.password.message}</p>
              )}
            </div>
            <Button type="submit" className="w-full" loading={form.formState.isSubmitting}>
              Sign in
            </Button>
            <p className="text-xs text-muted-foreground">
              Activity is logged. IP allow-listing and rate-limiting are enforced server-side.
            </p>
          </form>

          {/* The ADMIN app. The broker app is a separate install from its own
              page — both can sit on one phone. */}
          <div className="mt-5 space-y-3 rounded-xl border border-border p-3">
            <div className="flex items-center gap-3">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/icon-192.png"
                alt="StockEx Admin app"
                width={48}
                height={48}
                className="size-12 shrink-0 rounded-xl"
              />
              <div className="min-w-0">
                <div className="text-sm font-semibold">StockEx Admin app</div>
                <p className="text-[11px] leading-snug text-muted-foreground">
                  One-tap home-screen launcher. Stays signed in like a native app.
                </p>
              </div>
            </div>
            <InstallPWAButton />
          </div>

          <p className="mt-4 text-center text-xs text-muted-foreground">
            Broker?{" "}
            <Link href="/broker/login" className="font-medium text-primary underline-offset-4 hover:underline">
              Sign in at the broker login
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
