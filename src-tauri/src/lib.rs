use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use tauri::{Emitter, Listener, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Shared handle to the sidecar child process so the exit handler can kill it.
type SidecarHandle = Arc<Mutex<Option<CommandChild>>>;

/// Number of trailing stderr lines kept for crash diagnostics.
const STDERR_TAIL_LINES: usize = 20;

/// Header the sidecar checks on every request (see src/backends/main.py).
const TOKEN_HEADER: &str = "X-Psych-Cert-Token";

/// Port used if the OS refuses to hand out a free one, and the fixed port
/// debug builds (`bun run tauri dev`) use so a separately started API
/// (`uv run python src/backends/main.py`) is reachable.
const FALLBACK_PORT: u16 = 8008;

/// Fixed token for debug builds only. Release builds always use a random one.
const DEV_TOKEN: &str = "psych-cert-dev";

/// Placeholder in tauri.conf.json's CSP that is narrowed to the real port.
const CSP_ANY_LOCAL_PORT: &str = "http://127.0.0.1:*";

/// Per-launch connection details for the Python sidecar.
///
/// Release builds choose a fresh random port and a 256-bit random token on
/// every launch. Debug builds use port 8008 and the token `psych-cert-dev`
/// (override with PSYCH_CERT_DEV_PORT and PSYCH_CERT_DEV_TOKEN) so the
/// README's two-terminal dev setup can connect. The sidecar receives them
/// through environment variables and rejects any request without the token,
/// so other local processes and web pages cannot drive the API. The webview
/// reads them through the `backend_config` command.
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
pub struct BackendConfig {
    port: u16,
    token: String,
}

impl BackendConfig {
    /// Fixed settings for debug builds, random ones for release builds.
    fn for_build(debug: bool, env: impl Fn(&str) -> Option<String>) -> Self {
        if !debug {
            return Self::generate();
        }
        let port = env("PSYCH_CERT_DEV_PORT")
            .and_then(|raw| raw.trim().parse().ok())
            .unwrap_or(FALLBACK_PORT);
        let token = env("PSYCH_CERT_DEV_TOKEN")
            .map(|raw| raw.trim().to_string())
            .filter(|raw| !raw.is_empty())
            .unwrap_or_else(|| DEV_TOKEN.to_string());
        Self { port, token }
    }

    fn generate() -> Self {
        let port = std::net::TcpListener::bind("127.0.0.1:0")
            .and_then(|listener| listener.local_addr())
            .map(|addr| addr.port())
            .unwrap_or(FALLBACK_PORT);
        let mut bytes = [0u8; 32];
        getrandom::getrandom(&mut bytes).expect("OS random number generator unavailable");
        let token = bytes.iter().map(|b| format!("{b:02x}")).collect();
        Self { port, token }
    }

    fn url(&self, path: &str) -> String {
        format!("http://127.0.0.1:{}{}", self.port, path)
    }

    /// True when an API answering with this token is already listening
    /// (the README's dev setup starts one in another terminal).
    fn already_running(&self) -> bool {
        ureq::get(&self.url("/health"))
            .set(TOKEN_HEADER, &self.token)
            .timeout(std::time::Duration::from_millis(500))
            .call()
            .map(|r| r.status() == 200)
            .unwrap_or(false)
    }
}

/// Narrow the CSP's `http://127.0.0.1:*` to the one port the API uses.
fn pin_csp_port(csp: &str, port: u16) -> String {
    csp.replace(CSP_ANY_LOCAL_PORT, &format!("http://127.0.0.1:{port}"))
}

/// Hand the sidecar port and token to the frontend.
#[tauri::command]
fn backend_config(config: tauri::State<'_, BackendConfig>) -> BackendConfig {
    config.inner().clone()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let sidecar: SidecarHandle = Arc::new(Mutex::new(None));
    let sidecar_for_setup = sidecar.clone();
    let config = BackendConfig::for_build(cfg!(debug_assertions), |key| std::env::var(key).ok());
    let config_for_setup = config.clone();

    // Tauri injects this CSP into every page it serves at runtime, so the
    // webview can only reach the API on this launch's port.
    let mut context = tauri::generate_context!();
    let security = &mut context.config_mut().app.security;
    if let Some(csp) = security.csp.as_ref() {
        let pinned = pin_csp_port(&csp.to_string(), config.port);
        security.csp = Some(tauri::utils::config::Csp::Policy(pinned));
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(config.clone())
        .invoke_handler(tauri::generate_handler![backend_config])
        .setup(move |app| {
            let handle = app.handle().clone();
            if cfg!(debug_assertions) && config_for_setup.already_running() {
                // Dev: reuse the API started in another terminal.
                eprintln!(
                    "[sidecar] using the API already running on port {}",
                    config_for_setup.port
                );
                watch_health(&handle, &config_for_setup, Arc::new(AtomicBool::new(false)));
            } else {
                spawn_sidecar(&handle, &sidecar_for_setup, &config_for_setup);
            }
            let retry_handle = handle.clone();
            let retry_sidecar = sidecar_for_setup.clone();
            let retry_config = config_for_setup.clone();
            let _ = handle.listen("retry-sidecar", move |_| {
                respawn_sidecar(&retry_handle, &retry_sidecar, &retry_config);
            });
            Ok(())
        })
        .build(context)
        .expect("error while building tauri application")
        .run({
            let sidecar = sidecar.clone();
            move |_app_handle, event| {
                if let RunEvent::ExitRequested { .. } = event {
                    shutdown_sidecar(&sidecar, &config);
                }
            }
        });
}

// ── sidecar lifecycle ──────────────────────────────────────────────────────

/// Spawn the Python FastAPI sidecar, wire up stdout/stderr forwarding,
/// and begin health-check polling.
fn respawn_sidecar(handle: &tauri::AppHandle, sidecar: &SidecarHandle, config: &BackendConfig) {
    if let Some(child) = sidecar.lock().unwrap().take() {
        let _ = child.kill();
    }
    spawn_sidecar(handle, sidecar, config);
}

fn spawn_sidecar(handle: &tauri::AppHandle, sidecar: &SidecarHandle, config: &BackendConfig) {
    // Resolve and spawn the sidecar binary declared in tauri.conf.json.
    //
    // NOTE: use the *basename* "psych-cert-gen", not "bin/api/psych-cert-gen".
    // tauri-plugin-shell resolves a sidecar to `<exe_dir>/<name>` verbatim
    // (see relative_command_path in the plugin), while the Tauri bundler
    // flattens externalBin into the executable directory as just the
    // basename (Contents/MacOS/psych-cert-gen on macOS,
    // psych-cert-gen.exe next to the app on Windows). Passing the
    // "bin/api/" subpath made runtime look for <exe_dir>/bin/api/... which
    // does not exist in the bundle, so the sidecar never spawned and the
    // backend never started.
    eprintln!("[sidecar] resolving psych-cert-gen ...");
    let mut rx = match handle.shell().sidecar("psych-cert-gen") {
        Ok(cmd) => match cmd
            .env("PSYCH_CERT_PORT", config.port.to_string())
            .env("PSYCH_CERT_TOKEN", &config.token)
            .spawn()
        {
            Ok((rx, child)) => {
                eprintln!("[sidecar] spawned OK, pid={:?}", child.pid());
                *sidecar.lock().unwrap() = Some(child);
                rx
            }
            Err(e) => {
                eprintln!("[sidecar] FAILED to spawn: {e}");
                handle
                    .emit(
                        "sidecar-error",
                        format!("Failed to spawn sidecar: {e}"),
                    )
                    .ok();
                return;
            }
        },
        Err(e) => {
            eprintln!("[sidecar] NOT FOUND / resolution error: {e}");
            handle
                .emit(
                    "sidecar-error",
                    format!("Sidecar binary not found: {e}"),
                )
                .ok();
            return;
        }
    };

    // Set once the health check sees its first 200, so a post-shutdown
    // process exit doesn't get misreported as a startup crash.
    let became_healthy = Arc::new(AtomicBool::new(false));
    let mut stderr_tail: VecDeque<String> = VecDeque::with_capacity(STDERR_TAIL_LINES);

    // ── stdout / stderr forwarding ──────────────────────────────────────
    let fwd_handle = handle.clone();
    let healthy_for_events = became_healthy.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let line = String::from_utf8_lossy(&bytes);
                    fwd_handle
                        .emit("sidecar-stdout", line.to_string())
                        .ok();
                }
                CommandEvent::Stderr(bytes) => {
                    let line = String::from_utf8_lossy(&bytes).into_owned();
                    if stderr_tail.len() == STDERR_TAIL_LINES {
                        stderr_tail.pop_front();
                    }
                    stderr_tail.push_back(line.clone());
                    fwd_handle.emit("sidecar-stderr", line).ok();
                }
                CommandEvent::Terminated(payload) => {
                    fwd_handle
                        .emit("sidecar-terminated", payload.code)
                        .ok();
                    // Only surface this as a startup error if the backend
                    // never became healthy — otherwise it's an expected
                    // shutdown after the app already moved past startup.
                    if !healthy_for_events.load(Ordering::SeqCst) {
                        let tail = Vec::from(stderr_tail.clone()).join("\n");
                        let detail = if tail.is_empty() {
                            "(no output captured)".to_string()
                        } else {
                            tail
                        };
                        fwd_handle
                            .emit(
                                "sidecar-error",
                                format!(
                                    "Backend process exited early (code {:?}). Last output:\n{}",
                                    payload.code, detail
                                ),
                            )
                            .ok();
                    }
                    break;
                }
                CommandEvent::Error(msg) => {
                    fwd_handle.emit("sidecar-error", msg).ok();
                }
                _ => {}
            }
        }
    });

    // ── health-check polling ────────────────────────────────────────────
    watch_health(handle, config, became_healthy);
}

