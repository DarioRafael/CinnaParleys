"use client";

import { ChatsCircle } from "@phosphor-icons/react";
import { Check, Copy, FolderOpen, MessageSquareText, PlugZap, Terminal } from "lucide-react";
import { useState } from "react";
import { GameCard, useApi } from "@/lib/api";
import { SectionTitle, PageHeader } from "@/components/ui";

function CopyLine({ text, hint }: { text: string; hint?: string }) {
  const [ok, setOk] = useState(false);
  return (
    <button
      onClick={() => { navigator.clipboard?.writeText(text).then(() => { setOk(true); setTimeout(() => setOk(false), 1500); }); }}
      className="group flex w-full items-start gap-3 rounded-xl border border-line bg-s2/50 px-3.5 py-2.5 text-left hover:border-accent"
    >
      <span className="min-w-0 flex-1">
        <span className="block break-all font-mono text-[13px] text-ink">{text}</span>
        {hint && <span className="mt-0.5 block text-xs text-mute">{hint}</span>}
      </span>
      {ok ? <Check size={15} className="mt-0.5 text-good" /> : <Copy size={15} className="mt-0.5 text-mute group-hover:text-ink" />}
    </button>
  );
}

export default function ClaudePage() {
  const { data } = useApi<{ games: GameCard[] }>("/api/week");
  // la carpeta la dice la API (cada PC la tiene en otro lugar)
  const { data: st } = useApi<{ carpeta?: string }>("/api/status");
  const FOLDER = st?.carpeta ?? "la carpeta donde instalaste CinnaParleys";
  const next = (data?.games ?? []).filter((g) => g.status === "pre").slice(0, 3);
  const g0 = next[0];

  return (
    <div className="space-y-6">
      <PageHeader duo={ChatsCircle} tone="rosa" kicker="para entender" title="Pregúntale a Claude">
        <p>
          Claude está conectado a CinnaParleys: puede ver todo lo que ves aquí (simulaciones, jugadores, lesiones, noticias, líneas de
          8 casas y de Playdoit, picks y el backtest) y razonar contigo el partido, armar varios parlays y verificarlos con la
          probabilidad real. Usa tu plan de Claude, <b>sin créditos ni APIs de pago</b>.
        </p>
      </PageHeader>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card p-5">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><FolderOpen size={16} className="text-accent" /> 1. Abre la carpeta</div>
          <p className="text-sm text-ink2">En la app de Claude, pestaña <b>Code</b>, inicia una sesión nueva en la carpeta:</p>
          <div className="mt-2"><CopyLine text={FOLDER} /></div>
        </div>
        <div className="card p-5">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><PlugZap size={16} className="text-accent" /> 2. Aprueba el conector</div>
          <p className="text-sm text-ink2">
            La primera vez Claude te pedirá permiso para usar el conector <b>cerebro-nfl</b> (viene en la carpeta). Acéptalo.
            Si CinnaParleys no está abierta, el conector la enciende sola.
          </p>
        </div>
        <div className="card p-5">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><MessageSquareText size={16} className="text-accent" /> 3. Pregunta</div>
          <p className="text-sm text-ink2">
            Habla normal, como con un amigo que sabe de apuestas. Claude consulta los datos antes de responder y te da
            probabilidad, pago y valor esperado de lo que recomiende.
          </p>
        </div>
      </div>

      <section>
        <SectionTitle>Atajos</SectionTitle>
        <div className="grid gap-2 md:grid-cols-3">
          <CopyLine text="/semana" hint="Resumen de la jornada: favoritos, totales y lo más sólido" />
          <CopyLine text={`/partido ${g0 ? `${g0.away.abbr} vs ${g0.home.abbr}` : "Eagles"}`} hint="Análisis del partido + 3 parlays verificados" />
          <CopyLine text="/parlays presupuesto 500 pesos, líneas de Playdoit" hint="5 parlays de perfiles distintos, con cuánto poner a cada uno" />
        </div>
      </section>

      <section>
        <SectionTitle>Ideas de preguntas</SectionTitle>
        <div className="grid gap-2 md:grid-cols-2">
          {g0 && <CopyLine text={`¿Cómo ves el ${g0.away.name} vs ${g0.home.name}? ¿Quién gana y por qué?`} />}
          {g0 && <CopyLine text={`Ármame 3 parlays del ${g0.away.abbr} vs ${g0.home.abbr} con líneas de Playdoit, uno seguro, uno balanceado y uno arriesgado`} />}
          <CopyLine text="En Draftea tengo Barkley menos de 70.5 yds por tierra a 1.87x y Hurts más de 215.5 yds de pase a 1.85x. ¿Las junto?" />
          <CopyLine text="¿Cuáles son los 5 picks más sólidos de la semana y cuánto le pondrías a cada uno con 1,000 pesos?" />
          <CopyLine text="Quiero un parlay que pague alrededor de 5x con la mayor probabilidad posible" />
          <CopyLine text="¿Qué lesiones de hoy mueven más las líneas y cómo lo aprovecho?" />
          <CopyLine text="¿Qué receptor tiene el mejor partido contra la defensa rival esta semana?" />
          <CopyLine text="¿Qué tan confiable ha sido Cinna? Dame los números reales" />
        </div>
      </section>

      <div className="card flex items-start gap-3 p-4 text-sm text-ink2">
        <Terminal size={18} className="mt-0.5 shrink-0 text-mute" />
        <div>
          También funciona desde la terminal: abre una terminal en la carpeta de CinnaParleys y escribe <code className="rounded bg-s2 px-1.5 py-0.5 text-ink">claude</code>.
          Claude responde con los datos del momento; si quieres lo último, pídele “actualiza los datos”.
        </div>
      </div>
    </div>
  );
}
