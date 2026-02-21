import json
import logging
import os

logger = logging.getLogger(__name__)


def get_appdata_path(app_name="VideoDownloader") -> str:
    """Returns the AppData/Local/VideoDownloader path, creating it if needed."""
    local_appdata = os.getenv("LOCALAPPDATA", os.path.expanduser("~"))
    app_folder = os.path.join(local_appdata, app_name)
    os.makedirs(app_folder, exist_ok=True)
    return app_folder


CONFIG_PATH = os.path.join(get_appdata_path(), "config.json")


def load_setting(key: str, default=False):
    """Load a single setting from config.json. Returns default on any failure."""
    try:
        if os.path.exists(CONFIG_PATH) and os.path.getsize(CONFIG_PATH) > 0:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(key, default)
    except json.JSONDecodeError as e:
        logger.warning("config.json is malformed, using defaults. Error: %s", e)
    except Exception as e:
        logger.error("Failed to load setting '%s': %s", key, e)
    return default


def save_setting(key: str, value) -> None:
    """Save a single setting to config.json."""
    try:
        data = {}
        if os.path.exists(CONFIG_PATH) and os.path.getsize(CONFIG_PATH) > 0:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

        data[key] = value

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error("Failed to save setting '%s': %s", key, e)