fn watch_health(
    handle: &tauri::AppHandle,
    config: &BackendConfig,
    became_healthy: Arc<AtomicBool>,
) {
    let hc_handle = handle.clone();
    let hc_config = config.clone();
    tauri::async_runtime::spawn(async move {
        poll_health(hc_handle, became_healthy, hc_config).await;
    });
}

/// Poll `GET http://127.0.0.1:<port>/health` (with the launch token) every 200 ms until the first
/// 200 response (up to 60 s — PyInstaller onefile cold starts can be slow,
/// especially under antivirus scanning on first run on Windows). Once
/// healthy, emit `sidecar-ready` and switch to a slow periodic check every
/// 5 s to detect crashes.
async fn poll_health(
    handle: tauri::AppHandle,
    became_healthy: Arc<AtomicBool>,
    config: BackendConfig,
) {
    let health_url = config.url("/health");
    let start = std::time::Instant::now();
    let timeout = std::time::Duration::from_secs(60);
    let mut ready_emitted = false;
    let mut last_error: Option<String> = None;
    let mut last_logged_at: Option<std::time::Instant> = None;
    const LOG_INTERVAL: std::time::Duration = std::time::Duration::from_secs(2);

    loop {
        if !ready_emitted && start.elapsed() > timeout {
            let detail = last_error
                .map(|e| format!(" Last connection error: {e}"))
                .unwrap_or_default();
            handle
                .emit(
                    "sidecar-error",
                    format!("Health check timed out after 60 seconds.{detail}"),
                )
                .ok();
            return;
        }

        let attempt = {
            let url = health_url.clone();
            let token = config.token.clone();
            tokio::task::spawn_blocking(move || {
                ureq::get(&url)
                    .set(TOKEN_HEADER, &token)
                    .call()
                    .map(|r| r.status())
                    .map_err(|e| e.to_string())
            })
            .await
            .unwrap_or_else(|join_err| Err(format!("task join error: {join_err}")))
        };

        match attempt {
            Ok(200) => {
                if !ready_emitted {
                    became_healthy.store(true, Ordering::SeqCst);
                    handle
                        .emit("sidecar-ready", serde_json::Value::Null)
                        .ok();
                    ready_emitted = true;
                }
                tokio::time::sleep(std::time::Duration::from_secs(5)).await;
                continue;
            }
            Ok(status) => last_error = Some(format!("unexpected status {status}")),
            Err(e) => last_error = Some(e),
        }

        // Re-announce the current connection error at most once per
        // LOG_INTERVAL (rather than only on first occurrence) so the
        // startup screen's live log is guaranteed to show it even if the
        // very first attempt's event fires before the frontend finishes
        // registering its listener — a real race, since polling starts
        // immediately on the Rust side while the webview still has to
        // mount React first.
        let should_log = last_logged_at
            .map(|t| t.elapsed() >= LOG_INTERVAL)
            .unwrap_or(true);
        if should_log {
            handle
                .emit(
                    "sidecar-stderr",
                    format!("[health-check] {}", last_error.as_deref().unwrap_or("?")),
                )
                .ok();
            last_logged_at = Some(std::time::Instant::now());
        }

        tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    }
}

