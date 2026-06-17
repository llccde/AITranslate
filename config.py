import csv
import os

from deep_translator import GoogleTranslator

OCR_LANG: list[str] = ['en', 'ch_sim', 'ja']
TARGET_LANG: str = 'zh-CN'
INTERVAL: float = 2.0
API_PARALLEL_LIMIT: int = 5
FOCUS_GUARD_ENABLED: bool = True

DEEPSEEK_API_KEY: str = ""
DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
DEEPSEEK_THINKING: bool = False
TRANSLATE_ENGINE: str = "google"

SETTINGS_PATH: str = os.path.join(os.path.dirname(__file__), "settings.csv")

AVAILABLE_OCR_LANGS: dict[str, str] = {
    'en': 'English',
    'ch_sim': '简体中文',
    'ch_tra': '繁体中文',
    'ja': '日语',
    'ko': '韩语',
}

translator: GoogleTranslator = GoogleTranslator(source='auto', target=TARGET_LANG)



def load_settings() -> None:
    global DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_THINKING, TRANSLATE_ENGINE, OCR_LANG
    if not os.path.exists(SETTINGS_PATH):
        return
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8", newline='') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 2:
                    continue
                key = row[0].strip()
                if key == "deepseek_api_key":
                    DEEPSEEK_API_KEY = row[1].strip()
                elif key == "deepseek_base_url":
                    DEEPSEEK_BASE_URL = row[1].strip()
                elif key == "deepseek_thinking":
                    DEEPSEEK_THINKING = row[1].strip().lower() == "true"
                elif key == "translate_engine":
                    TRANSLATE_ENGINE = row[1].strip()
                elif key == "ocr_lang":
                    OCR_LANG = [v.strip() for v in row[1:] if v.strip()]
    except Exception:
        pass


def save_settings() -> None:
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["deepseek_api_key", DEEPSEEK_API_KEY])
            writer.writerow(["deepseek_base_url", DEEPSEEK_BASE_URL])
            writer.writerow(["deepseek_thinking", str(DEEPSEEK_THINKING)])
            writer.writerow(["translate_engine", TRANSLATE_ENGINE])
            writer.writerow(["ocr_lang"] + OCR_LANG)
    except Exception:
        pass


load_settings()
