; FlintTrade NSIS installer hooks, wired via bundle.windows.nsis.installerHooks
; in tauri.conf.json. Compiled into Tauri's installer.nsi template, which
; !includes this file and !insertmacro's each NSIS_HOOK_* macro it defines.
;
; The stock Tauri uninstaller's "Delete the application data" checkbox removes
; only the bundle-id folders ($APPDATA\com.flinttrade.app and
; $LOCALAPPDATA\com.flinttrade.app - the Tauri config and WebView2 profile).
; FlintTrade's actual trading data lives in the backend workspace at
; $APPDATA\flinttrade (encrypted credential vault, auth.db, journals,
; workspace.json, runtime backend payload), with a build-from-source clone
; under $PROFILE\.flinttrade. When that checkbox is ticked, this hook offers
; to remove those folders too - behind its own explicit confirmation that
; names the vault, because the stock checkbox label never mentions trading
; data and must not silently gain the power to destroy it.
;
; Safety guards, matching the template's own app-data block:
;   - $UpdateMode <> 1 - the updater re-runs the uninstaller in update mode;
;     an auto-update must never delete trading data.
;   - Silent uninstalls (/S) never show the confirm page, so
;     $DeleteAppDataCheckboxState stays 0 and all data is kept fail-safe;
;     the MessageBox silent defaults (/SD) also both refuse.
;     Scripted full removal goes through flinttrade-uninstall.ps1 -Purge.
;   - RMDir /r only sets the error flag on locked files, so the hook checks
;     for leftovers afterwards and tells the user instead of reporting a
;     clean purge while the vault survives.

!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    MessageBox MB_YESNO|MB_ICONEXCLAMATION|MB_DEFBUTTON2 "Also delete FlintTrade's trading data?$\r$\n$\r$\nThis permanently removes the encrypted credential vault, auth database, trade journals, and settings at:$\r$\n$APPDATA\flinttrade$\r$\n$\r$\nThis cannot be undone." /SD IDNO IDNO ft_uninstall_keep_workspace
    SetShellVarContext current
    ClearErrors
    RMDir /r "$APPDATA\flinttrade"
    RMDir /r "$PROFILE\.flinttrade"
    ${If} ${Errors}
    ${OrIf} ${FileExists} "$APPDATA\flinttrade\*.*"
    ${OrIf} ${FileExists} "$PROFILE\.flinttrade\*.*"
      MessageBox MB_OK|MB_ICONEXCLAMATION "Some FlintTrade data could not be removed (files may still be in use).$\r$\n$\r$\nPlease check and delete these folders manually:$\r$\n$APPDATA\flinttrade$\r$\n$PROFILE\.flinttrade" /SD IDOK
    ${EndIf}
  ft_uninstall_keep_workspace:
  ${EndIf}
!macroend
