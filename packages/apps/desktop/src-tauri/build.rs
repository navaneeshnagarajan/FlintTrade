fn main() {
    // App commands are ACL-gated like plugin commands: listing them here makes
    // tauri-build autogenerate the updater permissions plus the narrowly scoped
    // ``allow-quit-after-backend-failure`` recovery permission (command names
    // are slugified, ``_`` -> ``-``), which
    // ``capabilities/main-remote.json`` grants to the main window.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "updater_state",
            "run_binary_update",
            "run_self_update",
            "check_native_update",
            "apply_native_update",
            "check_payload_update",
            "apply_payload_update",
            "retry_bootstrap",
            "bootstrap_status",
            "quit_after_backend_failure",
        ]),
    ))
    .expect("failed to run tauri-build");
}
