"""Настройки верстака.

Набор значений по умолчанию встроен в программу и создаёт файл `morphbench.json` рядом с ней
при первом запуске. Ничего настраиваемого в коде числом быть не должно: путь к чужой библиотеке,
размер картинки, углы съёмки, фон и свет, пороги разборов — это настройки, а не константы.
Ключи, которых в старом файле нет, дописываются в него из умолчаний; значения пользователя
не трогаются.
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
    # Свет. За камерой (lightFollowCamera) направление задаётся в осях камеры - вправо,
    # вверх, к зрителю - и едет вместе с ракурсом: что видно, то и освещено. Отдельно от
    # камеры - направление в мировых координатах (lightDirection). Силы: рассеянная,
    # направленная и встречная подсветка с противоположной стороны. Затенение по нормали
    # вершины (smooth) или по нормали треугольника (flat).
    "lightFollowCamera": True,
    "lightCameraDirection": [0.35, 0.45, 0.82],
    "lightDirection": [-0.4, -0.7, 0.6],
    "ambient": 0.35,
    "diffuse": 0.65,
    "fill": 0.15,
    "shading": "smooth",
    # Обзор мешей. Корень по умолчанию: пусто - под MO2 это Data игры из реестра, вне MO2
    # корень надо назвать. Подпапки корня, где искать меши.
    "catalogRoot": "",
    "catalogSubdirs": ["meshes"],
    # Страница со списком мешей: адрес и порт локального сервера.
    "serveHost": "127.0.0.1",
    "servePort": 8767,
    # Слои. Радиус, в котором вершина оболочки считается лежащей над базовой частью
    # (в единицах модели; оболочки шерсти стоят над кожей в двух-трёх единицах), и доля
    # таких вершин над сдвигаемой областью, начиная с которой оболочка обязана следовать.
    "contactRadius": 6.0,
    "minContact": 0.02,
    # Наведение камеры: запас вокруг части, на которую смотрим, в долях её радиуса.
    "focusPadding": 1.25,
    # Имя базовой части меша - кожи, за которой следуют оболочки.
    "baseShape": "body",
    # Разборы. Порог растяжения ребра, с которого оно считается разорванным; доля вершин
    # морфа на кости, с которой кость попадает в список задетых; доля вершин кости,
    # оставшихся на месте, с которой кость считается брошенной; наименьшее число вершин
    # кости, чтобы о ней вообще судить.
    "strainThreshold": 0.25,
    "boneShareMin": 0.02,
    "leftBehindMin": 0.35,
    "boneMinVertices": 8,
    # Лицевой формат FRTRI хранит морфы абсолютными координатами; сдвиг короче порога - ноль.
    "frtriEpsilon": 1e-4,
    # Колайдеры: на сколько долек делить окружность капсулы при отрисовке; наименьший
    # вес, с которым вершина считается принадлежащей кости при подгонке; процентиль
    # расстояния до оси, берущийся за радиус (сотня раздула бы капсулу по одной
    # выпирающей вершине); цвет и прозрачность слоя поверх тела.
    "colliderSegments": 14,
    "colliderMinWeight": 0.5,
    "colliderFitPercentile": 90.0,
    "colliderColour": [90, 200, 255],
    "colliderOpacity": 0.45,
    # Слои показа: доля кадра под модель; на странице - пределы и шаг ползунков,
    # чувствительность орбиты (градусов на пиксель) и скорость колеса.
    "frameFill": 0.92,
    "sliderRange": [0.0, 1.0],
    "sliderStep": 0.01,
    "orbitSensitivity": 0.4,
    "wheelZoomRate": 0.0015,
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
        if any(key not in raw for key in DEFAULTS):
            # Файл старше программы: дописать новые ключи, чтобы было видно, что настраивается.
            self.path.write_text(json.dumps(self._values, indent=2, ensure_ascii=False),
                                 encoding="utf-8")

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
