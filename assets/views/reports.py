"""
Tax + analytics report views. Each accepts ``?format=pdf`` to download
a ReportLab-generated PDF; otherwise an HTML preview is rendered (with
its own "Download PDF" button that re-issues the request with
``format=pdf``).
"""

from datetime import date as _date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render

from ._helpers import _parse_iso_date, _querystring_for


@login_required
def reports_index_view(request):
    """Landing page: pick a tax-report time frame, or jump to analytics report."""
    from ..reports import available_tax_years

    years = available_tax_years(request.user)
    today = _date.today()
    # Always offer the current year and the previous year as quick presets,
    # even if the user has no sells in them yet — they may run the report
    # before any have been entered.
    quick_years = sorted(
        {today.year, today.year - 1, *years}, reverse=True,
    )

    return render(request, "assets/reports_index.html", {
        "quick_years": quick_years,
        "today": today,
    })


@login_required
def tax_report_view(request):
    """
    Tax report. Accepts ``?year=YYYY`` OR ``?start=YYYY-MM-DD&end=YYYY-MM-DD``.
    Add ``?format=pdf`` to download the PDF; otherwise an HTML preview is
    rendered (which has its own "Download PDF" button that re-issues the
    request with format=pdf).
    """
    from ..pdf import render_tax_report_pdf
    from ..reports import build_tax_report

    year_raw = request.GET.get("year")
    start_raw = request.GET.get("start")
    end_raw = request.GET.get("end")
    fmt = request.GET.get("format", "html")

    try:
        year = int(year_raw) if year_raw else None
    except ValueError:
        year = None
    start = _parse_iso_date(start_raw)
    end = _parse_iso_date(end_raw)

    if year is None and (start is None or end is None):
        messages.error(
            request,
            "Pick a tax year or a custom start + end date to generate a report.",
        )
        return redirect("reports")

    if year is None and start > end:
        messages.error(request, "End date must be on or after start date.")
        return redirect("reports")

    try:
        report = build_tax_report(request.user, year=year, start=start, end=end)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect("reports")

    if fmt == "pdf":
        pdf = render_tax_report_pdf(report)
        if year is not None:
            fname = f"folio-tax-report-{year}.pdf"
        else:
            fname = f"folio-tax-report-{start.isoformat()}-to-{end.isoformat()}.pdf"
        resp = HttpResponse(pdf.getvalue(), content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{fname}"'
        return resp

    # HTML preview: pass through everything the PDF uses so the user sees
    # exactly what the PDF will contain before downloading.
    return render(request, "assets/report_tax.html", {
        "report": report,
        "download_qs": _querystring_for(year, start, end, fmt="pdf"),
    })


@login_required
def analytics_report_view(request):
    """
    Analytics report. Snapshot of current portfolio state — no time frame
    needed (the data IS the present moment). Add ``?format=pdf`` to
    download the PDF; otherwise the HTML preview is rendered.
    """
    from ..pdf import render_analytics_report_pdf
    from ..reports import build_analytics_report

    fmt = request.GET.get("format", "html")
    report = build_analytics_report(request.user)

    if fmt == "pdf":
        pdf = render_analytics_report_pdf(report)
        fname = f"folio-analytics-report-{_date.today().isoformat()}.pdf"
        resp = HttpResponse(pdf.getvalue(), content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{fname}"'
        return resp

    return render(request, "assets/report_analytics.html", {
        "report": report,
    })
