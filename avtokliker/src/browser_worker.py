"""Poll the rendered application, including its cross-origin iframe."""

import logging
import math
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("avtokliker")
ROOT = Path(__file__).resolve().parent.parent


def column_headers(frame, column_title):
    title = re.compile(r"^\s*" + r"\s+".join(
        re.escape(word.lower().replace("ё", "е")).replace("е", "[её]")
        for word in column_title.split()) + r"\s*$", re.IGNORECASE)
    return frame.locator("th, td.main-grid-cell-head, [role=columnheader]").filter(has_text=title)


def page_health(page, host, column_title):
    for frame in page.frames:
        parsed = urlparse(frame.url)
        if parsed.hostname in ("auth2.bitrix24.by", "auth.bitrix24.by", "auth2.bitrix24.ru"):
            return "auth"
        if frame.locator('input[type="password"]:visible').count():
            return "auth"
    for frame in page.frames:
        if urlparse(frame.url).hostname == host:
            headers = column_headers(frame, column_title)
            if any(header.is_visible() for header in headers.all()):
                return "healthy"
    return "unavailable"


def column_controls(frame, column_title):
    """Find controls by table column, never by their caption or screen position."""
    headers = column_headers(frame, column_title)
    if not headers.count():
        log.warning("Целевая колонка «%s» не найдена в документе приложения", column_title)
    else:
        log.info("Найдена целевая колонка «%s»", column_title)
    controls = []
    for header in headers.all():
        # A merged header cannot unambiguously identify the target column.
        index = header.evaluate("""el => {
            const cells = Array.from(el.parentElement.children);
            if (cells.some(c => Number(c.getAttribute('colspan') || 1) !== 1)) return -1;
            return cells.indexOf(el);
        }""")
        if index < 0:
            continue
        table = header.locator("xpath=ancestor::*[self::table or @role='grid' or @role='table'][1]")
        rows = table.locator(":scope > tbody > tr, :scope > tr, :scope > [role=row], :scope > [role=rowgroup] > [role=row]")
        for row in rows.all():
            cells = row.locator(":scope > td, :scope > [role=cell], :scope > [role=gridcell]")
            if cells.count() <= index:
                continue
            if cells.evaluate_all("els => els.some(el => Number(el.getAttribute('colspan') || 1) !== 1 || Number(el.getAttribute('rowspan') || 1) !== 1)"):
                continue
            controls.extend(cells.nth(index).locator(
                'button, input[type=button], input[type=submit], [role=button], '
                'a[href], a[onclick], .ui-btn, .webform-small-button'
            ).element_handles())
    return controls


def scan_page(page, host, column_title="Предложения партнёров", dry_run=False):
    """Click each visible enabled matching control once per scan.

    Element handles deliberately retain identity if rows disappear after a click.
    A successful click is not treated as confirmation of server acceptance.
    """
    from playwright.sync_api import Error

    clicks = 0
    frames = [frame for frame in page.frames if urlparse(frame.url).hostname == host]
    if not frames:
        log.warning("Не найдено приложение %s. Проверьте вход и вкладку «Заявки».", host)
    for frame in frames:
        controls = column_controls(frame, column_title)
        for control in controls:
            try:
                if not control.is_visible() or not control.is_enabled():
                    continue
                if control.evaluate("el => !!el.closest('[aria-disabled=true], [disabled], .ui-btn-disabled, .webform-small-button-disabled')"):
                    continue
                if dry_run:
                    log.info("DRY-RUN: найдена доступная кнопка заявки")
                    continue
                control.click(timeout=3000)
                clicks += 1
                log.info("Нажата кнопка заявки; результат приёма проверяйте в приложении")
                page.wait_for_timeout(500)
            except Error as exc:
                log.warning("Кнопка исчезла или недоступна: %s", type(exc).__name__)
    return clicks


def run_browser(cfg):
    from alerts import HealthAlerts
    health_alerts = HealthAlerts(cfg)
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        raise SystemExit("Установите зависимости: pip install -r requirements.txt")

    options = cfg.get("browser", {})
    interval = float(cfg.get("pollIntervalSec", 10))
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("pollIntervalSec должен быть положительным числом")
    column_title = options.get("columnTitle", "Предложения партнёров")
    if not isinstance(column_title, str) or not column_title.strip():
        raise ValueError("browser.columnTitle должен содержать заголовок колонки")
    host = options.get("frameHost", "util.1c-bitrix.by")
    url = options.get("appUrl", "https://crmby.bitrix24.by/marketplace/app/60/")
    login_only = os.environ.get("AVTOKLIKER_LOGIN") == "1"
    state_path = options.get("storageStatePath")
    export_path = os.environ.get("AVTOKLIKER_EXPORT_STATE")
    if state_path and not login_only and not Path(state_path).is_file():
        raise SystemExit("Нет файла авторизации. Сначала выполните вход и загрузите storage-state.json.")
    headless = options.get("headless", False) and not login_only
    profile = Path(options.get("profileDir", str(ROOT / "browser-profile")))
    profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = None
        if state_path and not login_only:
            browser = pw.chromium.launch(channel=options.get("channel", "msedge"), headless=headless)
            context = browser.new_context(storage_state=state_path)
        else:
            context = pw.chromium.launch_persistent_context(
                str(profile), channel=options.get("channel", "msedge"), headless=headless,
            )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Error:
                if login_only or options.get("interactive", True):
                    raise
                log.warning("Начальная загрузка не удалась; повторим в цикле")
            if login_only or options.get("interactive", True):
                input("Войдите в браузере и откройте «Заявки». Нажмите Enter здесь для продолжения: ")
            if login_only:
                if export_path:
                    context.storage_state(path=export_path, indexed_db=True)
                    log.info("Файл авторизации сохранён. Не добавляйте его в Git.")
                log.info("Профиль сохранён. Режим входа завершён без нажатий.")
                return
            log.info("Проверка каждые %s секунд. Режим: %s. Остановка: Ctrl+C.",
                     interval, "DRY-RUN" if cfg.get("dryRun", False) else "AUTO")
            while not page.is_closed():
                started = time.monotonic()
                try:
                    if urlparse(page.url).hostname != urlparse(url).hostname:
                        page.goto(url, wait_until="load", timeout=20000)
                    else:
                        page.reload(wait_until="load", timeout=20000)
                    page.wait_for_timeout(options.get("settleMs", 2000))
                    health = page_health(page, host, column_title)
                    health_alerts.observe(health)
                    count = 0
                    if health == "healthy":
                        count = scan_page(page, host, column_title, cfg.get("dryRun", False))
                    else:
                        log.warning("Приём приостановлен: %s", health)
                    if state_path and health == "healthy":
                        temporary = Path(state_path).with_suffix(".tmp")
                        context.storage_state(path=str(temporary), indexed_db=True)
                        temporary.replace(state_path)
                    log.info("Проверка завершена, нажатий: %d", count)
                except Error as exc:
                    if page.is_closed():
                        break
                    log.warning("Ошибка проверки: %s; повтор в следующем цикле", type(exc).__name__)
                    health_alerts.observe("unavailable")
                # No overlapping scans or catch-up bursts after a slow response.
                delay = max(0.1, interval - (time.monotonic() - started))
                page.wait_for_timeout(delay * 1000)
        except KeyboardInterrupt:
            log.info("Остановлено пользователем")
        finally:
            context.close()
            if browser:
                browser.close()
