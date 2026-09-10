"""Telegram health alerts. Never log tokens, URLs or response bodies."""
import json
import logging
import os
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("avtokliker")
MESSAGES = {
    "auth": "Автокликер: требуется вход в Битрикс24. Приём заявок приостановлен. Обновите файл авторизации и перезапустите службу.",
    "unavailable": "Автокликер: таблица заявок недоступна несколько проверок подряд. Приём приостановлен. Проверьте авторизацию, сеть и журнал службы.",
    "healthy": "Автокликер: доступ к таблице заявок восстановлен. Проверки возобновлены.",
}


def send_telegram(cfg, message):
    options = cfg.get("notify", {})
    token = os.environ.get("AVTOKLIKER_TELEGRAM_BOT_TOKEN") or options.get("telegramBotToken")
    chat = os.environ.get("AVTOKLIKER_TELEGRAM_CHAT_ID") or options.get("telegramChatId")
    if not token or not chat:
        log.warning("Telegram не настроен: нужны токен бота и chat_id")
        return False
    try:
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps({"chat_id": chat, "text": message}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            success = json.load(response).get("ok") is True
        if not success:
            log.warning("Telegram отклонил уведомление")
        return success
    except Exception as exc:
        log.warning("Не удалось отправить уведомление Telegram: %s", type(exc).__name__)
        return False


class HealthAlerts:
    def __init__(self, cfg, sender=send_telegram, clock=time.monotonic):
        self.cfg, self.sender, self.clock = cfg, sender, clock
        path = cfg.get("notify", {}).get("stateFile")
        self.path = Path(path) if path else None
        self.announced = "healthy"
        if self.path and self.path.exists():
            try:
                value = json.loads(self.path.read_text())["announced"]
                if value in MESSAGES:
                    self.announced = value
            except (OSError, ValueError, KeyError):
                log.warning("Не удалось прочитать состояние уведомлений")
        self.pending, self.count, self.next_retry = None, 0, 0

    def observe(self, status):
        if status != self.pending:
            self.pending, self.count = status, 0
        self.count += 1
        if self.count < 3 or status == self.announced or self.clock() < self.next_retry:
            return
        self.next_retry = self.clock() + 300
        if not self.sender(self.cfg, MESSAGES[status]):
            return
        self.announced = status
        if self.path:
            try:
                temporary = self.path.with_suffix(".tmp")
                temporary.write_text(json.dumps({"announced": status}))
                temporary.replace(self.path)
            except OSError:
                log.warning("Не удалось сохранить состояние уведомлений")


if __name__ == "__main__":
    raise SystemExit(0 if send_telegram({}, "Тест: уведомления автокликера подключены.") else 1)
