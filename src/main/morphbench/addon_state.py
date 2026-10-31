"""Bounded, detached JSON for add-on-owned session data.

The facade validates values without knowing a browser, storage key or persistence
lifetime. A host supplies its storage adapter; add-ons never choose another ID's
namespace. This data is independent of meshes and is never a preview replay recipe.
"""
from __future__ import annotations

import json
import math

from .addons import AddonError
from .i18n import t


class AddonStateMixin:
    def addon_state_limits(self) -> dict:
        limits = {"maxBytes": self.cfg["addonStateMaxBytes"],
                  "maxDepth": self.cfg["addonStateMaxDepth"]}
        if any(type(value) is not int or value <= 0 for value in limits.values()):
            raise AddonError("invalidLimits", t("err.addonLimits"))
        return limits

    def addon_validate_state(self, value):
        """Validate structure/depth and detach; decode_state bounds exact wire bytes."""
        limits = self.addon_state_limits()
        ancestors = set()

        def check(item, depth):
            if depth > limits["maxDepth"]:
                raise AddonError("limitExceeded", t("err.addonParams"))
            if item is None or type(item) in (str, bool):
                return
            if type(item) in (int, float):
                try:
                    if math.isfinite(item):
                        return
                except OverflowError:
                    pass
            if type(item) in (list, dict) and id(item) not in ancestors:
                ancestors.add(id(item))
                try:
                    if type(item) is dict:
                        if any(type(key) is not str for key in item):
                            raise AddonError("invalidState", t("err.addonParams"))
                        children = item.values()
                    else:
                        children = item
                    for child in children:
                        check(child, depth + 1)
                    return
                finally:
                    ancestors.remove(id(item))
            raise AddonError("invalidState", t("err.addonParams"))

        try:
            check(value, 0)
            data = json.dumps(value, ensure_ascii=False, allow_nan=False,
                              separators=(",", ":")).encode("utf-8")
        except (ValueError, UnicodeError, RecursionError) as error:
            if isinstance(error, AddonError):
                raise
            raise AddonError("invalidState", t("err.addonParams")) from None
        return json.loads(data)

    def addon_decode_state(self, data: str):
        """Bound and decode the exact JSON text, independent of encoder formatting."""
        if type(data) is not str:
            raise AddonError("invalidState", t("err.addonParams"))
        try:
            size = len(data.encode("utf-8"))
        except UnicodeError:
            raise AddonError("invalidState", t("err.addonParams")) from None
        if size > self.addon_state_limits()["maxBytes"]:
            raise AddonError("limitExceeded", t("err.addonParams"))
        try:
            value = json.loads(data)
        except (ValueError, RecursionError):
            raise AddonError("invalidState", t("err.addonParams")) from None
        return self.addon_validate_state(value)
