# ТЗ №4 — Илияр: Backend real-time engine и игровые правила

**Ветка:** `feature/iliyar-game-engine`  
**Репозиторий:** `ibrodevs/among-us-backend`  
**Стек:** Django Channels + Django REST Framework, Redis Channel Layer, PostgreSQL, ASGI.  
**Владение:** `game/**` (модели, migrations, routing, consumers, services, state machine, tests). Совместные `config/**` и `rooms/**` согласовать с Кутманом.

## 1. Результат
Создать **серверно-авторитетную многопользовательскую игру**: один матч на комнату, 4–10 участников, создание секретных ролей, старт матча, перемещения, задания, убийства, тела, экстренное собрание, голосование и победа по правилам. Игра синхронизирует состояние через WebSocket и выдерживает повторные сообщения, переподключения и недопустимые действия. Клиент — только интерфейс, никогда не решает, убит ли игрок или кто победил.

## 2. Базовые правила MVP
- Игроки 4–6: **1 предатель**; 7–10: **2 предателя**. Роли распределяются случайно через `secrets.SystemRandom` / secure randomness один раз при старте.
- Каждому члену экипажа назначить **3** task assignments из заранее описанных точек карты.
- Одна оригинальная карта, логический размер 1600×900. Стартовые позиции не должны пересекаться со стенами.
- Ходьба max 150 px/sec, коллизии с геометрией стен, нормализация диагонали, server-side limit на частоту.
- Kill доступен только живому предателю против живого не-предателя, если расстояние ≤90 px, cooldown **25 секунд**, phase=playing; после убийства появляется body. Никто не может убить себя/товарища-предателя.
- Report доступен живому игроку не дальше 110px от видимого body (body не должно быть уже reported). Emergency доступен живому игроку 1 раз за матч.
- Meeting: обсуждение 30 sec, голосование 30 sec. Голосовать могут только живые участники, 1 голос/meeting; `target_player_id=null` — skip. По истечении таймера подсчитать, даже если не все проголосовали. При tie/победе skip никто не исключается; при большинстве одной цели игрок исключается из живых.
- После встречи игра возвращается на карту, если не наступила победа.
- Победа **экипажа**, если все назначенные задачи выполнены или все предатели устранены. Победа **предателя**, если живых предателей ≥ живых членов экипажа, и предателей хотя бы один. Точку проверки победы вызывать после убийства, изгнания, выхода игрока, завершения заданий.
- Игроки, признанные мёртвыми, не голосуют, не убивают, не завершают задания и не вызывают новые встречи. Они могут наблюдать (без возможности менять состояние мира).
- Выход/потеря соединения: краткий disconnect сохраняет состояние до reconnect, не считается мгновенной смертью. Явный leave mid-match обрабатывается сервером как выбывание по согласованному правилу и может завершить матч.

