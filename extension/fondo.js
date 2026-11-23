// Cinna · fondo: manda cada partido a CinnaParleys (la API en tu compu). El número en el ícono = partidos enviados.
const APIS = ["http://127.0.0.1:8765", "http://localhost:8765"];
const vistos = new Set();

async function enviar(m) {
  for (const base of APIS) {
    try {
      const r = await fetch(`${base}/api/playdoit/captura`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: m.url, texto: m.txt }),
      });
      if (!r.ok) continue;
      const j = await r.json();
      if (j.guardado && j.tipo === "partido") {
        vistos.add(j.partido);
        chrome.action.setBadgeBackgroundColor({ color: "#2e9d5b" });
        chrome.action.setBadgeText({ text: String(vistos.size) });
        chrome.action.setTitle({ title: `Cinna: ${vistos.size} partido(s) enviados. Último: ${j.partido}` });
      }
      return;
    } catch (e) { /* probar la otra dirección */ }
  }
  chrome.action.setBadgeBackgroundColor({ color: "#d64550" });
  chrome.action.setBadgeText({ text: "!" });
  chrome.action.setTitle({ title: "Cinna: la app no está abierta (inicia CinnaParleys)" });
}

chrome.runtime.onMessage.addListener((m) => {
  if (m && m.tipo === "captura" && typeof m.txt === "string") enviar(m);
});
