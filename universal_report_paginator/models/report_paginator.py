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
        dynamic_field_width_mm,
        content_height_mm,
        last_page_content_height_mm=None,
        min_last_page_content_mm=30.0,
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
            Available detail height for normal pages.

        last_page_content_height_mm:
            Available detail height for the last page.
            If omitted, content_height_mm is used.

        min_last_page_content_mm:
            Minimum desired detail content height on the last page.
            The paginator will try to keep at least this amount of content
            on the last page when physically possible.

        font_size_mm:
            Font size in millimeters.

        line_height_mm:
            Height of one rendered text line in millimeters.
            If omitted, defaults to font_size_mm * 1.4.

        padding_height_mm:
            Extra fixed vertical height added to every detail row.

        subtotal_getter:
            Optional callable(record) -> numeric amount.

        separator:
            Separator used when combining multiple dynamic fields.

        chars_per_width_unit:
            Approximate character density per millimeter.

        min_lines:
            Minimum estimated number of text lines per record.

        Returns
        -------
        list[dict]
        """

        records = list(lines or [])
        fields = self._normalize_fields(dynamic_fields)

        # ---------------------------------------------------------
        # Validate parameters
        # ---------------------------------------------------------

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

        if last_page_content_height_mm > content_height_mm:
            raise ValueError(
                "last_page_content_height_mm cannot be greater "
                "than content_height_mm."
            )

        if min_last_page_content_mm < 0:
            raise ValueError(
                "min_last_page_content_mm must be zero or greater."
            )

        if min_last_page_content_mm > last_page_content_height_mm:
            raise ValueError(
                "min_last_page_content_mm cannot be greater "
                "than last_page_content_height_mm."
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

        if padding_height_mm < 0:
            raise ValueError(
                "padding_height_mm must be zero or greater."
            )

        if chars_per_width_unit <= 0:
            raise ValueError(
                "chars_per_width_unit must be greater than zero."
            )

        if min_lines < 1:
            raise ValueError(
                "min_lines must be at least 1."
            )

        # ---------------------------------------------------------
        # Empty input
        # ---------------------------------------------------------

        if not records:
            return []

        # ---------------------------------------------------------
        # Estimate characters per line
        # ---------------------------------------------------------

        chars_per_line = max(
            1,
            int(
                round(
                    dynamic_field_width_mm
                    * chars_per_width_unit
                )
            ),
        )

        # ---------------------------------------------------------
        # Calculate row information
        # ---------------------------------------------------------

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
                + padding_height_mm
            )

            height = max(
                float(line_height_mm),
                float(height),
            )

            # -----------------------------------------------------
            # A single row must be able to fit on a normal page.
            # -----------------------------------------------------

            if height > content_height_mm:
                raise ValueError(
                    "Satu record memiliki tinggi estimasi "
                    f"{height:.2f} mm, melebihi kapasitas halaman "
                    f"normal {content_height_mm:.2f} mm."
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
        # Total height
        # ---------------------------------------------------------

        total_height = sum(
            item["height"]
            for item in row_infos
        )

        # =========================================================
        # CASE 1
        #
        # Semua record muat di last page.
        #
        # Contoh:
        #
        # total = 140
        # last  = 160
        #
        # Maka:
        #
        # Page 1
        # used = 140
        # capacity = 160
        # is_last = True
        # =========================================================

        if total_height <= last_page_content_height_mm:
            pages = [
                self._make_page(
                    row_infos,
                    last_page_content_height_mm,
                )
            ]

        else:
            # =====================================================
            # CASE 2
            #
            # Content membutuhkan lebih dari satu halaman.
            #
            # Kita tentukan LAST PAGE terlebih dahulu dari belakang.
            #
            # Ini bagian penting.
            #
            # Misalnya:
            #
            # total = 208.2
            # last capacity = 160
            #
            # Dari belakang kita ambil record sebanyak mungkin:
            #
            # last page = 157.8
            #
            # Record berikutnya = 6.5
            #
            # 157.8 + 6.5 = 164.3
            #
            # Karena > 160, record 6.5 TIDAK boleh masuk last page.
            #
            # Maka record tersebut tetap berada di page sebelumnya.
            #
            # Hasil:
            #
            # Page 1 = 50.4
            # Page 2 = 157.8
            # =====================================================

            total_height = sum(
                item["height"]
                for item in row_infos
            )

            pages = []

            if total_height <= last_page_content_height_mm:
                pages = [
                    self._make_page(
                        row_infos,
                        last_page_content_height_mm,
                    )
                ]

            else:
                # Cari split terbaik:
                #
                # page 1 harus <= content_height_mm
                # page 2 harus <= last_page_content_height_mm
                #
                # Prioritas:
                # 1. Page 1 dibuat semaksimal mungkin.
                # 2. Page 2 tetap harus <= last_page_content_height_mm.

                best_split = None
                best_page1_height = -1.0

                running_height = 0.0

                for split_index in range(
                    1,
                    len(row_infos),
                ):
                    running_height += row_infos[
                        split_index - 1
                    ]["height"]

                    page1_height = running_height
                    page2_height = (
                        total_height
                        - page1_height
                    )

                    if page1_height > content_height_mm:
                        break

                    if page2_height > last_page_content_height_mm:
                        continue

                    # Page 2 harus punya isi minimum
                    if (
                        page2_height < min_last_page_content_mm
                        and split_index < len(row_infos)
                    ):
                        continue

                    # Ambil split yang membuat page 1
                    # paling penuh.
                    if page1_height > best_page1_height:
                        best_page1_height = page1_height
                        best_split = split_index

                if best_split is None:
                    raise ValueError(
                        "Tidak ditemukan pembagian halaman yang valid."
                    )

                prefix_items = row_infos[:best_split]
                last_items = row_infos[best_split:]

                # Prefix bisa saja lebih dari satu halaman.
                current_items = []
                current_height = 0.0

                for item in prefix_items:
                    item_height = item["height"]

                    if (
                        current_items
                        and current_height + item_height
                        > content_height_mm
                    ):
                        pages.append(
                            self._make_page(
                                current_items,
                                content_height_mm,
                            )
                        )

                        current_items = []
                        current_height = 0.0

                    current_items.append(item)
                    current_height += item_height

                if current_items:
                    pages.append(
                        self._make_page(
                            current_items,
                            content_height_mm,
                        )
                    )

                pages.append(
                    self._make_page(
                        last_items,
                        last_page_content_height_mm,
                    )
                )

        # ---------------------------------------------------------
        # Remove empty pages
        # ---------------------------------------------------------

        pages = [
            page
            for page in pages
            if page["items"]
        ]

        # ---------------------------------------------------------
        # Final safety validation
        # ---------------------------------------------------------

        for index, page in enumerate(
            pages,
            start=1,
        ):
            is_last = (
                index == len(pages)
            )

            capacity = (
                last_page_content_height_mm
                if is_last
                else content_height_mm
            )

            if page["used_height"] > capacity:
                raise ValueError(
                    f"Pagination menghasilkan page {index} "
                    f"dengan tinggi {page['used_height']:.2f} mm "
                    f"yang melebihi kapasitas "
                    f"{capacity:.2f} mm."
                )

        # ---------------------------------------------------------
        # Build result
        # ---------------------------------------------------------

        result = []
        running_total = 0.0

        total_pages = len(pages)

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

            is_last = (
                index == total_pages
            )

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