# Установка на Ubuntu 24.04 LTS

Нужны SSH-доступ, sudo и исходящий HTTPS. Замените `YOUR_LOGIN`, `YOUR_REPO`,
`USER@SERVER` своими значениями. Входящие порты приложения открывать не нужно.
Для другой ОС команды установки могут отличаться.

## 1. GitHub — на компьютере, из корня проекта

```powershell
git add avtokliker/src avtokliker/deploy avtokliker/config.json avtokliker/requirements.txt avtokliker/README.md avtokliker/.gitignore
git diff --cached --stat
git commit -m "Add server auto-accept worker"
git push
```

Проверьте список перед коммитом: не публикуйте профиль браузера, файлы авторизации,
содержимое `curl` и пароли. `.gitignore` не исключает уже отслеживаемые Git файлы.
Для приватного репозитория используйте настроенный SSH-ключ GitHub для чтения
и SSH URL вместо HTTPS URL ниже. Не вставляйте токен в URL.

## 2. Первая установка — на сервере

```sh
sudo apt-get update
sudo apt-get install -y git python3 python3-venv
sudo useradd --system --user-group --home-dir /var/lib/avtokliker --create-home --shell /usr/sbin/nologin avtokliker
sudo install -d -o avtokliker -g avtokliker -m 700 /var/lib/avtokliker
git clone https://github.com/YOUR_LOGIN/YOUR_REPO.git ~/avtokliker-repo
sudo install -d /opt/avtokliker/src /opt/avtokliker/deploy
sudo cp -r ~/avtokliker-repo/avtokliker/src/. /opt/avtokliker/src/
sudo cp ~/avtokliker-repo/avtokliker/requirements.txt /opt/avtokliker/
sudo cp ~/avtokliker-repo/avtokliker/deploy/config.server.json /opt/avtokliker/deploy/
sudo cp ~/avtokliker-repo/avtokliker/deploy/avtokliker.service /etc/systemd/system/
sudo python3 -m venv /opt/avtokliker/.venv
sudo /opt/avtokliker/.venv/bin/python -m pip install -r /opt/avtokliker/requirements.txt
sudo env PLAYWRIGHT_BROWSERS_PATH=/opt/avtokliker/browsers /opt/avtokliker/.venv/bin/python -m playwright install --with-deps chromium
```

Код принадлежит root, служба работает отдельным пользователем. Сессия хранится
в `/var/lib/avtokliker`, отдельно от кода. `useradd` и `git clone` нужны только
при первой установке; обновление описано ниже.

## 3. Авторизация — на компьютере

Остановите локальный автокликер (Ctrl+C). PowerShell, корень проекта:

```powershell
.\avtokliker\.venv\Scripts\python.exe -m pip install -r avtokliker\requirements.txt
$env:AVTOKLIKER_LOGIN = '1'
$env:AVTOKLIKER_EXPORT_STATE = "$PWD\avtokliker\storage-state.json"
.\avtokliker\.venv\Scripts\python.exe avtokliker\src\avtokliker.py
Remove-Item Env:AVTOKLIKER_LOGIN
Remove-Item Env:AVTOKLIKER_EXPORT_STATE
```

Если venv ещё нет: `py -m venv avtokliker\.venv`.
В открывшемся Edge войдите в Битрикс24, откройте приложение, дождитесь таблицы
«Заявки» и нажмите Enter в консоли. Режим входа не принимает заявки.
Создаётся `avtokliker/storage-state.json` с cookies, localStorage и IndexedDB.
Вход в браузере Codex не заменяет этот шаг — профили разные.

Передайте файл из PowerShell:

```powershell
scp .\avtokliker\storage-state.json USER@SERVER:~/avtokliker-state.json
```

На сервере:

```sh
sudo install -o avtokliker -g avtokliker -m 600 ~/avtokliker-state.json /var/lib/avtokliker/storage-state.json
rm ~/avtokliker-state.json
```

