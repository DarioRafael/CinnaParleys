"use client";

import { Cards } from "@phosphor-icons/react";
import { pct, useApi } from "@/lib/api";
import { ArmadosConBoton, ArmadosResp, JuntarPartidos, LineasCasa } from "@/components/armados";
import { PageHeader } from "@/components/ui";
import { ConectaTuCasa } from "@/components/enviar-cinna";

const PERFIL_TXT: Record<string, string> = { seguro: "Seguro", partido: "Del partido", menos: "Partido cerrado", guion: "Si gana el favorito",
  balanceado: "Balanceado", buen_pago: "Buen pago", juego_grande: "Juego grande" };

export default function ArmadosPage() {
  const { data } = useApi<ArmadosResp>("/api/armados");
  const rec = Object.entries(data?.record ?? {});
  return (
    <div className="space-y-6">
      <PageHeader duo={Cards} tone="miel" kicker="a jugar" title="Parlays armados">
        <p>
          Por partido, varias opciones listas: <b>Seguro</b>, <b>Del partido</b> (quién gana o por cuánto, puntos, touchdowns y
          goles de campo), <b>Partido cerrado</b> (con «Menos»), <b>Si gana el favorito</b>, <b>Balanceado</b> y <b>Buen pago</b>.
          Toca cada pata para ver por qué está, qué la ayuda, qué la complica y en qué caso se cae. Respetan la regla de Draftea
          (una sola Más/Menos de jugador por partido).
        </p>
      </PageHeader>
      {rec.length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="self-center font-semibold text-ink2">Récord real:</span>
          {rec.map(([k, v]) => (
            <span key={k} className="rounded-lg bg-s2 px-2.5 py-1.5">
              {PERFIL_TXT[k] ?? k}: <b className="tnum">{v.salieron}/{v.n}</b> ({pct(v.acierto)}; decía {pct(v.decia)}) ·
              retorno {v.retorno_por_peso >= 0 ? "+" : ""}{pct(v.retorno_por_peso)}
            </span>
          ))}
        </div>
      )}
      <ConectaTuCasa />
      <LineasCasa />
      <JuntarPartidos />
      <ArmadosConBoton />
    </div>
  );
}
