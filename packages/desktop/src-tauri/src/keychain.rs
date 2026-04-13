//! OS keychain credential storage for FlintTrade Desktop.
//!
//! Provides a thin, cross-platform wrapper around the [`keyring`] crate so that
//! sensitive values (API keys, broker tokens, encryption keys) are stored in the
//! operating-system credential store rather than plain files:
//!
//! * **Windows** — Windows Credential Manager
//! * **macOS**   — macOS Keychain
//! * **Linux**   — libsecret / GNOME Keyring (or KWallet via D-Bus)
//!
//! All values are namespaced under the `"flinttrade"` service name so they never
//! collide with other applications.
//!
//! # Example
//!
//! ```no_run
//! use flinttrade_desktop_lib::keychain;
//!
//! keychain::store_credential("api_key", "my-secret-api-key").unwrap();
//! let value = keychain::get_credential("api_key").unwrap();
//! assert_eq!(value, "my-secret-api-key");
//! keychain::delete_credential("api_key").unwrap();
//! ```

use keyring::Entry;
use thiserror::Error;

/// Service name used for every keychain entry.
const SERVICE: &str = "flinttrade";

/// Errors that can arise from keychain operations.
#[derive(Debug, Error)]
pub enum KeychainError {
    /// The underlying OS keychain returned an error.
    #[error("keychain error for key '{key}': {source}")]
    Keyring {
        key: String,
        #[source]
        source: keyring::Error,
    },
}

/// Convenience alias so callers can write `keychain::Result<T>`.
pub type Result<T> = std::result::Result<T, KeychainError>;

// ─────────────────────────────────────────────────────────────────────────────
// Core helpers (not exported as Tauri commands — used by other modules)
// ─────────────────────────────────────────────────────────────────────────────

/// Store `value` under `key` in the OS keychain.
///
/// If an entry for `key` already exists it is silently overwritten.
///
/// # Arguments
///
/// * `key`   — Logical name for the credential (e.g. `"api_key"`, `"broker_token"`).
/// * `value` — Secret string to persist.
///
/// # Errors
///
/// Returns [`KeychainError::Keyring`] if the OS denies the write.
pub fn store_credential(key: &str, value: &str) -> Result<()> {
    let entry = make_entry(key)?;
    entry
        .set_password(value)
        .map_err(|source| KeychainError::Keyring {
            key: key.to_owned(),
            source,
        })
}

/// Retrieve the secret stored under `key` from the OS keychain.
///
/// # Errors
///
/// Returns [`KeychainError::Keyring`] if the key does not exist or the OS
/// denies the read.
pub fn get_credential(key: &str) -> Result<String> {
    let entry = make_entry(key)?;
    entry
        .get_password()
        .map_err(|source| KeychainError::Keyring {
            key: key.to_owned(),
            source,
        })
}

/// Delete the credential stored under `key` from the OS keychain.
///
/// Succeeds silently if the credential does not exist (`NoEntry` is treated as
/// success to allow idempotent deletion).
///
/// # Errors
///
/// Returns [`KeychainError::Keyring`] for any OS-level failure other than a
/// missing entry.
pub fn delete_credential(key: &str) -> Result<()> {
    let entry = make_entry(key)?;
    match entry.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()), // already gone — that is fine
        Err(source) => Err(KeychainError::Keyring {
            key: key.to_owned(),
            source,
        }),
    }
}

/// Build a [`keyring::Entry`] for `(SERVICE, key)`.
///
/// This is infallible on all currently supported platforms, so the `Result`
/// wrapper is a forward-compatibility precaution.
fn make_entry(key: &str) -> Result<Entry> {
    Entry::new(SERVICE, key).map_err(|source| KeychainError::Keyring {
        key: key.to_owned(),
        source,
    })
}

// ─────────────────────────────────────────────────────────────────────────────
// Tauri commands (IPC surface exposed to the WebView)
// ─────────────────────────────────────────────────────────────────────────────

/// Store a credential in the OS keychain.
///
/// Exposed as the Tauri IPC command `store_credential`.
///
/// # Arguments
///
/// * `key`   — Logical name for the credential.
/// * `value` — Secret value to store.
///
/// # Errors
///
/// Returns a human-readable error string if the OS keychain rejects the write.
#[tauri::command]
pub fn cmd_store_credential(key: String, value: String) -> std::result::Result<(), String> {
    store_credential(&key, &value).map_err(|e| e.to_string())
}

/// Retrieve a credential from the OS keychain.
///
/// Exposed as the Tauri IPC command `get_credential`.
///
/// # Errors
///
/// Returns a human-readable error string if the key is not found or the OS
/// denies the read.
#[tauri::command]
pub fn cmd_get_credential(key: String) -> std::result::Result<String, String> {
    get_credential(&key).map_err(|e| e.to_string())
}

/// Delete a credential from the OS keychain.
///
/// Exposed as the Tauri IPC command `delete_credential`.
/// Idempotent — succeeds even if the key does not exist.
///
/// # Errors
///
/// Returns a human-readable error string for unexpected OS-level failures.
#[tauri::command]
pub fn cmd_delete_credential(key: String) -> std::result::Result<(), String> {
    delete_credential(&key).map_err(|e| e.to_string())
}

// ─────────────────────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    /// Unique key prefix so parallel test runs do not stomp on each other.
    fn test_key(suffix: &str) -> String {
        format!("__ft_test_{suffix}")
    }

    #[test]
    fn store_and_retrieve() {
        let key = test_key("store_retrieve");
        let _ = delete_credential(&key); // clean slate

        store_credential(&key, "secret-value-123").unwrap();
        let got = get_credential(&key).unwrap();
        assert_eq!(got, "secret-value-123");

        delete_credential(&key).unwrap();
    }

    #[test]
    fn overwrite_existing() {
        let key = test_key("overwrite");
        let _ = delete_credential(&key);

        store_credential(&key, "first").unwrap();
        store_credential(&key, "second").unwrap(); // must not error
        let got = get_credential(&key).unwrap();
        assert_eq!(got, "second");

        delete_credential(&key).unwrap();
    }

    #[test]
    fn delete_idempotent() {
        let key = test_key("delete_idem");
        let _ = delete_credential(&key);

        // Deleting a non-existent key must succeed
        delete_credential(&key).unwrap();
    }

    #[test]
    fn get_missing_key_errors() {
        let key = test_key("missing");
        let _ = delete_credential(&key);

        let result = get_credential(&key);
        assert!(result.is_err(), "expected an error for a missing key");
    }
}
