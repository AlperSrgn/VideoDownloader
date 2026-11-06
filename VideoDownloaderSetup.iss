[Setup]
AppName=Video Downloader
AppVersion=3.x.x
DefaultDirName={autopf}\VideoDownloader
DefaultGroupName=VideoDownloader
OutputDir=output
OutputBaseFilename=VideoDownloaderSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=yes
PrivilegesRequired=lowest
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
[Files]
Source: "dist\main.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "icons\appIcon.ico"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{group}\Video Downloader"; Filename: "{app}\main.exe"; IconFilename: "{app}\appIcon.ico"
Name: "{userdesktop}\Video Downloader"; Filename: "{app}\main.exe"; Tasks: desktopicon; IconFilename: "{app}\appIcon.ico"
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
[Run]
Filename: "{app}\main.exe"; Description: "{cm:LaunchProgram,Video Downloader}"; Flags: nowait postinstall skipifsilent
[UninstallDelete]
; Settings, icons, yt-dlp.exe and cookies.txt (see get_appdata_path() in settings.py)
Type: filesandordirs; Name: "{localappdata}\VideoDownloader"
