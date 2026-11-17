DICOM 批次轉 NIfTI Windows 安裝檔專案
====================================
本專案直接採用使用者提供的 Tkinter Python 原始碼，不修改轉換邏輯。

取得真正的 Windows Setup.exe 的方式：
A. 不在自己的電腦安裝開發環境（建議）
1. 在 GitHub 建立私人 repository，將這個專案所有檔案及 .github 資料夾上傳。
2. GitHub Actions > Build Windows installer > Run workflow。
3. 工作完成後，從 Artifacts 下載 DICOM_to_NIfTI_Windows_v2_1。
4. 解壓縮後取得 installer_output/DICOM_to_NIfTI_Setup_v2_1.exe。
5. 在 Windows 上實際測試安裝、開啟 GUI 與一筆非敏感 DICOM 測試資料。
注意：GitHub 上傳的只有原始程式碼，不要上傳 DICOM 或任何病患資料。

B. 自己在 Windows 建置一次
1. 建置電腦安裝 Python 3.12 x64 與 Inno Setup 6。
2. 雙擊 建立安裝檔_Windows.bat。
3. 安裝檔位於 installer_output/DICOM_to_NIfTI_Setup_v2_1.exe。
4. 提供 Setup.exe 給醫師；醫師不需要 Python、pip、Inno Setup。

醫師使用：安裝後從開始功能表開啟 DICOM to NIfTI，選來源與新的輸出資料夾，按開始轉換。
輸出結構與 CSV 中可能含病患識別資訊，請放在院方允許的位置。

重要限制：本環境是 Linux，無法驗證 Windows EXE 或 Windows 安裝流程；建置腳本也尚未在 Windows 實機執行。
