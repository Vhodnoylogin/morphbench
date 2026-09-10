"""Где запущена программа: под Mod Organizer 2 или сама по себе.

MO2 подменяет файловую систему запущенному процессу библиотекой usvfs: все моды сливаются
в один `Data` игры, и там лежат меши всей сборки. Опознать это можно по самой библиотеке -
она загружена в наш процесс. Тогда корнем обзора становится `Data` игры, и наружу из него
выходить не надо. Без MO2 корень - любая папка компьютера.

Путь к игре берётся из реестра: установщики Bethesda пишут его в `Installed Path`.
Всё, что нельзя вывести, задаётся ключом `catalogRoot` в настройках.
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

# Игры семейства, чьи меши читает nifly; порядок - предпочтение при выборе корня.
_GAME_KEYS = (
    ("Skyrim VR", r"SOFTWARE\WOW6432Node\Bethesda Softworks\Skyrim VR"),
    ("Skyrim Special Edition", r"SOFTWARE\WOW6432Node\Bethesda Softworks\Skyrim Special Edition"),
    ("Skyrim", r"SOFTWARE\WOW6432Node\Bethesda Softworks\Skyrim"),
    ("Fallout 4", r"SOFTWARE\WOW6432Node\Bethesda Softworks\Fallout4"),
    ("Fallout 4 VR", r"SOFTWARE\WOW6432Node\Bethesda Softworks\Fallout 4 VR"),
)
_USVFS = ("usvfs_x64.dll", "usvfs_x86.dll")


def dir_exists(path) -> bool:
    """Есть ли папка - так, чтобы это работало и под usvfs.

    Под подменой MO2 виртуальная папка (например, `Data\\meshes`, собранная из модов) не
    отвечает на `is_dir()`: проверка атрибутов идёт мимо подмены и говорит «нет». Зато
    чтение списка каталога подмена обслуживает. Поэтому папка есть, если её можно перечислить.
    """
    import os
    try:
        os.listdir(path)
        return True
    except OSError:
        return os.path.isdir(path)


def file_exists(path) -> bool:
    """Есть ли файл - так, чтобы это работало и под usvfs: виртуальный файл на проверку
    атрибутов отвечает «нет», а открыться даёт. Поэтому файл есть, если его можно открыть."""
    try:
        with open(path, "rb"):
            return True
    except OSError:
        return False


def same_file(a, b) -> bool:
    """Один ли это файл - по нормализованному пути, без resolve(): под usvfs настоящий
    путь виртуального файла уводит в папку мода."""
    return _canonical(a) == _canonical(b)


def _canonical(path) -> str:
    """Абсолютный путь в одном написании: без «..», в одном регистре, без хвостовой косой."""
    import os
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


class Environment:
    """Окружение процесса: под MO2 ли мы, где игра и какой корень обзора по умолчанию."""

    def __init__(self, cfg):
        self.cfg = cfg

    # ---- MO2 --------------------------------------------------------------------------
    @staticmethod
    def inside_mo2() -> bool:
        """Библиотека usvfs загружена в наш процесс - значит, запущены через MO2."""
        if sys.platform != "win32":
            return False
        fn = ctypes.windll.kernel32.GetModuleHandleW
        # Без объявления типов ctypes усёк бы 64-битный HMODULE до 32 бит, и база DLL
        # с нулевыми младшими битами дала бы ложное «не под MO2».
        fn.restype = ctypes.c_void_p
        fn.argtypes = [ctypes.c_wchar_p]
        return any(fn(name) for name in _USVFS)

    # ---- игры -------------------------------------------------------------------------
    @staticmethod
    def game_roots() -> list[dict]:
        """Установленные игры по реестру: имя и папка."""
        if sys.platform != "win32":
            return []
        import winreg
        out = []
        for name, key in _GAME_KEYS:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                    path = winreg.QueryValueEx(k, "Installed Path")[0]
            except OSError:
                continue
            root = Path(str(path).rstrip("\\/"))
            if root.is_dir():
                out.append({"game": name, "root": str(root)})
        return out

    def data_root(self) -> Path | None:
        """Корень обзора по умолчанию.

        Явный `catalogRoot` перевешивает всё. Под MO2 - `Data` той игры, где видны
        россыпные меши: сама игра держит их в архивах, поэтому папка `Data\\meshes`
        появляется только сквозь usvfs. Вне MO2 умолчания нет - корень надо назвать.
        """
        explicit = str(self.cfg.get("catalogRoot", "") or "").strip()
        if explicit:
            return Path(explicit)
        if not self.inside_mo2():
            return None
        candidates = [Path(g["root"]) / "Data" for g in self.game_roots()]
        for data in candidates:
            if dir_exists(data / "meshes"):
                return data
        return candidates[0] if candidates else None

    def allows(self, root) -> bool:
        """Можно ли смотреть в эту папку: под MO2 - только внутрь Data, иначе куда угодно."""
        if not self.inside_mo2():
            return True
        data = self.data_root()
        if data is None:
            return False
        # Сравниваются нормализованные абсолютные пути, а не resolve(): под usvfs
        # настоящий путь виртуальной папки уводит в папку мода, и Data перестала бы
        # быть её родителем.
        try:
            Path(_canonical(root)).relative_to(Path(_canonical(data)))
        except ValueError:
            return False
        return True

    def candidates(self) -> list[dict]:
        """Что видно в Data каждой игры глазами ЭТОГО процесса: есть ли папка meshes и первые
        имена в Data. Под usvfs это и есть проверка, действует ли подмена: настоящая Data
        Skyrim держит меши в архивах, россыпные папки появляются только сквозь VFS."""
        import os
        out = []
        for g in self.game_roots():
            data = Path(g["root"]) / "Data"
            try:
                names = sorted(os.listdir(data), key=str.lower)
            except OSError:
                names = []
            out.append({"game": g["game"], "data": str(data),
                        "meshes": dir_exists(data / "meshes"),
                        "meshesIsDir": (data / "meshes").is_dir(),
                        "entries": len(names), "sample": names[:12]})
        return out

    def describe(self) -> dict:
        data = self.data_root()
        return {"insideMo2": self.inside_mo2(), "dataRoot": None if data is None else str(data),
                "games": self.game_roots(), "catalogRoot": str(self.cfg.get("catalogRoot", "") or ""),
                "candidates": self.candidates()}
