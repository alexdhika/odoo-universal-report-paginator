import math
import re

from odoo import api, models


class UniversalReportPaginator(models.AbstractModel):
    _name = "universal_report_paginator.paginator"
    _description = "Universal Report Paginator"

    @api.model
    def paginate(
        self,
        lines,
        dynamic_fields,
        dynamic_field_width,
        content_height,
        last_page_content_height=None,
        font_size=10.0,
        line_height=None,
        padding_height=0.0,
        subtotal_getter=None,
        separator="\n",
        chars_per_width_unit=0.16,
        min_lines=1,
    ):
        """
        Paginate arbitrary Odoo records for a QWeb report.

        Parameters
        ----------
        lines:
            Odoo recordset or iterable of records.

        dynamic_fields:
            A string or list/tuple of field names. Their values are combined
            before estimating the rendered height.

        dynamic_field_width:
            Width of the dynamic text column in the same unit used by the
            report CSS. Usually px.

        content_height:
            Available detail height for normal pages.

        last_page_content_height:
            Available detail height for the last page. If omitted, the normal
            content_height is used. This is useful when the last page reserves
            space for signatures.

        font_size:
            Font size in the same unit expected by the approximation.

        line_height:
            Height of one rendered text line. If omitted, defaults to
            font_size * 1.4.

        padding_height:
            Extra fixed height added to every detail row.

        subtotal_getter:
            Optional callable(record) -> numeric amount. If omitted, page
            subtotal is not calculated.

        separator:
            Separator used when combining multiple dynamic fields.

        chars_per_width_unit:
            Approximate character density. With width=300 and the default
            0.16, the estimated capacity is 48 characters per rendered line.

        min_lines:
            Minimum estimated number of text lines per record.

        Returns
        -------
        list[dict]
            Each page contains:
                lines
                subtotal
                running_total
                page
                is_last
                content_height
                used_height
        """
        records = list(lines or [])
        fields = self._normalize_fields(dynamic_fields)

        if dynamic_field_width <= 0:
            raise ValueError("dynamic_field_width must be greater than zero.")
        if content_height <= 0:
            raise ValueError("content_height must be greater than zero.")
        if last_page_content_height is None:
            last_page_content_height = content_height
        if last_page_content_height <= 0:
            raise ValueError("last_page_content_height must be greater than zero.")
        if font_size <= 0:
            raise ValueError("font_size must be greater than zero.")
        if line_height is None:
            line_height = font_size * 1.4
        if line_height <= 0:
            raise ValueError("line_height must be greater than zero.")

        # Approximate characters per line from the dynamic column width.
        chars_per_line = max(
            1,
            int(round(dynamic_field_width * chars_per_width_unit)),
        )

        row_infos = []
        for record in records:
            text = self._combined_text(record, fields, separator)
            estimated_lines = self._estimate_text_lines(
                text,
                chars_per_line=chars_per_line,
                min_lines=min_lines,
            )
            height = (estimated_lines * line_height) + padding_height

            # Prevent a zero/negative row height from breaking pagination.
            height = max(float(line_height), float(height))

            amount = subtotal_getter(record) if subtotal_getter else 0.0
            amount = self._to_number(amount)

            row_infos.append({
                "record": record,
                "height": height,
                "amount": amount,
                "text": text,
                "estimated_lines": estimated_lines,
            })

        # First create pages using the normal-page capacity. The last-page
        # reservation is then respected by moving trailing rows to a new page.
        pages = []
        current = []
        current_height = 0.0

        for info in row_infos:
            if current and current_height + info["height"] > content_height:
                pages.append(self._make_page(current, content_height))
                current = []
                current_height = 0.0

            # A single row may be taller than the available area. Keep it on
            # its own page rather than creating an empty page.
            current.append(info)
            current_height += info["height"]

        if current:
            pages.append(self._make_page(current, content_height))

        # Ensure the final page fits the smaller last-page area reserved for
        # signatures or other last-page content.
        while len(pages) > 1 and pages[-1]["used_height"] > last_page_content_height:
            overflow = pages[-1]["items"].pop(0)
            pages[-1]["used_height"] -= overflow["height"]

            if pages[-2]["used_height"] + overflow["height"] <= content_height:
                pages[-2]["items"].append(overflow)
                pages[-2]["used_height"] += overflow["height"]
            else:
                # If moving one row back would overflow the previous page,
                # create a new page before the current last page.
                pages.insert(
                    -1,
                    self._make_page([overflow], content_height),
                )

            if not pages[-1]["items"]:
                pages.pop()

        result = []
        running_total = 0.0

        for index, page in enumerate(pages, start=1):
            page_lines = [item["record"] for item in page["items"]]
            subtotal = sum(item["amount"] for item in page["items"])
            running_total += subtotal

            result.append({
                "lines": page_lines,
                "subtotal": subtotal,
                "running_total": running_total,
                "page": index,
                "page_number": index,
                "is_last": index == len(pages),
                "content_height": (
                    last_page_content_height
                    if index == len(pages)
                    else content_height
                ),
                "used_height": page["used_height"],
                "remaining_height": max(
                    0.0,
                    (
                        last_page_content_height
                        if index == len(pages)
                        else content_height
                    ) - page["used_height"],
                ),
                "line_count": len(page_lines),
            })

        return result

    @api.model
    def _normalize_fields(self, dynamic_fields):
        if isinstance(dynamic_fields, str):
            return [dynamic_fields]
        return list(dynamic_fields or [])

    @api.model
    def _combined_text(self, record, fields, separator):
        values = []
        for field_name in fields:
            value = self._get_field_value(record, field_name)
            if value is None or value is False:
                continue
            value = self._html_to_text(value)
            value = str(value).strip()
            if value:
                values.append(value)
        return separator.join(values)

    @api.model
    def _get_field_value(self, record, field_name):
        value = record
        for part in field_name.split("."):
            if value is None or value is False:
                return False
            if hasattr(value, "_name") and hasattr(value, part):
                value = getattr(value, part)
            else:
                return False
        return value

    @api.model
    def _html_to_text(self, value):
        if not isinstance(value, str) or "<" not in value:
            return value

        # Lightweight HTML-to-text conversion. This is deliberately simple:
        # the paginator only needs an approximate line count, not HTML output.
        value = re.sub(r"(?i)<br\s*/?>", "\n", value)
        value = re.sub(r"(?i)</p\s*>", "\n", value)
        value = re.sub(r"(?i)</div\s*>", "\n", value)
        value = re.sub(r"<[^>]+>", "", value)
        value = re.sub(r"\s+\n", "\n", value)
        return value

    @api.model
    def _estimate_text_lines(self, text, chars_per_line, min_lines=1):
        if not text:
            return max(1, min_lines)

        total = 0
        for paragraph in str(text).splitlines() or [""]:
            paragraph = paragraph.strip()
            if not paragraph:
                total += 1
                continue

            # Explicitly account for existing line breaks and approximate
            # wrapping inside each paragraph.
            total += max(1, math.ceil(len(paragraph) / chars_per_line))

        return max(min_lines, total)

    @api.model
    def _make_page(self, items, capacity):
        return {
            "items": list(items),
            "used_height": sum(item["height"] for item in items),
            "capacity": capacity,
        }

    @api.model
    def _to_number(self, value):
        if value is None or value is False:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
