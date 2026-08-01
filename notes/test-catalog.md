# Test catalog

Карта «фича → тест-файлы → что покрыто». Обновляется скиллом karma-tests при
каждом добавлении/изменении тестов. Все записи прошли цикл: спарринг по
сценариям → независимое ревью (порог 8/10) → 3× flaky-check → mutation-гейт
(cosmic-ray), где отмечен.

Запуск: `.venv/Scripts/python -m pytest -q` (Windows) / `pytest -q`.
Полный гейт качества: `pytest -q` + `ruff check .` + `ruff format --check .` +
`mypy src` (strict, держится на нуле ошибок).
Схема БД версионируется alembic (`alembic upgrade head`; на БД, где таблицы
создавались вручную — сперва `alembic stamp 0001`).
Тестовая БД — in-memory SQLite (aiosqlite, dev-зависимость): проверяет логику
запросов, НЕ Postgres-специфику (FOR UPDATE no-op, naive datetime,
NULL-ordering отличается — см. флаги в docstring tests/test_repos.py).

| Фича / модуль | Тесты | Покрыто | Гейты |
|---|---|---|---|
| Конфиг (`src/config.py`) + guard бот-режима (`src/main.py`) | `test_config.py` | optional-Telegram, poll_schedule валидатор, SystemExit без токена | ревью 8/10 |
| AppContext (`src/sidecar/context.py`) | `test_context.py` | реестр источников по конфигу (в т.ч. частичный slskd-конфиг), download в жанровый subdir, download_result, unknown source, поиск для не-Spotify источников, отказ уже скачанному, single-flight | ревью 8/10 |
| Пакетная загрузка плейлиста (`src/sidecar/context.py`, `src/db/repos.py`, `src/sidecar/app.py`) | `test_context.py`, `test_repos.py`, `test_sidecar.py` | waterfall soulseek→bandcamp→spotify (fallback, запись ошибки при полном провале, тихий скип уже скачанного), воркер не падает на одном треке, single-flight per playlist + рестарт после завершения, пустой плейлист без задачи, отмена в aclose; repos: set/clear download_error, list_playlist_tracks, playlist_download_stats (derived-статусы, ретрай прячет ошибку); роуты: 202+queued, 404, 409, статы в /playlists, прогресс-поля в /tracks | 3× flaky-check |
| Инициализация жанровых плейлистов (`src/genre/defaults.py`, `src/sidecar/context.py`) | `test_context.py`, `test_repos.py`, `test_sidecar.py` | создание недостающих + посев алиасов на реальной SQLite, идемпотентность (повтор без Spotify-авторизации), auth лениво — только при создании, ничего не создано до провала auth, crew_id на созданных; repos: add_genre_playlist, add_genre_alias (нормализация регистра, дедуп); роут: 200 со счётчиками, NotAuthorizedError→400, SpotifyException→502 без URL-шума | — |
| Данные под редизайн (`src/sources/base.py`, `src/sidecar/context.py`) | `test_sources.py`, `test_context.py`, `test_sidecar.py`, `test_repos.py`, `test_genre_pipeline.py` | quality/healthy у источников (slskd отвечает или нет, Spotify без OAuth), source_states (порядок по качеству, упавшая проба = down), /health не падает от источников; создание плейлиста (hue round-robin и persist, имя как алиас, отказ на существующий жанр без осиротевшего плейлиста в Spotify), POST /playlists (201, пустое имя → 422, без auth → 400); record_label и download_source сохраняются | — |
| Команды (`src/db/bootstrap.py`, users/crews в `src/db/repos.py`) | `test_bootstrap.py`, `test_repos.py`, `test_context.py`, `test_sidecar.py` | посев users+crew+членства из настроек, идемпотентность, добавленный руками участник переживает повторный запуск, усыновление плейлистов без crew, пустой DEFAULT_USERS → без crew; repos: ensure_user/ensure_crew/ensure_crew_member (get-or-create, оригинальный владелец сохраняется), get_crew_members в порядке вступления; context.bootstrap строит клиентов из таблицы users (включая добавленных позже), owner_client до bootstrap → NotAuthorizedError; роуты: GET /crew (участники + connected + owner), пустой ответ до посева, bootstrap в lifespan; SpotifyClient: без строки в БД → NotAuthorizedError (env-фолбэк удалён), e2e refresh-once на реальной SQLite | 3× flaky-check |
| TrackDownloader / zotify (`src/spotify/downloader.py`) | `test_downloader.py` | успех/перезапись/креды-флаг, rc≠0, нет файла, нет zotify, таймаут+kill, _find_audio | ревью 9/10 |
| Spotify OAuth (`src/spotify/oauth.py`) | `test_spotify_oauth.py`, `test_sidecar.py` | authorize-URL со state, обмен кода, одноразовость и протухание state, подделанный state, ответ без refresh-токена, ненастроенное приложение; роуты login/callback/status (редирект, 404 чужого аккаунта, токен в query, отказ пользователя) | — |
| SpotifyClient токены (`src/spotify/client.py`) | `test_spotify_client.py` | reuse живого, refresh истёкшего, ротация refresh-токена persist, fallback на settings, unknown label, сквозной тест на реальной пустой БД (строка создаётся, второй вызов не рефрешит) | ревью 8/10 |
| Репозитории (`src/db/repos.py`) | `test_repos.py` | все функции; пины: save_tokens создаёт строку при первом refresh (гонка → UPDATE), assigned_at при снятии, затирание telegram_message_id, пустые фильтры; claim/release скачивания (эксклюзивность, перехват протухшего, очистка при отметке) | ревью 9/10 |
| Sidecar HTTP (`src/sidecar/app.py`) | `test_sidecar.py` | health/fetch/tracks(+passthrough, границы limit)/playlists/assign(404/400/happy/дубль/перенос)/downloads/lifespan/origin-guard/токен (401, подделка `null`, query только для audio, открытый `/health`)/preflight в обоих режимах/audio-эндпоинт (200/404)/host-guard (DNS rebinding) | ревью 9/10 |
| Плейлисты Spotify (`src/spotify/playlist.py`) | `test_playlist.py` | пагинация дедупа, терминация, add/remove, `move_track` (remove до add) | ревью 9/10; мутации 25/0 |
| Жанровый каскад (`src/genre/*`) | `test_genre_resolver.py`, `test_genre_lookups.py`, `test_mapper.py` | маршрутизация уровней 1–3/manual, label once, квирк raw[0], батч sp.artists, genres→styles, строковые веса, приоритет маппера, единый Discogs-запрос | ревью 9/10; мутации 95/0 |
| Миграции (`alembic/`) | `test_migrations.py` | `upgrade head` на чистой БД + пустой autogenerate-diff против моделей (ловит дрейф baseline↔models) | — |
| Общий resolve+store (`src/genre/pipeline.py`) | `test_genre_pipeline.py` | запись detected_genre/genre_source на реальной SQLite, manual-результат | — |
| Поллер лайков (`src/spotify/poller.py`) | `test_poller.py` | новый/существующий трек, пропуск `"track": null`, сбой `on_new_track` не отменяет остальные треки | — |
| Soulseek download (`src/sources/soulseek_source.py`) | `test_sources.py` | search (ранее) + download: enqueue payload, сбор из вложенных папок (буквальное имя — glob-спецсимволы `[FLAC]`), перезапись, poll-цикл, таймаут, guard downloads_dir, guard пустого extra | ревью 9/10; мутации 168/0 |
| Mailbox / IMAP (`src/sources/mailbox.py`) | `test_mailbox.py` | wait-цикл (happy/poll/timeout), селективный \Seen, пустой UNSEEN, extract из plain и html | ревью 9/10; мутации 110/0 |
| SpotifySource (`src/sources/spotify_source.py`) | `test_sources.py` | search-маппинг, download→move (даты до текущего захода) | — |
| LibraryManager (`src/library/manager.py`) | `test_library.py` | sanitize, копирование в subdir, missing source (даты до текущего захода) | — |
| Бот: клавиатуры (`src/bot/keyboards.py`) | `test_bot_callbacks.py` | ✨-маркер, «Другой…», download-кнопка, лимит 64 байта callback_data (даты до текущего захода) | — |
| Бот: команды (`src/bot/handlers/commands.py`) | `test_bot_commands.py` | /stats на реальной SQLite (парсинг периода, счётчики вкл. авто-регрессию, фильтр по дате), /fetch (успех/ноль/ошибка) | ревью — см. журнал |
| Бот: нотификации (`src/bot/notifications.py`) | `test_bot_notifications.py` | текст (Label/Detected), выбор клавиатуры по match, message_id/chat_id | ревью — см. журнал |
| Бот: download-callback и reassign (`src/bot/handlers/callbacks.py`) | `test_bot_download_callback.py` | доставка аудио + отметка в БД, ошибка доставки не тонет в фоновой задаче, повторное скачивание отклоняется, single-flight при повторном нажатии, reassign чистит Spotify до БД | — |

