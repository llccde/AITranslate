import json
import os

from deep_translator import GoogleTranslator

OCR_LANG: list[str] = ['en', 'ch_sim', 'ja']
TARGET_LANG: str = 'zh-CN'
INTERVAL: float = 2.0
API_PARALLEL_LIMIT: int = 5
FOCUS_GUARD_ENABLED: bool = True

DEEPSEEK_API_KEY: str = ""
TRANSLATE_ENGINE: str = "google"

SETTINGS_PATH: str = os.path.join(os.path.dirname(__file__), "settings.json")

translator: GoogleTranslator = GoogleTranslator(source='auto', target=TARGET_LANG)


def get_translation_config() -> str:
    engine_name = "GoogleTranslator" if TRANSLATE_ENGINE == "google" else "deepseek"
    return f"{engine_name}|auto|{TARGET_LANG}"


def load_settings() -> None:
    global DEEPSEEK_API_KEY, TRANSLATE_ENGINE
    if not os.path.exists(SETTINGS_PATH):
        return
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        DEEPSEEK_API_KEY = data.get("deepseek_api_key", "")
        TRANSLATE_ENGINE = data.get("translate_engine", "google")
    except Exception:
        pass


def save_settings() -> None:
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "deepseek_api_key": DEEPSEEK_API_KEY,
                "translate_engine": TRANSLATE_ENGINE,
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


load_settings()
