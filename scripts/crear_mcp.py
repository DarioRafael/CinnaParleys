"""Genera .mcp.json (el conector de Claude) con las rutas de ESTA computadora.

Cada PC tiene su propia ruta, por eso .mcp.json no se sube a GitHub: lo crea instalar.bat.
Uso:  .venv\\Scripts\\python.exe scripts\\crear_mcp.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    py = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not py.exists():
        py = ROOT / ".venv" / "Scripts" / "python.exe"
    cfg = {"mcpServers": {"cerebro-nfl": {"type": "stdio", "command": str(py),
                                          "args": [str(ROOT / "asistente" / "mcp_server.py")], "env": {}}}}
    (ROOT / ".mcp.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print("Conector de Claude listo:", ROOT / ".mcp.json")


if __name__ == "__main__":
    main()
