; Script Inno Setup de tao bo cai dat (Setup.exe) cho GCode Vision tren Windows.
; Chay tren may Windows (hoac GitHub Actions windows-latest) bang Inno Setup 6,
; TU THU MUC GOC cua du an (khong phai tu installer_scripts\):
;   iscc installer_scripts\installer.iss
; Yeu cau: da build san file portable bang PyInstaller vao dist\GCode-Vision.exe
; (xem .github/workflows/build.yml) truoc khi chay script nay.

#define MyAppName "GCode Vision"
#define MyAppVersion "3.2.2"
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
OutputDir=..\installer_output
OutputBaseFilename=GCodeVision-Setup-{#MyAppVersion}
SetupIconFile=..\assets\logo.ico
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
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
{ Xac minh MA LICENSE truoc khi cho cai dat, qua 1 API tren Vercel (khong
  con so sanh mat khau cung nhu truoc) - moi ma CHI DUNG DUOC 1 LAN, server
  se DANH DAU da dung ngay khi xac minh thanh cong, nen du ai giu lai duoc
  file Setup.exe va thu dung lai DUNG MA cu cung se bi tu choi. Doi
  LICENSE_API_URL neu doi domain/API endpoint sau nay. }
const
  LICENSE_API_URL = 'https://gcode-license.tranvanhuy.io.vn/api/verify';
  { Ten file token luu LAI TREN MAY sau khi kich hoat thanh cong - ung dung
    GCode Vision (Python) se doc file nay MOI LAN KHOI DONG de tu xac minh
    lai voi server (qua /api/check), dam bao file .exe dang chay DUNG TREN
    MAY da duoc kich hoat hop le, khong phai bi copy tu may khac. }
  LICENSE_TOKEN_FILENAME = 'license.token';

var
  LicensePage: TInputQueryWizardPage;

{ Machine GUID cua Windows (HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid)
  - 1 chuoi duy nhat, on dinh, duoc Windows tu tao cho MOI LAN CAI DAT HE
  DIEU HANH (khong doi khi restart/cap nhat may, nhung SE KHAC neu cai lai
  Windows hoac dung tren may khac) - dung lam "dau van tay may" don gian,
  khong can tinh toan phuc tap tu phan cung. }
function GetMachineId(): String;
var
  Guid: String;
begin
  if not RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\Cryptography', 'MachineGuid', Guid) then
    Guid := '';
  Result := Guid;
end;

procedure InitializeWizard();
begin
  LicensePage := CreateInputQueryPage(wpWelcome,
    'Yêu cầu mã bản quyền', 'Nhập mã bản quyền để tiếp tục cài đặt',
    'Vui lòng nhập mã bản quyền (định dạng XXXX-XXXX-XXXX-XXXX) do người quản lý cung cấp. ' +
    'Mỗi mã chỉ sử dụng được đúng 1 lần.');
  LicensePage.Add('Mã bản quyền:', False);
end;

{ Goi API xac minh qua PowerShell (co san tren moi Windows 10/11, khong can
  cai them gi) - PowerShell goi HTTP POST toi LICENSE_API_URL, ghi ket qua
  JSON ra 1 file tam de Pascal Script (khong the tu doc HTTP response truc
  tiep) doc lai. Tra ve True neu server xac nhan ma hop le (va vua danh dau
  da dung), False neu bi tu choi hoac loi ket noi. }
function VerifyLicenseOnline(const Code: String; const MachineId: String; var ErrorMsg: String): Boolean;
var
  ResultFile, PsCommand: String;
  ResultCode: Integer;
  ResultLines: TArrayOfString;
  ResultText: String;
begin
  Result := False;
  ResultFile := ExpandConstant('{tmp}\license_check.json');

  { -NoProfile -NonInteractive de chay nhanh, on dinh, khong bi anh huong
    boi profile PowerShell cua may nguoi dung. Bat loi (try/catch) va LUON
    ghi ra file JSON du (ke ca khi loi ket noi), de Pascal Script luon doc
    duoc ket qua thay vi bi treo cho input khong bao gio den. Gui kem
    machineId de server GAN ma nay voi DUNG MAY dang cai dat. }
  PsCommand :=
    '-NoProfile -NonInteractive -Command "' +
    '$ErrorActionPreference=''Stop''; ' +
    'try { ' +
    '  $body = @{ code = ''' + Code + '''; machineId = ''' + MachineId + ''' } | ConvertTo-Json; ' +
    '  $resp = Invoke-RestMethod -Uri ''' + LICENSE_API_URL + ''' -Method Post -Body $body -ContentType ''application/json'' -TimeoutSec 15; ' +
    '  $resp | ConvertTo-Json -Compress | Out-File -FilePath ''' + ResultFile + ''' -Encoding utf8; ' +
    '} catch { ' +
    '  $err = @{ ok = $false; reason = ''connection_error'' } | ConvertTo-Json -Compress; ' +
    '  $err | Out-File -FilePath ''' + ResultFile + ''' -Encoding utf8; ' +
    '}"';

  if not Exec('powershell.exe', PsCommand, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    ErrorMsg := 'Không thể khởi chạy PowerShell để xác minh mã bản quyền.';
    Exit;
  end;

  if not LoadStringsFromFile(ResultFile, ResultLines) or (GetArrayLength(ResultLines) = 0) then
  begin
    ErrorMsg := 'Không nhận được phản hồi từ máy chủ xác minh. Vui lòng kiểm tra kết nối mạng.';
    Exit;
  end;

  ResultText := ResultLines[0];

  { Pascal Script khong co JSON parser san - vi cau truc phan hoi CO DINH va
    don gian (chi can biet "ok":true hay khong), kiem tra bang chuoi con la
    du, khong can parser day du. }
  if Pos('"ok":true', ResultText) > 0 then
  begin
    Result := True;
  end
  else if Pos('already_used', ResultText) > 0 then
    ErrorMsg := 'Mã bản quyền này đã được sử dụng trước đó. Mỗi mã chỉ dùng được 1 lần.'
  else if Pos('not_found', ResultText) > 0 then
    ErrorMsg := 'Mã bản quyền không tồn tại. Vui lòng kiểm tra lại.'
  else if Pos('connection_error', ResultText) > 0 then
    ErrorMsg := 'Không thể kết nối máy chủ xác minh. Vui lòng kiểm tra kết nối mạng và thử lại.'
  else
    ErrorMsg := 'Mã bản quyền không hợp lệ.';
end;

{ Kiem tra Code dung DINH DANG XXXX-XXXX-XXXX-XXXX (chu hoa A-Z, so 0-9, gach
  ngang o dung 3 vi tri) - khong dung regex (Pascal Script khong co san) ma
  duyet tung ky tu, vua du don gian vua chan duoc ky tu la truoc khi Code
  duoc chen vao lenh PowerShell. }
function IsValidLicenseFormat(const Code: String): Boolean;
var
  i: Integer;
  c: Char;
begin
  Result := False;
  if Length(Code) <> 19 then Exit;
  for i := 1 to 19 do
  begin
    c := Code[i];
    if (i = 5) or (i = 10) or (i = 15) then
    begin
      if c <> '-' then Exit;
    end
    else
    begin
      if not (((c >= 'A') and (c <= 'Z')) or ((c >= '0') and (c <= '9'))) then Exit;
    end;
  end;
  Result := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Code, ErrorMsg, MachineId: String;
begin
  Result := True;
  if CurPageID = LicensePage.ID then
  begin
    Code := Trim(Uppercase(LicensePage.Values[0]));
    if Code = '' then
    begin
      MsgBox('Vui lòng nhập mã bản quyền.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    { Chi cho phep dung ky tu chu hoa, so va dau gach ngang - dung dinh dang
      XXXX-XXXX-XXXX-XXXX ma server tao ra. Chan som cac ky tu la (vd dau
      nhay don ') truoc khi chen vao lenh PowerShell, tranh loi cu phap hoac
      hanh vi bat thuong du kha nang xay ra trong thuc te rat thap. }
    if not IsValidLicenseFormat(Code) then
    begin
      MsgBox('Mã bản quyền không đúng định dạng (XXXX-XXXX-XXXX-XXXX).', mbError, MB_OK);
      Result := False;
      Exit;
    end;

    MachineId := GetMachineId();
    if MachineId = '' then
    begin
      MsgBox('Không thể xác định định danh máy tính. Vui lòng liên hệ hỗ trợ.', mbError, MB_OK);
      Result := False;
      Exit;
    end;

    WizardForm.Cursor := crHourglass;
    try
      if not VerifyLicenseOnline(Code, MachineId, ErrorMsg) then
      begin
        MsgBox(ErrorMsg, mbError, MB_OK);
        Result := False;
      end
      else
      begin
        { Luu lai token (ma + machineId) VAO THU MUC CAI DAT - ung dung
          GCode Vision se doc file nay moi lan khoi dong de tu xac minh lai
          voi server, dam bao dang chay DUNG TREN MAY da kich hoat. Thu muc
          cai dat (constant app) co the CHUA TON TAI o thoi diem nay (truoc
          khi cac buoc cai dat file chinh chay), nen phai tu tao truoc khi
          ghi file. }
        ForceDirectories(ExpandConstant('{app}'));
        SaveStringToFile(ExpandConstant('{app}\' + LICENSE_TOKEN_FILENAME),
          Code + #13#10 + MachineId, False);
      end;
    finally
      WizardForm.Cursor := crDefault;
    end;
  end;
end;
