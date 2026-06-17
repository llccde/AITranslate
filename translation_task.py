import traceback
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import Any, Callable, Optional

from utils import clean_text, is_target_language


class TranslationTask:
    _lines: list[dict[str, Any]]
    _force: bool
    _translate_fn: Callable[[str], str]
    _max_workers: int
    _on_progress: Optional[Callable[[int, int], None]]
    _on_line_done: Optional[Callable[[int, str, dict[str, Any]], None]]
    _on_cancelled: Optional[Callable[[], bool]]
    _cancelled: bool

    def __init__(self, lines: list[dict[str, Any]], force: bool,
                 translate_fn: Callable[[str], str],
                 max_workers: int = 5,
                 on_progress: Optional[Callable[[int, int], None]] = None,
                 on_line_done: Optional[Callable[[int, str, dict[str, Any]], None]] = None,
                 on_cancelled: Optional[Callable[[], bool]] = None) -> None:
        self._lines = lines
        self._force = force
        self._translate_fn = translate_fn
        self._max_workers = max_workers
        self._on_progress = on_progress
        self._on_line_done = on_line_done
        self._on_cancelled = on_cancelled
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _is_cancelled(self) -> bool:
        if self._cancelled:
            return True
        if self._on_cancelled and self._on_cancelled():
            return True
        return False

    def execute(self) -> Optional[list[dict[str, Any]]]:
        total = len(self._lines)
        results: list[Optional[str]] = [None] * total

        if self._on_progress:
            self._on_progress(0, total)

        executor = ThreadPoolExecutor(max_workers=self._max_workers)
        try:
            fut_map: dict[Any, int] = {}
            for i in range(total):
                if self._is_cancelled():
                    return None
                fut = executor.submit(self._translate_fn, self._lines[i]['text'])
                fut_map[fut] = i

            pending = set(fut_map.keys())
            stall_count = 0
            while pending:
                if self._is_cancelled():
                    for f in pending:
                        f.cancel()
                    return None
                done, pending = wait(
                    pending, timeout=15, return_when=FIRST_COMPLETED
                )
                if done:
                    stall_count = 0
                    for future in done:
                        idx = fut_map[future]
                        try:
                            tr = future.result()
                        except Exception:
                            traceback.print_exc()
                            tr = "[错误]"
                        results[idx] = tr
                        if self._on_line_done:
                            self._on_line_done(idx, tr, self._lines[idx])
                        if self._on_progress:
                            completed = len([r for r in results if r is not None])
                            self._on_progress(completed, total)
                else:
                    stall_count += 1
                    if stall_count >= 2:
                        for future in list(pending):
                            future.cancel()
                            idx = fut_map[future]
                            results[idx] = "[超时]"
                            if self._on_line_done:
                                self._on_line_done(idx, "[超时]", self._lines[idx])
                        break
        finally:
            executor.shutdown(wait=False)

        line_results: list[dict[str, Any]] = []
        for i, line in enumerate(self._lines):
            line_results.append({
                'original': line['text'],
                'translated': results[i] or '…',
                'rel_x': line['x'],
                'rel_y': line['y'],
                'rel_w': line['w'],
                'rel_h': line['h']
            })
        return line_results
