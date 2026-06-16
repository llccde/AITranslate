import json
import re
import traceback
import urllib.request
import urllib.error
from typing import Any, Callable, Optional, Tuple

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

SYSTEM_PROMPT = """你现在是一个翻译助手。你需要翻译以下json文本中的每一个text字段。
你必须严格按照以下格式输出翻译结果，用[index]和[!index]包裹每个文本块：

[1]
{
"id"="1",
"text"="翻译后的文本"
}
[!1]
[2]
{
"id"="2",
"text"="翻译后的文本"
}
[!2]

不要添加任何额外的解释或说明，只输出上述格式的翻译结果。"""


def _build_example_pair(source_lang: str, target_lang: str) -> Tuple[list[dict[str, str]], str]:
    """Generate a few-shot example tailored to the language pair."""
    examples: dict[Tuple[str, str], Tuple[list[dict[str, str]], str]] = {
        ('日语', '中文'): (
            [
                {"id": "1", "text": "こんにちは、お元気ですか？"},
                {"id": "2", "text": "私は元気です、ありがとう！"},
            ],
            """[1]
{
"id"="1",
"text"="你好，你还好吗？"
}
[!1]
[2]
{
"id"="2",
"text"="我很好，谢谢！"
}
[!2]""",
        ),
        ('英语', '中文'): (
            [
                {"id": "1", "text": "Hello, how are you?"},
                {"id": "2", "text": "I am fine, thank you!"},
            ],
            """[1]
{
"id"="1",
"text"="你好，你好吗？"
}
[!1]
[2]
{
"id"="2",
"text"="我很好，谢谢！"
}
[!2]""",
        ),
        ('中文', '英语'): (
            [
                {"id": "1", "text": "你好，最近怎么样？"},
                {"id": "2", "text": "我很好，谢谢关心！"},
            ],
            """[1]
{
"id"="1",
"text"="Hello, how have you been?"
}
[!1]
[2]
{
"id"="2",
"text"="I'm fine, thanks for asking!"
}
[!2]""",
        ),
        ('韩语', '中文'): (
            [
                {"id": "1", "text": "안녕하세요, 잘 지내세요?"},
                {"id": "2", "text": "네, 잘 지내요. 감사합니다!"},
            ],
            """[1]
{
"id"="1",
"text"="你好，你过得好吗？"
}
[!1]
[2]
{
"id"="2",
"text"="是的，我过得很好，谢谢！"
}
[!2]""",
        ),
    }
    pair = examples.get((source_lang, target_lang))
    if not pair:
        pair = examples.get(('英语', target_lang))
    if not pair:
        pair = examples[('日语', '中文')]
    return pair[0], pair[1]


class BlockParser:
    """Parses streaming text and extracts complete [N]...[!N] blocks."""

    _BLOCK_PATTERN: re.Pattern = re.compile(r'\[(\d+)\](.*?)\[!(\d+)\]', re.DOTALL)

    _on_block: Callable[[int, str], None]
    _buffer: str

    def __init__(self, on_block: Callable[[int, str], None]) -> None:
        self._on_block = on_block
        self._buffer = ""

    def feed(self, text: str) -> None:
        self._buffer += text
        while True:
            m = self._BLOCK_PATTERN.search(self._buffer)
            if not m:
                break
            idx_str, content, close_idx_str = m.group(1), m.group(2), m.group(3)
            if idx_str != close_idx_str:
                self._buffer = self._buffer[m.start() + len(f'[{idx_str}]'):]
                continue
            try:
                idx = int(idx_str)
            except ValueError:
                self._buffer = self._buffer[m.start() + len(f'[{idx_str}]'):]
                continue
            self._on_block(idx, content.strip())
            self._buffer = self._buffer[m.end():]

    def finish(self) -> None:
        pass


def _parse_block_content(content: str) -> str:
    """Extract translated text from a block's inner JSON content."""
    text_match = re.search(r'"text"\s*[=:]\s*"([^"]*)"', content)
    if text_match:
        return text_match.group(1)
    text_match = re.search(r'"text"\s*[=:]\s*\'([^\']*)\'', content)
    if text_match:
        return text_match.group(1)
    return content.strip()


class DeepSeekTranslator:
    _api_key: str

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def translate_batch(self, items: list[dict[str, Any]], source_lang: str, target_lang: str,
                         on_line: Optional[Callable[[int, str], None]] = None,
                         on_cancelled: Optional[Callable[[], bool]] = None,
                         on_prompt: Optional[Callable[[str], None]] = None,
                         on_stream: Optional[Callable[[str], None]] = None) -> Optional[dict[int, str]]:
        """
        Translate a batch of texts using DeepSeek streaming API.

        Args:
            items: List of dicts with 'id' (int, index into original lines) and 'text'
            source_lang: Source language name, e.g. '日语'
            target_lang: Target language name, e.g. '中文'
            on_line: Callback(idx, translated_text) for each completed line
            on_cancelled: Callback() -> bool
            on_prompt: Callback(prompt_text) with full conversation prompt
            on_stream: Callback(chunk_text) with each streaming delta chunk

        Returns:
            dict mapping idx -> translated_text, or None if cancelled
        """
        data_items = [{"id": str(item['id']), "text": item['text']} for item in items]
        json_input = json.dumps({"data": data_items}, ensure_ascii=False, indent=4)

        user_message = f"请翻译以下[{source_lang}]文本为[{target_lang}]：\n\n{json_input}"

        example_data, example_response = _build_example_pair(source_lang, target_lang)
        example_json = json.dumps({"data": example_data}, ensure_ascii=False, indent=4)
        example_user = f"请翻译以下[{source_lang}]文本为[{target_lang}]：\n\n{example_json}"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": example_user},
            {"role": "assistant", "content": example_response},
            {"role": "user", "content": user_message},
        ]

        if on_prompt:
            prompt_parts = []
            for m in messages:
                role_label = {"system": "系统", "user": "用户", "assistant": "助手"}.get(m["role"], m["role"])
                prompt_parts.append(f"=== {role_label} ===\n{m['content']}")
            on_prompt("\n\n".join(prompt_parts))

        payload: dict[str, Any] = {
            "model": DEEPSEEK_MODEL,
            "messages": messages,
            "stream": True,
            "temperature": 0.1,
            "max_tokens": 8192,
        }

        results: dict[int, str] = {}

        def on_block(idx: int, content: str) -> None:
            translated = _parse_block_content(content)
            results[idx] = translated
            if on_line:
                on_line(idx, translated)

        parser = BlockParser(on_block=on_block)

        try:
            req = urllib.request.Request(
                DEEPSEEK_API_URL,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {self._api_key}',
                    'Accept': 'text/event-stream',
                },
                method='POST',
            )

            with urllib.request.urlopen(req, timeout=180) as resp:
                for line in resp:
                    if on_cancelled and on_cancelled():
                        return None
                    line_text = line.decode('utf-8', errors='replace').strip()
                    if not line_text.startswith('data: '):
                        continue
                    data_str = line_text[6:]
                    if data_str == '[DONE]':
                        break
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = event.get('choices', [])
                    if not choices:
                        continue
                    delta = choices[0].get('delta', {})
                    content = delta.get('content', '')
                    if content:
                        if on_stream:
                            on_stream(content)
                        parser.feed(content)

            parser.finish()
            return results

        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode('utf-8', errors='replace')
            except Exception:
                pass
            traceback.print_exc()
            raise RuntimeError(f"DeepSeek API HTTP {e.code}: {error_body}")
        except Exception:
            traceback.print_exc()
            raise
