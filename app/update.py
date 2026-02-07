import webbrowser
import requests

try:
    from packaging import version
    PACKAGING_AVAILABLE = True
except Exception:
    PACKAGING_AVAILABLE = False


def check_for_updates(app):
    """Sprawdza dostępność nowych wydań na GitHub i informuje aplikację."""
    if not PACKAGING_AVAILABLE:
        return

    API_URL = "https://api.github.com/repos/kpasek/subtitle-studio/releases/latest"
    try:
        response = requests.Session().get(API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        latest_tag = data.get('tag_name')
        if latest_tag and version.parse(latest_tag) > version.parse(app.APP_VERSION):
            download_url = (
                f"https://github.com/kpasek/subtitle-studio/releases/download/{latest_tag}/SubtitleStudioWindows.zip"
                if app.sys.platform == "win32"
                else data.get('html_url')
            )
            app.latest_version_info = (latest_tag, download_url)
            # Push UI task to main thread
            app.queue.put(lambda: show_update_button(app))
    except Exception:
        # Nie przerywamy działania aplikacji z powodu błędu sprawdzania aktualizacji
        pass


def show_update_button(app):
    if app.latest_version_info and app.update_button:
        app.update_button.configure(text=f"Nowa Wersja! ({app.latest_version_info[0]})")
        app.update_button.pack(side="left", padx=5)
        if hasattr(app, 'lbl_filename') and app.lbl_filename:
            app.lbl_filename.pack_configure(side="left", anchor="w", padx=5)


def download_update(app):
    if app.latest_version_info:
        webbrowser.open(app.latest_version_info[1], new=2)
