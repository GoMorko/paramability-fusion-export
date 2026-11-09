"""Event handler classes. Fusion drops a handler that is garbage collected, so HandlerList keeps them alive."""
import adsk.core

from .log import error_box


class HandlerList:
    def __init__(self):
        self._items = []

    def keep(self, handler):
        self._items.append(handler)
        return handler

    def clear(self):
        self._items.clear()


def _guarded(callback, args, what):
    try:
        callback(args)
    except Exception:
        error_box(f"Something went wrong ({what}).")


class _Created(adsk.core.CommandCreatedEventHandler):
    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def notify(self, args):
        _guarded(self._callback, args, "opening the dialog")


class _Command(adsk.core.CommandEventHandler):
    def __init__(self, callback, what):
        super().__init__()
        self._callback = callback
        self._what = what

    def notify(self, args):
        _guarded(self._callback, args, self._what)


class _Custom(adsk.core.CustomEventHandler):
    def __init__(self, callback, what):
        super().__init__()
        self._callback = callback
        self._what = what

    def notify(self, args):
        _guarded(self._callback, args, self._what)


class _InputChanged(adsk.core.InputChangedEventHandler):
    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def notify(self, args):
        _guarded(self._callback, args, "reading the dialog")


class _Validate(adsk.core.ValidateInputsEventHandler):
    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def notify(self, args):
        try:
            self._callback(args)
        except Exception:
            args.areInputsValid = False


class _PreSelect(adsk.core.SelectionEventHandler):
    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def notify(self, args):
        try:
            self._callback(args)
        except Exception:
            args.isSelectable = False


def on_pre_select(event, callback, handlers):
    event.add(handlers.keep(_PreSelect(callback)))


def on_command_created(event, callback, handlers):
    event.add(handlers.keep(_Created(callback)))


def on_execute(event, callback, handlers):
    event.add(handlers.keep(_Command(callback, "exporting")))


def on_custom_event(event, callback, handlers, what="showing a window"):
    event.add(handlers.keep(_Custom(callback, what)))


def on_destroy(event, callback, handlers):
    event.add(handlers.keep(_Command(callback, "closing the dialog")))


def on_input_changed(event, callback, handlers):
    event.add(handlers.keep(_InputChanged(callback)))


def on_validate(event, callback, handlers):
    event.add(handlers.keep(_Validate(callback)))