Файл даёт доступ к сессии: не публикуйте его в GitHub и не присылайте в чат.
Пароль программа не хранит. Перенос сессии нужно проверить: Битрикс24 может
потребовать вход с нового IP; sessionStorage этим способом не переносится.
Если сервер не видит таблицу, используйте вход на самом сервере через защищённый
графический сеанс, как описано в `README.md` этой папки.

## 4. Проверить без нажатий — на сервере

```sh
sudo /opt/avtokliker/.venv/bin/python -c 'import json; from pathlib import Path; p=Path("/opt/avtokliker/deploy/config.server.json"); c=json.loads(p.read_text()); c["dryRun"]=True; p.write_text(json.dumps(c, ensure_ascii=False, indent=2))'
sudo systemctl daemon-reload
sudo systemctl start avtokliker
sudo journalctl -u avtokliker -n 50 --no-pager
```

Дождитесь нескольких циклов. В журнале должна обнаруживаться целевая колонка.
Сообщение `DRY-RUN: найдена доступная кнопка заявки` означает обнаружение без
клика. Если свободных заявок нет, отсутствие кнопок нормально. Если приложение
или колонка не найдены, сначала исправьте вход/разметку. Полную проверку принятия
можно провести только при появлении настоящей доступной заявки.

## 5. Включить автоматический приём

```sh
sudo systemctl stop avtokliker
sudo /opt/avtokliker/.venv/bin/python -c 'import json; from pathlib import Path; p=Path("/opt/avtokliker/deploy/config.server.json"); c=json.loads(p.read_text()); c["dryRun"]=False; p.write_text(json.dumps(c, ensure_ascii=False, indent=2))'
sudo systemctl enable --now avtokliker
sudo systemctl status avtokliker --no-pager
sudo journalctl -u avtokliker -f
```

Ctrl+C закрывает просмотр журнала, служба продолжает работать. После перезагрузки
сервера она запускается автоматически, после падения перезапускается через 10 секунд.
Не запускайте локальный и серверный автокликер одновременно.

```sh
sudo systemctl restart avtokliker
sudo systemctl stop avtokliker
sudo systemctl disable --now avtokliker
```

Это, соответственно: перезапуск, остановка, остановка с отключением автозапуска.

## 6. Обновление из GitHub

```sh
cd ~/avtokliker-repo
git pull --ff-only
sudo systemctl stop avtokliker
sudo cp -r avtokliker/src/. /opt/avtokliker/src/
sudo cp avtokliker/requirements.txt /opt/avtokliker/
sudo cp avtokliker/deploy/avtokliker.service /etc/systemd/system/
sudo /opt/avtokliker/.venv/bin/python -m pip install -r /opt/avtokliker/requirements.txt
sudo env PLAYWRIGHT_BROWSERS_PATH=/opt/avtokliker/browsers /opt/avtokliker/.venv/bin/python -m playwright install --with-deps chromium
sudo systemctl daemon-reload
sudo systemctl start avtokliker
sudo journalctl -u avtokliker -n 50 --no-pager
```

Серверная конфигурация и сессия не перезаписываются. Новые настройки переносите
в установленную конфигурацию отдельно, сравнив её с копией в Git.

## 7. Обновление авторизации и ограничения

Если вход истёк, остановите службу, повторите раздел 3 и запустите её заново.
В работе обновлённое состояние сессии сохраняется после проверки, но это не
гарантирует бессрочный вход. systemd не восстанавливает авторизацию.
Telegram-уведомления настраиваются по [TELEGRAM.md](TELEGRAM.md).

Цикл обновляет открытую страницу каждые 10 секунд, при медленной загрузке — дольше.
Кнопка ищется в колонке «Предложения партнеров» (е/ё допускаются), независимо от
её текста. Нажатие запускает штатный запрос приложения. API принятия отдельно
не воспроизводится. Лог фиксирует клик, не подтверждение приёма сервером.
Дополнительные диалоги не подтверждаются, пагинация не обходится.

Документация: [браузеры Playwright](https://playwright.dev/python/docs/browsers),
[авторизация Playwright](https://playwright.dev/python/docs/auth).
