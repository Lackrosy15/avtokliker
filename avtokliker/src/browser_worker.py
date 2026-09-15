"""Poll the rendered application, including its cross-origin iframe."""

import logging
import math
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("avtokliker")
ROOT = Path(__file__).resolve().parent.parent


def in_work_hours(now=None):
    """Daily 09:00 inclusive to 22:00 exclusive, Minsk (UTC+3)."""
    now = now or datetime.now(timezone.utc)
    return 9 <= now.astimezone(timezone(timedelta(hours=3))).hour < 22


def is_blocked(page, host):
    pattern = re.compile(r"доступ\s+к\s+заявкам\s+заблокирован|подозрительн\w*\s+активност", re.I)
    return any(frame.get_by_text(pattern).first.is_visible()
               for frame in page.frames if urlparse(frame.url).hostname == host)


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
        return []  # Outer application frames need not contain the grid.
    controls = []
    checked_rows = 0
    for header in headers.all():
        if not header.is_visible():
            continue
        metadata = header.evaluate("""el => {
            const cells = Array.from(el.parentElement.children)
                .filter(c => c.matches('th,td,[role=columnheader],[role=cell],[role=gridcell]'));
            const width = c => Number(c.getAttribute('colspan') || 1);
            return {start: cells.slice(0, cells.indexOf(el)).reduce((s,c) => s+width(c), 0),
                width: width(el), total: cells.reduce((s,c) => s+width(c), 0),
                name: el.getAttribute('data-name'), aria: el.getAttribute('aria-colindex')};
        }""")
        if metadata["width"] != 1:
            log.warning("Заголовок объединяет несколько колонок: пропуск")
            continue
        table = header.locator("xpath=ancestor::*[self::table or @role='grid' or @role='table'][1]")
        rows = table.locator(":scope > tbody > tr, :scope > tr, :scope > [role=row], :scope > [role=rowgroup] > [role=row]")
        log.info("Таблица %s: колонка=%s, позиция=%d, ширина строки заголовка=%d, строк=%d",
                 urlparse(frame.url).path, column_title, metadata["start"] + 1,
                 metadata["total"], rows.count())
        for row in rows.all():
            if not row.is_visible():
                continue
            if row.locator(":scope > th, :scope > .main-grid-cell-head, :scope > [role=columnheader]").count():
                continue
            cells = row.locator(":scope > td, :scope > [role=cell], :scope > [role=gridcell]")
            checked_rows += 1
            match = cells.evaluate_all("""(cells, h) => {
                for (const [attr, value] of [['data-name', h.name], ['aria-colindex', h.aria]]) {
                    if (!value) continue;
                    const matches = cells.map((c,i) => c.getAttribute(attr) === value ? i : -1).filter(i => i >= 0);
                    if (matches.length === 1) return {index:matches[0], reason:attr};
                    if (matches.length > 1) return {index:-1, reason:'duplicate-column-key'};
                }
                if (cells.some(c => Number(c.getAttribute('rowspan') || 1) !== 1))
                    return {index:-1, reason:'rowspan'};
                const width = c => Number(c.getAttribute('colspan') || 1);
                const total = cells.reduce((s,c) => s+width(c),0);
                if (total !== h.total) return {index:-1, reason:'column-count-mismatch', total};
                let start = 0;
                for (let i=0; i<cells.length; i++) {
                    if (start === h.start && width(cells[i]) === 1) return {index:i, reason:'position'};
                    start += width(cells[i]);
                }
                return {index:-1, reason:'merged-target-cell'};
            }""", metadata)
            if match["index"] < 0:
                log.warning("Строка %d: пропуск=%s, ячеек=%d, суммарная ширина=%s",
                            checked_rows, match["reason"], cells.count(), match.get("total", "—"))
                continue
            cell = cells.nth(match["index"])
            found = cell.locator(
                'button, input[type=button], input[type=submit], [role=button], '
                'a[href], a[onclick], .ui-btn, .webform-small-button'
            ).element_handles()
            no_slots = "нет свободных мест" in cell.inner_text().lower()
            log.info("Строка %d: сопоставление=%s, ячейка=%d, кнопок=%d, нет мест=%s",
                     checked_rows, match["reason"], match["index"] + 1, len(found), no_slots)
            controls.extend(found)
    log.info("Поиск кнопок: проверено строк=%d, кандидатов=%d", checked_rows, len(controls))
    return controls


