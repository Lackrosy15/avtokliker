# Размещение на Linux с systemd

Основная пошаговая инструкция с командами GitHub, установки и переносом сессии:
[INSTALL.md](INSTALL.md). Ниже резервный вариант входа непосредственно на сервере.

Шаблон подготовлен; фактическая установка зависит от ОС и доступа к серверу.
Код: `/opt/avtokliker`, отдельный пользователь `avtokliker`, профиль:
`/var/lib/avtokliker/profile`. Не переносите Windows-профиль Chromium на Linux:
авторизуйтесь на сервере под пользователем службы через защищённый графический
сеанс (например, уже настроенный удалённый рабочий стол).

1. Установить Python с venv, создать пользователя и каталоги. Скопировать
   `src`, `requirements.txt`, `deploy` в `/opt/avtokliker`.
2. Создать `/opt/avtokliker/.venv`, установить `requirements.txt`.
3. Установить системные зависимости командой
   `/opt/avtokliker/.venv/bin/python -m playwright install-deps chromium` от root.
   Установить браузер с `PLAYWRIGHT_BROWSERS_PATH=/opt/avtokliker/browsers`
   командой `/opt/avtokliker/.venv/bin/python -m playwright install chromium`.
   Пользователю службы требуется чтение браузера и запись в каталог профиля.
4. В графическом сеансе пользователя службы выполнить (служба должна быть остановлена):

```sh
AVTOKLIKER_CONFIG=/opt/avtokliker/deploy/config.server.json \
PLAYWRIGHT_BROWSERS_PATH=/opt/avtokliker/browsers \
AVTOKLIKER_EXPORT_STATE=/var/lib/avtokliker/storage-state.json \
AVTOKLIKER_LOGIN=1 /opt/avtokliker/.venv/bin/python /opt/avtokliker/src/avtokliker.py
```

Войти в портал, открыть «Заявки» и нажать Enter. Этот режим только сохраняет
профиль и завершается, заявки не принимает. Сессия встроенного браузера Codex
не переносится на сервер автоматически.

5. До включения службы запустить с `dryRun: true` в серверной конфигурации
   и проверить доступ к таблице и выбор правильной колонки. Затем установить
   `dryRun: false`. Не запускайте локальный автоприём одновременно с серверным.
6. Скопировать unit в `/etc/systemd/system/avtokliker.service`, выполнить:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now avtokliker
sudo systemctl status avtokliker
sudo journalctl -u avtokliker -n 50 --no-pager
```

Перезапуск: `sudo systemctl restart avtokliker`.
Остановка: `sudo systemctl stop avtokliker`.
При истечении авторизации повторить шаг 4 и перезапустить службу.
Отсутствие iframe может означать истёкшую сессию; сообщение пишется в журнал.
Telegram-уведомления: [TELEGRAM.md](TELEGRAM.md). Unit перезапускает процесс после сбоя,
но не восстанавливает истёкшую авторизацию.

Процесс обновляет открытую страницу раз в 10 секунд (дольше при медленном ответе)
и нажимает доступные элементы целевой колонки. Клик запускает штатный запрос
приложения; отдельный API принятия не воспроизводится. Запись о клике не является
подтверждением серверного успеха. Дополнительные диалоги не подтверждаются.

Документация: [браузеры Playwright](https://playwright.dev/python/docs/browsers),
[сохранение авторизации](https://playwright.dev/python/docs/auth).
