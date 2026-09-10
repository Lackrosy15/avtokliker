# Разведка API партнёрского приложения Битрикс24

> Заполняется по мере исследования. Дата начала: 2026-09-03.

## Что известно сразу

- Портал: `crmby.bitrix24.by`
- URL приложения: `/marketplace/app/60/` — это iframe-приложение (тип «встраиваемое приложение» Б24)
- Вкладки: Заявки / Синхронизация настроек CRM / Клиенты / Задать вопрос
- В таблице заявок есть колонки: Описание, Заявка создана, Город, Предложения партнёров, Подробности, Направление, Тип
- Кнопка «Принять заявку» появляется в строке заявки, когда есть свободные места
- Если мест нет — «Нельзя взять эту заявку: Нет свободных мест»

## Как устроено приложение (ПОДТВЕРЖДЕНО)

`/marketplace/app/60/` — iframe-обёртка Битрикса. Реальный сервер приложения:
**`https://util.1c-bitrix.by/b24application/work.php`** (сервер 1С-Битрикс, не портал).

Авторизация внутри iframe — через сессионные cookies `util.1c-bitrix.by`
(Битрикс пробрасывает членство партнёра при открытии приложения).

---

## Найденные endpoint'ы (2026-09-04)

### Страница приложения
```
GET https://util.1c-bitrix.by/b24application/work.php
```

### Список заявок (оба вызываются при загрузке вкладки «Заявки»)
```
GET https://util.1c-bitrix.by/bitrix/services/main/ajax.php?mode=class&c=bx%3Apartner.application.b24.list.work&action=synchronizeQualificationData
GET https://util.1c-bitrix.by/bitrix/services/main/ajax.php?mode=class&c=bx%3Apartner.application.b24.list.work&action=synchronizeQualificationDataStartGrid
```
`synchronizeQualificationDataStartGrid` — скорее всего, данные грида (строки таблицы заявок).
`synchronizeQualificationData` — счётчики/квалификация (В работе 12/14 и т.п.).
Точный формат — выяснить из тела ответа (см. Шаг 2 ниже).

### Принятие заявки (ПОКА НЕ ПОЙМАН — заявки появляются редко)
Ожидается POST на тот же `ajax.php` с `c=bx:partner.application.b24.list.work`
и action вроде `takeWork` / `acceptWork` / `addWork`.

### Не относится к делу
`crmby.bitrix24.by/.../main.userOption.saveOptions` — просто сохранение настроек UI портала.

## Шаг 1. Открыть DevTools и найти iframe

1. Открыть `https://crmby.bitrix24.by/marketplace/app/60/` в Chrome
2. F12 → вкладка **Elements**
3. Найти `<iframe` (Ctrl+F в панели Elements, поиск по `iframe`)
4. Скопировать значение атрибута `src`

**URL iframe:** _<заполнить>_

## Шаг 2. Поймать ПОЛНЫЙ трафик грида (критично!)

⚠️ **Обновление после разведки:** запросы `synchronizeQualificationData` и
`synchronizeQualificationDataStartGrid` возвращают `{"status":"success","data":null}` —
это **триггеры синхронизации**, а НЕ данные грида. Реальный запрос, который
возвращает строки таблицы (описание, город, свободные места, ID), — другой.

`auth` и `parameters` в POST body — это **подписанные/зашифрованные токены**,
их нельзя подделать, только скопировать из реального запроса. Поэтому нужен
полный захват трафика:

1. Открой `https://crmby.bitrix24.by/marketplace/app/60/` → вкладка **«Заявки»**
2. F12 → **Network** → фильтр: `ajax.php`
3. Поставь **Preserve log** и **Disable cache**
4. Обнови страницу (F5), затем **прокрути список / переключи страницу пагинации /
   нажми в фильтре** — чтобы грид перезагрузил данные
5. В Network появится **несколько** запросов `ajax.php`. Найди тот, у которого
   во вкладке **Response** есть JSON со строками заявок (description, city, id)
6. ПКМ по нему → **Copy → Copy as cURL (bash)** → сохрани в `avtokliker/curl/list.txt`

**Подсказка:** у нужного запроса в Response будет массив объектов заявок,
а не `data:null`. Скорее всего action у него другой (не `synchronize...`).

**Какой action вернул строки:** _<заполнить>_

**Формат ответа (структура одной заявки):**
```json
_<вставить пример>_
```

## Шаг 3. Поймать запрос принятия заявки

Заявки появляются редко, поэтому: держи вкладку с приложением открытой,
Network → **Preserve log** включён, фильтр `ajax.php`. Как только увидел
заявку со свободными местами:

1. Нажать «Принять заявку»
2. В Network найти новый POST на `ajax.php`
3. ПКМ → **Copy → Copy as cURL (bash)** → сохранить в `avtokliker/curl/accept.txt`
4. Записать сюда URL и payload:

**Endpoint принятия:** _<заполнить>_

**Payload (тело POST):**
```
_<вставить>_
```

**Ответ сервера:**
```json
_<вставить>_
```

## Шаг 4. Авторизация (установлено)

- [x] Cookie сессии на домене `util.1c-bitrix.by` — автоматически попадают в Copy as cURL
- [x] Подписанные параметры Битрикса (`signedParameters` + `sessid`) — тоже в cURL

⚠️ **Важно:** `sessid` и cookies протухают (обычно живут часы). Если скрипт начал
получать 401/403 или пустые ответы — пересохрани cURL из DevTools заново.

---

## Выводы / план автоматизации

Скрипт `src/avtokliker.py` читает `curl/list.txt` и `curl/accept.txt`,
повторяет их как есть (urllib, stdlib-only), парсит JSON списка, фильтрует по
ключевым словам и в dry-run режиме только сообщает. ID заявки подставляется
в accept-запрос вместо значения из curl/accept.txt.
