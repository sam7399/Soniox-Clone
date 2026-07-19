; Inno Setup script for GlobalVoice AI
; Build the exe first (build_windows.bat), then compile this script
; with Inno Setup 6+ (https://jrsoftware.org/isinfo.php)

#define AppName "GlobalVoice AI"
#define AppVersion "1.0.0"
#define AppPublisher "Your Company"
#define AppExe "GlobalVoiceAI.exe"

[Setup]
AppId={{8E4C2F7A-1B7D-4A57-9C1E-0AB374C11D29}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=Output
OutputBaseFilename=GlobalVoiceAI-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
PrivilegesRequired=lowest
; User data lives in %APPDATA%\GlobalVoiceAI and is NEVER touched by
; install/uninstall, so updates preserve sessions and settings.

[Files]
Source: "..\dist\GlobalVoiceAI\*"; DestDir: "{app}"; \
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
