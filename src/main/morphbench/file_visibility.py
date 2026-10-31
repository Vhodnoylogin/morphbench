"""NiAVObject hidden flags and their ancestry, read through PyNifly's native API.

This describes the file, not an engine frame. An unread flag or an incomplete graph is
unknown: even an observed hidden bit cannot turn an uncertain ancestry into a verdict.
"""
from __future__ import annotations

from ctypes import c_int, c_void_p
from operator import index


def unknown_visibility(block: int = -1, issue: str = "not-read") -> dict:
    """Fresh metadata for a shape made in memory, or one whose file data is unavailable."""
    return {"block": block, "localFlags": None, "localHidden": None, "ancestors": [],
            "ancestryComplete": False, "complete": False, "inheritedHidden": None,
            "effectiveHidden": None, "state": "unknown", "issues": [issue]}


def _number(value, maximum: int) -> int | None:
    try:
        number = index(value)
        return int(number) if not isinstance(value, bool) and 0 <= number <= maximum else None
    except (TypeError, ValueError, OverflowError):
        return None


def _block(value) -> int | None:
    # The declared child-ID API uses c_int; -1 / UINT32_MAX denote an absent reference.
    return _number(value, 0x7FFFFFFF)


def _node_block(node) -> int | None:
    try:
        return _block(node.id)
    except Exception:
        return None


def _flags(node) -> int | None:
    try:
        value = getattr(node, "flags", None)
        if value is None:
            value = getattr(getattr(node, "properties", None), "flags", None)
        return _number(value, 0xFFFFFFFF)
    except Exception:                       # PyNifly raises the bare Exception class
        return None


def _name(node) -> str:
    try:
        return str(node.name)
    except Exception:
        return ""


def _issue(issues: list[str], code: str) -> None:
    if code not in issues:
        issues.append(code)


def _native_graph(nif, pynifly, shapes: list, limit: int):
    """Read the full native node/child lists, keeping block IDs instead of node names.

    NiNode.parent returns one parent only; a reverse index of every child list is needed
    to detect multiple ancestry. The native root handle is the sole root authority.
    """
    nodes, parents, issues = {}, {}, []
    root = None

    def add_node(block, node):
        if block is None or node is None:
            _issue(issues, "node-unresolved")
        elif block not in nodes:
            if len(nodes) >= limit:
                _issue(issues, "graph-limit")
                return
            flags = _flags(node)
            nodes[block] = {"block": block, "name": _name(node), "flags": flags,
                            "hidden": None if flags is None else bool(flags & 1)}

    for shape in shapes:
        add_node(_node_block(shape), shape)
    if "graph-limit" in issues:
        return nodes, parents, root, issues

    try:
        dll, handle = pynifly.nifly, nif._handle
        root_handle = dll.getRoot(handle)
        if root_handle:
            root = _block(dll.getBlockID(handle, root_handle))
        if root is None:
            _issue(issues, "root-unresolved")
        count = _number(dll.getNodeCount(handle), 0x7FFFFFFF)
        if count is None:
            _issue(issues, "node-count-invalid")
            return nodes, parents, root, issues
        # Check before allocating, including the shapes already reported by PyNifly.
        if count > limit - len(nodes):
            _issue(issues, "graph-limit")
            return nodes, parents, root, issues
        handles = (c_void_p * count)()
        dll.getNodes(handle, handles)
        enumerated = set()
        for node_handle in handles:
            if not node_handle:
                _issue(issues, "node-unresolved")
                continue
            block = _block(dll.getBlockID(handle, node_handle))
            if block is None:
                _issue(issues, "node-unresolved")
                continue
            if block in enumerated:
                _issue(issues, "node-enumeration-incomplete")
            enumerated.add(block)
            try:
                node = nif.read_node(id=block)
                if node is not None and _node_block(node) != block:
                    node = None
                add_node(block, node)
            except Exception:
                _issue(issues, "node-read-error")
        if root is not None and root not in nodes:
            _issue(issues, "root-unresolved")

        edge_count = 0
        for block in nodes:
            try:
                count = dll.getNodeChildren(handle, block, 0, None)
                count = _number(count, 0x7FFFFFFF)
                if count is None:
                    _issue(issues, "child-count-invalid")
                    continue
                if count > limit - len(nodes) - edge_count:
                    _issue(issues, "graph-limit")
                    break
                edge_count += count
                children = (c_int * count)()
                found = dll.getNodeChildren(handle, block, count, children) if count else 0
                if found != count:
                    _issue(issues, "children-read-incomplete")
                    continue
                observed_children = set()
                for child in children:
                    child = _block(child)
                    if child is None or child not in nodes:
                        _issue(issues, "child-unresolved")
                        continue
                    if child in observed_children:
                        _issue(issues, "child-reference-duplicate")
                    observed_children.add(child)
                    parents.setdefault(child, set()).add(block)
            except Exception:
                _issue(issues, "children-read-error")
        if root is not None and parents.get(root):
            _issue(issues, "root-has-parent")
    except Exception:
        _issue(issues, "graph-read-error")
    return nodes, parents, root, issues


