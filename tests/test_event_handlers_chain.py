"""An overridden Qt event handler either handles the event or passes it on.

Two different rules, because Qt has two different kinds of handler, and
applying one rule to both introduces bugs.

**Notification handlers** — show/hide/close/resize/move/enter/leave/focus —
have no accept/ignore semantics. Their default implementation does real
bookkeeping (spontaneous state, palette propagation) and skipping it is
simply a bug. These MUST call `super()`.

**Accept/ignore handlers** — mouse, wheel, drag, drop, context menu — must
NOT blanket-chain. `QWidget`'s default implementation of every one of them
calls `event->ignore()`. Appending `super().dragEnterEvent(event)` after
`event.acceptProposedAction()` therefore UNDOES the accept and breaks the
drop outright; on a context menu it lets the event through to a parent that
shows a second menu. For these the rule is: on the path where you handled
it, `accept()`; on the path where you did not, chain.

`paintEvent` is exempt from both: a widget that paints itself completely is
supposed not to chain, or the default appearance is drawn underneath it.
"""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"

#: No accept/ignore semantics — the default implementation is bookkeeping.
NOTIFICATION_HANDLERS = {
    "showEvent", "hideEvent", "closeEvent", "resizeEvent", "moveEvent",
    "changeEvent", "focusInEvent", "focusOutEvent", "enterEvent",
    "leaveEvent",
}

#: The default implementation ignores the event, so blanket chaining is wrong.
ACCEPT_IGNORE_HANDLERS = {
    "keyPressEvent", "keyReleaseEvent", "mousePressEvent",
    "mouseReleaseEvent", "mouseMoveEvent", "mouseDoubleClickEvent",
    "wheelEvent", "contextMenuEvent", "dragEnterEvent", "dragMoveEvent",
    "dragLeaveEvent", "dropEvent",
}


def _calls(node, name):
    """Whether `node`'s body contains a call to `super().<name>(...)`."""
    return any(
        isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Attribute)
        and inner.func.attr == name
        and isinstance(inner.func.value, ast.Call)
        and isinstance(inner.func.value.func, ast.Name)
        and inner.func.value.func.id == "super"
        for inner in ast.walk(node)
    )


def _accepts(node):
    """Whether the handler calls event.accept()/acceptProposedAction()."""
    return any(
        isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Attribute)
        and inner.func.attr in ("accept", "acceptProposedAction", "ignore")
        for inner in ast.walk(node)
    )


def _has_toplevel_super(node):
    """A `super().<name>(event)` sitting directly in the function body."""
    for stmt in node.body:
        if (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Attribute)
                and stmt.value.func.attr == node.name
                and isinstance(stmt.value.func.value, ast.Call)
                and isinstance(stmt.value.func.value.func, ast.Name)
                and stmt.value.func.value.func.id == "super"):
            return True
    return False


def _every_accept_returns(node):
    """Whether every block that accepts the event then returns.

    If it does, the top-level super() below is unreachable from the
    accepting path and the two never both run.
    """
    def accepts(stmt):
        return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Attribute)
                and stmt.value.func.attr in ("accept", "acceptProposedAction"))

    for block in ast.walk(node):
        body = getattr(block, "body", None)
        if not isinstance(body, list):
            continue
        for index, stmt in enumerate(body):
            if not accepts(stmt):
                continue
            rest = body[index + 1:]
            if not any(isinstance(s, ast.Return) for s in rest):
                return False
    return True


def _handlers():
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                yield path, node


def test_notification_handlers_chain_to_super():
    offenders = [
        f"{path.relative_to(SRC).as_posix()}:{node.lineno} {node.name}"
        for path, node in _handlers()
        if node.name in NOTIFICATION_HANDLERS and not _calls(node, node.name)
    ]
    assert offenders == [], (
        "these skip Qt's own bookkeeping for the event:\n  "
        + "\n  ".join(offenders))


def test_accept_ignore_handlers_either_accept_or_chain():
    """Never neither. A handler that does its work and then falls off the
    end leaves the event in whatever state it arrived in — usually
    'ignored', so it also propagates to the parent."""
    offenders = [
        f"{path.relative_to(SRC).as_posix()}:{node.lineno} {node.name}"
        for path, node in _handlers()
        if node.name in ACCEPT_IGNORE_HANDLERS
        and not _calls(node, node.name)
        and not _accepts(node)
    ]
    assert offenders == [], (
        "these neither accept the event nor pass it on:\n  "
        + "\n  ".join(offenders))


def test_no_handler_accepts_and_then_unconditionally_chains():
    """The bug this file exists to prevent: `event.acceptProposedAction()`
    followed by `super().dragEnterEvent(event)`, whose default
    implementation calls ignore() and undoes it."""
    offenders = []
    for path, node in _handlers():
        if node.name not in ACCEPT_IGNORE_HANDLERS:
            continue
        if not (_accepts(node) and _calls(node, node.name)):
            continue
        # Accepting and chaining is fine when the two cannot both run:
        # either they sit on different branches of an if/else, or the
        # accepting branch returns before reaching the super() call. It is
        # wrong only when an accept can fall through INTO the chain.
        if not _has_toplevel_super(node):
            continue
        if _every_accept_returns(node):
            continue
        offenders.append(
            f"{path.relative_to(SRC).as_posix()}:{node.lineno} {node.name}")
    assert offenders == [], (
        "accepting and then chaining undoes the accept:\n  "
        + "\n  ".join(offenders))
