// Cinna · puente: recibe la copia que hizo escucha.js en esta misma página y se la pasa a fondo.js.
window.addEventListener("message", (e) => {
  if (e.source !== window || !e.data || e.data.__cinna__ !== true) return;
  try { chrome.runtime.sendMessage({ tipo: "captura", url: e.data.url, txt: e.data.txt }); } catch (err) { /* extensión recargada */ }
});