def _ancestry(block, nodes, parents, root, graph_issues, budget):
    """Walk all observed parent paths without recursion, even when the graph is cyclic."""
    ancestors, issues = [], list(graph_issues)
    seen, active = {block}, {block}
    stack = []

    def enter(current):
        links = parents.get(current, set())
        if current != root and not links:
            _issue(issues, "ancestry-orphan")
        if len(links) > 1:
            _issue(issues, "ancestry-multiple-parents")
        stack.append((current, iter(sorted(links))))

    enter(block)
    while stack:
        current, links = stack[-1]
        parent = next(links, None)
        if parent is None:
            active.remove(current)
            stack.pop()
            continue
        if budget[0] <= 0:
            _issue(issues, "graph-limit")
            break
        budget[0] -= 1
        if parent in active:
            _issue(issues, "ancestry-cycle")
            continue
        if parent in seen:
            _issue(issues, "ancestry-multiple-paths")
            continue
        seen.add(parent)
        if parent not in nodes:
            _issue(issues, "ancestor-unresolved")
            continue
        ancestors.append(dict(nodes[parent]))
        active.add(parent)
        enter(parent)
    if root is None or root not in seen:
        _issue(issues, "root-unreached")
    return ancestors, not issues, issues


def read_file_visibility(nif, pynifly, limit: int) -> dict[int, dict]:
    """Metadata per shape block, using only PyNifly and its declared native functions.

    A failed optional visibility read must not prevent the geometry from loading. Bounds
    apply before native list allocations and also to the combined ancestor output, whose
    size could otherwise grow quadratically for many shapes in a deep node hierarchy.
    """
    shapes = list(nif.shapes)
    metadata = {}
    for shape in shapes:
        block = _node_block(shape)
        block = -1 if block is None else block
        entry = unknown_visibility(block)
        entry["localFlags"] = _flags(shape)
        if entry["localFlags"] is not None:
            entry["localHidden"] = bool(entry["localFlags"] & 1)
        metadata[block] = entry
    bounded = _number(limit, 0x7FFFFFFF)
    if not bounded:
        for entry in metadata.values():
            entry["issues"] = ["graph-limit"]
        return metadata
    nodes, parents, root, graph_issues = _native_graph(nif, pynifly, shapes, bounded)
    budget = [bounded]
    for block, entry in metadata.items():
        ancestors, ancestry_complete, issues = _ancestry(
            block, nodes, parents, root, graph_issues, budget)
        entry["ancestors"] = ancestors
        entry["ancestryComplete"] = ancestry_complete
        ancestor_flags_known = all(a["flags"] is not None for a in ancestors)
        if entry["localFlags"] is None:
            _issue(issues, "local-flags-unavailable")
        if not ancestor_flags_known:
            _issue(issues, "ancestor-flags-unavailable")
        if any(a["hidden"] is True for a in ancestors):
            entry["inheritedHidden"] = True
        elif ancestry_complete and ancestor_flags_known:
            entry["inheritedHidden"] = False
        entry["complete"] = ancestry_complete and not issues
        if entry["complete"]:
            entry["effectiveHidden"] = bool(entry["localHidden"] or entry["inheritedHidden"])
            entry["state"] = "hidden" if entry["effectiveHidden"] else "visible"
        entry["issues"] = issues
    return metadata
