# ТЗ №3 — Кутман: Backend, гостевая авторизация и комнаты

**Ветка:** `feature/kutman-rooms-api`  
**Репозиторий:** `ibrodevs/among-us-backend`  
**Стек:** Django 5.2, Django REST Framework, PostgreSQL, Redis/Channels на интеграции.  
**Владение:** `players/**`, `rooms/**`, миграции этих приложений; общие изменения `config/**` — согласовать с Илияр.

## 1. Результат
Сервер предоставляет устойчивый, безопасный REST API гостевых игроков и комнат. Пользователь получает подписанный guest-token, создаёт комнату с кодом, приглашает участников, проверяет статус лобби, выходит. Сервер надёжно защищает комнаты и определяет полномочия хоста, не допускает превышения лимита и не теряет целостность базы при параллельных запросах. Все данные готовы к подключению игрового движка Илияра.

## 2. Структура и ответственность
- `players/models.py`: Player(UUID, nickname, created_at). При необходимости last_seen / revoked_at с миграцией и тестами.
- `players/authentication.py`: подпись и проверка guest token. Срок действия 24h, invalid signature → 401, отсутствие заголовка → 401 на защищённых endpoints.
- `players/serializers.py`, `players/views.py`, `players/urls.py`: создание гостевой сессии.
- `rooms/models.py`: Room, RoomMembership, unique constraints, host, status, creation timestamp. Минимум 4/максимум 10 игроков.
- `rooms/services.py`: secure room code generation, atomic transactions; бизнес-логика вне views при росте сложности.
- `rooms/serializers.py`, `rooms/views.py`, `rooms/urls.py`: все REST методы лобби.
- `rooms/tests.py` (можно вынести в `rooms/tests/`): полноценные тесты.
- `config/settings.py`: only with coordination; env and CORS, production security.

## 3. REST API — фиксированный контракт
Все пути начинаются с `/api/v1/`. JSON snake_case. Использовать `Authorization: Guest <signed-token>`. Стандартизировать ошибки `{"detail":"..."}`.

### 3.1 POST /guests/
Request `{"nickname":"Ibro"}`. Ответ 201 `{"player_id":"uuid","nickname":"Ibro","token":"opaque signed token"}`.
- Ник 2–16 символов после trim. Разрешить русские/английские буквы, цифры и корректный Unicode; отклонять пустой/пробельный ник.
- Не позволять клиенту задавать UUID, время выпуска токена, статус.
- Токен ограничен серверным 24h TTL, подписан SECRET_KEY, не хардкодить ключ в Git.
- Обеспечить ограничение частоты создания гостей (например 10 запросов в минуту/IP на старте, но учесть прокси и тесты), чтобы не засоряли базу.
- Никаких обычных паролей, email и регистрации в MVP.

### 3.2 POST /rooms/
Request `{"max_players":10}`, значение 4–10, по умолчанию 10. Ответ 201: Room DTO.
- Только авторизованный Guest; создатель становится host и первой записью Membership.
- `code` — 6 uppercase символов генерирует только сервер через cryptographically secure random; уникальный индекс в БД.
- При кодовой коллизии безопасно повторить генерацию внутри транзакции; при серьёзном DB error не делать бесконечные retry.
- Возвращать status `waiting`, `min_players=4`, `max_players`, `host_player_id`, `players`, `created_at`.
- Один пользователь может иметь несколько ожидающих комнат? Для MVP выбрать и задокументировать ограничение; рекомендуем разрешить создание нескольких для простоты, но не соединять их игровое состояние.

### 3.3 POST /rooms/join/
Request `{"code":"AB12CD"}`. Ответ 200 Room DTO.
- Формат uppercase 6 символов: 400 для неверного формата; 404 для отсутствующей комнаты.
- Не принимать join, если status не waiting (409), комната заполнена (409), ник уже занят другим участником (409).
- Повторный запрос от того же Player по тому же коду — идемпотентный 200 без новой membership.
- Конкурентный join: `transaction.atomic()`, `select_for_update()` по Room и защита unique constraint; два человека не должны занимать последнее место одновременно.
- При успешном join уведомлять Илияра через согласованный сервис/сигнал для `room.snapshot`; нельзя напрямую модифицировать `game/**` без договорённости.

