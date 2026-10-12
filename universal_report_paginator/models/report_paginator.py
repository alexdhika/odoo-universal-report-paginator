
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
        records = list(lines or [])
        fields = self._normalize_fields(dynamic_fields)

        if dynamic_field_width_mm <= 0:
            raise ValueError("dynamic_field_width_mm must be greater than zero.")
        if content_height_mm <= 0:
            raise ValueError("content_height_mm must be greater than zero.")

        if last_page_content_height_mm is None:
            last_page_content_height_mm = content_height_mm

        if last_page_content_height_mm <= 0:
            raise ValueError(
                "last_page_content_height_mm must be greater than zero."
            )
        if last_page_content_height_mm > content_height_mm:
            raise ValueError(
                "last_page_content_height_mm cannot exceed content_height_mm."
            )
        if min_last_page_content_mm < 0:
            raise ValueError("min_last_page_content_mm must be zero or greater.")
        if min_last_page_content_mm > last_page_content_height_mm:
            raise ValueError(
                "min_last_page_content_mm cannot exceed "
                "last_page_content_height_mm."
            )
        if font_size_mm <= 0:
            raise ValueError("font_size_mm must be greater than zero.")

        if line_height_mm is None:
            line_height_mm = font_size_mm * 1.4

        if line_height_mm <= 0:
            raise ValueError("line_height_mm must be greater than zero.")
        if padding_height_mm < 0:
            raise ValueError("padding_height_mm must be zero or greater.")
        if chars_per_width_unit <= 0:
            raise ValueError("chars_per_width_unit must be greater than zero.")
        if min_lines < 1:
            raise ValueError("min_lines must be at least 1.")

        if not records:
            return []

        chars_per_line = max(
            1,
            int(round(dynamic_field_width_mm * chars_per_width_unit)),
        )

        row_infos = []

        for record in records:
            text = self._combined_text(record, fields, separator)
            estimated_lines = self._estimate_text_lines(
                text,
                chars_per_line,
                min_lines,
            )

            height = max(
                float(line_height_mm),
                float(estimated_lines * line_height_mm + padding_height_mm),
            )

            if height > content_height_mm:
                raise ValueError(
                    f"Record memiliki tinggi estimasi {height:.2f} mm, "
                    f"melebihi kapasitas halaman normal "
                    f"{content_height_mm:.2f} mm."
                )

            amount = subtotal_getter(record) if subtotal_getter else 0.0

            row_infos.append({
                "record": record,
                "height": height,
                "amount": self._to_number(amount),
                "text": text,
                "estimated_lines": estimated_lines,
            })

        count = len(row_infos)
        heights = [item["height"] for item in row_infos]

        # Prefix sum untuk menghitung tinggi rentang record.
        prefix = [0.0]
        for height in heights:
            prefix.append(prefix[-1] + height)

        # DP: jumlah minimum halaman normal untuk setiap prefix.
        dp = [float("inf")] * (count + 1)
        previous = [None] * (count + 1)
        dp[0] = 0

        for end in range(1, count + 1):
            for start in range(end - 1, -1, -1):
                segment_height = prefix[end] - prefix[start]

                if segment_height > content_height_mm:
                    break

                if dp[start] + 1 < dp[end]:
                    dp[end] = dp[start] + 1
                    previous[end] = start

        # Coba semua kemungkinan awal halaman terakhir.
        candidates = []

        for split in range(count):
            last_height = prefix[count] - prefix[split]

            if last_height > last_page_content_height_mm:
                continue

            if dp[split] == float("inf"):
                continue

            # Rekonstruksi pembagian halaman normal.
            segments = []
            cursor = split

            while cursor > 0:
                start = previous[cursor]

                if start is None:
                    segments = []
                    break

                segments.append((start, cursor))
                cursor = start

            segments.reverse()

            if split > 0 and not segments:
                continue

            candidates.append({
                "split": split,
                "last_height": last_height,
                "page_count": int(dp[split]) + 1,
                "segments": segments,
                "meets_minimum": (
                    last_height >= min_last_page_content_mm
                ),
            })

        if not candidates:
            raise ValueError(
                "Tidak ditemukan pembagian halaman yang valid. "
                "Periksa kapasitas halaman normal dan halaman terakhir."
            )

        # Prioritas pertama: jumlah halaman paling sedikit.
        minimum_pages = min(
            candidate["page_count"]
            for candidate in candidates
        )

        candidates = [
            candidate
            for candidate in candidates
            if candidate["page_count"] == minimum_pages
        ]

        # Prioritas kedua: memenuhi minimum isi halaman terakhir.
        eligible = [
            candidate
            for candidate in candidates
            if candidate["meets_minimum"]
        ]

        if eligible:
            candidates = eligible

        # Prioritas ketiga: minimalkan isi halaman terakhir
        # agar record sebanyak mungkin tetap di halaman sebelumnya.
        best = min(
            candidates,
            key=lambda candidate: candidate["last_height"],
        )

        pages = []

        for start, end in best["segments"]:
            pages.append(
                self._make_page(
                    row_infos[start:end],
                    content_height_mm,
                )
            )

        pages.append(
            self._make_page(
                row_infos[best["split"]:],
                last_page_content_height_mm,
            )
        )

        pages = [page for page in pages if page["items"]]

        # Validasi kapasitas seluruh halaman.
        for index, page in enumerate(pages):
            capacity = (
                last_page_content_height_mm
                if index == len(pages) - 1
                else content_height_mm
            )

            if page["used_height"] > capacity + 1e-9:
                raise ValueError(
                    f"Page {index + 1} memiliki tinggi "
                    f"{page['used_height']:.2f} mm, melebihi "
                    f"kapasitas {capacity:.2f} mm."
                )

        # Susun hasil dan subtotal.
        result = []
        running_total = 0.0
        total_pages = len(pages)

        for index, page in enumerate(pages, start=1):
            page_lines = [
                item["record"]
                for item in page["items"]
            ]

            subtotal = sum(
                item["amount"]
                for item in page["items"]
            )

            running_total += subtotal
            is_last = index == total_pages

            capacity = (
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
                "content_height": capacity,
                "used_height": page["used_height"],
                "remaining_height": max(
                    0.0,
                    capacity - page["used_height"],
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
            else:
                total += max(
                    1,
                    math.ceil(len(paragraph) / chars_per_line),
                )

        return max(min_lines, total)

    @api.model
    def _make_page(self, items, capacity):
        return {
            "items": list(items),
            "used_height": sum(
                item["height"] for item in items
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
