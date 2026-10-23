from openpyxl import Workbook
from reportlab.pdfgen import canvas
from phosphate.reports import get_daily_pipe_report

def export_pipe_report_pdf(filepath='pipe_report.pdf', date=None, shift=None):
    data = get_daily_pipe_report(date, shift)
    c = canvas.Canvas(filepath)
    c.drawString(80, 800, "Pipe Phosphate Daily Report")
    y = 770

    for entry in data:
        text = (
            f"{entry.date:%Y-%m-%d} | "
            f"{entry.joint_number.joint_number if entry.joint_number else '—'} | "
            f"BJO: {entry.bjo.bjo if entry.bjo else '—'} | "
            f"Shift: {entry.shift.name if entry.shift else '—'} | "
            f"Tally: {entry.tally or 00.00} | "
            f"{'Completed' if entry.is_completed else 'Not complete yet'}"
        )
        c.drawString(80, y, text)
        y -= 20
        if y < 50:
            c.showPage()
            y = 800

    c.save()

def export_pipe_report_excel(filepath='pipe_report.xlsx', date=None, shift=None):
    data = get_daily_pipe_report(date, shift)
    wb = Workbook()
    ws = wb.active
    ws.title = "Pipe Report"

    ws.append(['Date', 'Joint Number', 'BJO', 'Shift', 'Operator', 'Tally', 'Completed'])

    for entry in data:
        ws.append([
            entry.date.strftime('%Y-%m-%d') if entry.date else '',
            entry.joint_number.joint_number if entry.joint_number else '',
            entry.bjo.bjo if entry.bjo else '',
            entry.shift.name if entry.shift else '',
            entry.operator.name if entry.operator else '',
            entry.tally or 0,
            'Completed' if entry.is_completed else 'Not complete yet'
        ])

    wb.save(filepath)