def scan_page(page, host, column_title="Подробности", dry_run=False):
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
        for number, control in enumerate(controls, 1):
            try:
                # The details cell also contains ordinary navigation links.
                if control.evaluate("""el => {
                    const link = el.closest('a');
                    if (!link) return false;
                    const href = (link.getAttribute('href') || '').trim();
                    if (/\\/crm\\/(deal|lead)\\//i.test(href)) return true;
                    return href !== '' && !href.startsWith('#') &&
                        !href.toLowerCase().startsWith('javascript:') &&
                        !link.hasAttribute('onclick') && link.getAttribute('role') !== 'button' &&
                        !link.matches('.ui-btn, .webform-small-button');
                }"""):
                    log.info("Кнопка %d: пропуск=навигационная ссылка", number)
                    continue
                if not control.is_visible():
                    log.info("Кнопка %d: пропуск=скрыта или удалена", number)
                    continue
                if not control.is_enabled():
                    log.info("Кнопка %d: пропуск=отключена", number)
                    continue
                if control.evaluate("el => !!el.closest('[aria-disabled=true], [disabled], .ui-btn-disabled, .webform-small-button-disabled')"):
                    log.info("Кнопка %d: пропуск=отключена стилем или контейнером", number)
                    continue
                if dry_run:
                    log.info("DRY-RUN: найдена доступная кнопка заявки")
                    continue
                log.info("Кнопка %d: попытка нажатия", number)
                control.click(timeout=3000)
                clicks += 1
                log.info("Нажата кнопка заявки; результат приёма проверяйте в приложении")
                page.wait_for_timeout(500)
                remains = control.is_visible() and control.is_enabled()
                log.info("Кнопка %d: после клика %s; серверный успех не подтверждён",
                         number, "остаётся доступной" if remains else "исчезла или отключена")
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
    interval = float(cfg.get("pollIntervalSec", 90))
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("pollIntervalSec должен быть положительным числом")
    column_title = options.get("columnTitle", "Подробности")
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
    block_file = Path(options.get("blockStateFile", str(profile.parent / "blocked.json")))
    if block_file.exists():
        raise SystemExit(78)  # Persistent manual-reset latch, including after reboot.
    if not login_only:
        while not in_work_hours():
            time.sleep(30)
    with sync_playwright() as pw:
        browser = None
        if state_path and not login_only:
            browser = pw.chromium.launch(channel=options.get("channel", "msedge"), headless=headless)
            context = browser.new_context(storage_state=state_path, service_workers="block")
        else:
            context = pw.chromium.launch_persistent_context(
                str(profile), channel=options.get("channel", "msedge"), headless=headless,
                service_workers="block",
            )
        stopped = False
        context.route("**/*", lambda route: route.abort() if stopped or
                      (not login_only and not in_work_hours()) else route.continue_())
        try:
            page = context.pages[0] if context.pages else context.new_page()
            initial_loaded = False
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                initial_loaded = True
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
                if not in_work_hours():
                    page.wait_for_timeout(30000)
                    continue
                started = time.monotonic()
                try:
                    if initial_loaded:
                        initial_loaded = False
                    elif urlparse(page.url).hostname != urlparse(url).hostname:
                        page.goto(url, wait_until="load", timeout=20000)
                    else:
                        page.reload(wait_until="load", timeout=20000)
                    page.wait_for_timeout(options.get("settleMs", 2000))
                    if is_blocked(page, host):
                        stopped = True
                        block_file.write_text(json.dumps({"blockedAt": datetime.now(timezone.utc).isoformat()}))
                        log.error("Обнаружена блокировка: запросы отключены до ручного снятия паузы")
                        from alerts import send_telegram
                        send_telegram(cfg, "Автокликер: Битрикс24 заблокировал доступ к заявкам. Запросы отключены. После снятия блокировки требуется ручное включение.")
                        raise SystemExit(78)
                    if not in_work_hours():
                        continue
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
