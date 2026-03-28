from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TaskInfo:
    name: str
    path: str
    status: str      # "Ready" | "Running" | "Disabled" | "Unknown"
    last_run: str
    last_result: str
    next_run: str
    author: str
    triggers: str
    xml: str
    enabled: bool


@dataclass
class TaskFolder:
    name: str
    path: str
    subfolders: List["TaskFolder"] = field(default_factory=list)


def _fmt_date(dt) -> str:
    try:
        s = str(dt)
        if s.startswith("1899") or s.startswith("1900"):
            return "Never"
        return s[:16].replace("T", " ")
    except Exception:
        return ""


def get_folder_tree() -> TaskFolder:
    """Returns root TaskFolder with nested subfolders. Must be called from COMWorker."""
    import win32com.client
    svc = win32com.client.Dispatch("Schedule.Service")
    svc.Connect()
    root = svc.GetFolder("\\")
    return _build_folder(root, "\\")


def _build_folder(com_folder, path: str) -> TaskFolder:
    tf = TaskFolder(name=com_folder.Name or "\\", path=path)
    try:
        for sub in com_folder.GetFolders(0):
            subpath = path.rstrip("\\") + "\\" + sub.Name
            tf.subfolders.append(_build_folder(sub, subpath))
    except Exception:
        pass
    return tf


def get_tasks_in_folder(folder_path: str) -> List[TaskInfo]:
    """Get tasks in a specific folder. Must be called from COMWorker."""
    import win32com.client
    svc = win32com.client.Dispatch("Schedule.Service")
    svc.Connect()
    folder = svc.GetFolder(folder_path)
    tasks = []
    try:
        for i in range(folder.GetTasks(0).Count):
            task = folder.GetTasks(0).Item(i + 1)
            try:
                state_map = {0: "Unknown", 1: "Disabled", 2: "Queued", 3: "Ready", 4: "Running"}
                status = state_map.get(task.State, "Unknown")
                # Triggers summary
                try:
                    trig_count = task.Definition.Triggers.Count
                    if trig_count > 0:
                        trig_type = task.Definition.Triggers.Item(1).Type
                        type_map = {
                            1: "Event", 2: "Time", 3: "Daily", 4: "Weekly", 5: "Monthly",
                            6: "MonthlyDOW", 7: "Idle", 8: "Registration", 9: "Boot",
                            10: "Logon", 11: "SessionStateChange",
                        }
                        triggers = type_map.get(trig_type, f"Type{trig_type}")
                        if trig_count > 1:
                            triggers += f" (+{trig_count - 1})"
                    else:
                        triggers = "None"
                except Exception:
                    triggers = ""
                # Author
                try:
                    author = task.Definition.RegistrationInfo.Author or ""
                except Exception:
                    author = ""
                tasks.append(TaskInfo(
                    name=task.Name,
                    path=task.Path,
                    status=status,
                    last_run=_fmt_date(task.LastRunTime),
                    last_result=str(task.LastTaskResult),
                    next_run=_fmt_date(task.NextRunTime),
                    author=author,
                    triggers=triggers,
                    xml=task.Xml,
                    enabled=(task.State != 1),
                ))
            except Exception:
                continue
    except Exception:
        pass
    return tasks
