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
; under $PROFILE\.flinttrade. This hook extends that SAME checkbox to those
; folders, so ticking it truly removes all data the app has created.
;
; Safety guards, matching the template's own app-data block:
;   - $UpdateMode <> 1 - the updater re-runs the uninstaller in update mode;
;     an auto-update must never delete trading data.
;   - Silent uninstalls (/S) never show the confirm page, so
;     $DeleteAppDataCheckboxState stays 0 and all data is kept fail-safe.
;     Scripted full removal goes through flinttrade-uninstall.ps1 -Purge.

!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    SetShellVarContext current
    RMDir /r "$APPDATA\flinttrade"
    RMDir /r "$PROFILE\.flinttrade"
  ${EndIf}
!macroend
