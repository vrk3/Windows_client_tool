"""Triggers a Microsoft Store update scan via the MDM enterprise-app-management
CIM class, so pending Store app updates start downloading in the background —
the same mechanism Update Center uses (Invoke-UcStoreTrigger).

Must run inside a COMWorker (uses win32com WMI access, needs CoInitialize).
"""
import logging
from typing import Callable

logger = logging.getLogger(__name__)


def trigger_store_scan(output_cb: Callable[[str], None] = None) -> int:
    """Trigger UpdateScanMethod on every MDM_EnterpriseModernAppManagement_AppManagement01
    instance found in root\\cimv2\\mdm\\dmmap. Returns the number of instances triggered.
    """
    def _log(msg: str) -> None:
        if output_cb:
            output_cb(msg)
        logger.info(msg)

    try:
        import win32com.client

        wmi = win32com.client.GetObject(r"winmgmts:\\.\root\cimv2\mdm\dmmap")
        instances = wmi.ExecQuery(
            "SELECT * FROM MDM_EnterpriseModernAppManagement_AppManagement01"
        )
        count = 0
        for inst in instances:
            try:
                inst.ExecMethod_("UpdateScanMethod")
                count += 1
            except Exception as e:
                logger.warning("UpdateScanMethod failed for one instance: %s", e)
        if count > 0:
            _log(f"Store: update scan triggered on {count} instance(s), downloads continue in background.")
        else:
            _log("Store: MDM class unavailable — use the Open Store button instead.")
        return count
    except Exception as e:
        _log(f"Store trigger failed: {e}")
        return 0
