; Inno Setup script for Personify Voice AI (Personify Crafters)
; Build the exe first (build_windows.bat), then compile this script
; with Inno Setup 6+ (https://jrsoftware.org/isinfo.php)

#define AppName "Personify Voice AI"
#define AppVersion "1.1.0"
#define AppPublisher "Personify Crafters"
#define AppExe "PersonifyVoiceAI.exe"

[Setup]
AppId={{3D6B91C4-52E8-4F0A-B7D3-9C2E51AF60B8}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=Output
OutputBaseFilename=PersonifyVoiceAI-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
PrivilegesRequired=lowest
; User data lives in %APPDATA%\PersonifyVoiceAI and is NEVER touched by
; install/uninstall, so updates preserve sessions and settings.

[Files]
Source: "..\dist\PersonifyVoiceAI\*"; DestDir: "{app}"; \
    Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; \
    Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; \
    Flags: nowait postinstall skipifsilent
