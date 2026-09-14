; Script Inno Setup de tao bo cai dat (Setup.exe) cho GCode Vision tren Windows.
; Chay tren may Windows (hoac GitHub Actions windows-latest) bang Inno Setup 6:
;   iscc installer.iss
; Yeu cau: da build san file portable bang PyInstaller vao dist\GCode-Vision.exe
; (xem .github/workflows/build.yml) truoc khi chay script nay.

#define MyAppName "GCode Vision"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Tran Van Huy"
#define MyAppURL "https://www.tranvanhuy.io.vn"
#define MyAppExeName "GCode-Vision.exe"

[Setup]
AppId={{B7B6B1B0-2C1C-4D6E-9C4C-1F6E9C6C5A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=GCodeVision-Setup-{#MyAppVersion}
SetupIconFile=logo.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
{ Yeu cau nguoi dung nhap dung mat khau TRUOC KHI qua trinh cai dat bat dau,
  de kiem soat ai co the cai duoc ung dung tu file Setup.exe nay. Mat khau nay
  chi bao ve o muc "nguoi thuong khong the tu cai" - repo la Private nen chap
  nhan duoc, nhung day KHONG phai ma hoa/bao mat manh (ai co source deu doc
  duoc plain-text nay). Doi INSTALLER_PASSWORD o day khi can thay mat khau. }
const
  INSTALLER_PASSWORD = 'hichan26032006@';

var
  PasswordPage: TInputQueryWizardPage;

procedure InitializeWizard();
begin
  PasswordPage := CreateInputQueryPage(wpWelcome,
    'Yêu cầu mật khẩu', 'Bộ cài đặt này được bảo vệ bằng mật khẩu',
    'Vui lòng nhập mật khẩu do người quản lý cung cấp để tiếp tục cài đặt GCode Vision.');
  PasswordPage.Add('Mật khẩu:', True); { True = an ky tu nhap (hien dau *) }
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = PasswordPage.ID then
  begin
    if PasswordPage.Values[0] <> INSTALLER_PASSWORD then
    begin
      MsgBox('Mật khẩu không đúng. Vui lòng thử lại.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;
