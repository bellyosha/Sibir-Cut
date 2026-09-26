#define MyAppName "Сибирь Cut"
#define MyAppVersion "0.2.11"
#define MyAppExeName "SibirCut.exe"

[Setup]
AppId={{0F38D788-9A41-4E9B-9DDA-5FC5E88B9301}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\Сибирь Cut
DefaultGroupName=Сибирь Cut
OutputDir=..\dist
OutputBaseFilename=Sibir_Cut_Setup_0.2.11_x64
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}

[InstallDelete]
Type: files; Name: "{app}\NovatechCut.exe"
Type: files; Name: "{group}\Novatech Cut.lnk"
Type: files; Name: "{autodesktop}\Novatech Cut.lnk"

[Files]
Source: "..\dist\SibirCut.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Сибирь Cut"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Сибирь Cut"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить Сибирь Cut"; Flags: nowait postinstall skipifsilent
