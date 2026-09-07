"""Настройки верстака.

Набор значений по умолчанию встроен в программу и создаёт файл `morphbench.json` рядом с ней
при первом запуске. Ничего настраиваемого в коде числом быть не должно: путь к чужой библиотеке,
размер картинки, углы съёмки и палитра — это настройки, а не константы.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_FILE = _ROOT / "morphbench.json"

DEFAULTS = {
    # Пусто - значит искать самому в каталоге аддонов Blender.
    "pynifly": "",
    # Растеризатор.
    "imageWidth": 900,
    "imageHeight": 900,
    "background": [26, 28, 32],
    # Съёмка: угол поворота вокруг модели и подъём камеры, в градусах.
    "views": {
        "front": [0.0, 0.0],
        "side": [90.0, 0.0],
        "back": [180.0, 0.0],
        "top": [0.0, 80.0],
        "below": [0.0, -60.0],
        "quarter": [40.0, 15.0],
    },
    # Свет: направление в мировых координатах и доли рассеянного и направленного.
    "lightDirection": [-0.4, -0.7, 0.6],
    "ambient": 0.35,
    "diffuse": 0.65,
}


class Config:
    """Настройки как объект, а не как словарь, разбросанный по коду."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else _FILE
        if not self.path.exists():
            self.path.write_text(json.dumps(DEFAULTS, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
        raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        self._values = {**DEFAULTS, **raw}

    def __getitem__(self, key: str):
        return self._values[key]

    def get(self, key: str, default=None):
        return self._values.get(key, default)

    # ---- то, что нельзя записать числом: чужая библиотека ----------------------------
    def pynifly_root(self) -> Path:
        """Папка аддона PyNifly. Явная настройка перевешивает поиск."""
        if self._values.get("pynifly"):
            p = Path(self._values["pynifly"])
            if p.is_dir():
                return p
            raise FileNotFoundError("в morphbench.json указан несуществующий путь pynifly: %s" % p)
        root = Path(os.environ.get("APPDATA", "")) / "Blender Foundation" / "Blender"
        if root.is_dir():
            for ver in sorted(root.iterdir(), reverse=True):
                cand = ver / "scripts" / "addons" / "io_scene_nifly"
                if cand.is_dir():
                    return cand
        raise FileNotFoundError(
            "не найден аддон PyNifly; укажите его папку ключом pynifly в %s" % self.path)
