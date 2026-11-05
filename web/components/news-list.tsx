"use client";

import clsx from "clsx";
import { ExternalLink } from "lucide-react";
import { ago } from "@/lib/api";
import { Empty } from "./ui";

export type NewsItem = {
  news_id: string; source: string; tier: number; tier_label: string; published_at: string; title: string; url: string;
  summary?: string; players?: { player_id: string; name: string; team: string }[];
  events?: { label: string; player_id: string; type: string }[];
};

export function NewsList({ items, showEvents = false }: { items: NewsItem[]; showEvents?: boolean }) {
  if (!items.length) return <Empty>Sin noticias recientes.</Empty>;
  return (
    <div className="card divide-y divide-[var(--border)]">
      {items.map((n) => (
        <a key={n.news_id} href={n.url} target="_blank" rel="noopener noreferrer" className="flex items-start gap-3 px-4 py-3 hover:bg-s2">
          <span className={clsx("mt-0.5 w-16 shrink-0 rounded-md px-1.5 py-0.5 text-center text-[10px] font-semibold",
            n.tier <= 1 ? "bg-good-soft text-good" : n.tier === 2 ? "bg-accent-soft text-accent" : "bg-s3 text-ink2")}>{n.tier_label}</span>
          <div className="min-w-0 flex-1">
            <div className="text-sm leading-snug">{n.title}</div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-mute">
              <span>{n.source} · {ago(n.published_at)}</span>
              {showEvents && n.events && n.events.length > 0 && Array.from(new Set(n.events.map((e) => e.label))).slice(0, 3).map((l) => (
                <span key={l} className="rounded bg-serious-soft px-1.5 py-px text-[10px] font-semibold text-serious">{l}</span>
              ))}
            </div>
          </div>
          <ExternalLink size={13} className="mt-1 shrink-0 text-mute" />
        </a>
      ))}
    </div>
  );
}
