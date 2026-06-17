import json
import re
import traceback
import urllib.request
import urllib.error
from typing import Any, Callable, Optional, Tuple

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

SYSTEM_PROMPT = """你是一个翻译助手，专门处理从屏幕OCR识别出的文本

## 核心任务
翻译json文本中的每一个text字段,对于出错的文本进行推测。

### 3. 格式要求
严格按照以下格式输出翻译结果，用[index]和[!index]包裹每个文本块：

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
不确定的文本可以在guess字段中给出推测，但最终的text字段必须有翻译结果（可以是空字符串）。例如：
不要添加任何额外的解释或说明，只输出上述格式的翻译结果。
即使某条原文是乱码需要丢弃，也必须输出该条目（text可为空字符串）。"""


def _build_example_pair(source_lang: str, target_lang: str) -> Tuple[list[dict[str, str]], str]:
    """Generate a few-shot example tailored to the language pair.
    The examples now include 4 entries to demonstrate:
    - Clear text (no guess)
    - Recoverable garbled text (with guess)
    - Pure noise (empty text, no guess)
    - Clear text (no guess)
    This encourages the model to output a guess field when it can recover the original text.
    """
    examples: dict[Tuple[str, str], Tuple[list[dict[str, str]], str]] = {
        ('日语', '中文'): (
            [
                {"id": "1", "text": "こんにちは、お元気ですか？"},
                {"id": "2", "text": "今日は夭気がいいですね%%"},
                {"id": "3", "text": "@@@###$$$"},
                {"id": "4", "text": "ありがとうございます"},
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
"guess"="今日は天気がいいですね",
"text"="今天天气真好啊"
}
[!2]
[3]
{
"id"="3",
"text"=""
}
[!3]
[4]
{
"id"="4",
"text"="谢谢"
}
[!4]""",
        ),
        ('英语', '中文'): (
            [
                {"id": "1", "text": "Hello, how are you?"},
                {"id": "2", "text": "Th1s is a t3st message%%%"},
                {"id": "3", "text": "###@@@%%%&"},
                {"id": "4", "text": "I am fine,thank you thank you thank you!"},
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
"guess"="This is a test message",
"text"="这是一条测试消息"
}
[!2]
[3]
{
"id"="3",
"text"=""
}
[!3]
[4]
{
"id"="4",
"guess" = "thank you 出现了三次，可能是强调或者重复输入,推测原文是: I am fine, thank you!",
"text"="我很好，谢谢！"
}
[!4]""",
        ),
        ('中文', '英语'): (
            [
                {"id": "1", "text": "你好，最近怎么样？"},
                {"id": "2", "text": "我己经完完成任努任务任务了%%"},
                {"id": "3", "text": "锟斤拷烫烫烫###@@@%"},
                {"id": "4", "text": "谢谢你的帮助"},
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
"guess"="推测原始文本是:我已经完成任务了",
"text"="I have completed the task"
}
[!2]
[3]
{
"id"="3",
"text"=""
}
[!3]
[4]
{
"id"="4",
"text"="Thank you for your help"
}
[!4]""",
        ),
        ('韩语', '中文'): (
            [
                {"id": "1", "text": "안녕하세요, 잘 지내세요?"},
                {"id": "2", "text": "오늘 달씨가 좋네요%%"},
                {"id": "3", "text": "#@!*&^%$word"},
                {"id": "4", "text": "감사합니다"},
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
"guess"="오늘 날씨가 좋네요",
"text"="今天天气真好"
}
[!2]
[3]
{
"id"="3",
"text"=""
}
[!3]
[4]
{
"id"="4",
"text"="谢谢"
}
[!4]""",
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
    """Extract translated text from a block's inner JSON-like content.
    Ignores optional 'guess' field and extracts only the final 'text' field.
    """
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
                         on_stream: Optional[Callable[[str], None]] = None,
                         on_usage: Optional[Callable[[int, int], None]] = None) -> Optional[dict[int, str]]:
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
            on_usage: Callback(prompt_tokens, completion_tokens) when usage data arrives

        Returns:
            dict mapping idx -> translated_text, or None if cancelled
        """
        data_items = [{"id": str(item['id']), "text": item['text']} for item in items]
        json_input = json.dumps({"data": data_items}, ensure_ascii=False, indent=4)

        user_message = f"请翻译以下文本为[{target_lang}]：\n\n{json_input}"

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
                    usage = event.get('usage')
                    if usage and on_usage:
                        on_usage(usage.get('prompt_tokens', 0),
                                 usage.get('completion_tokens', 0))
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
        except Exception as e:
            traceback.print_exc()
            raise RuntimeError(f"DeepSeek API request failed: {str(e)}")