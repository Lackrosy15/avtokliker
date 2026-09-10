# Уведомления Telegram

1. Создайте отдельного бота через [BotFather](https://t.me/BotFather), команда
   `/newbot`. Сохраните токен. Откройте своего бота и отправьте `/start`.
2. Узнайте ID вашего чата через `getUpdates` API Telegram. Например, на компьютере
   в PowerShell (токен вводится скрыто и не попадает в текст команды):

```powershell
$botSecret = Read-Host 'Токен бота' -AsSecureString
$botToken = [System.Net.NetworkCredential]::new('', $botSecret).Password
try {
    $updates = Invoke-RestMethod -Uri "https://api.telegram.org/bot$botToken/getUpdates"
    $updates.result | ForEach-Object { $_.message.chat } | Select-Object id, type, first_name, username -Unique
} catch { Write-Host 'Не удалось получить chat_id. Проверьте токен и подключение.' }
Remove-Variable botToken, botSecret
```

Выберите ID именно своего чата. Если список пуст, напишите боту ещё одно сообщение.
Используйте отдельного бота без webhook и других получателей обновлений.

3. На сервере создайте файл с доступом только root:

```sh
sudo touch /etc/avtokliker.env
sudo chmod 600 /etc/avtokliker.env
sudo nano /etc/avtokliker.env
```

Содержимое (замените значения):

```text
AVTOKLIKER_TELEGRAM_BOT_TOKEN=ТОКЕН_БОТА
AVTOKLIKER_TELEGRAM_CHAT_ID=ВАШ_CHAT_ID
```

Не добавляйте файл в Git и не присылайте токен в чат.

4. Обновите код и unit по разделу 6 `INSTALL.md`. В установленный
   `/opt/avtokliker/deploy/config.server.json` добавьте на верхнем уровне:

```json
"notify": {"stateFile": "/var/lib/avtokliker/alerts-state.json"}
```

При первой установке это уже есть в серверном шаблоне. Проверьте запятые в JSON.
Файл состояния подавляет повторные уведомления после перезапуска процесса.

5. Отправьте тестовое уведомление, не запуская приём заявок:

```sh
sudo systemd-run --wait --pipe --collect --property=User=avtokliker --property=EnvironmentFile=/etc/avtokliker.env /opt/avtokliker/.venv/bin/python /opt/avtokliker/src/alerts.py
sudo systemctl daemon-reload
sudo systemctl restart avtokliker
```

В Telegram должно прийти «Тест: уведомления автокликера подключены».

## Поведение

- Три подряд проверки показывают вход/пароль — уведомление о необходимости входа.
- Три подряд проверки без таблицы или с ошибкой загрузки — уведомление о
  недоступности приложения, без утверждения, что точно истекла авторизация.
- Нет свободных заявок, но таблица доступна — это штатная работа, тревоги нет.
- Пока таблица недоступна, кнопки не нажимаются, файл сессии не перезаписывается.
- После трёх успешных проверок — сообщение о восстановлении доступа.
- Между попытками отправки минимум пять минут, повторная отправка при ошибке
  Telegram тоже через пять минут. При стабильной проблеме повторов нет.

При обычных быстрых проверках проблема обнаруживается примерно за 20–30 секунд;
сетевая задержка и ограничение отправки могут увеличить время. Если сервер выключен,
процесс не запускается или полностью отсутствует интернет, он не сможет отправить
Telegram: для таких случаев нужен внешний мониторинг.

API: [sendMessage и getUpdates](https://core.telegram.org/bots/api).
