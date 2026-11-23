import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono, Plus_Jakarta_Sans } from "next/font/google";
import { Shell } from "@/components/shell";
import "./globals.css";

// Plus Jakarta Sans: títulos, cifras grandes y la marca (geométrica, sobria). Inter: cuerpo y tablas (muy legible, números parejos).
const display = Plus_Jakarta_Sans({ variable: "--font-display-face", subsets: ["latin"], weight: ["500", "600", "700", "800"] });
const inter = Inter({ variable: "--font-body-face", subsets: ["latin"] });
const mono = JetBrains_Mono({ variable: "--font-mono-face", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "CinnaParleys", template: "%s · CinnaParleys" },
  description: "Análisis de la NFL con datos: ganador, props de jugadores, escalones y parlays con su probabilidad real.",
  applicationName: "CinnaParleys",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f4f1" },
    { media: "(prefers-color-scheme: dark)", color: "#121010" },
  ],
  width: "device-width",
  initialScale: 1,
};

// Aplica el tema guardado antes de pintar (sin parpadeo).
const THEME_INIT = `try{var t=localStorage.getItem("cinna_theme");if(t==="dark"||t==="light")document.documentElement.dataset.theme=t;}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className={`${display.variable} ${inter.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