## Не покрыто (осознанно)

- `src/sources/bandcamp_source.py` — селекторы не сверены с живым сайтом;
  тесты закрепили бы выдумку. Сначала живая проверка потока.
- `src/bot/handlers/callbacks.py` — assign/reassign/expand (download-флоу и
  клавиатуры покрыты). Бэклог топ-3: happy path assign, guard дабл-клика,
  дедлайн 24ч у reassign.
- `electron/` (renderer, TS) — тест-инфры нет (нужен vitest — отдельное решение).
  Редизайн по дизайн-системе проверен вручную через Playwright (все три
  экрана, ⋯ меню с созданием жанра, мультиселект, поповер источников).
  Логика, которую стоит покрыть при заведении vitest: `fileMany`
  (оптимистичное обновление + откат при ошибке), выбор трёх picks под трек,
  автопереключение источника в поиске при падении выбранного.
- `src/spotify/poller.py` — пагинация >50 лайков и остановка по last_liked_at
  покрыты слабо (только базовые случаи).

## Починенные баги (все закреплены регрессионными тестами)

- Краш на `"track": null` от Spotify — в плейлистах
  (`test_playlist.py::test_null_track_items_are_skipped`) и в поллере
  (`test_poller.py::test_poller_skips_null_track_items`).
- `test_bot_commands.py::test_stats_auto_count` — `notin_(["manual", None])`
  никогда не совпадал, авто-счётчик всегда показывал 0.
