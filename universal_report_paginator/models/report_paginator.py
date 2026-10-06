import math
import re

from odoo import api, models


class UniversalReportPaginator(models.AbstractModel):
    _name = "universal_report_paginator.paginator"
    _description = "Universal Report Paginator"

    @api.model
    def debug_rows(
        self,
        lines,
        dynamic_fields,
        dynamic_field_width_mm,
        font_size_mm=3.5,
        line_height_mm=None,
        padding_height_mm=0.0,
        separator="\n",
        chars_per_width_unit=0.55,
        min_lines=1,
    ):
        if line_height_mm is None:
            line_height_mm = font_size_mm * 1.4

        chars_per_line = max(
            1,
            int(round(
                dynamic_field_width_mm
                * chars_per_width_unit
            )),
        )

        result = []

        for record in lines:
            text = self._combined_text(
                record,
                dynamic_fields,
                separator,
            )

            estimated_lines = self._estimate_text_lines(
                text,
                chars_per_line,
                min_lines,
            )

            height = max(
                float(line_height_mm),
                estimated_lines * line_height_mm
                + padding_height_mm,
            )

            result.append({
                "id": record.id,
                "text": text,
                "chars": len(text),
                "estimated_lines": estimated_lines,
                "height": height,
            })

        return {
            "chars_per_line": chars_per_line,
            "line_height_mm": line_height_mm,
            "rows": result,
        }

    @api.model
    def paginate(
        self,
        lines,
        dynamic_fields,
        dynamic_field_width_mm,
        content_height_mm,
        last_page_content_height_mm=None,
        font_size_mm=3.5,
        line_height_mm=None,
        padding_height_mm=0.0,
        subtotal_getter=None,
        separator="\n",
        chars_per_width_unit=0.55,
        min_lines=1,
    ):
        """
        Paginate arbitrary Odoo records for a QWeb report.

        All physical dimensions are expressed in millimeters (mm).

        Parameters
        ----------
        lines:
            Odoo recordset or iterable of records.

        dynamic_fields:
            A string or list/tuple of field names. Their values are combined
            before estimating the rendered height.

        dynamic_field_width_mm:
            Width of the dynamic text column in millimeters.

        content_height_mm:
            Available detail height for normal pages in millimeters.

        last_page_content_height_mm:
            Available detail height for the last page in millimeters.
            If omitted, content_height_mm is used.

        font_size_mm:
            Font size in millimeters.
            Example: 10pt ≈ 3.53mm.

        line_height_mm:
            Height of one rendered text line in millimeters.
            If omitted, defaults to font_size_mm * 1.4.

        padding_height_mm:
            Extra fixed height added to every detail row.

        subtotal_getter:
            Optional callable(record) -> numeric amount.

        separator:
            Separator used when combining multiple dynamic fields.

        chars_per_width_unit:
            Approximate character density per millimeter.

            Example:
                width = 100mm
                chars_per_width_unit = 2.8

                => approximately 280 characters per line

            This is only an approximation and should be calibrated
            against the actual QWeb PDF rendering.

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
                page_number
                is_last
                content_height
                used_height
                remaining_height
                line_count
        """

        records = list(lines or [])
        fields = self._normalize_fields(dynamic_fields)

        if dynamic_field_width_mm <= 0:
            raise ValueError(
                "dynamic_field_width_mm must be greater than zero."
            )

        if content_height_mm <= 0:
            raise ValueError(
                "content_height_mm must be greater than zero."
            )

        if last_page_content_height_mm is None:
            last_page_content_height_mm = content_height_mm

        if last_page_content_height_mm <= 0:
            raise ValueError(
                "last_page_content_height_mm must be greater than zero."
            )

        if font_size_mm <= 0:
            raise ValueError(
                "font_size_mm must be greater than zero."
            )

        if line_height_mm is None:
            line_height_mm = font_size_mm * 1.4

        if line_height_mm <= 0:
            raise ValueError(
                "line_height_mm must be greater than zero."
            )

        if chars_per_width_unit <= 0:
            raise ValueError(
                "chars_per_width_unit must be greater than zero."
            )

        # Approximate characters per line from the dynamic column width.
        chars_per_line = max(
            1,
            int(round(
                dynamic_field_width_mm * chars_per_width_unit
            )),
        )

        row_infos = []

        for record in records:
            text = self._combined_text(
                record,
                fields,
                separator,
            )

            estimated_lines = self._estimate_text_lines(
                text,
                chars_per_line=chars_per_line,
                min_lines=min_lines,
            )

            height = (
                estimated_lines * line_height_mm
            ) + padding_height_mm

            # Prevent zero/negative row height.
            height = max(
                float(line_height_mm),
                float(height),
            )

            amount = (
                subtotal_getter(record)
                if subtotal_getter
                else 0.0
            )

            amount = self._to_number(amount)

            row_infos.append({
                "record": record,
                "height": height,
                "amount": amount,
                "text": text,
                "estimated_lines": estimated_lines,
            })

        # ---------------------------------------------------------
        # Build normal pages first.
        # ---------------------------------------------------------

        pages = []
        current = []
        current_height = 0.0

        for info in row_infos:

            # If adding this row would exceed the normal page,
            # start a new page.
            if (
                current
                and current_height + info["height"] > content_height_mm
            ):
                pages.append(
                    self._make_page(
                        current,
                        content_height_mm,
                    )
                )

                current = []
                current_height = 0.0

            current.append(info)
            current_height += info["height"]

        if current:
            pages.append(
                self._make_page(
                    current,
                    content_height_mm,
                )
            )

        # ---------------------------------------------------------
        # Ensure the final page fits the last-page capacity.
        # ---------------------------------------------------------

        if pages:

            while (
                len(pages) > 1
                and pages[-1]["used_height"]
                > last_page_content_height_mm
            ):
                overflow = pages[-1]["items"].pop(0)

                pages[-1]["used_height"] -= (
                    overflow["height"]
                )

                previous_page = pages[-2]

                if (
                    previous_page["used_height"]
                    + overflow["height"]
                    <= content_height_mm
                ):
                    previous_page["items"].append(
                        overflow
                    )

                    previous_page["used_height"] += (
                        overflow["height"]
                    )

                else:
                    pages.insert(
                        -1,
                        self._make_page(
                            [overflow],
                            content_height_mm,
                        ),
                    )

                if not pages[-1]["items"]:
                    pages.pop()

        # ---------------------------------------------------------
        # Build result.
        # ---------------------------------------------------------

        result = []
        running_total = 0.0

        for index, page in enumerate(
            pages,
            start=1,
        ):
            page_lines = [
                item["record"]
                for item in page["items"]
            ]

            subtotal = sum(
                item["amount"]
                for item in page["items"]
            )

            running_total += subtotal

            is_last = index == len(pages)

            page_capacity = (
                last_page_content_height_mm
                if is_last
                else content_height_mm
            )

            result.append({
                "lines": page_lines,
                "subtotal": subtotal,
                "running_total": running_total,
                "page": index,
                "page_number": index,
                "is_last": is_last,

                "content_height": page_capacity,

                "used_height": page["used_height"],

                "remaining_height": max(
                    0.0,
                    page_capacity
                    - page["used_height"],
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
    def _combined_text(
        self,
        record,
        fields,
        separator,
    ):
        values = []

        for field_name in fields:
            value = self._get_field_value(
                record,
                field_name,
            )

            if value is None or value is False:
                continue

            value = self._html_to_text(value)
            value = str(value).strip()

            if value:
                values.append(value)

        return separator.join(values)

    @api.model
    def _get_field_value(
        self,
        record,
        field_name,
    ):
        value = record

        for part in field_name.split("."):

            if value is None or value is False:
                return False

            if (
                hasattr(value, "_name")
                and hasattr(value, part)
            ):
                value = getattr(value, part)

            else:
                return False

        return value

    @api.model
    def _html_to_text(self, value):
        if not isinstance(value, str) or "<" not in value:
            return value

        value = re.sub(
            r"(?i)<br\s*/?>",
            "\n",
            value,
        )

        value = re.sub(
            r"(?i)</p\s*>",
            "\n",
            value,
        )

        value = re.sub(
            r"(?i)</div\s*>",
            "\n",
            value,
        )

        value = re.sub(
            r"<[^>]+>",
            "",
            value,
        )

        value = re.sub(
            r"\s+\n",
            "\n",
            value,
        )

        return value

    @api.model
    def _estimate_text_lines(
        self,
        text,
        chars_per_line,
        min_lines=1,
    ):
        if not text:
            return max(
                1,
                min_lines,
            )

        total = 0

        for paragraph in (
            str(text).splitlines()
            or [""]
        ):
            paragraph = paragraph.strip()

            if not paragraph:
                total += 1
                continue

            total += max(
                1,
                math.ceil(
                    len(paragraph)
                    / chars_per_line
                ),
            )

        return max(
            min_lines,
            total,
        )

    @api.model
    def _make_page(
        self,
        items,
        capacity,
    ):
        return {
            "items": list(items),
            "used_height": sum(
                item["height"]
                for item in items
            ),
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