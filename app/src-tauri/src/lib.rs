//! Sabhalekh desktop shell.
//!
//! * Starts the Python backend sidecar (127.0.0.1 only, random per-launch auth token), waits for its
//!   `SABHALEKH_READY port=N` line and hands port + token to the UI. If the backend dies, the UI is told why
//!   (last stderr lines) and can restart it.
//! * System tray with an always-visible recording indicator, close-to-tray, single instance.
//! * No network code at all: the webview CSP only allows the bundled UI and the local backend.

use std::collections::VecDeque;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;

use serde::Serialize;
use tauri::image::Image;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIcon, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, WindowEvent};

const TRAY_IDLE: &[u8] = include_bytes!("../icons/tray-idle.png");
const TRAY_REC: &[u8] = include_bytes!("../icons/tray-recording.png");

#[derive(Clone, Serialize, Default)]
struct BackendInfo {
    status: String, // starting | ready | exited
    port: u16,
    token: String,
    error: Option<String>,
}

#[derive(Default)]
struct Shell {
    info: Mutex<BackendInfo>,
    child: Mutex<Option<Child>>,
    stderr_tail: Arc<Mutex<VecDeque<String>>>,
    close_to_tray: Mutex<bool>,
    quitting: Mutex<bool>,
    tray: Mutex<Option<TrayIcon>>,
}

fn new_token() -> String {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("OS random generator");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// `\\?\C:\x` -> `C:\x`. canonicalize() and resource_dir() return verbatim paths; native libraries in the backend
/// (CTranslate2) append "/model.bin", and Windows does not translate '/' inside verbatim paths.
fn plain_path(p: PathBuf) -> PathBuf {
    let s = p.to_string_lossy();
    if let Some(rest) = s.strip_prefix(r"\\?\UNC\") {
        PathBuf::from(format!(r"\\{rest}"))
    } else if let Some(rest) = s.strip_prefix(r"\\?\") {
        PathBuf::from(rest)
    } else {
        p
    }
}

/// (program, args before the shared ones, SABHALEKH_APP_DIR)
fn backend_command(app: &AppHandle) -> Result<(PathBuf, Vec<String>, PathBuf), String> {
    if cfg!(debug_assertions) {
        // development: the repo's virtualenv runs backend/run_backend.py
        let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("..");
        let repo = plain_path(repo.canonicalize().map_err(|e| format!("repo root: {e}"))?);
        let python = if cfg!(windows) {
            repo.join(".venv").join("Scripts").join("python.exe")
        } else {
            repo.join(".venv").join("bin").join("python")
        };
        let script = repo.join("backend").join("run_backend.py");
        if !python.exists() {
            return Err(format!("development Python not found: {}", python.display()));
        }
        return Ok((python, vec![script.to_string_lossy().into_owned()], repo));
    }
    let res = plain_path(app.path().resource_dir().map_err(|e| format!("resource dir: {e}"))?);
    let exe = res.join("backend").join(if cfg!(windows) { "sabhalekh-backend.exe" } else { "sabhalekh-backend" });
    if !exe.exists() {
        return Err(format!("backend not found: {}", exe.display()));
    }
    Ok((exe, vec![], res))
}

fn start_backend(app: &AppHandle) {
    let shell = app.state::<Shell>();
    let token = new_token();
    {
        let mut info = shell.info.lock().unwrap();
        *info = BackendInfo { status: "starting".into(), port: 0, token: token.clone(), error: None };
    }
    shell.stderr_tail.lock().unwrap().clear();
    let (program, mut args, app_dir) = match backend_command(app) {
        Ok(v) => v,
        Err(e) => {
            fail(app, e);
            return;
        }
    };
    args.extend([
        "--token".to_string(),
        token,
        "--parent-pid".to_string(),
        std::process::id().to_string(),
    ]);
    let mut cmd = Command::new(&program);
    cmd.args(&args)
        .env("SABHALEKH_APP_DIR", &app_dir)
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUNBUFFERED", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => {
            fail(app, format!("could not start the backend: {e}"));
            return;
        }
    };
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    *shell.child.lock().unwrap() = Some(child);

    if let Some(out) = stdout {
        let app = app.clone();
        thread::spawn(move || {
            for line in BufReader::new(out).lines().map_while(Result::ok) {
                if let Some(rest) = line.strip_prefix("SABHALEKH_READY port=") {
                    if let Ok(port) = rest.trim().parse::<u16>() {
                        let shell = app.state::<Shell>();
                        let info = {
                            let mut i = shell.info.lock().unwrap();
                            i.status = "ready".into();
                            i.port = port;
                            i.clone()
                        };
                        let _ = app.emit("backend://ready", info);
                    }
                }
            }
        });
    }
    if let Some(err) = stderr {
        let tail = shell.stderr_tail.clone();
        thread::spawn(move || {
            for line in BufReader::new(err).lines().map_while(Result::ok) {
                let mut t = tail.lock().unwrap();
                if t.len() >= 40 {
                    t.pop_front();
                }
                t.push_back(line);
            }
        });
    }
    // watcher: report an unexpected exit to the UI
    let app = app.clone();
    thread::spawn(move || loop {
        thread::sleep(std::time::Duration::from_millis(500));
        let shell = app.state::<Shell>();
        let mut guard = shell.child.lock().unwrap();
        let Some(child) = guard.as_mut() else { return };
        if let Ok(Some(status)) = child.try_wait() {
            *guard = None;
            drop(guard);
            if *shell.quitting.lock().unwrap() {
                return;
            }
            let tail: Vec<String> = shell.stderr_tail.lock().unwrap().iter().cloned().collect();
            let lines: Vec<&String> = tail.iter().rev().take(12).collect::<Vec<_>>().into_iter().rev().collect();
            let msg = format!(
                "The processing engine stopped (exit code {}).\n{}",
                status.code().unwrap_or(-1),
                lines.iter().map(|s| s.as_str()).collect::<Vec<_>>().join("\n")
            );
            fail(&app, msg);
            return;
        }
    });
}

