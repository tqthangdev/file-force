"""QueueDelegate — paints one job row and handles the per-file target selector."""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QEvent, QModelIndex, QRect, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QMenu, QStyledItemDelegate, QStyle, QStyleOptionViewItem

from app.core.format_registry import FormatRegistry
from app.models.conversion_job import ConversionJob, JobStatus
from app.ui.queues.queue_model import JobRoles
from app.utils.format_utils import format_label, human_size

ROW_HEIGHT = 64

_STATUS_TEXT = {
    JobStatus.WAITING: "Waiting",
    JobStatus.CONVERTING: "Converting",
    JobStatus.COMPLETED: "Done",
    JobStatus.FAILED: "Failed",
    JobStatus.CANCELLED: "Cancelled",
    JobStatus.BLOCKED: "Blocked",
}

_STATUS_COLOR = {
    JobStatus.WAITING: QColor(120, 120, 120),
    JobStatus.CONVERTING: QColor(30, 110, 200),
    JobStatus.COMPLETED: QColor(30, 150, 70),
    JobStatus.FAILED: QColor(200, 50, 50),
    JobStatus.CANCELLED: QColor(150, 120, 30),
    JobStatus.BLOCKED: QColor(200, 50, 50),
}

_MUTED = QColor(130, 130, 130)
_BADGE_BORDER = QColor(160, 160, 160)
_ERROR = QColor(200, 50, 50)


class QueueDelegate(QStyledItemDelegate):
    def __init__(
        self,
        registry: FormatRegistry,
        on_target_changed: Callable[[ConversionJob, str], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.registry = registry
        self.on_target_changed = on_target_changed

    # ------------------------------------------------------------------ geometry
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), ROW_HEIGHT)

    @staticmethod
    def _target_rect(rect: QRect) -> QRect:
        return QRect(rect.left() + 140, rect.top() + 28, 100, 20)

    # --------------------------------------------------------------------- paint
    @staticmethod
    def _selection_background(option: QStyleOptionViewItem) -> QColor:
        """Blend the highlight over the base colour.

        A full-strength highlight with the default palette is only ~3.7:1 against
        its text, which washes text out. A tint keeps dark/light text readable and
        lets the semantic status colours stay meaningful.
        """
        highlight = option.palette.highlight().color()
        base = option.palette.base().color()
        alpha = 0.32
        return QColor(
            round(base.red() * (1 - alpha) + highlight.red() * alpha),
            round(base.green() * (1 - alpha) + highlight.green() * alpha),
            round(base.blue() * (1 - alpha) + highlight.blue() * alpha),
        )

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        job: ConversionJob | None = index.data(JobRoles.JOB)
        if job is None:
            return

        painter.save()
        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(rect, self._selection_background(option))

        text_color = option.palette.text().color()
        muted = _MUTED

        # Name
        name_font = QFont(option.font)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(text_color)
        name_rect = QRect(rect.left() + 12, rect.top() + 8, rect.width() - 260, 20)
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            painter.fontMetrics().elidedText(
                job.filename, Qt.TextElideMode.ElideMiddle, name_rect.width()
            ),
        )

        if selected:
            # Accent bar so selection stays obvious on light and dark themes.
            accent = option.palette.highlight().color()
            painter.fillRect(QRect(rect.left(), rect.top(), 4, rect.height()), accent)

        # Source → target
        painter.setFont(option.font)
        painter.setPen(muted)
        src_rect = QRect(rect.left() + 12, rect.top() + 28, 120, 20)
        painter.drawText(
            src_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            format_label(job.source_format),
        )

        badge = self._target_rect(rect)
        painter.setPen(_BADGE_BORDER)
        painter.drawRoundedRect(badge, 4, 4)
        painter.setPen(text_color)
        painter.drawText(
            badge,
            Qt.AlignmentFlag.AlignCenter,
            format_label(job.target_format) + "  ▾",
        )

        # Right column: status + size. Semantic colour is kept while selected; the
        # tinted background keeps it readable.
        painter.setPen(_STATUS_COLOR.get(job.status, muted))
        status_rect = QRect(rect.right() - 230, rect.top() + 8, 218, 20)
        painter.drawText(
            status_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            _STATUS_TEXT.get(job.status, ""),
        )
        painter.setPen(muted)
        size_rect = QRect(rect.right() - 230, rect.top() + 28, 218, 18)
        painter.drawText(
            size_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            human_size(self._source_size(job)),
        )

        # Bottom: error message or progress bar
        if job.error and job.status in (
            JobStatus.FAILED,
            JobStatus.BLOCKED,
            JobStatus.CANCELLED,
        ):
            painter.setPen(_ERROR)
            error_rect = QRect(rect.left() + 12, rect.top() + 48, rect.width() - 24, 14)
            painter.drawText(
                error_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                painter.fontMetrics().elidedText(
                    job.error, Qt.TextElideMode.ElideRight, error_rect.width()
                ),
            )
        elif job.status in (JobStatus.CONVERTING,):
            bar = QRect(rect.left() + 12, rect.top() + 52, rect.width() - 260, 6)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(210, 210, 210))
            painter.drawRoundedRect(bar, 3, 3)
            filled = QRect(bar)
            filled.setWidth(int(bar.width() * max(0, min(100, job.progress)) / 100))
            painter.setBrush(QColor(30, 140, 230))
            painter.drawRoundedRect(filled, 3, 3)
            painter.setBrush(Qt.BrushStyle.NoBrush)

        painter.restore()

    @staticmethod
    def _source_size(job: ConversionJob) -> int | None:
        try:
            return job.source.stat().st_size
        except OSError:
            return None

    # -------------------------------------------------------------------- target menu
    def editorEvent(self, event, model, option, index) -> bool:
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        ):
            pos = event.position().toPoint()
            if self._target_rect(option.rect).contains(pos):
                job: ConversionJob | None = index.data(JobRoles.JOB)
                if job is not None and job.status is not JobStatus.CONVERTING:
                    self._show_target_menu(job, event.globalPosition().toPoint())
                return True
        return False

    def _show_target_menu(self, job: ConversionJob, global_pos) -> None:
        menu = QMenu()
        targets = self.registry.targets_for(job.source_format)
        if not targets:
            action = menu.addAction("No target formats available")
            action.setEnabled(False)
        for target in targets:
            action = menu.addAction(self.registry.display_name(target))
            action.setData(target)
            action.setCheckable(True)
            action.setChecked(target == job.target_format)
            if not self.registry.is_available(job.source_format, target):
                action.setEnabled(False)
                action.setToolTip(
                    self.registry.disabled_reason(job.source_format, target) or ""
                )
        chosen = menu.exec(global_pos)
        if chosen is not None and chosen.data():
            self.on_target_changed(job, chosen.data())
