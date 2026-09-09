"""Точечная правка чисел в файле NIF - там, где PyNifly писать не умеет.

Единственное место верстака, которое трогает байты NIF, и оно намеренно крошечное.
Разбор формата остаётся за PyNifly: здесь читается ровно заголовок и ровно ради адресов
блоков. Заголовок перечисляет длины всех блоков подряд, поэтому смещение любого из них
получается сложением, без понимания содержимого.

Ради чего: `setBlock` из PyNifly на форме капсулы отвечает «NYI Unimplemented function SET
of type 19», а посаженную капсулу в скелет записать надо. Блок формы-капсулы имеет
ПОСТОЯННЫЙ размер, и меняются в нём только вещественные числа, поэтому файл копируется
байт в байт, а значения правятся на своих местах: ни длины блоков, ни таблица строк,
ни ссылки не сдвигаются. Как только PyNifly научится писать капсулы, этот модуль
становится лишним целиком.
"""
from __future__ import annotations

import struct
from pathlib import Path


class NifPatch:
    """Копия файла NIF в памяти со смещениями блоков; правит числа на месте."""

    #: Блок формы-капсулы: материал (4), общий радиус (4), восемь неиспользуемых байтов,
    #: затем первый конец с радиусом (16) и второй конец с радиусом (16).
    CAPSULE_BLOCK = 48
    CAPSULE_RADIUS = 4
    CAPSULE_POINTS = 16

    #: Часть меша: имя (4), число доп. данных (4) и их ссылки, контроллер (4), флаги (4),
    #: перенос (12), поворот (36), масштаб (4), коллизия (4) - и затем центр (12) и радиус (4)
    #: шара охвата. Ссылки на доп. данные - единственное переменное место до шара.
    SHAPE_TYPES = ("BSTriShape", "BSDynamicTriShape", "BSSubIndexTriShape")
    SHAPE_HEAD = 4 + 4 + 4 + 4 + 12 + 36 + 4 + 4

    def __init__(self, path):
        self.path = Path(path)
        self.raw = bytearray(self.path.read_bytes())
        self.offsets, self.sizes, self.types, self.bs_version, self.end = self._block_table(self.raw)

    # ---- заголовок --------------------------------------------------------------------
    @staticmethod
    def _block_table(raw: bytearray) -> tuple[dict[int, int], list[int], list[str], int, int]:
        """Смещение, длина и тип каждого блока по его номеру, версия Bethesda и позиция
        сразу за последним блоком."""
        pos = raw.index(b"\n") + 1                       # строка версии формата
        pos += 4 + 1 + 4                                 # версия, порядок байтов, версия игры
        blocks = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        bs_version = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        for _ in range(3):                               # три строки о том, чем собран файл
            pos += 1 + raw[pos]
        types = struct.unpack_from("<H", raw, pos)[0]
        pos += 2
        names = []
        for _ in range(types):
            n = struct.unpack_from("<I", raw, pos)[0]
            names.append(raw[pos + 4:pos + 4 + n].decode("ascii", "replace"))
            pos += 4 + n
        kinds = struct.unpack_from("<%dH" % blocks, raw, pos)
        pos += 2 * blocks                                # тип каждого блока
        block_types = [names[k] if k < len(names) else "?" for k in kinds]
        sizes = list(struct.unpack_from("<%dI" % blocks, raw, pos))
        pos += 4 * blocks
        strings, _maxlen = struct.unpack_from("<II", raw, pos)
        pos += 8
        for _ in range(strings):
            pos += 4 + struct.unpack_from("<I", raw, pos)[0]
        groups = struct.unpack_from("<I", raw, pos)[0]
        pos += 4 + 4 * groups
        offsets = {}
        for i, size in enumerate(sizes):
            offsets[i] = pos
            pos += size
        return offsets, sizes, block_types, bs_version, pos

    @property
    def block_count(self) -> int:
        return len(self.sizes)

    def consistent(self) -> bool:
        """Сходится ли разбор заголовка с файлом: за последним блоком лежит подвал -
        число корней и их номера, - и на нём файл кончается. Проверка для тех, кто
        не верит сложению, и для проверок."""
        if self.end + 4 > len(self.raw):
            return False
        roots = struct.unpack_from("<I", self.raw, self.end)[0]
        return self.end + 4 + 4 * roots == len(self.raw)

    def has_block(self, block: int) -> bool:
        return block in self.offsets

    # ---- правка -----------------------------------------------------------------------
    def write_capsule(self, block: int, p1, p2, radius: float) -> None:
        """Концы и радиус капсулы в её блок. Числа - в единицах Havok, как лежат в файле."""
        if block not in self.offsets:
            raise KeyError("в файле нет блока %d (всего %d)" % (block, self.block_count))
        if self.sizes[block] != self.CAPSULE_BLOCK:
            raise ValueError("блок %d не похож на капсулу: длина %d, а не %d"
                             % (block, self.sizes[block], self.CAPSULE_BLOCK))
        off = self.offsets[block]
        r = float(radius)
        struct.pack_into("<f", self.raw, off + self.CAPSULE_RADIUS, r)
        struct.pack_into("<3ff3ff", self.raw, off + self.CAPSULE_POINTS,
                         float(p1[0]), float(p1[1]), float(p1[2]), r,
                         float(p2[0]), float(p2[1]), float(p2[2]), r)

    # ---- шар охвата части -----------------------------------------------------------
    def _bounds_offset(self, block: int) -> int:
        if block not in self.offsets:
            raise KeyError("в файле нет блока %d (всего %d)" % (block, self.block_count))
        if self.types[block] not in self.SHAPE_TYPES:
            raise ValueError("блок %d - %s, а не часть меша" % (block, self.types[block]))
        if self.bs_version < 100:
            raise ValueError("файл версии Bethesda %d: раскладка части известна от 100 (SSE)"
                             % self.bs_version)
        off = self.offsets[block]
        extra = struct.unpack_from("<I", self.raw, off + 4)[0]
        return off + self.SHAPE_HEAD + 4 * extra

    def read_bounds(self, block: int) -> tuple[tuple[float, float, float], float]:
        """Центр и радиус шара охвата части, как они лежат в файле."""
        off = self._bounds_offset(block)
        x, y, z, r = struct.unpack_from("<4f", self.raw, off)
        return (x, y, z), r

    def write_bounds(self, block: int, centre, radius: float) -> None:
        """Новый шар охвата части - на то же место, тем же числом байтов."""
        off = self._bounds_offset(block)
        struct.pack_into("<4f", self.raw, off, float(centre[0]), float(centre[1]),
                         float(centre[2]), float(radius))

    def read_capsule(self, block: int) -> tuple[tuple[float, float, float],
                                               tuple[float, float, float], float]:
        """Обратное чтение - для проверки того, что записано."""
        off = self.offsets[block]
        x1, y1, z1, r, x2, y2, z2, _ = struct.unpack_from("<3ff3ff", self.raw,
                                                          off + self.CAPSULE_POINTS)
        return (x1, y1, z1), (x2, y2, z2), r

    def save(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(self.raw))
        return path
