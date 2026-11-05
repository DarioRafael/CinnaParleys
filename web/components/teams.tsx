"use client";

import { useMemo } from "react";
import { Team, useApi } from "@/lib/api";

/** Mapa abreviatura → metadatos del equipo (logo, nombre, color). */
export function useTeams(): Record<string, Team> {
  const { data } = useApi<{ teams: (Team & { ranks: unknown })[] }>("/api/teams", { revalidateOnFocus: false });
  return useMemo(() => Object.fromEntries((data?.teams ?? []).map((t) => [t.abbr, t])), [data]);
}
