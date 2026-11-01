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

/// Port used only if the OS refuses to hand out a free one.
const FALLBACK_PORT: u16 = 8008;

/// Per-launch connection details for the Python sidecar.
///
/// A fresh random port and a 256-bit random token are chosen on every launch.
/// The sidecar receives them through environment variables and rejects any
/// request without the token, so other local processes and web pages cannot
/// drive the API. The webview reads them through the `backend_config` command.
#[derive(Clone, serde::Serialize)]
pub struct BackendConfig {
    port: u16,
    token: String,
}

impl BackendConfig {
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
    let config = BackendConfig::generate();
    let config_for_setup = config.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(config.clone())
        .invoke_handler(tauri::generate_handler![backend_config])
        .setup(move |app| {
            let handle = app.handle().clone();
            spawn_sidecar(&handle, &sidecar_for_setup, &config_for_setup);
            let retry_handle = handle.clone();
            let retry_sidecar = sidecar_for_setup.clone();
            let retry_config = config_for_setup.clone();
            let _ = handle.listen("retry-sidecar", move |_| {
                respawn_sidecar(&retry_handle, &retry_sidecar, &retry_config);
            });
            Ok(())
        })
        .build(tauri::generate_context!())
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
