"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { MarketwatchAPI } from "@/lib/api";
import { setSpecialSessions } from "@/lib/marketHours";

/** Keeps lib/marketHours in step with today's special sessions (Muhurat), so
 *  the buy / sell / exit buttons open exactly when the server will accept. */
export function SpecialSessionsSync() {
  const { data } = useQuery({
    queryKey: ["special-sessions"],
    queryFn: MarketwatchAPI.specialSessions,
    refetchInterval: 5 * 60_000,
    staleTime: 60_000,
  });
  useEffect(() => {
    if (data) setSpecialSessions(data);
  }, [data]);
  return null;
}
