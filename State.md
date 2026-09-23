# State.md

- [2026-09-23] Инициализирован отдельный Git-репозиторий для публикации Telegram-парсера | .git | local_ready

- [2026-09-20] Создан MVP агрегатора ссылок Telegram | app.py, collector.py, parser.py, database.py | done
- [2026-09-20] Добавлены SQLite-история, дедупликация, стартовые каналы и журнал запусков | data/, logs/ | done
- [2026-09-20] Добавлена инструкция Streamlit Cloud/PythonAnywhere и Mermaid-архитектура | README.md | done
- [2026-09-20] Выполнены compileall и smoke-тесты SQLite/HTML, удалены временные артефакты | *.py | verified
- [2026-09-20] Исправлены PowerShell-инструкции и быстрый выход при недоступном t.me | README.md, parser.py | done
- [2026-09-20] Добавлен быстрый выход для asyncio timeout и connect-timeout 4с | parser.py | verified
- [2026-09-20] Проверен запуск Streamlit на 8502: 10 каналов завершились timeout t.me, SQLite записал run errors=10 без падения | data/telegram_links.sqlite3, logs/ | diagnosed
- [2026-09-20] Добавлены allowed_domains, строгая фильтрация URL и UI управления белым списком; история до миграции сохранена, но скрыта из чистой выдачи | database.py, parser.py, app.py | done
- [2026-09-20] Добавлены переключатель Русский/English в Streamlit и двуязычный README с русским разделом по умолчанию | app.py, README.md | done
