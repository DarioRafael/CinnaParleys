"use client";

import { Target } from "@phosphor-icons/react";
import clsx from "clsx";
import { Crown, Flame, Gem, ShieldCheck } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { Pick, useApi } from "@/lib/api";
import { PickCard } from "@/components/pick-card";
import { Empty, Loading, Segmented, PageHeader } from "@/components/ui";

type Tier = "segura" | "valor" | "arriesgada" | "todas";
type Kind = "todos" | "ou" | "alt" | "td" | "game";

type BtSel = { n: number; hit: number | null; roi?: number } | null | undefined;
type Bt = { seasons?: { test: number; cur: number }; super_test?: BtSel; super_cur?: BtSel; elite_solo_test?: BtSel; elite_solo_cur?: BtSel };

const pc = (x?: number | null) => (x == null ? "—" : `${Math.round(x * 100)}%`);
const roiTxt = (x: BtSel) => (x?.roi != null ? ` (retorno ${x.roi >= 0 ? "+" : ""}${Math.round(x.roi * 100)}%)` : "");

function info(bt?: Bt): Record<string, { icon: typeof ShieldCheck; title: string; text: string }> {
  const ss = bt?.seasons;
  const hist = (a: BtSel, b: BtSel) => (a && ss
    ? ` Acertaron ${pc(a.hit)} en ${ss.test}${roiTxt(a)}${b?.n ? ` y ${pc(b.hit)} en ${ss.cur}${roiTxt(b)}` : ""} contra líneas de cierre.`
    : "");
  return {
    segura: { icon: ShieldCheck, title: "Seguras", text: `En Más/Menos son los Súper élite: Cinna y el meta-modelo coinciden con más fuerza.${hist(bt?.super_test, bt?.super_cur)} En escaleras y TDs son las muy probables (aciertan ~90%), pero la casa las paga poco: sirven de base para parlays, solas no ganan a la larga.` },
    valor: { icon: Gem, title: "Valor", text: `Picks Élite de Más/Menos: Cinna y el meta-modelo (entrenado con apuestas reales) van del mismo lado.${hist(bt?.elite_solo_test, bt?.elite_solo_cur)} Para ganarle a -110 basta 52.4%.` },
    arriesgada: { icon: Flame, title: "Arriesgadas", text: "Pagan mucho pero fallan seguido: TDs, techos altos, underdogs y tiempo extra. En el backtest no mostraron ventaja a la larga: juégalas con poco." },
  };
}

function PicksInner() {
  const sp = useSearchParams();
  const [tier, setTier] = useState<Tier>((sp.get("tier") as Tier) ?? "segura");
  const [kind, setKind] = useState<Kind>("todos");
  const [sort, setSort] = useState<"confidence" | "prob" | "edge">("confidence");
  const [eliteOnly, setEliteOnly] = useState(sp.get("elite") === "1");
  const { data, isLoading } = useApi<{ picks: Pick[]; counts: Record<string, number>; bt?: Bt }>("/api/picks?limit=500");
  const nElite = (data?.picks ?? []).filter((p) => p.elite).length;

  const list = useMemo(() => {
    let l = data?.picks ?? [];
    if (eliteOnly) l = l.filter((p) => p.elite);
    else if (tier !== "todas") l = l.filter((p) => p.tier === tier);
    if (kind === "game") l = l.filter((p) => p.type === "game");
    else if (kind === "td") l = l.filter((p) => p.kind === "td" || p.kind === "td2");
    else if (kind !== "todos") l = l.filter((p) => p.kind === kind);
    const key = (p: Pick) => (p.super_elite ? 2 : p.elite ? 1 : 0);
    return [...l].sort((a, b) => key(b) - key(a) || (sort === "edge" ? (b.edge ?? -1) - (a.edge ?? -1) : sort === "prob" ? b.prob - a.prob : b.confidence - a.confidence));
  }, [data, tier, kind, sort, eliteOnly]);

  if (isLoading && !data) return <Loading label="Buscando las mejores apuestas…" />;
  const c = data?.counts ?? {};
  const infoBox = tier !== "todas" ? info(data?.bt)[tier] : null;

  return (
    <div className="space-y-5">
      <PageHeader duo={Target} tone="rosa" kicker="la jornada" title="Picks">
        <p>Cada línea de 8 casas evaluada por Cinna (modelo + mercado + expertos), con el mejor precio disponible y su valor esperado. Si la línea de Draftea es distinta, usa la calculadora del jugador.</p>
      </PageHeader>
      <div className="flex flex-wrap items-center gap-3">
        <Segmented value={tier} onChange={setTier} options={[
          { value: "segura", label: "Seguras", count: c.segura ?? 0 },
          { value: "valor", label: "Valor", count: c.valor ?? 0 },
          { value: "arriesgada", label: "Arriesgadas", count: c.arriesgada ?? 0 },
          { value: "todas", label: "Todas" },
        ]} />
        <Segmented value={kind} onChange={setKind} options={[
          { value: "todos", label: "Todo" }, { value: "ou", label: "Más/Menos" }, { value: "alt", label: "Al menos X" },
          { value: "td", label: "Touchdowns" }, { value: "game", label: "Partido" },
        ]} />
        <button onClick={() => setEliteOnly((x) => !x)}
          className={clsx("inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-semibold",
            eliteOnly ? "border-warning bg-[var(--warning)]/15 text-warning" : "border-line text-ink2 hover:text-ink")}>
          <Crown size={15} /> Solo Élite <span className="rounded-md bg-page/60 px-1.5 text-[11px] tnum">{nElite}</span>
        </button>
        <select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}
          className="rounded-lg border border-line bg-s1 px-3 py-2 text-sm text-ink2 outline-none">
          <option value="confidence">Ordenar: confianza</option>
          <option value="prob">Ordenar: probabilidad</option>
          <option value="edge">Ordenar: ventaja vs línea</option>
        </select>
      </div>
      {infoBox && (
        <div className="card flex items-start gap-3 px-4 py-3">
          <infoBox.icon size={18} className="mt-0.5 shrink-0 text-ink2" />
          <div className="text-sm text-ink2"><b className="text-ink">{infoBox.title}:</b> {infoBox.text}</div>
        </div>
      )}
      {list.length ? (
        <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">{list.map((p) => <PickCard key={p.pick_id} p={p} />)}</div>
      ) : (
        <Empty>No hay picks con este filtro todavía. Las casas publican las props de cada jugador unos días antes del partido.</Empty>
      )}
    </div>
  );
}

export default function PicksPage() {
  return <Suspense fallback={<Loading />}><PicksInner /></Suspense>;
}
