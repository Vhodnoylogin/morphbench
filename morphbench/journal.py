"""Журнал: что писать решает уровень, куда писать - приёмники, и отказ одного приёмника
не уносит ни запись, ни программу.

Три вопроса здесь намеренно разделены, потому что их смешение уже стоило нам отказа.
Сервер писал строку журнала прямо в трубу к окну запуска; окно снимали, труба закрывалась,
запись падала - а падала она внутри отправки ответа, до заголовков, и клиент получал обрыв
связи без единого слова. То есть отказ журнала уносил с собой каждый обслуживаемый запрос.

- **Что писать** - уровень записи против порога приёмника. Пороги разные у разных
  приёмников: в окно идёт крупное, в файл - подробное.
- **Куда писать** - набор приёмников. «Журнал» и «труба, в которую мы сейчас пишем» -
  разные понятия; приёмники подключаются и выбывают независимо друг от друга.
- **Что при отказе** - выбывает один приёмник, а не журнал. Остальные получают запись,
  и первыми получают известие о выбывшем. Ни один путь отсюда наружу не бросает.

Визуала здесь нет: приёмник знает, куда положить готовую строку, и ничего не решает
о её виде. Слои показа могут подставить свой приёмник (`ListSink` - для проверок).
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40}
_NAMES = {v: k for k, v in LEVELS.items()}


def level_of(level) -> int:
    """Уровень числом: имя из `LEVELS` либо уже число. Неизвестное имя - отказ сразу,
    а не молча пропущенные записи."""
    if isinstance(level, (int, float)):
        return int(level)
    key = str(level).strip().lower()
    if key not in LEVELS:
        raise ValueError("неизвестный уровень журнала %r; известны: %s"
                         % (level, ", ".join(LEVELS)))
    return LEVELS[key]


def level_name(level) -> str:
    value = level_of(level)
    return _NAMES.get(value, str(value))


class Sink:
    """Приёмник записей: порог и место. Отказ снимает с обслуживания его одного.

    Наследник переопределяет `emit`; ловить отказы ему не нужно - это делает журнал,
    он же помечает приёмник выбывшим.
    """

    __slots__ = ("level", "failure")

    def __init__(self, level="info"):
        self.level = level_of(level)
        self.failure: str | None = None      # почему выбыл; None - жив

    @property
    def alive(self) -> bool:
        return self.failure is None

    def accepts(self, level) -> bool:
        return self.alive and level_of(level) >= self.level

    def emit(self, line: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __repr__(self) -> str:
        return "%s(%s%s)" % (type(self).__name__, level_name(self.level),
                             "" if self.alive else ", выбыл: %s" % self.failure)


class StreamSink(Sink):
    """Поток: труба к окну запуска или консоль.

    Консоль на этой машине живёт в cp1251 и падает на кириллице, поэтому неудача
    кодировки - не отказ приёмника, а повод написать ту же строку заменами. Отказ самой
    трубы (окно снято) - настоящий отказ, и разбирается он журналом.
    """

    __slots__ = ("stream",)

    def __init__(self, stream=None, level="info"):
        super().__init__(level)
        self.stream = stream

    def _target(self):
        # sys.stderr берётся при записи, а не при создании: проверки подменяют его на время.
        return self.stream if self.stream is not None else sys.stderr

    def emit(self, line: str) -> None:
        target = self._target()
        if target is None:
            raise OSError("потока нет")
        try:
            target.write(line + "\n")
        except UnicodeEncodeError:
            target.write(line.encode("ascii", "replace").decode("ascii") + "\n")
        target.flush()


class FileSink(Sink):
    """Файл рядом с программой. Открывается при первой записи и держится открытым:
    сервер живёт часами, и открывать файл на каждую строку незачем."""

    __slots__ = ("path", "_handle")

    def __init__(self, path, level="debug"):
        super().__init__(level)
        self.path = Path(path)
        self._handle = None

    def emit(self, line: str) -> None:
        if self._handle is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = open(self.path, "a", encoding="utf-8")
        self._handle.write(line + "\n")
        self._handle.flush()

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass


class ListSink(Sink):
    """Приёмник в память: для проверок и для тех слоёв показа, что рисуют журнал сами."""

    __slots__ = ("lines", "limit")

    def __init__(self, level="debug", limit: int = 1000):
        super().__init__(level)
        self.lines: list[str] = []
        self.limit = int(limit)

    def emit(self, line: str) -> None:
        self.lines.append(line)
        if len(self.lines) > self.limit:
            del self.lines[:-self.limit]


class Journal:
    """Набор приёмников и одна точка записи.

    `log` не бросает никогда - ни при отказе приёмника, ни при отсутствии приёмников
    вовсе. Выбывший приёмник больше не зовётся, а остальные получают об этом одну
    строку уровня `error`: молчание о потере приёмника - та же потеря сведений.
    """

    def __init__(self, sinks=(), prefix: str = ""):
        self.sinks: list[Sink] = list(sinks)
        self.prefix = str(prefix)
        self._lock = threading.Lock()        # сервер обслуживает запросы в нескольких нитях

    def add(self, sink: Sink) -> Sink:
        with self._lock:
            self.sinks.append(sink)
        return sink

    def remove(self, sink: Sink) -> None:
        with self._lock:
            if sink in self.sinks:
                self.sinks.remove(sink)

    @property
    def alive_sinks(self) -> list[Sink]:
        return [s for s in self.sinks if s.alive]

    def line(self, level, text: str) -> str:
        """Готовая строка: уровень, имя источника и текст. Времени здесь нет намеренно -
        его ставит приёмник, которому оно нужно (файл), а окну оно только мешает."""
        head = "%-5s" % level_name(level)
        return "%s %s%s" % (head, self.prefix and self.prefix + ": ", text)

    def log(self, level, text: str) -> None:
        value = level_of(level)
        with self._lock:
            targets = [s for s in self.sinks if s.accepts(value)]
            line = self.line(value, text)
            failed = []
            for sink in targets:
                try:
                    sink.emit(line)
                except Exception as e:       # noqa: BLE001 - любой отказ приёмника
                    sink.failure = repr(e)
                    failed.append(sink)
            for sink in failed:
                note = self.line(LEVELS["error"], "приёмник %s выбыл: %s"
                                 % (type(sink).__name__, sink.failure))
                for other in self.sinks:
                    if other is sink or not other.accepts(LEVELS["error"]):
                        continue
                    try:
                        other.emit(note)
                    except Exception as e:   # noqa: BLE001 - и этот выбыл, тем же порядком
                        other.failure = repr(e)

    def debug(self, text: str) -> None:
        self.log(LEVELS["debug"], text)

    def info(self, text: str) -> None:
        self.log(LEVELS["info"], text)

    def warn(self, text: str) -> None:
        self.log(LEVELS["warn"], text)

    def error(self, text: str) -> None:
        self.log(LEVELS["error"], text)

    def close(self) -> None:
        for sink in self.sinks:
            try:
                sink.close()
            except Exception:                # noqa: BLE001 - закрытие тоже не бросает
                pass


def from_config(cfg, prefix: str = "", stream=None) -> Journal:
    """Журнал по настройкам: поток с порогом `logLevel` и, если `logFile` не пуст,
    файл с порогом `logFileLevel`. Относительное имя файла - рядом с `morphbench.json`.

    Неверный уровень в настройках не должен лишать программу журнала целиком: приёмник
    с непонятным порогом заводится по умолчанию, а о подмене говорится первой же строкой.
    """
    journal = Journal(prefix=prefix)
    notes = []

    def threshold(key: str, fallback: str) -> int:
        try:
            return level_of(cfg.get(key, fallback) or fallback)
        except ValueError as e:
            notes.append(str(e))
            return level_of(fallback)

    journal.add(StreamSink(stream, threshold("logLevel", "info")))
    name = str(cfg.get("logFile", "") or "").strip()
    if name:
        path = Path(name)
        if not path.is_absolute():
            base = getattr(cfg, "path", None)
            path = (Path(base).parent if base else Path.cwd()) / path
        journal.add(FileSink(path, threshold("logFileLevel", "debug")))
    for note in notes:
        journal.error("настройки журнала: %s" % note)
    return journal
