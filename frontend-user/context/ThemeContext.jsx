"use client";

// Shim over next-themes (already provided at the app root) that exposes the
// same API the ported Stockex landing components expect.
import { useEffect, useState } from "react";
import { useTheme as useNextTheme } from "next-themes";

export function useTheme() {
  const { theme, resolvedTheme, setTheme } = useNextTheme();
  // The server can't know the visitor's theme, so it renders "light". Report
  // "light" until mounted too, so the first client render matches the server
  // HTML (else a dark visitor's Sun icon vs the server's Moon icon is a
  // hydration error), then switch to the real theme.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const active = mounted ? resolvedTheme || theme || "light" : "light";
  const isDark = active === "dark";
  return {
    theme: active,
    isDark,
    toggleTheme: () => setTheme(isDark ? "light" : "dark"),
    setDarkTheme: () => setTheme("dark"),
    setLightTheme: () => setTheme("light"),
    setTheme,
  };
}

// next-themes provider lives at the app root, so this is a pass-through.
export function ThemeProvider({ children }) {
  return children;
}

export default ThemeProvider;
