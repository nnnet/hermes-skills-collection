# hermes-skills-collection

Наши кастомные навыки для **Hermes Agent** (`nousresearch/hermes-agent`).

Этот репозиторий содержит только **то что мы написали сами** — upstream
скиллы из `nousresearch/hermes-agent:skills/` НЕ копируются (они
auto-sync-ятся в `~/.hermes/skills/` при старте контейнера).

## Структура

```
hermes-skills-collection/
├── orientation/                  ← наша категория
│   ├── desire-to-goal/           ← submodule (см. ниже)
│   ├── capabilities-2026-05/
│   └── skills-hygiene/
├── devops/                       ← наши добавки в upstream-категорию
│   ├── chief-manager/            ← submodule
│   ├── self-critique/            ← submodule
│   ├── chief-load-balancing/
│   ├── failure-recovery/
│   ├── kanban-pm-monitor/
│   ├── profile-design/
│   ├── profile-loadout/
│   ├── soul-md-authoring/
│   ├── task-decomposition/
│   ├── workflow-postmortem/
│   ├── workflow-synthesis/
│   └── workflow-templates/
├── cmf-ynvrsty/
├── evo-memory/
├── paper-navigator/
├── research-ideation/
├── research-survey/
├── data-science/
├── diagramming/
├── domain/
├── dogfood/
├── gifs/
├── inference-sh/
├── media/
├── mlops/
├── research/
└── yuanbao/
```

## Submodules pattern

Heavy-lifecycle скиллы вынесены в отдельные репозитории `nnnet/hermes-skill-*`
со своей историей коммитов и version-tagging. Остальные skills живут
непосредственно в этом super-repo как обычные файлы — миграция в submodule
делается по мере необходимости (когда skill становится heavy-lifecycle).

### Текущие submodules

| Path | Repo | Почему отдельно |
|---|---|---|
| `orientation/desire-to-goal` | [hermes-skill-desire-to-goal](https://github.com/nnnet/hermes-skill-desire-to-goal) | F1 baseline iteration — heavy weekly evolution |
| `devops/chief-manager` | [hermes-skill-chief-manager](https://github.com/nnnet/hermes-skill-chief-manager) | Core orchestration — careful versioning |
| `devops/self-critique` | [hermes-skill-self-critique](https://github.com/nnnet/hermes-skill-self-critique) | Aegis Hermes-tier — independent quality gate |

### Добавить новый submodule

```bash
# 1. Extract skill into new repo
mkdir /tmp/new-skill && cp -r path/to/skill/* /tmp/new-skill/
cd /tmp/new-skill && git init && git add . && git commit -m "Initial"
gh repo create nnnet/hermes-skill-<name> --private
git remote add origin git@github.com:nnnet/hermes-skill-<name>.git
git push -u origin main

# 2. Remove from super-repo + add as submodule
cd /path/to/hermes-skills-collection
git rm -r path/to/skill
git submodule add git@github.com:nnnet/hermes-skill-<name>.git path/to/skill
git commit -m "Extract <name> to submodule"
git push
```

## Использование (Hermes integration)

### Первый клон

```bash
git clone --recurse-submodules \
  git@github.com:nnnet/hermes-skills-collection.git
```

### Обновить submodules до последних main

```bash
git submodule update --remote --merge
```

### Bind-mount в контейнер

В `infra/hermes/docker-compose.hermes-core.yml`:

```yaml
volumes:
  # Наши custom skills overlay на ~/.hermes/skills (поверх upstream auto-sync)
  - ../../sources/hermes-skills-collection:/opt/data/skills-custom:ro
```

Hermes skill scanner находит наши skills через `--skills-dir` или
конфигурацию аналогично upstream skills.
