from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader

W, H = letter
FOREST = HexColor('#0F3C1F')
CREAM  = HexColor('#F7F4EB')
MUTED  = HexColor('#4A5750')
LOGO   = '/Users/craiglegault/duxbury-trading-post/public/images/logo.png'

CW, CH = W/2, H/2          # four cards per sheet, 4.25 x 5.5in

def card(c, ox, oy):
    c.saveState()
    c.translate(ox, oy)
    c.setFillColor(CREAM); c.rect(0, 0, CW, CH, stroke=0, fill=1)
    c.setStrokeColor(FOREST); c.setLineWidth(0.6); c.setDash(2, 3)
    c.rect(6, 6, CW-12, CH-12, stroke=1, fill=0); c.setDash()

    try:
        c.drawImage(ImageReader(LOGO), CW/2-36, CH-104, width=72, height=72,
                    mask='auto', preserveAspectRatio=True)
    except Exception:
        pass

    c.setFillColor(FOREST); c.setFont('Helvetica-Bold', 15)
    c.drawCentredString(CW/2, CH-124, 'DUXBURY TRADING POST')
    c.setFont('Helvetica', 8.5); c.setFillColor(MUTED)
    c.drawCentredString(CW/2, CH-139, 'Duxbury, Massachusetts')

    # NOTE: this insert deliberately does NOT advertise the website as a cheaper
    # place to buy. eBay prohibits "any action designed to complete or facilitate
    # a transaction outside of eBay" and the sharing of external URLs to lure
    # buyers off-platform. eBay is ~87% of revenue; an insert undercutting their
    # own prices is not worth the account risk. Buying collections is a different
    # transaction entirely and is not covered by that policy.
    c.setFillColor(FOREST)
    c.roundRect(CW/2-118, CH-196, 236, 42, 21, stroke=0, fill=1)
    c.setFillColor(CREAM); c.setFont('Helvetica-Bold', 17)
    c.drawCentredString(CW/2, CH-182, 'WE BUY COLLECTIONS')

    c.setFillColor(FOREST); c.setFont('Helvetica-Bold', 12)
    c.drawCentredString(CW/2, CH-224, 'Got cards to sell? We make offers.')
    c.setFillColor(MUTED); c.setFont('Helvetica', 9)
    c.drawCentredString(CW/2, CH-241, 'Singles, slabs, sealed product or a whole collection.')
    c.drawCentredString(CW/2, CH-254, 'Free, no-obligation offer in 1-2 business days.')

    c.setStrokeColor(HexColor('#DCD6C4')); c.setLineWidth(0.8)
    c.line(48, 96, CW-48, 96)

    c.setFillColor(FOREST); c.setFont('Helvetica-Bold', 10.5)
    c.drawCentredString(CW/2, 78, 'THANKS FOR YOUR ORDER')
    c.setFillColor(MUTED); c.setFont('Helvetica', 8.5)
    c.drawCentredString(CW/2, 63, 'Packed by hand in Duxbury, Massachusetts.')
    c.drawCentredString(CW/2, 51, 'Local pickup and in-person deals on the South Shore.')
    c.setFillColor(FOREST); c.setFont('Helvetica-Bold', 9)
    c.drawCentredString(CW/2, 33, '@duxburytradingpost   |   info@duxburytradingpost.com')
    c.restoreState()

c = canvas.Canvas('DTP-package-insert.pdf', pagesize=letter)
for ox, oy in ((0, CH), (CW, CH), (0, 0), (CW, 0)):
    card(c, ox, oy)
c.setStrokeColor(HexColor('#CCCCCC')); c.setLineWidth(0.4); c.setDash(1, 4)
c.line(CW, 0, CW, H); c.line(0, CH, W, CH)
c.showPage(); c.save()
print('wrote DTP-package-insert.pdf (4 per letter sheet, 4.25 x 5.5in)')
