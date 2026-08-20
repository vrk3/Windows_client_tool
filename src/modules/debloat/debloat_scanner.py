"""debloat_scanner — detects installed bloatware apps and tweak states."""
import json
import logging
import subprocess
from typing import Dict, List

logger = logging.getLogger(__name__)

KNOWN_PACKAGES = {
    # Bing Apps
    "Microsoft.BingWeather", "Microsoft.BingNews", "Microsoft.BingFinance",
    "Microsoft.BingSports", "Microsoft.BingTravel", "Microsoft.BingFoodAndDrink",
    "Microsoft.BingHealthAndFitness", "Microsoft.BingTranslator", "Microsoft.BingSearch",
    # System Utilities
    "Microsoft.WindowsCalculator", "Microsoft.WindowsCamera", "Microsoft.WindowsAlarms",
    "Microsoft.ScreenSketch", "Microsoft.WindowsNotepad", "Microsoft.Paint",
    "Microsoft.WindowsSoundRecorder", "MicrosoftCorporationII.QuickAssist",
    "Microsoft.MicrosoftStickyNotes", "Microsoft.WindowsTerminal",
    "Clipchamp.Clipchamp", "Microsoft.MicrosoftJournal",
    # Microsoft Communications
    "Microsoft.windowscommunicationsapps", "Microsoft.Messaging",
    "Microsoft.SkypeApp", "Microsoft.YourPhone", "Microsoft.549981C3F5F50",
    # Microsoft Office
    "Microsoft.MicrosoftOfficeHub", "Microsoft.Office.OneNote",
    "Microsoft.OutlookForWindows", "Microsoft.M365Companions",
    "Microsoft.PowerAutomateDesktop", "Microsoft.Todos", "Microsoft.Office.Sway",
    # Microsoft Media
    "Microsoft.ZuneVideo", "Microsoft.ZuneMusic", "Microsoft.Windows.Photos",
    "Microsoft.3DBuilder", "Microsoft.Microsoft3DViewer", "Microsoft.MSPaint",
    # Microsoft Gaming
    "Microsoft.XboxApp", "Microsoft.XboxGameOverlay", "Microsoft.GamingApp",
    "Microsoft.XboxIdentityProvider", "Microsoft.XboxSpeechToTextOverlay",
    "Microsoft.Xbox.TCUI", "Microsoft.XboxConsoleCompanion",
    # Microsoft Miscellaneous
    "Microsoft.WindowsStore", "MSTeams", "MicrosoftTeams",
    "Microsoft.MicrosoftSolitaireCollection", "Microsoft.Whiteboard",
    "Microsoft.Windows.DevHome", "MicrosoftCorporationII.MicrosoftFamily",
    "Microsoft.WindowsFeedbackHub", "Microsoft.GetHelp", "Microsoft.Getstarted",
    "Microsoft.PCManager", "Microsoft.MixedReality.Portal", "Microsoft.RemoteDesktop",
    "Microsoft.StartExperiencesApp", "Microsoft.NetworkSpeedTest",
    "LinkedInforWindows",
    # Third-Party Consumer
    "Amazon.com.Amazon", "Facebook", "Instagram", "Spotify", "Netflix",
    "Disney", "TikTok", "king.com.CandyCrushSaga", "king.com.CandyCrushSodaSaga",
    "king.com.BubbleWitch3Saga", "AdobeSystemsIncorporated.AdobePhotoshopExpress",
    "AutodeskSketchBook", "Duolingo-LearnLanguagesforFree", "PandoraMediaInc",
    "Plex", "TuneInRadio", "ACGMediaPlayer", "COOKINGFEVER",
    "DisneyMagicKingdoms", "FarmVille2CountryEscape", "Fitbit", "Flipboard",
    "HiddenCity", "HULULLC.HULUPLUS", "iHeartRadio", "MarchofEmpires",
    "NYTCrossword", "OneCalendar", "PhototasticCollage", "PicsArt-PhotoStudio",
    "PolarrPhotoEditorAcademicEdition", "PrimeVideo", "Royal Revolt", "Shazam",
    "SlingTV", "Twitter", "Viber", "WinZipUniversal", "Wunderlist",
    "Sidia.LiveWallpaper", "EclipseManager", "XING", "ActiproSoftwareLLC",
    "CyberLinkMediaSuiteEssentials", "Microsoft.OneConnect", "Asphalt8Airborne",
    # HP OEM
    "AD2F1837.HPAIExperienceCenter", "AD2F1837.HPConnectedMusic",
    "AD2F1837.HPConnectedPhotopoweredbySnapfish", "AD2F1837.HPDesktopSupportUtilities",
    "AD2F1837.HPEasyClean", "AD2F1837.HPFileViewer", "AD2F1837.HPJumpStarts",
    "AD2F1837.HPPCHardwareDiagnosticsWindows", "AD2F1837.HPPowerManager",
    "AD2F1837.HPPrinterControl", "AD2F1837.HPPrivacySettings", "AD2F1837.HPQuickDrop",
    "AD2F1837.HPQuickTouch", "AD2F1837.HPRegistration", "AD2F1837.HPSupportAssistant",
    "AD2F1837.HPSureShieldAI", "AD2F1837.HPSystemInformation", "AD2F1837.HPWelcome",
    "AD2F1837.HPWorkWell", "AD2F1837.myHP",
    # Dell OEM
    "DellInc.DellDigitalDelivery", "DellInc.DellMobileConnect",
    "DellInc.DellSupportAssistforPCs",
    # Lenovo OEM
    "E046963F.LenovoCompanion", "LenovoCompanyLimited.LenovoVantageService",
}


def get_installed_packages() -> Dict[str, str]:
    """Return {package_name: display_name} for known installed Appx packages."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-AppxPackage | Select-Object Name, PackageFullName | ConvertTo-Json -Compress"],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    installed: Dict[str, str] = {}
    if not result.stdout.strip():
        return installed
    try:
        data = json.loads(result.stdout)
        if isinstance(data, dict):
            data = [data]
        for entry in data:
            name = entry.get("Name", "")
            if name in KNOWN_PACKAGES:
                installed[name] = name
    except Exception as e:
        logger.debug("Failed to parse AppxPackage output: %s", e)
    return installed


def check_app_installed(package_name: str) -> bool:
    """Return True if the given Appx package is installed."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Get-AppxPackage '{package_name}' -ErrorAction SilentlyContinue | Select-Object -First 1 Name"],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return bool(result.stdout.strip())


PROTECTED_APPS = {
    "Microsoft.WindowsStore",
    "Microsoft.WindowsTerminal",
    "Microsoft.GetHelp",
    "Microsoft.WindowsAlarms",
    "Microsoft.WindowsCalculator",
    "Microsoft.WindowsNotepad",
}

PROTECTED_REASONS = {
    "Microsoft.WindowsStore": "Required for installing apps from Microsoft Store",
    "Microsoft.WindowsTerminal": "Recommended terminal — removal not advised",
    "Microsoft.GetHelp": "Built-in Windows help system",
    "Microsoft.WindowsAlarms": "System clock and alarms",
    "Microsoft.WindowsCalculator": "System calculator",
    "Microsoft.WindowsNotepad": "System text editor",
}
