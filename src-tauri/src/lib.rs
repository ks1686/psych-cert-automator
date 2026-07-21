use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use tauri::{Emitter, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Shared handle to the sidecar child process so the exit handler can kill it.
type SidecarHandle = Arc<Mutex<Option<CommandChild>>>;

/// Number of trailing stderr lines kept for crash diagnostics.
const STDERR_TAIL_LINES: usize = 20;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let sidecar: SidecarHandle = Arc::new(Mutex::new(None));
    let sidecar_for_setup = sidecar.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_http::init())
        .setup(move |app| {
            let handle = app.handle().clone();
            spawn_sidecar(app, &sidecar_for_setup, &handle);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run({
            let sidecar = sidecar.clone();
            move |_app_handle, event| {
                if let RunEvent::ExitRequested { .. } = event {
                    shutdown_sidecar(&sidecar);
                }
            }
        });
}

// ── sidecar lifecycle ──────────────────────────────────────────────────────

/// Spawn the Python FastAPI sidecar, wire up stdout/stderr forwarding,
/// and begin health-check polling.
fn spawn_sidecar(
    app: &tauri::App,
    sidecar: &SidecarHandle,
    handle: &tauri::AppHandle,
) {
    // Resolve and spawn the sidecar binary declared in tauri.conf.json
    let mut rx = match app.shell().sidecar("bin/api/psych-cert-gen") {
        Ok(cmd) => match cmd.spawn() {
            Ok((rx, child)) => {
                *sidecar.lock().unwrap() = Some(child);
                rx
            }
            Err(e) => {
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
    tauri::async_runtime::spawn(async move {
        poll_health(hc_handle, became_healthy).await;
    });
}

/// Poll `GET http://127.0.0.1:8008/health` every 200 ms until the first
/// 200 response (up to 60 s — PyInstaller onefile cold starts can be slow,
/// especially under antivirus scanning on first run on Windows). Once
/// healthy, emit `sidecar-ready` and switch to a slow periodic check every
/// 5 s to detect crashes.
async fn poll_health(handle: tauri::AppHandle, became_healthy: Arc<AtomicBool>) {
    let health_url = "http://127.0.0.1:8008/health";
    let start = std::time::Instant::now();
    let timeout = std::time::Duration::from_secs(60);
    let mut ready_emitted = false;

    loop {
        if start.elapsed() > timeout {
            handle
                .emit(
                    "sidecar-error",
                    "Health check timed out after 60 seconds",
                )
                .ok();
            return;
        }

        let is_healthy = {
            let url = health_url.to_string();
            tokio::task::spawn_blocking(move || {
                ureq::get(&url).call().map(|r| r.status() == 200).unwrap_or(false)
            })
            .await
            .unwrap_or(false)
        };

        if is_healthy {
            if !ready_emitted {
                became_healthy.store(true, Ordering::SeqCst);
                handle
                    .emit("sidecar-ready", serde_json::Value::Null)
                    .ok();
                ready_emitted = true;
            }
            tokio::time::sleep(std::time::Duration::from_secs(5)).await;
        } else {
            tokio::time::sleep(std::time::Duration::from_millis(200)).await;
        }
    }
}

/// Gracefully shut down the sidecar.
///
/// 1. POST http://127.0.0.1:8008/shutdown to ask the FastAPI server
///    to exit gracefully (works cross-platform, unlike stdin).
/// 2. Wait up to 2 seconds for the process to exit on its own.
/// 3. Force-kill the process if it is still running (fallback).
fn shutdown_sidecar(sidecar: &SidecarHandle) {
    // Primary: HTTP graceful shutdown
    let _ = ureq::post("http://127.0.0.1:8008/shutdown").call();

    // Give the process up to 2 s to exit cleanly
    std::thread::sleep(std::time::Duration::from_secs(2));

    // Fallback: force-kill if still alive
    if let Some(child) = sidecar.lock().unwrap().take() {
        let _ = child.kill();
    }
}
