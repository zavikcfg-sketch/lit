"""Менеджер массовой рассылки (для админ-панели) с ограничением скорости."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field

from app.services import notifications


@dataclass
class BroadcastJob:
    id: str
    text: str
    rate: float
    total: int
    sent: int = 0
    failed: int = 0
    running: bool = True
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    log: deque = field(default_factory=lambda: deque(maxlen=30))


class BroadcastManager:
    """Одновременная рассылка — только одна. Остальные запуски отклоняются."""

    def __init__(self) -> None:
        self._job: BroadcastJob | None = None
        self._task: asyncio.Task | None = None

    def start(self, text: str, rate: float, chat_ids: list[int]) -> tuple[bool, str]:
        if self._job is not None and self._job.running:
            return False, "Рассылка уже запущена — дождитесь завершения."
        if not chat_ids:
            return False, "Нет получателей."
        job = BroadcastJob(id=time.strftime("%Y%m%d-%H%M%S"), text=text, rate=rate, total=len(chat_ids))
        job.log.append(f"Старт: получателей {len(chat_ids)}, скорость {rate:g} msg/s")
        self._job = job
        self._task = asyncio.create_task(self._run(job, chat_ids))
        return True, "Рассылка запущена."

    async def _run(self, job: BroadcastJob, chat_ids: list[int]) -> None:
        def progress(sent: int, failed: int, total: int) -> None:
            job.sent, job.failed, job.total = sent, failed, total
            if (sent + failed) % 25 == 0:
                job.log.append(f"Прогресс: {sent + failed}/{total} (ошибок: {failed})")

        try:
            sent, failed = await notifications.broadcast(
                job.text, rate_per_sec=job.rate, chat_ids=chat_ids, progress=progress
            )
            job.sent, job.failed = sent, failed
            job.log.append(f"Готово: отправлено {sent}, ошибок {failed}")
        except Exception as exc:  # noqa: BLE001
            job.log.append(f"Аварийное завершение: {type(exc).__name__}: {exc}")
        finally:
            job.running = False
            job.finished_at = time.time()

    def status(self) -> dict:
        job = self._job
        if job is None:
            return {"running": False, "total": 0, "sent": 0, "failed": 0, "percent": 0, "log": []}
        done = job.sent + job.failed
        percent = int(done * 100 / job.total) if job.total else 100
        return {
            "id": job.id,
            "running": job.running,
            "total": job.total,
            "sent": job.sent,
            "failed": job.failed,
            "percent": percent if job.running else 100,
            "log": list(job.log),
        }

    def is_running(self) -> bool:
        return self._job is not None and self._job.running


manager = BroadcastManager()
