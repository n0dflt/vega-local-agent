"""Terminal rendering for safe execution progress events."""

from __future__ import annotations

import sys
from typing import TextIO

from core.execution_progress import ExecutionProgressEvent, ExecutionProgressStage
from ui.terminal_theme import TerminalCapabilities, detect_terminal_capabilities


class TerminalProgressRenderer:
    """Render progress without owning or mutating execution state."""

    _UNICODE_SPINNER = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧")
    _ASCII_SPINNER = ("|", "/", "-", "\\")

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        interactive: bool | None = None,
        ansi: bool | None = None,
        unicode: bool | None = None,
        width: int = 20,
    ) -> None:
        if type(width) is not int or width < 4:
            raise ValueError("width must be an integer of at least 4")
        self.stream = stream or sys.stdout
        self.capabilities: TerminalCapabilities = detect_terminal_capabilities(
            self.stream,
            interactive=interactive,
            ansi=ansi,
            unicode=unicode,
        )
        self.width = width
        self._spinner_index = 0
        self._line_active = False
        self._closed = False

    def __enter__(self) -> "TerminalProgressRenderer":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def __call__(self, event: ExecutionProgressEvent) -> None:
        self.handle(event)

    def _symbol(self, unicode_value: str, ascii_value: str) -> str:
        return unicode_value if self.capabilities.unicode else ascii_value

    def _spinner(self) -> str:
        frames = self._UNICODE_SPINNER if self.capabilities.unicode else self._ASCII_SPINNER
        frame = frames[self._spinner_index % len(frames)]
        self._spinner_index += 1
        return frame

    def _write_line(self, text: str) -> None:
        if self.capabilities.interactive:
            prefix = "\r\x1b[2K" if self.capabilities.ansi else "\r"
            self.stream.write(prefix + text)
            self._line_active = True
        else:
            self.stream.write(text + "\n")
        self.stream.flush()

    def _finish_line(self, text: str | None = None) -> None:
        if self.capabilities.interactive:
            if text is not None:
                prefix = "\r\x1b[2K" if self.capabilities.ansi else "\r"
                self.stream.write(prefix + text)
            if self._line_active or text is not None:
                self.stream.write("\n")
            self._line_active = False
        elif text is not None:
            self.stream.write(text + "\n")
        self.stream.flush()

    def _bar(self, event: ExecutionProgressEvent) -> str:
        if event.total_steps <= 0:
            return ""
        filled = round(self.width * event.current_step / event.total_steps)
        if event.stage is not ExecutionProgressStage.COMPLETED:
            filled = min(filled, self.width - 1)
        filled = max(0, min(self.width, filled))
        if self.capabilities.unicode:
            return "[" + "█" * filled + "░" * (self.width - filled) + "]"
        return "[" + "#" * filled + "-" * (self.width - filled) + "]"

    def _count(self, event: ExecutionProgressEvent) -> str:
        return f"{event.current_step}/{event.total_steps}"

    def _display_title(self, event: ExecutionProgressEvent, fallback: str) -> str:
        title = event.title or fallback
        if not self.capabilities.unicode and not title.isascii():
            return fallback
        return title

    def _progress_line(self, event: ExecutionProgressEvent, marker: str) -> str:
        ascii_fallbacks = {
            ExecutionProgressStage.STEP_RUNNING: "Step running",
            ExecutionProgressStage.AWAITING_CONFIRMATION: "Awaiting confirmation",
            ExecutionProgressStage.STEP_COMPLETED: "Step completed",
            ExecutionProgressStage.STEP_SKIPPED: "Step skipped",
            ExecutionProgressStage.STEP_FAILED: "Step failed",
            ExecutionProgressStage.COMPLETED: "Done",
            ExecutionProgressStage.FAILED: "Execution failed",
        }
        title = self._display_title(
            event,
            "Шаг выполняется"
            if self.capabilities.unicode
            else ascii_fallbacks.get(event.stage, "Progress"),
        )
        separator = " · " if self.capabilities.unicode else " - "
        return f"{marker} {self._bar(event)} {self._count(event)}{separator}{title}"

    def _render_plan(self, event: ExecutionProgressEvent) -> str:
        if self.capabilities.unicode:
            header = f"План выполнения · {event.total_steps} шагов"
        else:
            header = f"Execution plan - {event.total_steps} steps"
        lines = [header, ""]
        for index, title in enumerate(event.plan_titles, 1):
            if not self.capabilities.unicode and not title.isascii():
                title = f"Operation {index}"
            lines.append(f"  {index}. {title}")
        return "\n".join(lines).rstrip()

    def handle(self, event: ExecutionProgressEvent) -> None:
        if self._closed:
            return
        if not isinstance(event, ExecutionProgressEvent):
            raise TypeError("event must be an ExecutionProgressEvent")
        stage = event.stage
        if stage is ExecutionProgressStage.RECEIVED:
            text = "VEGA приняла запрос…" if self.capabilities.unicode else "VEGA received the request..."
            self._write_line(f"{self._spinner()} {text}")
        elif stage is ExecutionProgressStage.ANALYZING:
            text = event.title or ("VEGA анализирует запрос…" if self.capabilities.unicode else "VEGA analyzes the request...")
            self._write_line(f"{self._spinner()} {text}")
        elif stage is ExecutionProgressStage.PLANNING:
            text = event.title or ("VEGA строит план выполнения…" if self.capabilities.unicode else "VEGA builds the execution plan...")
            self._write_line(f"{self._spinner()} {text}")
        elif stage is ExecutionProgressStage.PLAN_READY:
            self._finish_line()
            self.stream.write(self._render_plan(event) + "\n\n")
            self.stream.flush()
        elif stage is ExecutionProgressStage.STEP_RUNNING:
            self._write_line(self._progress_line(event, self._spinner()))
        elif stage is ExecutionProgressStage.AWAITING_CONFIRMATION:
            marker = self._symbol("◆", "!")
            self._finish_line(self._progress_line(event, marker))
        elif stage is ExecutionProgressStage.STEP_COMPLETED:
            marker = self._symbol("✓", "+")
            self._write_line(self._progress_line(event, marker))
        elif stage is ExecutionProgressStage.STEP_SKIPPED:
            marker = self._symbol("–", "-")
            self._finish_line(self._progress_line(event, marker))
        elif stage is ExecutionProgressStage.STEP_FAILED:
            marker = self._symbol("✗", "x")
            self._write_line(self._progress_line(event, marker))
        elif stage is ExecutionProgressStage.COMPLETED:
            marker = self._symbol("✓", "+")
            title = self._display_title(
                event,
                "Готово" if self.capabilities.unicode else "Done",
            )
            if event.elapsed_seconds is not None:
                duration = f"{event.elapsed_seconds:.1f}"
                if self.capabilities.unicode:
                    duration = duration.replace(".", ",")
                    title = f"{title} за {duration} сек."
                else:
                    title = f"{title} in {duration} sec."
            terminal = ExecutionProgressEvent(
                stage=stage,
                current_step=event.total_steps,
                total_steps=event.total_steps,
                title=title,
                elapsed_seconds=event.elapsed_seconds,
            )
            if terminal.total_steps:
                line = self._progress_line(terminal, marker)
            else:
                line = f"{marker} {title}"
            self._finish_line(line)
        elif stage is ExecutionProgressStage.FAILED:
            marker = self._symbol("✗", "x")
            title = self._display_title(
                event,
                "Выполнение завершилось с ошибкой"
                if self.capabilities.unicode
                else "Execution failed",
            )
            failed = ExecutionProgressEvent(
                stage=stage,
                current_step=event.current_step,
                total_steps=event.total_steps,
                title=title,
            )
            line = self._progress_line(failed, marker) if failed.total_steps else f"{marker} {title}"
            self._finish_line(line)

    def close(self) -> None:
        if self._closed:
            return
        self._finish_line()
        self._closed = True


__all__ = ["TerminalProgressRenderer"]
