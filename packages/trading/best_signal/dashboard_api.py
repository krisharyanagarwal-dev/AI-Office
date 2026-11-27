"""FastAPI dashboard server for best-signal execution data."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import StreamingResponse


def create_app(reports_dir: Path) -> FastAPI:
    app = FastAPI(title="Best-Signal Execution Dashboard")
    reports_dir = Path(reports_dir)

    @app.get("/api/execution/fills")
    async def get_fills(
        symbol: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        fills_path = reports_dir / "best_signal_fills.jsonl"
        if not fills_path.exists():
            fills_path = reports_dir / "fills.jsonl"
        if not fills_path.exists():
            return []
        lines = fills_path.read_text().strip().splitlines()
        fills = [json.loads(l) for l in lines]
        if symbol:
            fills = [f for f in fills if f.get("symbol") == symbol]
        return fills[offset:offset + limit]

    @app.get("/api/execution/telemetry")
    async def get_telemetry(
        symbol: Optional[str] = Query(None),
        hours: int = Query(24, ge=1, le=168),
    ):
        telemetry_path = reports_dir / "best_signal_telemetry.jsonl"
        if not telemetry_path.exists():
            telemetry_path = reports_dir / "telemetry.jsonl"
        if not telemetry_path.exists():
            return []
        lines = telemetry_path.read_text().strip().splitlines()
        telemetry = [json.loads(l) for l in lines]
        from datetime import datetime, timezone
        cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
        telemetry = [
            t for t in telemetry
            if datetime.fromisoformat(t.get("cycle_ts", "").replace("Z", "+00:00")).timestamp() >= cutoff
        ]
        if symbol:
            telemetry = [t for t in telemetry if t.get("symbol") == symbol]
        return telemetry

    @app.get("/api/execution/summary")
    async def get_summary(period: str = Query("daily", pattern="^(daily|weekly|monthly)$")):
        summary_path = reports_dir / "execution_summary.json"
        if not summary_path.exists():
            raise HTTPException(404, "Summary not available")
        return json.loads(summary_path.read_text())

    @app.get("/api/report/latest")
    async def get_report():
        report_path = reports_dir / "best_signal_report.json"
        if not report_path.exists():
            raise HTTPException(404, "Report not available")
        return json.loads(report_path.read_text())

    @app.get("/api/execution/fills/stream")
    async def stream_fills(symbol: Optional[str] = Query(None)):
        """SSE stream for live fill updates."""
        async def event_generator():
            fills_path = reports_dir / "best_signal_fills.jsonl"
            if not fills_path.exists():
                fills_path = reports_dir / "fills.jsonl"
            last_pos = 0
            while True:
                if fills_path.exists():
                    content = fills_path.read_text()
                    lines = content.strip().splitlines()[last_pos:]
                    for line in lines:
                        fill = json.loads(line)
                        if not symbol or fill.get("symbol") == symbol:
                            yield f"data: {json.dumps(fill)}\n\n"
                    last_pos = len(content.strip().splitlines())
                await asyncio.sleep(1)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    return app


def main():
    import uvicorn
    import sys
    reports_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "reports" / "best_signal"
    app = create_app(reports_dir)
    uvicorn.run(app, host="0.0.0.0", port=4750)


if __name__ == "__main__":
    main()