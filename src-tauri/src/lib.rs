// Learn more about Tauri commands at https://tauri.app/develop/calling-rust/
#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

#[tauri::command]
async fn shrink_window_to_position(
    window: tauri::WebviewWindow,
    x: i32,
    y: i32,
) -> Result<(), String> {
    let monitor = window
        .current_monitor()
        .map_err(|error| error.to_string())?
        .or(window.primary_monitor().map_err(|error| error.to_string())?)
        .ok_or_else(|| "Unable to determine the current monitor.".to_string())?;
    let scale = monitor.scale_factor();
    let width = (150.0 * scale).round() as u32;
    let height = (150.0 * scale).round() as u32;

    window
        .set_size(tauri::PhysicalSize::new(width, height))
        .map_err(|error| error.to_string())?;
    window
        .set_position(tauri::PhysicalPosition::new(x, y))
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn hide_to_system_tray(window: tauri::WebviewWindow) -> Result<(), String> {
    window.hide().map_err(|error| error.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            use tauri::Manager;
            use tauri::menu::{Menu, MenuItem};
            use tauri::tray::{MouseButton, TrayIconBuilder, TrayIconEvent};

            let exit_item = MenuItem::with_id(app, "exit", "Exit", true, None::<&str>)?;
            let tray_menu = Menu::with_items(app, &[&exit_item])?;
            let tray_icon = tauri::image::Image::new(
                include_bytes!("../icons/jarvis-tray.rgba"),
                64,
                64,
            );
            TrayIconBuilder::new()
                .icon(tray_icon)
                .menu(&tray_menu)
                .tooltip("Jarvis")
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| {
                    if event.id() == "exit" {
                        app.exit(0);
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        ..
                    } = event
                    {
                        if let Some(window) = tray.app_handle().get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            if let Some(window) = app.get_webview_window("main") {
                if let Some(monitor) = window.primary_monitor()? {
                    let scale = monitor.scale_factor();
                    let size = monitor.size();
                    let position = monitor.position();
                    let width = (150.0 * scale).round() as i32;
                    let height = (150.0 * scale).round() as i32;
                    let margin = (18.0 * scale).round() as i32;

                    window.set_size(tauri::PhysicalSize::new(
                        width as u32,
                        height as u32,
                    ))?;
                    window.set_position(tauri::PhysicalPosition::new(
                        position.x + size.width as i32 - width - margin,
                        position.y + size.height as i32 - height - margin,
                    ))?;
                }
                window.show()?;
                window.set_focus()?;
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![greet, shrink_window_to_position, hide_to_system_tray])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
