"""
Avtokliker — автоприём заявок партнёрского приложения Битрикс24.

Принцип: повторяем реальные запросы браузера, скопированные из DevTools
(PKM по запросу в Network → Copy → Copy as cURL). Сохрани их:
  curl/list.txt   — запрос списка заявок (synchronizeQualificationDataStartGrid)
  curl/accept.txt — запрос принятия заявки (ловится при клике «Принять заявку»)

Режимы: dryRun=true — только сообщаем о подходящих заявках;
        dryRun=false — принимаем (подставляем ID заявки в accept-запрос).

Только стандартная библиотека Python.
"""

import json
import logging
import re
import shlex
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
SEEN_PATH = ROOT / "seen.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("avtokliker")

HOP_BY_HOP = {"content-length", "host", "connection"}


@dataclass
class Lead:
    id: str
    title: str
    city: str = ""
    direction: str = ""
    slots_free: bool = True
    raw: dict[str, Any] = field(default_factory=dict)

    def matches(self, include: list[str], exclude: list[str]) -> bool:
        text = f"{self.title} {self.direction}".lower()
        if any(k.lower() in text for k in exclude):
            return False
        if not include:
            return True
        return any(k.lower() in text for k in include)


@dataclass
class CurlRequest:
    method: str
    url: str
    headers: dict[str, str]
    data: str | None  # сырой POST body (form-encoded или json)


def parse_curl(path: Path) -> CurlRequest:
    """Разобрать файл с cURL-командой, скопированной из Chrome DevTools."""
    text = path.read_text(encoding="utf-8").strip()
    text = text.replace("\\\n", " ")  # склейка многострочного cURL
    tokens = shlex.split(text)
    if not tokens or tokens[0] != "curl":
        sys.exit(f"{path.name}: ожидается команда curl (Copy as cURL из DevTools)")

    method = "GET"
    url = ""
    headers: dict[str, str] = {}
    data_parts: list[str] = []

    i = 1
    while i < len(tokens):
        t = tokens[i]
        if t in ("-X", "--request"):
            method = tokens[i + 1].upper()
            i += 2
        elif t in ("-H", "--header"):
            name, _, value = tokens[i + 1].partition(":")
            name = name.strip().lower()
            if name not in HOP_BY_HOP:
                headers[name] = value.strip()
            i += 2
        elif t in ("--data-raw", "--data", "--data-binary", "--data-ascii", "-d"):
            data_parts.append(tokens[i + 1])
            i += 2
        elif t in ("--compressed", "-s", "-i", "-L", "--insecure", "-k") or t.startswith("--"):
            # флаги без значения / неизвестные одиночные флаги — пропускаем флаг
            i += 1
        elif t.startswith("http"):
            url = t
            i += 1
        else:
            i += 1

    data = "&".join(data_parts) if data_parts else None
    if data and method == "GET":
        method = "POST"
    if not url:
        sys.exit(f"{path.name}: не нашёл URL в cURL")
    return CurlRequest(method=method, url=url, headers=headers, data=data)


def execute(req: CurlRequest, timeout: int = 20) -> bytes:
    body = req.data.encode("utf-8") if req.data else None
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        **req.headers,
    }
    request = urllib.request.Request(req.url, data=body, headers=headers, method=req.method)
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return resp.read()


def parse_leads(payload: bytes) -> list[Lead]:
    """Вытащить заявки из ответа Битрикса. Структуру уточняем по реальному ответу."""
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        log.error("Ответ не JSON (%d байт): %.200s", len(payload), payload[:200])
        return []

    # типичная обёртка bx ajax.php: {"status": "success", "data": {...}}
    inner = data.get("data", data)

    rows = None
    for key in ("items", "rows", "leads", "works", "list", "ITEMS", "ROWS"):
        if isinstance(inner, dict) and isinstance(inner.get(key), list):
            rows = inner[key]
            break
    if rows is None and isinstance(inner, list):
        rows = inner
    if rows is None:
        log.warning("Не нашёл массив заявок в ответе. Ключи: %s",
                    list(inner.keys()) if isinstance(inner, dict) else type(inner).__name__)
        return []

    leads = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        flat = _flatten(row)
        lead_id = str(_first(flat, "id", "ID", "workId", "WORK_ID", "leadId", "LEAD_ID") or "")
        if not lead_id:
            continue
        title = str(_first(flat, "title", "TITLE", "description", "DESCRIPTION",
                           "name", "NAME", "opisanie") or "")
        city = str(_first(flat, "city", "CITY", "gorod") or "")
        direction = str(_first(flat, "direction", "DIRECTION", "napravlenie") or "")
        details = str(_first(flat, "details", "DETAILS", "podrobnosti", "statusText") or "")
        slots_free = "нет свободных мест" not in details.lower()
        leads.append(Lead(id=lead_id, title=title, city=city,
                          direction=direction, slots_free=slots_free, raw=row))
    return leads


