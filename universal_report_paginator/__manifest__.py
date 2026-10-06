{
    "name": "Universal Report Paginator",
    "version": "19.0.1.0.0",
    "category": "Reporting",
    "summary": "Generic page-aware pagination engine for QWeb reports",
    "description": """
Universal Report Paginator
=========================
Provides a reusable pagination service for QWeb reports.

The paginator estimates row heights from one or more dynamic text fields,
their rendered column width, font size, and configured content heights.
It returns pages with lines, page subtotals, running totals, page numbers,
and last-page information.

It is intentionally business-model agnostic.
    """,
    "author": "Surya Semesta",
    "license": "LGPL-3",
    "depends": ["base"],
    "data": [],
    "installable": True,
    "application": False,
}