/// Gracefully shut down the sidecar.
///
/// 1. POST http://127.0.0.1:<port>/shutdown (token header plus the JSON
///    body the endpoint requires) to ask the FastAPI server to exit
///    gracefully (works cross-platform, unlike stdin).
/// 2. Wait up to 2 seconds for the process to exit on its own.
/// 3. Force-kill the process if it is still running (fallback).
fn shutdown_sidecar(sidecar: &SidecarHandle, config: &BackendConfig) {
    // Never stop an API this app did not start (the dev setup's terminal).
    if sidecar.lock().unwrap().is_none() {
        return;
    }
    // Primary: HTTP graceful shutdown
    let _ = ureq::post(&config.url("/shutdown"))
        .set(TOKEN_HEADER, &config.token)
        .set("Content-Type", "application/json")
        .send_string(r#"{"reason": "app-exit"}"#);

    // Give the process up to 2 s to exit cleanly
    std::thread::sleep(std::time::Duration::from_secs(2));

    // Fallback: force-kill if still alive
    if let Some(child) = sidecar.lock().unwrap().take() {
        let _ = child.kill();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn no_env(_: &str) -> Option<String> {
        None
    }

    #[test]
    fn debug_builds_use_the_fixed_dev_port_and_token() {
        let config = BackendConfig::for_build(true, no_env);
        assert_eq!(config, BackendConfig { port: 8008, token: "psych-cert-dev".into() });
    }

    #[test]
    fn debug_builds_accept_env_overrides() {
        let config = BackendConfig::for_build(true, |key| match key {
            "PSYCH_CERT_DEV_PORT" => Some("9123".into()),
            "PSYCH_CERT_DEV_TOKEN" => Some("other".into()),
            _ => None,
        });
        assert_eq!(config, BackendConfig { port: 9123, token: "other".into() });
    }

    #[test]
    fn release_builds_ignore_dev_settings_and_stay_random() {
        let env = |_: &str| Some("9123".to_string());
        let a = BackendConfig::for_build(false, env);
        let b = BackendConfig::for_build(false, env);
        assert_eq!(a.token.len(), 64);
        assert_ne!(a.token, b.token);
        assert_ne!(a.token, DEV_TOKEN);
    }

    #[test]
    fn csp_is_pinned_to_the_api_port() {
        let csp = "connect-src 'self' ipc: http://127.0.0.1:*; img-src 'self'";
        assert_eq!(
            pin_csp_port(csp, 51234),
            "connect-src 'self' ipc: http://127.0.0.1:51234; img-src 'self'"
        );
    }
}
