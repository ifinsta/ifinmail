"""
MyDoc Parallel Executor (Phase 3 — Free-Threaded Python Integration)

Provides utilities for parallel execution of introspection tasks when
running under a free-threaded Python build (PEP 703, Python 3.13+).

On standard GIL-enabled builds, falls back to sequential execution.
The parallelism is only enabled when is_free_threaded() returns True,
which checks for the actual GIL-free runtime.

Usage:
    from backend.apps.core.mydoc._parallel import parallel_map, is_free_threaded

    results = parallel_map(inspect_endpoint, endpoints)
"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, TypeVar

T = TypeVar("T")
R = TypeVar("R")

# ---------------------------------------------------------------------------
# Free-threaded Python detection (PEP 703)
# ---------------------------------------------------------------------------

def is_free_threaded() -> bool:
    """Check if the current Python interpreter is free-threaded (no GIL).

    Detection strategy:
    1. Python 3.13+: Check sys._is_gil_enabled() if available
    2. Check PYTHON_GIL=0 environment variable
    3. Check sys.flags.nogil if available (development builds)
    """
    # Python 3.13+ has sys._is_gil_enabled()
    gil_enabled = getattr(sys, "_is_gil_enabled", None)
    if gil_enabled is not None:
        return not gil_enabled()

    # Development builds may have sys.flags.nogil
    if getattr(sys.flags, "nogil", False):
        return True

    # Environment variable override
    if os.environ.get("PYTHON_GIL", "").strip() == "0":
        return True

    return False


# ---------------------------------------------------------------------------
# Optimal worker count
# ---------------------------------------------------------------------------

def _optimal_workers() -> int:
    """Calculate optimal thread count for parallel introspection.

    For free-threaded Python: CPU count (true parallelism)
    For GIL-enabled Python: 1 (no benefit from threads for CPU-bound work)
    """
    if not is_free_threaded():
        return 1
    try:
        return min(os.cpu_count() or 4, 8)  # Cap at 8 for introspection
    except Exception:
        return 4


# ---------------------------------------------------------------------------
# Parallel execution utilities
# ---------------------------------------------------------------------------

def parallel_map(
    fn: Callable[[T], R],
    items: list[T],
    *,
    max_workers: int | None = None,
    desc: str = "task",
) -> list[R]:
    """Execute fn over items in parallel when free-threaded, sequentially otherwise.

    Args:
        fn: Function to apply to each item.
        items: List of input items.
        max_workers: Override worker count. If None, auto-detects.
        desc: Description for logging purposes.

    Returns:
        List of results in the same order as items.
    """
    if not items:
        return []

    workers = max_workers or _optimal_workers()

    if workers <= 1:
        # Sequential execution (GIL-enabled Python)
        return [fn(item) for item in items]

    # Parallel execution (free-threaded Python — no GIL)
    results: list[R | None] = [None] * len(items)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_idx = {
            executor.submit(fn, item): idx
            for idx, item in enumerate(items)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            results[idx] = future.result()

    return [r for r in results]  # type: ignore[return-value]


def parallel_sections(
    sections: list[Any],
    processor: Callable[[Any], Any],
    *,
    max_workers: int | None = None,
) -> list[Any]:
    """Process sections in parallel when free-threaded.

    Each section is processed independently — ideal for:
    - Parallel serializer inspection per section
    - Parallel audit checks per section
    - Parallel OpenAPI spec generation per section

    Args:
        sections: List of section objects to process.
        processor: Function that takes a section and returns processed result.
        max_workers: Override worker count.

    Returns:
        List of processed results in order.
    """
    return parallel_map(processor, sections, max_workers=max_workers, desc="section")


# ---------------------------------------------------------------------------
# Batch parallel executor for endpoint-level work
# ---------------------------------------------------------------------------

def parallel_endpoints(
    endpoints: list[Any],
    processor: Callable[[Any], Any],
    section_ref: Any = None,
    *,
    max_workers: int | None = None,
) -> list[Any]:
    """Process endpoints in parallel when free-threaded.

    Used for endpoint-level work like:
    - Parallel serializer field extraction
    - Parallel permission resolution
    - Parallel audit check evaluation

    Args:
        endpoints: List of endpoint objects.
        processor: Function that takes an endpoint and returns result.
        section_ref: Optional section reference for context.
        max_workers: Override worker count.

    Returns:
        List of results in order.
    """
    return parallel_map(processor, endpoints, max_workers=max_workers, desc="endpoint")


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

FREE_THREADED = is_free_threaded()
OPTIMAL_WORKERS = _optimal_workers()
