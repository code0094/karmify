# Test catalog

Карта «фича → тест-файлы → что покрыто». Обновляется скиллом karma-tests при
каждом добавлении/изменении тестов. Все записи прошли цикл: спарринг по
сценариям → независимое ревью (порог 8/10) → 3× flaky-check → mutation-гейт
(cosmic-ray), где отмечен.

Запуск: `.venv/Scripts/python -m pytest -q` (Windows) / `pytest -q`.
Полный гейт качества: `pytest -q` + `ruff check .` + `ruff format --check .` +
`mypy src` (strict, держится на нуле ошибок).
Тестовая БД — in-memory SQLite (aiosqlite, dev-зависимость): проверяет логику
запросов, НЕ Postgres-специфику (FOR UPDATE no-op, naive datetime,
NULL-ordering отличается — см. флаги в docstring tests/test_repos.py).

| Фича / модуль | Тесты | Покрыто | Гейты |
|---|---|---|---|
| Конфиг (`src/config.py`) + guard бот-режима (`src/main.py`) | `test_config.py` | optional-Telegram, poll_schedule валидатор, SystemExit без токена | ревью 8/10 |
| AppContext (`src/sidecar/context.py`) | `test_context.py` | реестр источников по конфигу (в т.ч. частичный slskd-конфиг), download в жанровый subdir, download_result, unknown source | ревью 8/10 |
| TrackDownloader / zotify (`src/spotify/downloader.py`) | `test_downloader.py` | успех/перезапись/креды-флаг, rc≠0, нет файла, нет zotify, таймаут+kill, _find_audio | ревью 9/10 |
| SpotifyClient токены (`src/spotify/client.py`) | `test_spotify_client.py` | reuse живого, refresh истёкшего, ротация refresh-токена persist, fallback на settings, unknown label | ревью 8/10 |
| Репозитории (`src/db/repos.py`) | `test_repos.py` | все 15 функций; пины: no-op update_tokens, assigned_at при снятии, затирание telegram_message_id, пустые фильтры | ревью 9/10 |
| Sidecar HTTP (`src/sidecar/app.py`) | `test_sidecar.py` | health/fetch/tracks(+passthrough)/playlists/assign(404/400/happy/дубль)/downloads/lifespan | ревью 9/10 |
| Плейлисты Spotify (`src/spotify/playlist.py`) | `test_playlist.py` | пагинация дедупа, терминация, add/remove; **xfail: краш на track=null** | ревью 9/10; мутации 25/0 |
| Жанровый каскад (`src/genre/*`) | `test_genre_resolver.py`, `test_genre_lookups.py`, `test_mapper.py` | маршрутизация уровней 1–3/manual, label once, квирк raw[0], батч sp.artists, genres→styles, строковые веса, приоритет маппера, единый Discogs-запрос | ревью 9/10; мутации 95/0 |
| Общий resolve+store (`src/genre/pipeline.py`) | `test_genre_pipeline.py` | запись detected_genre/genre_source на реальной SQLite, manual-результат | — |
| Поллер лайков (`src/spotify/poller.py`) | `test_poller.py` | новый/существующий трек (даты до текущего захода) | — |
| Soulseek download (`src/sources/soulseek_source.py`) | `test_sources.py` | search (ранее) + download: enqueue payload, сбор из вложенных папок, перезапись, poll-цикл, таймаут, guard downloads_dir | ревью 9/10; мутации 168/0 |
| Mailbox / IMAP (`src/sources/mailbox.py`) | `test_mailbox.py` | wait-цикл (happy/poll/timeout), селективный \Seen, пустой UNSEEN, extract из plain и html | ревью 9/10; мутации 110/0 |
| SpotifySource (`src/sources/spotify_source.py`) | `test_sources.py` | search-маппинг, download→move (даты до текущего захода) | — |
| LibraryManager (`src/library/manager.py`) | `test_library.py` | sanitize, копирование в subdir, missing source (даты до текущего захода) | — |
| Бот: клавиатуры (`src/bot/keyboards.py`) | `test_bot_callbacks.py` | ✨-маркер, «Другой…», download-кнопка, лимит 64 байта callback_data (даты до текущего захода) | — |
| Бот: команды (`src/bot/handlers/commands.py`) | `test_bot_commands.py` | /stats на реальной SQLite (парсинг периода, счётчики, фильтр по дате; **xfail: notin_-баг авто-счётчика**), /fetch (успех/ноль/ошибка) | ревью — см. журнал |
| Бот: нотификации (`src/bot/notifications.py`) | `test_bot_notifications.py` | текст (Label/Detected), выбор клавиатуры по match, message_id/chat_id | ревью — см. журнал |

## Не покрыто (осознанно)

- `src/sources/bandcamp_source.py` — селекторы не сверены с живым сайтом;
  тесты закрепили бы выдумку. Сначала живая проверка потока.
- `src/bot/handlers/callbacks.py` — хендлеры кнопок (клавиатуры покрыты).
  Бэклог топ-3: happy path assign, guard дабл-клика, дедлайн 24ч у reassign.
- `electron/` (renderer, TS) — тест-инфры нет (нужен vitest — отдельное решение).
- `src/spotify/poller.py` — пагинация >50 лайков и остановка по last_liked_at
  покрыты слабо (только базовые случаи).

## Починенные баги (xfail сняты, тесты стали регрессионными)

- `test_playlist.py::test_null_track_items_are_skipped` — краш на
  `"track": null` от Spotify (плюс тот же класс бага в поллере:
  `test_poller.py::test_poller_skips_null_track_items`).
- `test_bot_commands.py::test_stats_auto_count` — `notin_(["manual", None])`
  никогда не совпадал, авто-счётчик всегда показывал 0.

## Открытые баги (НЕ закреплены тестами — требуют решения)

- `AppContext.download_liked_track(source="soulseek")` сломан: `SearchResult`
  собирается без `extra`, `_download_blocking` читает только его → пустой
  username и сырой `ValueError`.
- `get_last_liked_at` на PostgreSQL: `ORDER BY liked_at DESC` ставит NULL
  первыми → одна строка с пустым `liked_at` вернёт None вместо максимума
  (портируемый фикс — `func.max`).
