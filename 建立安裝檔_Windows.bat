@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "LOG=%~dp0build_log.txt"
echo Build started > "%LOG%"
echo [1/4] 檢查 Python 3.12...
where py >nul 2>&1 || goto :missingpython
py -3.12 -c "import sys; assert sys.maxsize > 2**32" >> "%LOG%" 2>&1 || goto :missingpython
py -3.12 -m venv .venv >> "%LOG%" 2>&1 || goto :failed
set "PY=%~dp0.venv\Scripts\python.exe"
echo [2/4] 建立程式環境...
"%PY%" -m pip install --upgrade pip >> "%LOG%" 2>&1 || goto :failed
"%PY%" -m pip install -r requirements.txt >> "%LOG%" 2>&1 || goto :failed
echo [3/4] 封裝 GUI...
"%PY%" -m PyInstaller --noconfirm --clean --windowed --onedir --name DICOM_to_NIfTI --collect-all dicom2nifti --collect-all nibabel --collect-all pydicom --collect-all scipy dicom_nifti_gui.py >> "%LOG%" 2>&1 || goto :failed
if not exist "dist\DICOM_to_NIfTI\DICOM_to_NIfTI.exe" goto :failed
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" goto :missinginno
echo [4/4] 產生安裝檔...
"%ISCC%" DICOM_to_NIfTI.iss >> "%LOG%" 2>&1 || goto :failed
if not exist "installer_output\DICOM_to_NIfTI_Setup_v2_1.exe" goto :failed
echo 完成：installer_output\DICOM_to_NIfTI_Setup_v2_1.exe
explorer "%~dp0installer_output"
pause
exit /b 0
:missingpython
echo 找不到 64 位元 Python 3.12。請在 Windows 建置機安裝 Python 3.12。
goto :failed
:missinginno
echo 已產生可攜式應用程式 dist\DICOM_to_NIfTI，但缺少 Inno Setup 6，無法產生安裝檔。
echo 可安裝 Inno Setup 6 再重新執行，或使用 GitHub Actions 自動建置。
goto :failed
:failed
echo 建置未完成。請查看 build_log.txt
pause
exit /b 1
