"use client";

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { ProfileAPI } from "@/lib/api";
import { useAuthStore } from "@/stores/authStore";

/** Operator: the pink app is for female clients; everyone else gets gold.
 *  `data-gender` on <html> picks the token set in globals.css. The inline
 *  script in the root layout sets it before first paint from the saved user;
 *  this keeps it in step with login / logout, and reads /users/me for sessions
 *  saved before the login payload carried gender (and saves it for next time). */
export function GenderTheme() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: () => ProfileAPI.me(),
    enabled: !!user,
    staleTime: 5 * 60_000,
  });
  const gender = user ? (me?.gender ?? user.gender ?? null) : null;

  useEffect(() => {
    const el = document.documentElement;
    if (gender === "FEMALE") el.setAttribute("data-gender", "FEMALE");
    else el.removeAttribute("data-gender");
  }, [gender]);

  useEffect(() => {
    if (user && me && me.id === user.id && me.gender !== undefined && me.gender !== user.gender) {
      setUser({ ...user, gender: me.gender });
    }
  }, [user, me, setUser]);

  return null;
}
