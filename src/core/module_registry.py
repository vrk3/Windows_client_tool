import logging
from typing import Dict, List, Optional, Tuple

from core.admin_utils import is_admin
from core.base_module import BaseModule

logger = logging.getLogger(__name__)


class ModuleRegistry:
    """Manages module lifecycle: registration, startup, shutdown."""

    #: Names that outlived their module. A retired sidebar entry stays
    #: navigable — from the command palette, from a NAV_REQUEST_MODULE — by
    #: pointing at whatever absorbed it. `None` means "the whole module",
    #: as opposed to a composite child's tab index.
    ALIASES: Dict[str, Tuple[str, Optional[int]]] = {
        # Duplicate Finder was deleted: it full-MD5-hashed every file, where
        # TreeSize groups by size first and hashes almost nothing. The name
        # stays navigable so anyone who reaches for it lands somewhere useful.
        "Duplicate Finder": ("TreeSize", None),
    }

    def __init__(self):
        self._modules: List[BaseModule] = []
        self._disabled: List[BaseModule] = []
        self._failed_modules: List[BaseModule] = []

    @property
    def modules(self) -> List[BaseModule]:
        return list(self._modules)

    @property
    def disabled_modules(self) -> List[BaseModule]:
        return list(self._disabled)

    @property
    def failed_modules(self) -> List[BaseModule]:
        """Modules that failed to start due to an exception."""
        return list(self._failed_modules)

    def register(self, module: BaseModule) -> None:
        self._modules.append(module)
        logger.info("Registered module: %s", module.name)

    def start_all(self, app) -> None:
        _log = logging.getLogger("startup")
        running_as_admin = is_admin()
        for module in self._modules:
            if (module.requires_admin and not running_as_admin
                    and not module.read_only_unelevated):
                logger.warning(
                    "Module '%s' requires admin — disabled", module.name
                )
                self._disabled.append(module)
                continue
            _log.debug("[STARTUP] on_start(%s)", module.name)
            try:
                module.on_start(app)
                _log.debug("[STARTUP] on_start(%s) done", module.name)
                for provider in module.get_search_providers():
                    app.search.register_provider(provider)
                logger.info("Started module: %s", module.name)
            except Exception:
                logger.exception("Module '%s' failed to start", module.name)
                self._failed_modules.append(module)
                self._disabled.append(module)

    def route_map(self) -> Dict[str, Tuple[str, Optional[int]]]:
        """Names that are not sidebar entries, mapped to where they now live.

        `MainWindow` consults this only when a name misses the sidebar, so a
        real module always wins over a route of the same name.
        """
        routes: Dict[str, Tuple[str, Optional[int]]] = {}
        for module in self._modules:
            get_routes = getattr(module, "route_map", None)
            if callable(get_routes):
                routes.update(get_routes())
        routes.update(self.ALIASES)
        return routes

    def stop_all(self) -> None:
        for module in self._modules:
            if module in self._disabled:
                continue
            try:
                module.on_stop()
                logger.info("Stopped module: %s", module.name)
            except Exception:
                logger.exception("Module '%s' failed to stop cleanly", module.name)