def _flatten(d: dict, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        out[key] = v
        if isinstance(v, dict):
            out.update(_flatten(v, f"{key}."))
    return out


def _first(flat: dict, *names: str) -> Any:
    lower_map = {k.lower(): v for k, v in flat.items()}
    for name in names:
        if name in flat and flat[name] not in (None, ""):
            return flat[name]
        if name.lower() in lower_map and lower_map[name.lower()] not in (None, ""):
            return lower_map[name.lower()]
    return None


def build_accept_request(template: CurlRequest, lead: Lead) -> CurlRequest:
    """Подставить ID заявки в сохранённый accept-запрос (URL, query и body)."""
    url = template.url
    data = template.data

    known_ids = _candidate_ids(template)
    replaced = False
    for old_id in known_ids:
        if old_id and old_id != lead.id and old_id in (url + (data or "")):
            url = url.replace(old_id, lead.id)
            data = data.replace(old_id, lead.id) if data else data
            replaced = True
    if not replaced and data:
        # запасной вариант: добавить id параметром
        sep = "&" if data else ""
        data = f"{data}{sep}id={urllib.parse.quote(lead.id)}"
    return CurlRequest(method=template.method, url=url,
                       headers=template.headers, data=data)


def _candidate_ids(req: CurlRequest) -> list[str]:
    """Найти числовые значения в body/URL accept-запроса — кандидаты на ID заявки."""
    ids = []
    for source in (req.data or "", urllib.parse.urlparse(req.url).query):
        for value in re.findall(r"(?:^|[=&\"':])(\d{3,})(?=[&\"']|$)", source):
            ids.append(value)
    return ids


def notify(cfg: dict, text: str) -> None:
    tg = cfg.get("notify", {})
    token, chat_id = tg.get("telegramBotToken"), tg.get("telegramChatId")
    if not token or not chat_id:
        return
    try:
        payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload, headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:
        log.warning("Telegram notify failed: %s", e)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit("Нет config.json — заполни по docs/recon.md")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_seen() -> set[str]:
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text(encoding="utf-8")))
    return set()


def save_seen(seen: set[str]) -> None:
    SEEN_PATH.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2), encoding="utf-8")


def run() -> None:
    cfg = load_config()
    list_file = ROOT / cfg.get("listCurlFile", "curl/list.txt")
    accept_file = ROOT / cfg.get("acceptCurlFile", "curl/accept.txt")

    if not list_file.exists():
        sys.exit(f"Нет {list_file} — скопируй запрос списка из DevTools (Copy as cURL)")

    list_req = parse_curl(list_file)
    accept_req = parse_curl(accept_file) if accept_file.exists() else None

    interval = cfg.get("pollIntervalSec", 10)
    inc = cfg.get("keywords", {}).get("include", [])
    exc = cfg.get("keywords", {}).get("exclude", [])
    dry = cfg.get("dryRun", True)

    seen = load_seen()
    mode = "DRY-RUN (не принимаю)" if dry else ("AUTO" if accept_req else "AUTO, но нет curl/accept.txt!")
    log.info("Старт. Режим: %s. Интервал: %ss. Include: %s Exclude: %s", mode, interval, inc, exc)

    auth_fail_count = 0
    while True:
        try:
            payload = execute(list_req)
            leads = parse_leads(payload)
            auth_fail_count = 0

            fresh = [lead for lead in leads if lead.id not in seen]
            for lead in fresh:
                seen.add(lead.id)
                if not lead.slots_free:
                    log.info("Пропуск %s (нет мест): %s", lead.id, lead.title)
                    continue
                if not lead.matches(inc, exc):
                    log.info("Пропуск %s (по словам): %s", lead.id, lead.title)
                    continue
                msg = f"Подходящая заявка: [{lead.id}] {lead.title} — {lead.city}"
                log.info(msg)
                notify(cfg, msg)
                if not dry and accept_req:
                    req = build_accept_request(accept_req, lead)
                    try:
                        resp = execute(req)
                        log.info("Принял %s. Ответ: %.200s", lead.id, resp.decode("utf-8", "replace"))
                        notify(cfg, f"ПРИНЯЛ заявку [{lead.id}] {lead.title}")
                    except urllib.error.HTTPError as e:
                        log.error("Accept %s failed: HTTP %s — %.200s",
                                  lead.id, e.code, e.read().decode("utf-8", "replace"))
            save_seen(seen)

        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                auth_fail_count += 1
                log.error("HTTP %s — похоже, протух sessid/cookies. Пересохрани curl/*.txt (%d/3)",
                          e.code, auth_fail_count)
                if auth_fail_count >= 3:
                    notify(cfg, "Avtokliker: протухла авторизация, пересохрани cURL из DevTools")
                    auth_fail_count = 0
            else:
                log.error("HTTP %s: %s", e.code, e.reason)
        except urllib.error.URLError as e:
            log.error("Сеть: %s", e.reason)
        except Exception:
            log.exception("Неожиданная ошибка в цикле")

        time.sleep(interval)


if __name__ == "__main__":
    run()