fn fail(app: &AppHandle, error: String) {
    let shell = app.state::<Shell>();
    let info = {
        let mut i = shell.info.lock().unwrap();
        i.status = "exited".into();
        i.error = Some(error);
        i.clone()
    };
    let _ = app.emit("backend://exited", info);
}

fn stop_backend(shell: &Shell) {
    if let Some(mut child) = shell.child.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn show_main(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

// ------------------------------------------------------------------ commands
#[tauri::command]
fn backend_info(shell: State<Shell>) -> BackendInfo {
    shell.info.lock().unwrap().clone()
}

#[tauri::command]
fn restart_backend(app: AppHandle, shell: State<Shell>) {
    stop_backend(&shell);
    start_backend(&app);
}

#[tauri::command]
fn set_close_to_tray(shell: State<Shell>, enabled: bool) {
    *shell.close_to_tray.lock().unwrap() = enabled;
}

#[tauri::command]
fn set_recording_indicator(app: AppHandle, shell: State<Shell>, active: bool, label: Option<String>) {
    if let Some(tray) = shell.tray.lock().unwrap().as_ref() {
        let bytes = if active { TRAY_REC } else { TRAY_IDLE };
        if let Ok(img) = Image::from_bytes(bytes) {
            let _ = tray.set_icon(Some(img));
        }
        let tip = if active {
            format!("Sabhalekh: recording {}", label.clone().unwrap_or_default())
        } else {
            "Sabhalekh".to_string()
        };
        let _ = tray.set_tooltip(Some(tip));
    }
    if let Some(w) = app.get_webview_window("main") {
        let title = if active {
            format!("● Recording {} · Sabhalekh", label.unwrap_or_default())
        } else {
            "Sabhalekh".to_string()
        };
        let _ = w.set_title(&title);
    }
}

#[tauri::command]
fn quit_app(app: AppHandle, shell: State<Shell>) {
    *shell.quitting.lock().unwrap() = true;
    stop_backend(&shell);
    app.exit(0);
}

// ------------------------------------------------------------------ app
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| show_main(app)))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_autostart::init(tauri_plugin_autostart::MacosLauncher::LaunchAgent, Some(vec!["--minimized"])))
        .plugin(tauri_plugin_opener::init())
        .manage(Shell { close_to_tray: Mutex::new(true), ..Default::default() })
        .invoke_handler(tauri::generate_handler![
            backend_info,
            restart_backend,
            set_close_to_tray,
            set_recording_indicator,
            quit_app
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            start_backend(&handle);

            let show = MenuItem::with_id(app, "show", "Show Sabhalekh", true, None::<&str>)?;
            let record = MenuItem::with_id(app, "record", "Start / stop recording", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(app)?;
            let menu = Menu::with_items(app, &[&show, &record, &sep, &quit])?;
            let tray = TrayIconBuilder::with_id("main")
                .icon(Image::from_bytes(TRAY_IDLE)?)
                .tooltip("Sabhalekh")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "show" => show_main(app),
                    "record" => {
                        let _ = app.emit("tray://toggle-recording", ());
                    }
                    "quit" => {
                        show_main(app);
                        let _ = app.emit("tray://quit-requested", ());
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } =
                        event
                    {
                        show_main(tray.app_handle());
                    }
                })
                .build(app)?;
            *app.state::<Shell>().tray.lock().unwrap() = Some(tray);

            let minimized = std::env::args().any(|a| a == "--minimized");
            if let Some(w) = app.get_webview_window("main") {
                if !minimized {
                    let _ = w.show();
                }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let app = window.app_handle();
                let shell = app.state::<Shell>();
                if *shell.close_to_tray.lock().unwrap() && !*shell.quitting.lock().unwrap() {
                    api.prevent_close();
                    let _ = window.hide();
                } else {
                    api.prevent_close();
                    let _ = app.emit("tray://quit-requested", ());
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building Sabhalekh")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                let shell = app.state::<Shell>();
                *shell.quitting.lock().unwrap() = true;
                stop_backend(&shell);
            }
        });
}
