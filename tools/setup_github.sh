#!/usr/bin/env bash
# Первичная настройка GitHub: метки, доска «AIRA», стартовые задачи, защита main.
# Запуск (после `gh auth login` и создания репозитория):
#   OWNER=<организация или логин> REPO=aira bash tools/setup_github.sh
set -euo pipefail
: "${OWNER:?укажите OWNER}"; : "${REPO:=aira}"
R="$OWNER/$REPO"

echo "== метки"
while IFS='|' read -r name color desc; do
  gh label create "$name" --repo "$R" --color "$color" --description "$desc" --force >/dev/null
done <<'EOF'
engine|5319e7|ML-движок и модели
app|1d76db|Десктопное приложение
design|e99695|Интерфейс и макеты
contract|fbca04|Контракт приложение ↔ движок
research|0e8a16|Кастдев, ресерч, пилоты
nir|c5def5|НИР: отчёт, дневник, презентация
data|bfdadc|Данные и разметка
bug|d73a4a|Ошибка
EOF

echo "== доска"
PROJECT=$(gh project list --owner "$OWNER" --format json 2>/dev/null | python3 -c 'import json,sys; print(next((str(p["number"]) for p in json.load(sys.stdin)["projects"] if p["title"]=="AIRA"), ""))' 2>/dev/null || true)
if [ -z "$PROJECT" ]; then
  PROJECT=$(gh project create --owner "$OWNER" --title "AIRA" --format json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["number"])' 2>/dev/null || true)
fi
if [ -n "$PROJECT" ]; then
  gh project link "$PROJECT" --owner "$OWNER" --repo "$R" >/dev/null 2>&1 || true
  echo "  доска AIRA: №$PROJECT"
else
  echo "  доску создать не удалось — нужно право project: gh auth refresh -s project, затем перезапустить скрипт"
fi

echo "== задачи"
issue() {   # заголовок | метки | описание
  url=$(gh issue list --repo "$R" --state all --search "in:title \"$1\"" --json title,url --jq ".[] | select(.title==\"$1\") | .url" | head -1)
  [ -z "$url" ] && url=$(gh issue create --repo "$R" --title "$1" --label "$2" --body "$3")
  [ -n "$PROJECT" ] && gh project item-add "$PROJECT" --owner "$OWNER" --url "$url" >/dev/null 2>&1 || true
  echo "  + $1"
}
issue "Согласовать контракт движка v1" "contract" "Прочитать contracts/engine-api.md и примеры. Замечания — комментариями к этой задаче. Когда готово: обе стороны одобрили, контракт заморожен как v1."
issue "Каркас десктопа: запуск движка и /health" "app" "Electron или Tauri. Приложение запускает движок, читает первую строку stdout (порт, токен), показывает статус /health. Когда готово: окно с версией движка и пакета моделей."
issue "Редактор: вставка текста и импорт md/docx" "app" "Главный ввод — вставка. Импорт .md/.docx. Разбор через /v1/parse, подсветка по offset. Когда готово: вставил текст — видны фрагменты."
issue "Панель замечаний: типы, светофор, отклонение" "app,design" "По /v1/review: тип, красный/жёлтый, объяснение, второй фрагмент. Отклонить замечание, отключить тип (dismissed, disabled_types). Когда готово: ревью документа «Возвраты» из contracts/examples."
issue "Кнопка «Проверить влияние правки»" "app,design" "У изменённого пункта — вызов /v1/impact, список задетых мест со ссылками на них в редакторе."
issue "Макет: экран ревью по контракту" "design" "Обновить макет под поля контракта: светофор, второй фрагмент со статусом, вопросы «что уточнить», отключение типов."
issue "Пакет моделей 0.1 в Releases + проверка sha256" "engine" "Выложить models-0.1.zip в Releases; движок при старте сверяет sha256 из manifest.json."
issue "Модель v2: пары на декомпозицию и «соседние пункты»" "engine,data" "Синтетика «верхнее → детальное требование» по 30 доменам + соседние пункты как нейтральные для NLI. Повторить D12-ru. Порог: точность 🔴 на D12-ru ≥ 30 %."
issue "Сборка движка в бинарник (PyInstaller/Nuitka)" "engine,app" "Чтобы пользователю не нужен был Python. Размер, время старта, проверка на чистой Windows."
issue "Запустить форму кастдева и собрать 10 ответов" "research" "Скрипт формы — в папке проекта. Каналы: студии заказной разработки, интеграторы 20–100 человек."
issue "Интервью с 3 студиями заказной разработки" "research" "Вопросы — по гайду кастдева, обязательно про последнее изменение ТЗ: сколько мест правили, что пропустили."
issue "Промежуточная презентация НИР 3" "nir" "Общая часть + по 5 минут на каждого. Цифры H1/H2 — из engine/docs/experiment.md."

echo "== защита main (PR + 1 ревью, без force-push)"
gh api -X PUT "repos/$R/branches/main/protection" --input - >/dev/null <<'EOF' || echo "  защита не включилась: на бесплатном тарифе для приватных репозиториев организации она может быть недоступна"
{"required_status_checks": null, "enforce_admins": false,
 "required_pull_request_reviews": {"required_approving_review_count": 1},
 "restrictions": null, "allow_force_pushes": false, "allow_deletions": false}
EOF
echo "готово: https://github.com/$R  и доска в https://github.com/orgs/$OWNER/projects (или users/$OWNER/projects)"
