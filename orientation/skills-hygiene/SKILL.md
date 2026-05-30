---
name: skills-hygiene
description: "HARD RULE — выполненные задачи НЕ должны проникать в общие skill-файлы. Регламент: куда писать lessons-learned (memory tool / hindsight bank — да; SKILL.md общих скиллов — НЕТ); как анонимизировать примеры; что считается «загрязнением». Load WHENEVER ты собираешься записать урок / шаблон / lesson во время или после real-проекта."
allowed-tools: "read_file write_file edit_file"
metadata:
  hermes:
    tags: [meta, hygiene, skill-maintenance, hard-rule]
    related_skills: [evo-memory, self-critique, chief-manager, desire-to-goal]
---

# skills-hygiene — реальные задачи НЕ проникают в общие skill-файлы

## Хард-правило (severity: критично)

> Skill-файлы — это **обобщённые паттерны и инструкции**, а не журнал
> того, что ты делал в конкретном проекте.

**Конкретные board-id, chief-id, имена проектов, числа из реального
эксперимента, цитаты «Lesson 2026-MM-DD <real-project> сделал X»,
ссылки на real-paper-trades / live-deployment runs, домены конкретных
real-юзеров — НЕ ПИШУТСЯ в SKILL.md / references/\*.md общих скиллов.**

Skills читаются ВСЕМИ агентами и сессиями. Если ты впишешь в общий
skill «integration задокументирована из live deployment 2026-05-23,
board `chief-myproj-abc123`», то:

1. Следующая сессия с похожим запросом увидит этот текст и решит, что
   контекст уже есть — пропустит прояснение.
2. F1-тесты (orientation/desire-to-goal) будут фейлиться, потому что
   бот будет говорить «знаю» вместо «спроси заново».
3. Privacy-граница ломается: между разными проектами/пользователями
   нет изоляции, если skill держит конкретику одного из них.

## Что МОЖНО писать в общий skill

- Анонимизированные паттерны: «когда chief блокируется на OAuth-credentials,
  корректное поведение — ждать пока user даст». БЕЗ указания какого
  chief / какого проекта.
- Шаблоны вида `<example-chief-id>`, `<board-name>`, `<your-project>`.
- Lessons общего вида: «cron silently fails to persist if name collides
  → всегда verify через `cronjob(list)`». Без названия конкретного crona.
- Архитектурные правила, антипаттерны, чек-листы.

## Что НЕЛЬЗЯ писать в общий skill

- Имена конкретных chief-board-id (`chief-polymarket-paper-ac2ba3`,
  `chief-myproj-abcd12`).
- Имена конкретных проектов real-пользователя (Polymarket-trading-bot,
  CryptoBot-Bybit, любой реальный customer's project name).
- Конкретные числа из live-эксперимента («edge 6.7%/month», «$1000
  bankroll», «hit rate 62%»).
- Цитаты из real conversations с конкретными user'ами.
- Hardcoded board-paths типа `/opt/data/kanban/boards/chief-X-Y/kanban.db`
  с реальным `X-Y`. Только `<chief-id>` / `<board-name>` placeholders.
- Любая дата «captured from <real-session>» с привязкой к real-проекту.

## Куда тогда писать lessons (правильные места)

| Что | Куда | Почему |
|---|---|---|
| **lesson из конкретного real-проекта** (конкретика + проект) | `memory` tool (store='memory') — твоя личная память | Изолировано от общих skills, видит только текущий агент |
| **факт о текущем user'е** (имя, предпочтения, контекст) | `memory` tool (store='user') — user profile | То же — изолировано |
| **observation для эволюции системы** | hindsight bank (через `hindsight_retain`) | Изолированный bank, retrievable через `hindsight_recall` по таскам |
| **анонимизированный архитектурный паттерн** | общий SKILL.md | Это и есть назначение skills |
| **детальный snapshot real-проекта** (167-line integration notes) | НЕ в skill вообще; кода и docs внутри workspace проекта | Workspace — это где живёт сам проект |

## Перед записью урока — фильтр

Прежде чем сделать `edit_file` или `write_file` на любой `~/.hermes/skills/**/*.md`:

1. Проверь — у тебя в добавляемом тексте есть:
   - конкретный chief-id / board-id / repo-name? → REWRITE: используй `<placeholder>`.
   - название real-проекта (Polymarket, Bybit, etc.) если это **не общий пример**? → REWRITE: используй `<example-project>` или укажи общее «trading bot project» / «forecasting project».
   - числа из live-эксперимента? → REWRITE: пиши категорийно («single-digit-% monthly edge», без «6.7%»).
   - дату с «captured from live session» / «from prior deployment»? → REWRITE на «Lesson <date>» без указания источника-сессии.
2. Если хочется зафиксировать конкретику — переключайся на `memory(store='memory')` или `hindsight_retain`. НЕ в skill.

## Recovery если ты уже нарушил

Если обнаружил что в SKILL.md уже есть конкретика real-проекта:

1. Не редактируй слепо. Сначала перенеси конкретику в `memory(store='memory')`
   с тегом проекта.
2. Затем сделай `edit_file` на SKILL.md: замени конкретику на placeholder.
3. Проверь нет ли таких же хвостов в `references/*.md` под этим skill'ом.

## Связь с другими skill'ами

- `evo-memory`: пишет в IDEAS / EXPERIMENTS memory stores — там конкретика
  ОК (private memory). Но `evo-memory/SKILL.md` сам должен быть generic.
- `self-critique`: проверяет полноту работы — может выявить «ты добавил
  domain-specific lesson в общий skill».
- `chief-manager`: одна из главных точек куда писались lessons. Все
  «(Lesson 2026-MM-DD chief-X-Y...)» теперь анонимизируются.
- `desire-to-goal`: вместе с этим skill образует пару «прояснение цели +
  гигиена накопления знаний» — без второго первый загрязняется во
  времени.

## Real case 2026-05-24

Реальный случай:
- `chief-manager/SKILL.md` содержал 3 строки «Lesson 2026-05-22/-23
  chief-polymarket-…» + ссылку на `references/polymarket-integration.md`
  (167 строк live-deployment notes).
- `kanban-pm-monitor/SKILL.md` имел hardcoded `BOARD = "chief-polymarket-paper-ac2ba3"`.
- F1-тест на хотелку «Запусти систему для prediction-market betting»
  → бот прочитал эти файлы → ответил «интеграция задокументирована из
  предыдущих сессий, спавню чифа» вместо чистого прояснения.
- Lesson: skill-файлы — это публичное знание; live-конкретика принадлежит
  memory / hindsight / workspace, не shared skills.
