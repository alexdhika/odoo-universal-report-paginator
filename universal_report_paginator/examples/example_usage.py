# Example only; this file is not imported by Odoo.

def get_pages(self):
    return self.env["universal.report.paginator"].paginate(
        lines=self.invoice_line_ids,
        dynamic_fields=["name", "note"],
        dynamic_field_width=300,
        content_height=620,
        last_page_content_height=450,
        font_size=10,
        line_height=14,
        padding_height=6,
        subtotal_getter=lambda line: line.price_subtotal,
    )
