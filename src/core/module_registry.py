import logging
from typing import List

from core.admin_utils import is_admin
from core.base_module import BaseModule

logger = logging.getLogger(__name__)


class ModuleRegistry:
    """Manages module lifecycle: registration, startup, shutdown."""

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
        import logging
        _log = logging.getLogger("startup")
        running_as_admin = is_admin()
        for module in self._modules:
            if module.requires_admin and not running_as_admin:
                logger.warning(
                    "Module '%s' requires admin — disabled", module.name
                )
                self._disabled.append(module)
                continue
            _log.debug("[STARTUP] on_start(%s)", module.name)
            try:
                module.on_start(app)
                _log.debug("[STARTUP] on_start(%s) done", module.name)
                provider = module.get_search_provider()
                if provider is not None:
                    app.search.register_provider(provider)
                logger.info("Started module: %s", module.name)
            except Exception:
                logger.exception("Module '%s' failed to start", module.name)
                self._failed_modules.append(module)
                self._disabled.append(module)

    def stop_all(self) -> None:
        for module in self._modules:
            if module in self._disabled:
                continue
            try:
                module.cancel_all_workers()
                module.on_stop()
                logger.info("Stopped module: %s", module.name)
            except Exception:
                logger.exception("Module '%s' failed to stop cleanly", module.name)
