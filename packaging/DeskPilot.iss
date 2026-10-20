; Compile through scripts/build-installer.py after validating the payload.
#ifndef PackageDir
  #error PackageDir is required
#endif
#ifndef BuildId
  #error BuildId is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

; Only the lifecycle harness uses this alternate identity. Production identity
; remains stable across versions; never add a version number to AppId.
#ifdef ValidationBuild
  #define ProductId "DeskPilot.InstallerValidation"
  #define ProductName "DeskPilot Installer Validation"
  #define ProductDir "DeskPilot-InstallerValidation"
  #define RunningMutex "Local\DeskPilot.InstallerValidation.Running"
#else
  #define ProductId "DeskPilot.Desktop"
  #define ProductName "DeskPilot"
  #define ProductDir "DeskPilot"
  #define RunningMutex "Local\DeskPilot.Desktop.Running"
#endif

[Setup]
AppId={#ProductId}
AppName={#ProductName}
AppVersion={#AppVersion}
AppVerName={#ProductName} {#AppVersion} (test)
AppPublisher=DeskPilot
DefaultDirName={localappdata}\Programs\{#ProductDir}
DefaultGroupName={#ProductName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible and not arm64
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
AppMutex={#RunningMutex}
SetupMutex={#ProductId}.Setup
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\versions\{#BuildId}\DeskPilot.exe
UninstallDisplayName={#ProductName} (test)
OutputDir={#OutputDir}
OutputBaseFilename=DeskPilot-{#AppVersion}-{#BuildId}-setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#ProductName} test installer
InfoBeforeFile=installer-info.txt
Uninstallable=yes
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
; Separate runtimes prevent obsolete modules from an earlier version being
; imported by an update. Inno tracks all installed versions for uninstall.
Source: "{#PackageDir}\*"; DestDir: "{app}\versions\{#BuildId}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#ProductName}"; Filename: "{app}\versions\{#BuildId}\DeskPilot.exe"; WorkingDir: "{app}\versions\{#BuildId}"

; No Run, autostart, InstallDelete or UninstallDelete section. Installation never
; activates a microphone, and uninstall removes only files Inno installed.
; Documents/DeskPilot, LOCALAPPDATA/DeskPilot and model caches stay untouched.
