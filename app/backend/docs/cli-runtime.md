# Локальный Codex CLI для Ralph

Проверено 17 сентября 2026 года на macOS arm64. Первый запуск установленного CLI 0.149.1 остановился до изменения кода: сервер сообщил, что настроенная модель `gpt-6-astra` требует более новой версии Codex.

В `.runtime/codex-cli` установлен официальный **Codex CLI 0.154.0**, последний стабильный релиз по GitHub Releases API на момент проверки. В примечаниях к этому релизу указана поддержка GPT-6 Astra. Версия и наличие нужных аргументов проверены локально. Следующий запуск смог обратиться к модели, но остановился при запросе разрешения на чтение файлов. После проверки исходников runner настроен на штатный `--approve-for-me`, соответствующий режиму `auto_review`, явно указанному в основной сессии Codex.

Источники:

- [Официальная документация Codex CLI](https://learn.chatgpt.com/docs/codex/cli).
- [Релиз OpenAI rust-v0.154.0](https://github.com/openai/codex/releases/tag/rust-v0.154.0), опубликован 9 сентября 2026 года.
- [Метаданные последнего стабильного релиза](https://api.github.com/repos/openai/codex/releases/latest).
- [Пакет для macOS arm64](https://github.com/openai/codex/releases/download/rust-v0.154.0/codex-package-aarch64-apple-darwin.tar.gz).

Пакет содержит CLI и вспомогательные исполняемые файлы. SHA-256 скачанного архива совпал с `digest` официальных метаданных релиза:

```text
427ca74c027049e0cd1a330d611e7f8d1fe0f1eb6a6d85ac16f61bcf2cb4a485
```

SHA-256 распакованного `bin/codex`:

```text
4f85982624b3898c8991cb80c0981b2aa71070e3537046c9a95950318a95afcc
```

Метаданные и контрольные суммы сохранены в локальном `.runtime/codex-cli/installation.json`; исходные метаданные — в `release.json`. Весь `.runtime/` исключён из Git.

## Запуск

Из корня проекта:

```bash
bash scripts/ralph.sh --task T01-01 --dry-run
bash scripts/ralph.sh --task T01-01 --max-iterations 3 --agent-timeout 600
```

Обёртка ставит `.runtime/codex-cli/bin` первой в `PATH` только для данного процесса и использует Python из `.venv`. Существующие модель, провайдер и авторизация сохраняются. Runner вызывает `codex exec --approve-for-me ...`. Этот режим задаёт `on-request`, автоматического проверяющего `auto_review` и песочницу `workspace-write`; проверки разрешений и ограничения устройства продолжают действовать.

При отсутствии локального CLI запуск останавливается; автоматического перехода на системную версию нет. Прямой запуск `scripts/ralph.py` продолжает выбирать `codex` из переданного ему `PATH`. Dry-run сообщает запрашиваемые `approval_policy: on-request`, `approvals_reviewer: auto_review`, `sandbox: workspace-write`; постоянные настройки политики не меняются. Если CLI сообщает об отклонении политики или reviewer управляемыми требованиями, runner останавливается без перехода к другой политике, даже если CLI вернул код 0.

Обновление выполнено только внутри проекта: глобальная установка CLI, файлы настроек, учётные данные и режим оплаты не изменялись.

## Почему используется --approve-for-me

Это вывод из официального исходника конкретного релиза, а не предположение по успешно разобранной команде `--help`:

1. Ветка `exec` наследует общие параметры CLI, но не отдельную TUI-политику `--ask-for-approval`. Поэтому добавленный перед `exec` глобальный `-a on-request` не исправлял запуск. [CLI, строки 1226–1241](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/cli/src/main.rs#L1226-L1241).
2. `exec` задаёт программное переопределение `approval_policy=Never`; оно имеет приоритет над `-c approval_policy=...`. [Exec, строки 563–569](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/exec/src/lib.rs#L563-L569), [приоритет конфигурации, строки 3650–3654](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/core/src/config/mod.rs#L3650-L3654).
3. При `AutoReview` конфигурация пересобирается без принудительного `Never`. Флаг `--approve-for-me` выставляет `auto_review`, `on-request` и `workspace-write`. [Exec, строки 745–777](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/exec/src/lib.rs#L745-L777), [общие параметры, строки 80–92](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/utils/cli/src/shared_options.rs#L80-L92).
4. `--approve-for-me` конфликтует с дополнительным `--sandbox` в той же команде. Поэтому отдельный аргумент песочницы не передаётся: требуемое значение уже задаёт режим. [Объявление флага, строки 43–50](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/utils/cli/src/shared_options.rs#L43-L50).

Использование этого штатного режима авторизовано для текущего запуска, поскольку основная сессия уже работает с `approvals_reviewer=auto_review`. При другом режиме основной сессии выбор reviewer нужно заново согласовать. Наличие флага и успешный dry-run сами по себе не доказывают успешное выполнение задачи: это подтверждает только фактический запуск и независимые проверки.

## Воспроизводимая установка этой версии

Следующие команды скачивают публичный пакет; токен GitHub не нужен. Выполнять из корня проекта. Перед заменой существующего runtime завершить использующие его процессы.

```bash
mkdir -p .runtime/codex-cli
curl --fail --silent --show-error --location \
  https://github.com/openai/codex/releases/download/rust-v0.154.0/codex-package-aarch64-apple-darwin.tar.gz \
  --output .runtime/codex-cli/codex-package-aarch64-apple-darwin.tar.gz
printf '%s  %s\n' \
  '427ca74c027049e0cd1a330d611e7f8d1fe0f1eb6a6d85ac16f61bcf2cb4a485' \
  '.runtime/codex-cli/codex-package-aarch64-apple-darwin.tar.gz' \
  | shasum -a 256 --check -
```

Продолжать только при успешной проверке контрольной суммы:

```bash
tar -xzf .runtime/codex-cli/codex-package-aarch64-apple-darwin.tar.gz \
  -C .runtime/codex-cli
.runtime/codex-cli/bin/codex --version
.runtime/codex-cli/bin/codex exec --help
```

Ожидаемая версия — `codex-cli 0.154.0`. Для следующего обновления заново проверить официальный релиз и его digest, затем зафиксировать новые значения в этом документе. Обёртка сама ничего не скачивает и версию автоматически не меняет.
