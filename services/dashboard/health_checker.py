"""Health checker: probes Docker containers, Ollama, and Postgres connectivity."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import urllib.request
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


async def check_docker_containers() -> list[dict[str, Any]]:
    """Run `docker ps` and return a service dict per running container."""
    services: list[dict[str, Any]] = []
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            name = parts[0] if parts else "unknown"
            status = parts[1] if len(parts) > 1 else "unknown"
            ports = parts[2] if len(parts) > 2 else ""
            running = "Up" in status
            services.append({
                "name": name,
                "status": "ok" if running else "error",
                "detail": f"{status} {ports}".strip(),
                "type": "docker",
            })
    except Exception as exc:
        logger.warning("docker ps failed: %s", exc)
        services.append({
            "name": "docker",
            "status": "error",
            "detail": str(exc),
            "type": "docker",
        })
    return services


async def check_ollama() -> dict[str, Any]:
    """Probe Ollama /api/tags endpoint."""
    try:
        resp = await asyncio.to_thread(
            urllib.request.urlopen,
            "http://localhost:11434/api/tags",
            timeout=3,
        )
        data = json.loads(resp.read())
        model_count = len(data.get("models", []))
        return {
            "name": "ollama",
            "status": "ok",
            "detail": f"{model_count} model(s) loaded",
            "type": "service",
        }
    except Exception as exc:
        return {
            "name": "ollama",
            "status": "error",
            "detail": str(exc),
            "type": "service",
        }


async def check_postgres(pool: asyncpg.Pool) -> dict[str, Any]:
    """Verify Postgres pool connectivity with a trivial query."""
    try:
        await pool.fetchval("SELECT 1")
        return {"name": "postgres", "status": "ok", "detail": "Connected", "type": "service"}
    except Exception as exc:
        return {"name": "postgres", "status": "error", "detail": str(exc), "type": "service"}


async def get_all_health(pool: asyncpg.Pool | None) -> list[dict[str, Any]]:
    """Aggregate health checks: Docker + Ollama + Postgres (concurrent)."""
    docker_task = asyncio.create_task(check_docker_containers())
    ollama_task = asyncio.create_task(check_ollama())

    docker_results, ollama_result = await asyncio.gather(docker_task, ollama_task)

    services: list[dict[str, Any]] = list(docker_results)
    services.append(ollama_result)

    if pool is not None:
        pg_result = await check_postgres(pool)
        services.append(pg_result)
    else:
        services.append({
            "name": "postgres",
            "status": "error",
            "detail": "Pool not initialised",
            "type": "service",
        })

    return services
