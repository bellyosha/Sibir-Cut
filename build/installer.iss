#define MyAppName "Novatech Cut"
#define MyAppVersion "0.1.5"
#define MyAppExeName "NovatechCut.exe"

[Setup]
AppId={{0F38D788-9A41-4E9B-9DDA-5FC5E88B9301}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\Novatech Cut
DefaultGroupName=Novatech Cut
OutputDir=..\dist
OutputBaseFilename=Novatech_Cut_Setup_0.1.5_x64
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\NovatechCut.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Novatech Cut"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Novatech Cut"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить Novatech Cut"; Flags: nowait postinstall skipifsilent