## 3. State machine
`waiting → playing → meeting (discussion → voting → result) → playing → ... → finished`. 
- Чёткие переходы; rollback/повторный start не создаёт повторно роли/задачи.
- Таймеры считать по UTC server timestamps (`phase_deadline_at`), клиентские часы не считаются достоверными.
- `game.ended` фиксирует winner=`crew|impostor`, reason, finished_at. После finished команды движения/убийства/голосования отклоняются.
- Одно активное состояние GameSession на Room; уникальные ограничения для vote per meeting/player, task completion per assigned task.
- В модели хранения предусмотреть GameSession, PlayerGameState(private role, alive, position, last_move_at, kill_available_at), TaskAssignment, Corpse, Meeting, Vote; создать migrations **внутри game/**.
- Игровой код `game/services/`: отдельно start, movement validation, tasks, kill/report, meeting/voting, win evaluator, snapshots. Consumers должны быть thin: parse → authorize → delegate → broadcast.
- Конкурентные действия сериализовать через transaction.atomic + select_for_update или детерминированную комнатную очередь. Не создавать два параллельных таймера игры для одной комнаты.

## 4. Game start endpoint
`POST /api/v1/games/{code}/start/` в `game/views.py`.
- Guest authentication стандартный. Проверить членство, host_id, waiting, 4≤count≤10.
- 401/403/404/409 для invalid scenarios. Success 200 Room DTO (status playing), а приватная роль/задачи — **только в личный WebSocket**.
- Создать GameSession и PlayerGameState в одной транзакции. Установить начальные координаты/секретные роли/задачи, запустить timer ownership.
- В конце оповестить игроков `room.snapshot`, `game.started`, `game.snapshot`; приватные роли отправлять отдельно. Не group-send role map.
- Если у участника сокет отвалился, авторизация после reconnect отдаёт его приватное состояние только ему.

## 5. WebSocket transport и безопасность
- Путь `ws(s)://host/ws/rooms/{6-CHAR-CODE}/`.
- На connect принять только временный **unauthenticated** socket с лимитом времени до первого auth frame. Первый клиентский JSON обязан быть `{"type":"auth","token":"..."}`.
- Проверить signing/TTL и Membership. Успех `auth.ok`; неуспех `error:UNAUTHORIZED`, close 4401. Никогда не использовать URL query token.
- `room.snapshot` содержит только публичный Room DTO. `game.snapshot` содержит публичную фазу, игроков и координаты/живой статус, тела, таймеры, aggregate tasks; **нет ролей живых игроков**.
- `game.started`/ `game.self` приватным событием конкретному connection/send group каждого игрока сообщить только его role, task IDs, cooldown.
- На rejoin в running game отправить публичный snapshot + собственные секретные данные. Не выдавать роли по GET Room.
- Каждый input связан с ID из подписанного токена; `player_id`, присланный клиентом, не является источником прав.
- Каждое сообщение должно иметь `type`, ограничение размера, валидируемые типы и диапазоны, антиспам/ratelimit; unknown type → structured error, не 500.

## 6. Client messages
Сохранить `docs/API-CONTRACT.md` фронтенда. Обязательные команды:
- `player.move`: `{"type":"player.move","seq":12,"direction":{"x":1,"y":0}}`. Команда задаёт только направление, не координаты. Проверить seq > last_seq, length finite, скорость, стены, фазу.
- `task.complete`: `{"type":"task.complete","task_id":"uuid"}`. Валидировать назначенную задачу, роль crew, alive, within interaction radius, incomplete; duplicate должен быть no-op/controlled error.
- `player.kill`: `{"type":"player.kill","target_player_id":"uuid"}`; security above.
- `body.report`: `{"type":"body.report","body_id":"uuid"}`; body valid, range, alive.
- `meeting.call`: один раз/живой/игра, из указанной точки emergency console (взаимодействие рядом).
- `vote.cast`: `{"type":"vote.cast","target_player_id":"uuid-or-null"}`; только discussion→voting, нельзя голосовать за dead/missing.
- `ping`: вернуть `pong`.
Строго ограничить input частоту; запрещённые по правилам actions → `error` с кодами `INVALID_PHASE`, `FORBIDDEN`, `OUT_OF_RANGE`, `COOLDOWN`, `ALREADY_DONE`, `BAD_PAYLOAD`.

## 7. Server messages
- `auth.ok {player_id}`;
- `room.snapshot {room}`;
- `game.started {room_code, started_at, role, tasks}` **приватно**;
- `game.snapshot {phase, players:[id,nickname,x,y,alive], bodies, tasks_completed, tasks_total, deadline_at, seq/version}` публично;
- `player.moved {player_id, x,y,seq}`;
- `player.died {player_id}`; `body.spawned {body_id,x,y}`;
- `task.progress {completed,total}`;
- `meeting.started {meeting_id, stage, discussion_ends_at, voting_ends_at, reporter_id}`;
- `vote.updated {votes_cast, alive_voters}` (не раскрывать, кто кого выбрал до конца, если правила не требуют);
- `meeting.ended {ejected_player_id|null, counts, next_phase}`;
- `game.ended {winner, reason, players_with_roles}` только после завершения;
- `pong`, `error {code,detail}`.
Конкретные TypeScript-compatible JSON payloads зафиксировать в `docs/WS-EVENTS.md` этого репозитория и синхронизировать с Байэлом. Изменения формата сначала обсудить с frontend.

## 8. Разрыв связи, консистентность и производительность
- Client disconnect не удаляет участника, а помечает online presence. Reconnect возвращает тот же state через старый Guest token.
- Две вкладки одного игрока: определить политику single-active-connection или connection-count; старый disconnect не должен сбрасывать online=true нового.
- Ключевой match state хранить в БД; redis — transport / cache / locks, не единственное durable storage.
- В одной комнате ≤10 игроков. Целевой broadcast движения до 10 snapshots/sec, отдельные immediate events; не писать каждый render frame в БД.
- Часы фазы/таймеры нужны независимо от присутствия всех клиентов. Для MVP допускается один авторитетный ASGI game-worker с явным ограничением deployment; при нескольких воркерах нужен lock/leader election, иначе двойные тики/встречи.
- При ошибке Redis/DB логировать trace на сервере, клиенту отправить безопасный error. Не терять корректность vote/win при race.
- Тестировать 10 параллельных WebSocket clients, reconnect, late join (запрещён), duplicate move/vote/task messages.

## 9. Тесты (минимум 20 сценариев)
1. Start запрещён гостю не-хосту, room <4 игроков и повторному start.
2. Role count 4/6/7/10 игроков; роли не появляются в public snapshot.
3. Role distribution randomly; impostor never gets a crew task.
4. Unauthenticated websocket, bad token, чужая комната, malformed JSON.
5. Auth after reconnect сохраняет self-role/позицию/phase.
6. WASD diagonals normalise; wall collision, speed hack, seq replay, too-fast commands.
7. Kill: crew denied, impostor-to-impostor denied, range denied, cooldown, self-kill, dead target, duplicate.
8. Tasks: чужой task, слишком далеко, задача выполнена, общий прогресс.
9. Body report: too far / already reported / dead sender / valid.
10. Emergency once / away from console.
11. Meeting phase timers, reject kill/move/tasks during meeting.
12. Vote dead/unknown target, vote twice, skip, tie and majority.
13. Crew wins via all tasks and via last impostor ejected.
14. Impostor wins at parity after kill/leave.
15. No premature winner at start.
16. Disconnection doesn't kill; reconnect sync.
17. Two concurrent votes or kills don't create inconsistent state.
18. Finished game rejects all action; final state stable on reconnect.
19. 10 clients movement broadcast has bounded rate and CPU.
20. Verify leaks absent: public payload/logging never includes live role for another player.
Все важные тесты должны работать с PostgreSQL транзакциями. Для Channel tests можно использовать `channels.testing.WebsocketCommunicator` и изолированный in-memory layer в тесте, не в production.

## 10. Этапы / приёмка
**A.** Data models/migrations + start endpoint + роли без утечек.  
**B.** Авторизация WS, movement, snapshots, reconnect, серверные коллизии.  
**C.** Tasks/kill/report/meeting/votes/finish + concurrency/reconnect/load tests.

Definition of done: 4+ игрока запускаются, каждый видит только свою роль, позиции синхронизированы, правила работают и после reconnect, сервер отбрасывает cheating, meeting/voting/win не зависят от клиента, тесты зелёные и PR согласован с Кутманом/Байэлом.
