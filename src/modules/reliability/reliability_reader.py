import logging
from datetime import datetime
from typing import List, Optional, Callable

from core.types import LogEntry

logger = logging.getLogger(__name__)


def read_reliability_records(
    max_records: int = 1000,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> List[LogEntry]:
    """Read reliability records from WMI."""
    try:
        import wmi
    except ImportError:
        logger.error("wmi package not installed")
        return []

    entries = []
    try:
        c = wmi.WMI(namespace=r"root\cimv2")
        records = c.query("SELECT * FROM Win32_ReliabilityRecords")
        total = min(len(records), max_records)

        for i, record in enumerate(records[:max_records]):
            # Parse WMI timestamp: 20260325111727.224000-000
            ts = record.TimeGenerated
            try:
                event_time = datetime.strptime(ts[:14], "%Y%m%d%H%M%S")
            except (ValueError, TypeError):
                event_time = datetime.now()

            # Determine level from record type
            source_name = getattr(record, "SourceName", "Unknown")
            event_id = getattr(record, "EventIdentifier", 0)
            message = getattr(record, "Message", "") or ""
            product_name = getattr(record, "ProductName", "") or ""

            # Classify level
            level = "Info"
            if "fail" in message.lower() or "error" in message.lower():
                level = "Error"
            elif "warn" in message.lower():
                level = "Warning"

            display_message = message if message else product_name
            if not display_message:
                display_message = f"Event {event_id} from {source_name}"

            entries.append(LogEntry(
                timestamp=event_time,
                source=source_name,
                level=level,
                message=display_message,
                raw={
                    "event_id": event_id,
                    "product_name": product_name,
                    "computer_name": getattr(record, "ComputerName", ""),
                },
            ))

            if progress_callback and i % 50 == 0:
                progress_callback(min(int((i / total) * 100), 99))

    except Exception as e:
        logger.error("Failed to read reliability records: %s", e)

    entries.sort(key=lambda e: e.timestamp, reverse=True)
    if progress_callback:
        progress_callback(100)
    return entries
