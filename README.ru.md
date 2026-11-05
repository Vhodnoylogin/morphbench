# Morphbench

Верстак для Windows: меши Skyrim NIF/TRI, морфы, шары охвата и капсулы столкновений
скелета. В версии 0.8.8 доступны Морфы, Коллайдеры, автоматизация CLI/HTTP и браузерные
плагины. Ищите меши по имени или пути слева, управляйте плагинами в отдельном меню.
В выпущенной 0.8.8 Физика отключена. В этой ветке разработки доступны редактор параметров
физики и статический просмотр коллизий CBPC; встроенной вкладки Body Slots нет.

[English](README.md) · [Руководство](src/main/README.ru.md) ·
[Установка](src/main/docs/install-layout.ru.md) · [Первый запуск](src/main/docs/quickstart.ru.md)

Это основной репозиторий исходников — [Vhodnoylogin/morphbench](https://github.com/Vhodnoylogin/morphbench).
Исходники выпущенных версий находятся в `main`; активная ветка разработки — `experimental/body-slots`.

| Путь | Назначение |
|---|---|
| [src/main/](src/main/) | рабочий Python, файлы браузера, переводы, исходники лаунчера, документация и сценарии упаковки |
| [src/test/](src/test/README.ru.md) | автоматические проверки, повторно используемые фикстуры и инструкции игровых тестов |
| `target/` | игнорируемые деревья сборки, сгенерированные значки, пакеты и отчёты |
| `mb.py`, `release.py` | диспетчеры рабочей копии, передающие запуск основным точкам входа в `src/main/` |
| [CLAUDE.md](CLAUDE.md), [AGENTS.md](AGENTS.md) | инструкции участникам и ассистентам |

Из корня рабочей копии, с Python 3.12 и указанными в документации зависимостями:

```text
python mb.py --help
python src/test/run.py
python release.py --list
```

Необязательный лаунчер Windows собирается командой `src\main\launcher\build.cmd`;
результат остаётся в `target/launcher/`. См. [сборку и правила выпуска](src/main/docs/building.ru.md).
Структура исходников не меняет установленные пакеты: они сохраняют
`root/Morphbench/{launcher,app,plugins}` и документированные точки входа.

Готовые выпуски находятся среди [файлов GitHub Releases](https://github.com/Vhodnoylogin/morphbench/releases)
и [файлов Nexus](https://www.nexusmods.com/skyrimspecialedition/mods/194795).
На GitHub есть отдельные релизы [Application 0.8.8](https://github.com/Vhodnoylogin/morphbench/releases/tag/v0.8.8)
и [Launcher v3](https://github.com/Vhodnoylogin/morphbench/releases/tag/launcher-v3).
Для первой установки скачайте оба пакета; если Launcher v3 уже установлен, достаточно
обновить Application. На Nexus обе части тоже остаются отдельными загрузками.
Необязательный `morphbench-nifly-corresponding-source.zip` содержит соответствующие
DLL исходники C/C++ сторонней зависимости Nifly/PyNifly. Для установки он не нужен.
В этом репозитории самих сторонних исходников нет — только закрепления и рецепт сборки.
Нативный хост запускает комплектный Python; окно запуска и сервер принадлежат Application.
Адаптеры Launcher v1/v2 сохранены. Перед установкой v3 сначала обновите Application.
Лицензия Morphbench — [GNU GPL v3](LICENSE); разработка ведётся с помощью
[Codex (OpenAI)](https://github.com/codex).
