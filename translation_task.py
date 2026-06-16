import traceback
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import Any, Callable, Optional, Tuple


class TranslationTask:
    _lines: list[dict[str, Any]]
    _force: bool
    _cache_get: Callable[[str], Optional[str]]
    _cache_set: Callable[[str, str], None]
    _translate_fn: Callable[[str], str]
    _max_workers: int
    _on_progress: Optional[Callable[[int, int], None]]
    _on_line_done: Optional[Callable[[int, str, dict[str, Any]], None]]
    _on_cancelled: Optional[Callable[[], bool]]
    _on_cache_entry: Optional[Callable[[str, str, bool], None]]
    _cancelled: bool

    def __init__(self, lines: list[dict[str, Any]], force: bool,
                 cache_get: Callable[[str], Optional[str]],
                 cache_set: Callable[[str, str], None],
                 translate_fn: Callable[[str], str],
                 max_workers: int = 5,
                 on_progress: Optional[Callable[[int, int], None]] = None,
                 on_line_done: Optional[Callable[[int, str, dict[str, Any]], None]] = None,
                 on_cancelled: Optional[Callable[[], bool]] = None,
                 on_cache_entry: Optional[Callable[[str, str, bool], None]] = None) -> None:
        self._lines = lines
        self._force = force
        self._cache_get = cache_get
        self._cache_set = cache_set
        self._translate_fn = translate_fn
        self._max_workers = max_workers
        self._on_progress = on_progress
        self._on_line_done = on_line_done
        self._on_cancelled = on_cancelled
        self._on_cache_entry = on_cache_entry
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _is_cancelled(self) -> bool:
        if self._cancelled:
            return True
        if self._on_cancelled and self._on_cancelled():
            return True
        return False

    def execute(self) -> Optional[Tuple[list[dict[str, Any]], int, int]]:
        total = len(self._lines)
        results: list[Optional[str]] = [None] * total
        uncached: list[int] = []
        cache_hits = 0

        for i, line in enumerate(self._lines):
            if self._is_cancelled():
                return None
            cached = self._cache_get(line['text'])
            if cached and not self._force:
                results[i] = cached
                cache_hits += 1
                if self._on_cache_entry:
                    self._on_cache_entry(line['text'], cached, True)
                if self._on_line_done:
                    self._on_line_done(i, cached, line)
            else:
                uncached.append(i)

        if self._on_progress:
            self._on_progress(len([r for r in results if r is not None]), total)

        api_calls = 0
        if uncached:
            executor = ThreadPoolExecutor(max_workers=self._max_workers)
            try:
                fut_map: dict[Any, int] = {}
                for i in uncached:
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
                            self._cache_set(self._lines[idx]['text'], tr)
                            api_calls += 1
                            if self._on_cache_entry:
                                self._on_cache_entry(self._lines[idx]['text'], tr, False)
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
        return line_results, cache_hits, api_calls
