"""Local browser integration test; never contacts the real application."""
from playwright.sync_api import sync_playwright
from browser_worker import scan_page, page_health


def test_buttons():
    column = "Подробности"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        try:
            page = browser.new_page()
            page.route("https://app.test/**", lambda route: route.fulfill(
                content_type="text/html; charset=utf-8", body='''
                <button>Взять заявку</button>
                <table><thead><tr><th>Описание</th><th>Подробности</th></tr></thead><tbody>
                <tr><td><button>Принять заявку</button></td><td>Нет свободных мест</td></tr>
                <tr><td>Заявка 1</td><td><button onclick="this.closest('tr').remove()">Любой текст</button></td></tr>
                <tr><td>Заявка 2</td><td><a href="#" onclick="this.remove();return false">Взять</a></td></tr>
                <tr><td>Заявка 3</td><td><button onclick="this.remove()"><span aria-hidden="true">+</span></button></td></tr>
                <tr><td>Заявка 4</td><td><button disabled>Взять заявку</button>
                <button style="display:none">Взять заявку</button>
                <a class="ui-btn ui-btn-disabled" href="#">Недоступно</a></td></tr>
                <tr><td>Уже принята</td><td>Квалификация
                <a href="https://crm.test/crm/deal/show/942/" onclick="window.badClick=true">Открыть сделку</a>
                <a href="https://crm.test/details">Подробная информация</a></td></tr>
                </tbody></table>
                <table><tr><th>Другое</th></tr><tr><td><button>Взять заявку</button></td></tr></table>
                '''))
            page.set_content('<button>Взять заявку</button><iframe src="https://app.test/list"></iframe>')
            page.frame_locator("iframe").get_by_role("link", name="Взять", exact=True).wait_for()
            assert page_health(page, "app.test", column) == "healthy"
            assert scan_page(page, "app.test", column, True) == 0
            assert scan_page(page, "app.test", column) == 3
            assert scan_page(page, "app.test", column) == 0
            assert page.frames[1].evaluate("Boolean(window.badClick)") is False
            assert page.get_by_role("button", name="Взять заявку").count() == 1
            assert scan_page(page, "missing.test", column) == 0
            assert scan_page(page, "app.test", "Несуществующая колонка") == 0
            assert page_health(page, "app.test", "Несуществующая колонка") == "unavailable"
            # Merged description columns must not suppress the separate action cell.
            frame = page.frames[1]
            frame.locator("body").evaluate("""el => { el.innerHTML = `
                <table><tr><th colspan="2">Описание</th><th>Подробности</th></tr>
                <tr><td colspan="2">Описание</td><td><button onclick="this.remove()">Взять</button></td></tr>
                <tr><td>Неполная строка</td><td><button>Не нажимать</button></td></tr>
                <tr><td colspan="3"><button>Не нажимать</button></td></tr></table>`; }""")
            assert scan_page(page, "app.test", column) == 1
            assert frame.get_by_role("button").count() == 2
            # Stable column keys support an extra service cell in data rows.
            frame.locator("body").evaluate("""el => { el.innerHTML = `
                <table><tr><th>Описание</th><th data-name="DETAIL">Подробности</th></tr>
                <tr><td>Служебная</td><td><button>Не нажимать</button></td>
                <td data-name="DETAIL"><button onclick="this.remove()">Взять</button></td></tr></table>`; }""")
            assert scan_page(page, "app.test", column) == 1
            assert frame.get_by_role("button").count() == 1
            page.set_content('<input type="password">')
            assert page_health(page, "app.test", column) == "auth"
            page.set_content('<p>Нет свободных мест</p>')
            assert page_health(page, "app.test", column) == "unavailable"
            print("Browser tests passed: iframe, dry-run, buttons, hidden/disabled, removed rows")
        finally:
            browser.close()


if __name__ == "__main__":
    test_buttons()
