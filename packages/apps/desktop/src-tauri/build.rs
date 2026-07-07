fn main() {
    // App commands are ACL-gated like plugin commands: listing them here makes
    // tauri-build autogenerate ``allow-updater-state`` / ``allow-run-self-update``
    // permissions (command names are slugified, ``_`` -> ``-``), which
    // ``capabilities/main-remote.json`` then grants to the remote main window.
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&["updater_state", "run_self_update"]),
        ),
    )
    .expect("failed to run tauri-build");
}
