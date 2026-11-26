"""Servidor HTTP local para la interfaz web del simulador."""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from simulation import (
    MONTE_CARLO_THREAT_COUNTS,
    SimulationConfig,
    prepare_monte_carlo,
    run_monte_carlo,
    run_simulation,
)


WEB_ROOT = Path(__file__).resolve().parent / "web"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
MAX_REQUEST_BYTES = 1_000_000
MAX_WEB_WORK_UNITS = 1_000_000
MAX_WEB_MONTE_CARLO_WORK_UNITS = 20_000_000
SIMULATION_SLOTS = threading.BoundedSemaphore(2)


class SimulationHandler(BaseHTTPRequestHandler):
    """Sirve archivos estáticos y conecta el formulario con el motor Python."""

    def do_GET(self) -> None:
        route = urlsplit(self.path).path
        if route not in STATIC_FILES:
            self.send_error(404, "Ruta no encontrada.")
            return
        filename, content_type = STATIC_FILES[route]
        content = (WEB_ROOT / filename).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        route = urlsplit(self.path).path
        if route not in {"/api/simulate", "/api/monte-carlo"}:
            self._send_json(404, {"error": "Ruta no encontrada."})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Content-Length inválido."})
            return
        if content_length <= 0:
            self._send_json(400, {"error": "El cuerpo debe contener un objeto JSON."})
            return
        if content_length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "El payload supera el límite de 1 MB."})
            return
        try:
            payload = json.loads(self.rfile.read(content_length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "El cuerpo no contiene JSON válido."})
            return
        try:
            if route == "/api/monte-carlo":
                config, runs = prepare_monte_carlo(payload)
                work_units = (
                    runs
                    * config.duration_s
                    / config.dt_s
                    * sum(MONTE_CARLO_THREAT_COUNTS)
                )
                max_work_units = MAX_WEB_MONTE_CARLO_WORK_UNITS
            else:
                config = SimulationConfig.from_payload(payload)
                work_units = config.duration_s / config.dt_s * config.threat_count
                max_work_units = MAX_WEB_WORK_UNITS
            if work_units > max_work_units:
                raise ValueError(
                    "Esta interfaz limita el trabajo por solicitud; reduce duración, "
                    "número de corridas, número de amenazas o paso de integración."
                )
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
            return
        if not SIMULATION_SLOTS.acquire(blocking=False):
            self._send_json(503, {"error": "El simulador está ocupado; inténtalo de nuevo en unos segundos."})
            return
        stream_progress = (
            route == "/api/monte-carlo"
            and "application/x-ndjson" in self.headers.get("Accept", "").lower()
        )
        if stream_progress:
            try:
                self._stream_monte_carlo(payload, runs)
            finally:
                SIMULATION_SLOTS.release()
            return
        try:
            result = (
                run_monte_carlo(payload)
                if route == "/api/monte-carlo"
                else run_simulation(payload)
            )
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
            return
        finally:
            SIMULATION_SLOTS.release()
        self._send_json(200, result)

    def _stream_monte_carlo(self, payload: dict[str, object], runs: int) -> None:
        self._send_ndjson_headers()
        total_runs = runs * len(MONTE_CARLO_THREAT_COUNTS)
        self._send_ndjson(
            {
                "type": "progress",
                "completed": 0,
                "total": total_runs,
                "threat_count": None,
            }
        )
        try:
            result = run_monte_carlo(
                payload,
                progress_callback=lambda completed, total, threat_count: self._send_ndjson(
                    {
                        "type": "progress",
                        "completed": completed,
                        "total": total,
                        "threat_count": threat_count,
                    }
                ),
            )
        except ValueError as error:
            self._send_ndjson({"type": "error", "error": str(error)})
            return
        self._send_ndjson({"type": "result", "result": result})

    def _send_ndjson_headers(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    def _send_ndjson(self, payload: dict[str, object]) -> None:
        content = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.wfile.write(content + b"\n")
        self.wfile.flush()

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        content = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Interfaz web del simulador naval.")
    parser.add_argument("--host", default="127.0.0.1", help="Dirección de escucha local.")
    parser.add_argument("--port", type=int, default=8000, help="Puerto HTTP.")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), SimulationHandler)
    print(f"Interfaz disponible en http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
