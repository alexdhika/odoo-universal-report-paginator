# universal_report_paginator

Generic Odoo 19 QWeb report pagination service.

## Basic usage

```python
pages = self.env["universal.report.paginator"].paginate(
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
```

The returned value is a list of page dictionaries:

```python
[
    {
        "lines": recordset/list,
        "subtotal": 1000000.0,
        "running_total": 1000000.0,
        "page": 1,
        "page_number": 1,
        "is_last": False,
        "content_height": 620,
        "used_height": 560,
        "remaining_height": 60,
        "line_count": 5,
    },
    ...
]
```

## Important design choice

The paginator intentionally does not know anything about invoices,
purchase orders, sales orders, or other business models.

The calling report supplies:
- records
- dynamic fields
- dynamic column width
- normal detail height
- last-page detail height
- optional subtotal getter

This makes the service reusable across many modules.

## Multiple dynamic fields

```python
dynamic_fields=["name", "note"]
```

The fields are combined with a newline before line estimation.

Relational field paths are also supported:

```python
dynamic_fields=["product_id.display_name", "name"]
```

## HTML fields

Basic HTML tags, `<br>`, paragraph and div endings are converted to
plain text for approximate line estimation.

## Limitation

This is an estimation-based paginator. It does not inspect the final PDF
layout produced by wkhtmltopdf. For a controlled report template, tuning
`dynamic_field_width`, `font_size`, `line_height`, `padding_height`, and
the two content-height parameters can make pagination predictable.

The last-page capacity is reserved for signatures or other final-page
content.