- Потеря трека при сбое `on_new_track`: строка уже закоммичена, поэтому
  `track_exists` навсегда считал её обработанной
  (`test_poller.py::test_poller_continues_when_on_new_track_fails`).
- Тихая ошибка доставки в фоновой задаче скачивания
  (`test_bot_download_callback.py::test_delivery_failure_is_reported_not_swallowed`).
- Трек оставался в двух Spotify-плейлистах сразу: сайдкар не снимал его со
  старого, а бот чистил БД до вызова Spotify (`test_sidecar.py::
  test_assign_moves_track_between_playlists`, `test_bot_download_callback.py::
  test_reassign_removes_from_spotify_before_clearing_db`).
- Скачивание лайка через Soulseek/Bandcamp: результат собирался вручную из
  Spotify-id без `extra` → пустые username/filename. Теперь не-Spotify
  источники ищутся через `search()` (`test_context.py::
  test_download_liked_track_searches_non_spotify_sources`).
- Двойное скачивание одного трека из разных процессов (бот и сайдкар держали
  guard в своей памяти): claim перенесён в БД — `download_started_at` +
  условный UPDATE (`test_repos.py::test_claim_download_is_exclusive` и
  соседние; протухший claim перехватывается, чтобы упавший процесс не
  блокировал трек навсегда).

## Открытые баги (НЕ закреплены тестами — требуют решения)

- Бот не проверяет chat_id/user_id: любой, кто напишет боту, может дёрнуть
  `/fetch`, назначение и скачивание. Возможно, осознанно для приватного бота —
  требует решения владельца.
- Сайдкар без `SIDECAR_AUTH_TOKEN` доверяет origin `null` (иначе не работает
  упакованный рендерер на `file://`), а его же присылает sandboxed-iframe с
  любого сайта. Electron-приложение токен генерирует само; для standalone-
  запуска (VPS) его нужно прописать в `.env`.
