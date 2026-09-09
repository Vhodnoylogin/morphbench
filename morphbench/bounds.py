"""Шары охвата: по ним игра решает, попала ли часть меша в поле зрения.

У каждой части в файле записан шар - центр и радиус. Собирается он при сборке по телу
в покое, а морфы его не расширяют: деталь, вытянутая ползунком за шар, игра считает
невидимой и не рисует, когда шар выходит из кадра, - часть моргает и пропадает от ракурса.

Здесь считается шар, который накрывает **всё, во что может превратиться часть**: покой,
каждый ползунок на максимуме (и на минимуме, если предел отрицательный), все ползунки
разом и худший для каждой вершины набор - те ползунки, что уводят её от центра. Больше
нужного шар не раздувается: он же служит отсечению невидимого, и лишний запас стоит кадров.
Ни строчки про изображение и про формат файла: где шар лежит в файле, знает `NifPatch`.
"""
from __future__ import annotations

import numpy as np


class Sphere:
    """Центр и радиус - как в файле и как надо."""

    __slots__ = ("centre", "radius")

    def __init__(self, centre, radius: float):
        self.centre = np.asarray(centre, dtype=np.float32).reshape(3)
        self.radius = float(radius)

    def reach(self, points: np.ndarray) -> float:
        """Насколько далеко от центра этого шара уходит облако."""
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        return float(np.linalg.norm(pts - self.centre, axis=1).max()) if pts.size else 0.0

    def as_dict(self) -> dict:
        return {"centre": [round(float(c), 3) for c in self.centre],
                "radius": round(self.radius, 3)}

    def __repr__(self) -> str:
        return "Sphere(%s, r=%.2f)" % (self.centre.round(2).tolist(), self.radius)


def enclosing_sphere(points: np.ndarray, iterations: int = 100, start=None) -> Sphere:
    """Наименьший (с точностью в доли процента) шар, накрывающий облако точек.

    Начало - шар из середины охвата (или названный центр); дальше центр сдвигается
    к самой дальней точке убывающими шагами (ядро Бадою-Кларксона), и радиус на каждом
    шаге берётся по самой дальней точке ОТ ВСЕГО облака - значит, шар накрывает всё при
    любом числе шагов, а шаги лишь делают его теснее. Остаётся центр с наименьшим шаром;
    хуже начального он стать не может.
    """
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
    if pts.shape[0] == 0:
        return Sphere(np.zeros(3, np.float32), 0.0)
    start = (0.5 * (pts.min(axis=0) + pts.max(axis=0)) if start is None
             else np.asarray(start, dtype=np.float32).reshape(3))
    best_c, best_r = start, float(np.linalg.norm(pts - start, axis=1).max())
    c = start.astype(np.float64)
    for k in range(1, max(1, int(iterations)) + 1):
        d = np.linalg.norm(pts - c, axis=1)
        far = int(np.argmax(d))
        r = float(d[far])
        if r < best_r:
            best_c, best_r = c.astype(np.float32), r
        c = c + (pts[far] - c) / (k + 1.0)
    d = np.linalg.norm(pts - c, axis=1)
    r = float(d.max())
    if r < best_r:
        best_c, best_r = c.astype(np.float32), r
    return Sphere(best_c, best_r)


class Reach:
    """Во что может превратиться часть: покой и все состояния ползунков, которые стоит
    проверить. Смещения морфов складываются, поэтому самое дальнее положение вершины -
    в углу куба значений; углов 2^N, и перебираются не все, а те, что заведомо дальше
    прочих: каждый ползунок поодиночке, все разом и «худший набор» для каждой вершины -
    ползунки, уводящие её от центра. Радиус в конце всё равно меряется по всем точкам."""

    def __init__(self, rest: np.ndarray, deltas: dict[str, np.ndarray],
                 low: float = 0.0, high: float = 1.0):
        self.rest = np.asarray(rest, dtype=np.float32).reshape(-1, 3)
        self.deltas = {n: np.asarray(d, dtype=np.float32).reshape(-1, 3) for n, d in deltas.items()}
        self.low, self.high = float(low), float(high)

    def _ends(self) -> list[float]:
        ends = [self.high]
        if self.low < 0.0:
            ends.append(self.low)
        return ends

    def states(self, centre) -> dict[str, np.ndarray]:
        """Именованные облака: покой, каждый ползунок, все разом, худший набор от центра."""
        c = np.asarray(centre, dtype=np.float32).reshape(3)
        out = {"rest": self.rest}
        if not self.deltas:
            return out
        total = np.zeros_like(self.rest)
        for name, d in self.deltas.items():
            for end in self._ends():
                out["%s=%g" % (name, end)] = self.rest + d * end
            total = total + d * self.high
        out["all=%g" % self.high] = self.rest + total
        if self.low < 0.0:
            out["all=%g" % self.low] = self.rest + sum(d * self.low for d in self.deltas.values())
        away = self.rest - c
        worst = self.rest.copy()
        for d in self.deltas.values():
            dot = np.einsum("ij,ij->i", d, away)
            worst = worst + d * np.where(dot > 0.0, self.high, self.low if self.low < 0.0 else 0.0)[:, None]
        out["worst"] = worst
        return out

    def cloud(self, centre) -> np.ndarray:
        return np.vstack(list(self.states(centre).values()))

    def farthest(self, sphere: Sphere, single: bool = False) -> tuple[str, float]:
        """Какое состояние уходит дальше всех от центра шара и на сколько.
        `single` - только среди одиночных ползунков: что виновато само по себе."""
        best, reach = "rest", 0.0
        for name, pts in self.states(sphere.centre).items():
            if single and (name in ("rest", "worst") or name.startswith("all=")):
                continue
            r = sphere.reach(pts)
            if r > reach:
                best, reach = name, r
        return best, reach

    def needed(self, margin: float = 1.0, iterations: int = 100, start=None) -> Sphere:
        """Шар, накрывающий все состояния, с запасом `margin` (доля радиуса, 1 - без запаса).

        Худший набор зависит от центра, а центр - от облака, поэтому два прохода: облако
        от середины покоя даёт центр, облако от этого центра - окончательный шар. Радиус
        всегда меряется по всему облаку. Названный `start` (например, центр из файла)
        участвует как кандидат: хуже него шар не выйдет.
        """
        first = self.cloud(0.5 * (self.rest.min(axis=0) + self.rest.max(axis=0)))
        centre = enclosing_sphere(first, iterations, start).centre
        cloud = self.cloud(centre)
        sphere = enclosing_sphere(cloud, iterations, centre)
        if start is not None:
            alt = Sphere(start, 0.0)
            alt_r = alt.reach(cloud)
            if alt_r < sphere.radius:
                sphere = Sphere(start, alt_r)
        return Sphere(sphere.centre, sphere.reach(cloud) * max(1.0, float(margin)))
