#define MyAppName "DICOM to NIfTI"
#define MyAppVersion "2.1"
#define MyAppExeName "DICOM_to_NIfTI.exe"
[Setup]
AppId={{6DEAB410-93D1-4843-B8E6-05DA1249A30D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Medical Imaging Research
DefaultDirName={localappdata}\Programs\DICOM_to_NIfTI
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=DICOM_to_NIfTI_Setup_v2_1
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
DisableProgramGroupPage=yes
[Files]
Source: "dist\DICOM_to_NIfTI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "建立桌面捷徑"; GroupDescription: "其他選項："; Flags: unchecked
[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "開啟 DICOM to NIfTI"; Flags: nowait postinstall skipifsilent
