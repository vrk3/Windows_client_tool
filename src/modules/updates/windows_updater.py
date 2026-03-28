from dataclasses import dataclass, field
from typing import List, Callable, Optional


@dataclass
class WindowsUpdate:
    kb: str
    title: str
    classification: str
    size_mb: float
    release_date: str
    identity: object = field(default=None, repr=False)  # IUpdate COM object, stored for install


def fetch_pending_updates() -> List[WindowsUpdate]:
    """
    Uses Microsoft.Update.Session COM object to get pending updates.
    Must be called from a COMWorker thread (CoInitialize already done).
    """
    import win32com.client
    updates = []
    try:
        session = win32com.client.Dispatch("Microsoft.Update.Session")
        searcher = session.CreateUpdateSearcher()
        result = searcher.Search("IsInstalled=0 and IsHidden=0")
        for i in range(result.Updates.Count):
            u = result.Updates.Item(i)
            # KB numbers
            kb_list = [u.KBArticleIDs.Item(j) for j in range(u.KBArticleIDs.Count)]
            kb = ", ".join(f"KB{k}" for k in kb_list) if kb_list else "N/A"
            # Classification
            cats = [u.Categories.Item(j).Name for j in range(u.Categories.Count)]
            classification = cats[0] if cats else "Unknown"
            # Size
            try:
                size_mb = u.MaxDownloadSize / (1024 * 1024)
            except Exception:
                size_mb = 0.0
            # Date
            try:
                release_date = str(u.LastDeploymentChangeTime)[:10]
            except Exception:
                release_date = "Unknown"
            updates.append(WindowsUpdate(
                kb=kb, title=u.Title, classification=classification,
                size_mb=size_mb, release_date=release_date, identity=u,
            ))
    except Exception as e:
        raise RuntimeError(f"Failed to query Windows Updates: {e}") from e
    return updates


def install_updates(updates: List[WindowsUpdate],
                    output_cb: Callable[[str], None]) -> None:
    """
    Install a list of WindowsUpdate objects.
    Must be called from a COMWorker thread.
    """
    import win32com.client
    try:
        session = win32com.client.Dispatch("Microsoft.Update.Session")
        downloader = session.CreateUpdateDownloader()
        installer = session.CreateUpdateInstaller()

        # Create update collection
        coll = win32com.client.Dispatch("Microsoft.Update.UpdateColl")
        for u in updates:
            if u.identity is not None:
                coll.Add(u.identity)

        if coll.Count == 0:
            output_cb("No updates to install.")
            return

        # Download
        output_cb(f"Downloading {coll.Count} update(s)...")
        downloader.Updates = coll
        dl_result = downloader.Download()
        output_cb(f"Download result: {dl_result.ResultCode}")

        # Install
        output_cb("Installing updates...")
        installer.Updates = coll
        install_result = installer.Install()
        output_cb(f"Install result: {install_result.ResultCode}")
        if install_result.RebootRequired:
            output_cb("Reboot required to complete installation.")
    except Exception as e:
        output_cb(f"Error: {e}")