### 3.4 GET /rooms/{code}/
Ответ 200 Room DTO только для действующих участников с этим guest token.
- Чужой Guest не получает закрытый список игроков: 403; несуществующий код: 404.
- DTO содержит Player UUID, nickname, is_host, is_connected — **не** роль, секретные задания, session keys или raw tokens.
- GET без побочных эффектов, поддерживать частые запросы от лобби (2–3 sec fallback), избегать N+1 queries на длинном списке.

### 3.5 POST /rooms/{code}/leave/
Ответ 204 (пустой body) в лобби. 
- Удалить membership в атомарной транзакции; если уходит хост, назначить нового по joined_at.
- Если ушёл последний, удалить пустую комнату либо пометить expired (выбрать политику, покрыть тестами). Bootstrap удаляет сразу.
- Неверный токен → 401, не участник → 404/403 (выбрать единый ответ).
- **Важно:** текущий scaffold возвращает 409 при выходе из запущенного матча. Совместно с Илияр реализовать hook для выхода в фазах playing/meeting и пересчёт win condition, затем выполнить полный контракт.

### 3.6 GET /health/
200 `{"status":"ok"}`; не включать секреты, персональные данные, приватную базовую статистику.

## 4. Модель БД
Player: UUID PK, nickname max16, created_at. 
Room: UUID PK, code unique, status enum waiting/playing/meeting/finished, host FK, max_players, created_at.
RoomMembership: UUID PK, room FK, player FK, joined_at, is_connected; unique(room, player).
- Индексы для code и пары room/player; DB-level unique constraint.
- Никаких cascade-delete активных матчей без согласования с Илияр.
- Миграции обязаны храниться в git; изменения первоначальных миграций после начала разработки не переписывать, создавать новую `0002...`.
- В production PostgreSQL. Локальный SQLite допустим, но блокировки `select_for_update` в SQLite не заменяют concurrency тесты PostgreSQL.

## 5. Ошибки и безопасности
- 400 — некорректный nickname, код или max_players.
- 401 — отсутствует/неверен/истёк guest-token.
- 403 — чужая приватная комната.
- 404 — код не найден.
- 409 — полная/запущенная комната, занятый ник или конфликт состояния.
- 500 — реальная ошибка сервера, без раскрытия внутренних SQL/токена.
- CORS разрешает только `CORS_ALLOWED_ORIGINS`; сервер не должен делать wildcard в production.
- Не доверять `X-Forwarded-For` от неустановленного прокси для rate limits; не логировать raw auth header.
- Serializer/permissions проверять для каждого эндпоинта; приватность ролей относится и к Django Admin доступам API.

## 6. Тесты (минимум 15 сценариев)
1. Guest 201; ник 1/2/16/17 символов, пробельный, Unicode.
2. Токен отсутствует/искажён/истёк.
3. Room 201 и host — первый участник; уникальный шестизначный код.
4. max_players 3/4/10/11.
5. Join 200, повторный join не дублируется.
6. Code неверного формата/несуществующий.
7. Разные участники с одинаковым nickname.
8. Полная комната: 409.
9. Начатая игра: 409 при join.
10. Чужой GET: 403.
11. Host leave передаёт host следующему участнику.
12. Последний leave очищает комнату.
13. Два параллельных join на последнее место при PostgreSQL.
14. 10 последовательных GET не вызывают N+1 роста.
15. API не выдаёт роль, токен и secret-поля.
16. Health отвечает без авторизации.
17. Rate-limit и safe error handling, если включены.

## 7. Интеграция
- Ибро потребляет все REST API, имена полей менять только через согласование.
- Ильяр читает Room/RoomMembership, реализует start и WS. Предусмотреть интерфейс для `lobby_changed(room_code)`, не импортировать game внутри моделей через циклический import.
- `is_connected` сейчас обновляет Game WebSocket consumer; совместно решить многовкладочность и stale-disconnect (простая bool не всегда надёжна).
- Проверки: `python manage.py check`, `python manage.py makemigrations --check --dry-run`, `python manage.py test`.

## 8. Этапы / приёмка
**A.** Модели, миграции, API и документация; воспроизводимый локальный старт.  
**B.** Полные permission/validation/concurrency/rate-limit тесты.  
**C.** Реальное обновление лобби при join/leave, игра с Илияр, миграции и PR.

Definition of done: два фронтенда в разных браузерах могут безопасно создать/войти/выйти из одной комнаты, GET не раскрывает чужие данные, конкурентный join не превышает max_players, тесты проходят на PostgreSQL, PR в main со списком endpoint, миграций и тестов.
