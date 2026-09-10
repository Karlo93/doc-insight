"""Regenerate the committed extraction fixtures without network access."""

from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pypdfium2 as pdfium
from fixture_hr import PARAGRAPHS_HR
from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
FONT = ROOT / "scripts" / "fonts" / "fixture-sans.ttf"
ENGLISH = (
    "Alice Johnson visited London with David Miller. "
    "They met Professor Sarah Wilson at the British Museum. "
    "Their next journey will take them to Paris and Berlin."
)
CROATIAN = (
    "Marko Marić živi u Zagrebu i radi na Sveučilištu u Zagrebu. "
    "Ana Kovačević posjetila je Split i Dubrovnik. "
    "Ivan Horvat razgovarao je s Petrom Đurićem o Hrvatskoj. "
    "Škola čuva knjige o hrvatskoj povijesti i životu uz more."
)
PARAGRAPHS = [
    (
        "The observatory studies Saturn through a telescope on a quiet mountain. "
        "Astronomers record the bright rings and compare their shape each winter. "
        "A camera measures reflected sunlight while a second instrument measures "
        "temperature. The team waits for clear weather because thick clouds hide "
        "the planet. Each observation includes the date and the direction of the "
        "telescope. Students learn to distinguish a planet from a distant star. "
        "Saturn moves against the background stars as Earth travels around the Sun. "
        "The researchers check their measurements against earlier observations. "
        "They publish a chart showing changes in the visible angle of the rings. "
        "A patient observer can notice these changes without visiting space. "
        "Careful records matter more than a single beautiful photograph because "
        "the scientific question concerns motion over many months and years."
    ),
    (
        "The bakery prepares sourdough before sunrise using flour, water and salt. "
        "A living starter gives the bread its gentle sour taste and open texture. "
        "The baker feeds the starter every evening and checks its bubbles at dawn. "
        "Dough rests in covered bowls while natural fermentation produces gas. "
        "Several folds strengthen the dough without intensive mixing. A warm room "
        "shortens the resting period, so the baker watches the dough rather than "
        "trusting the clock alone. Round loaves rise in baskets dusted with flour. "
        "Steam in the oven keeps the surface flexible during the first minutes. "
        "The crust becomes brown after the steam escapes. Finished bread cools "
        "on wooden racks before slicing. Customers buy the loaves for lunch, "
        "and the remaining starter begins another batch for the following morning."
    ),
    (
        "The coral reef shelters colorful fish in a shallow tropical bay. "
        "Small coral animals build hard skeletons that slowly form the reef. "
        "Divers measure the water temperature at several marked locations. "
        "When the sea stays unusually warm, coral can lose the algae that feed it. "
        "This bleaching leaves pale patches visible in underwater photographs. "
        "Scientists compare photographs taken from exactly the same positions. "
        "They also count young fish hiding between branches of living coral. "
        "Fishing boats avoid the protected area during the breeding season. "
        "Local guides explain why anchors must never land on the fragile reef. "
        "Healthy coral protects the coast by reducing the force of incoming waves. "
        "The survey continues each summer so the community can see whether "
        "its conservation efforts help the damaged habitat recover over time."
    ),
    (
        "The railway connects a coastal harbor with a busy inland station. "
        "Electric trains carry commuters in the morning and return in the evening. "
        "A signaling system keeps enough distance between trains on the same track. "
        "Drivers receive permission before entering a section occupied by workers. "
        "Maintenance crews inspect the rails at night when passenger traffic stops. "
        "They measure wear around curves and replace damaged fasteners promptly. "
        "At the harbor, freight wagons receive containers unloaded from ships. "
        "Dispatchers schedule these slower trains between the passenger services. "
        "A published timetable shows expected arrivals at every intermediate stop. "
        "Passengers can change platforms using a sheltered pedestrian bridge. "
        "Reliable railway service reduces the number of cars on the coastal road. "
        "The city tracks delays monthly to identify bottlenecks before expanding service."
    ),
    (
        "The hospital pharmacy stores vaccines in monitored refrigerators. "
        "Each delivery arrives with a temperature record and a batch number. "
        "A pharmacist checks both before placing the boxes on labeled shelves. "
        "An alarm sounds if a refrigerator becomes warmer than its approved range. "
        "Staff transfer the stock to backup storage while engineers investigate. "
        "Nurses request the required doses before scheduled vaccination clinics. "
        "The pharmacy records which batches were supplied to each clinic that day. "
        "Older suitable stock is used first to reduce waste from expired doses. "
        "Patients receive information about expected effects and follow-up visits. "
        "The team practices its power-failure procedure every few months. "
        "These exercises reveal missing supplies and unclear responsibilities. "
        "A dependable cold chain protects the usefulness of vaccines throughout "
        "their journey from the manufacturer to the person receiving a dose."
    ),
    (
        "The orchard grows apples on a hillside with deep, well-drained soil. "
        "Farmers prune the trees in winter to admit sunlight into their branches. "
        "Bees visit the flowers in spring and carry pollen between neighboring trees. "
        "A small weather station records rainfall and warns of overnight frost. "
        "During dry weeks, drip irrigation supplies water close to the roots. "
        "Workers remove damaged fruit before disease spreads to healthy apples. "
        "They check sweetness and firmness to choose the best harvest date. "
        "Picked apples travel in shallow crates that prevent unnecessary bruising. "
        "The largest fruit goes to local markets while smaller apples become juice. "
        "Fallen leaves are composted away from the packing area. "
        "The orchard keeps annual records of yield, weather and pest damage. "
        "Those records help the farmer decide which varieties to plant next season."
    ),
    (
        "The wind farm generates electricity on an open plain near the coast. "
        "Tall turbines turn slowly as moving air pushes their carefully shaped blades. "
        "A controller adjusts the blade angle when wind speed changes. "
        "In a severe storm, the machines stop to avoid excessive mechanical loads. "
        "Technicians inspect bearings and electrical connections during planned visits. "
        "Sensors report vibration so unusual wear can be investigated early. "
        "An underground cable carries power to a nearby distribution station. "
        "Grid operators forecast production using local weather observations. "
        "A battery can store some electricity when demand is temporarily low. "
        "The project also measures noise near the closest houses. "
        "Bird surveys inform decisions about seasonal operating restrictions. "
        "Monthly reports compare actual output with the forecast and explain "
        "how maintenance and weather affected the amount of electricity delivered."
    ),
    (
        "The museum restores a medieval tapestry in a bright conservation room. "
        "Specialists examine the woven threads under magnification before cleaning. "
        "They identify fragile areas and record earlier repairs in detailed drawings. "
        "A gentle vacuum removes loose dust through a protective screen. "
        "New support fabric carries the weight of weakened sections during display. "
        "Conservators choose stitches that can be removed in a future treatment. "
        "They avoid strong light because old dyes may fade permanently. "
        "Humidity sensors help staff keep the exhibition room stable throughout winter. "
        "Visitors can read a short account of how the tapestry was made. "
        "Photographs taken before and after treatment show the repaired areas. "
        "The restoration does not attempt to make the ancient textile look new. "
        "Its purpose is to preserve the surviving material and make its history "
        "understandable without hiding the evidence of age and earlier use."
    ),
    (
        "The chess club teaches beginners how to protect their king. "
        "Players first learn the movement of each piece on an empty board. "
        "They then practice short games that begin with only a few pieces. "
        "The coach explains why controlling central squares creates useful choices. "
        "A knight can jump over other pieces, unlike a bishop or a rook. "
        "Students learn to check whether an apparent capture loses a stronger piece. "
        "They write their moves in notebooks and review mistakes after the game. "
        "Weekly puzzles introduce simple forks, pins and mating patterns. "
        "During friendly tournaments, clocks give both opponents equal thinking time. "
        "The club values patient analysis more than winning one quick game. "
        "Experienced members explain their reasoning aloud during practice sessions. "
        "This habit helps new players turn isolated rules into a coherent plan."
    ),
    (
        "The ceramics studio turns soft clay into durable bowls and cups. "
        "An artist centers a lump of clay on a rotating pottery wheel. "
        "Wet hands shape the walls gradually while keeping their thickness even. "
        "The vessel dries slowly under a loose cover to prevent cracks. "
        "A first firing changes the dry clay into a porous ceramic body. "
        "The artist then applies glaze with a brush or by dipping the object. "
        "A second firing melts the glaze into a smooth protective surface. "
        "Different minerals create different colors at the selected kiln temperature. "
        "Students label test tiles so successful recipes can be repeated later. "
        "Hot kilns remain closed until their contents have cooled safely. "
        "The studio recycles unfired scraps in separate containers. "
        "Finished pieces are checked for sharp edges before they reach the shop."
    ),
    (
        "The library preserves old newspapers in a climate-controlled archive. "
        "Readers request a particular issue using its publication date and title. "
        "Staff bring the fragile pages to a supported reading surface. "
        "Cotton covers protect the bindings while photographs document their condition. "
        "A scanning program creates digital copies for readers working from home. "
        "Operators capture each page with even lighting and check that no edges vanish. "
        "Text recognition makes many articles searchable by a name or a phrase. "
        "The original scans remain available when recognition makes a mistake. "
        "Catalog records distinguish local editions printed on the same day. "
        "Researchers compare advertisements and news reports to study everyday life. "
        "Digital access reduces repeated handling of the brittle paper originals. "
        "The archive maintains separate backup copies so a damaged disk "
        "does not erase the only record of a newspaper that no longer exists."
    ),
    (
        "The mountain rescue team trains to locate hikers after sunset. "
        "Volunteers study maps before practicing navigation on marked training routes. "
        "A radio operator records each team's position and expected check-in time. "
        "Search leaders divide the terrain into areas that can be covered safely. "
        "A trained dog follows a scent while another team checks nearby paths. "
        "Rescuers carry warm blankets, drinking water and basic medical supplies. "
        "They use a stretcher when an injured person cannot walk downhill. "
        "Weather forecasts guide decisions about exposed ridges and helicopter flights. "
        "The coordinator keeps the missing person's family informed of confirmed news. "
        "After each exercise, volunteers discuss what slowed their progress. "
        "Regular training makes communication clearer during a real emergency. "
        "The team reminds visitors to share their route and return time "
        "before setting out into unfamiliar mountain terrain."
    ),
]


def make_pdf(paragraphs: list[str]) -> FPDF:
    pdf = FPDF()
    pdf.set_creation_date(datetime(2026, 1, 1, tzinfo=UTC))
    pdf.add_font("fixture", fname=FONT)
    pdf.set_font("fixture", size=12)
    for index, paragraph in enumerate(paragraphs):
        if index % 2 == 0:
            pdf.add_page()
        pdf.multi_cell(0, 6, paragraph, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)
    return pdf


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    make_pdf([ENGLISH]).output(FIXTURES / "text_en.pdf")
    make_pdf([CROATIAN]).output(FIXTURES / "text_hr.pdf")
    make_pdf(PARAGRAPHS).output(FIXTURES / "text_long.pdf")
    make_pdf(PARAGRAPHS_HR).output(FIXTURES / "text_long_hr.pdf")
    with (
        pdfium.PdfDocument(FIXTURES / "text_en.pdf") as pdf,
        closing(pdf[0]) as page,
        closing(page.render(scale=200 / 72)) as bitmap,
        bitmap.to_pil() as image,
    ):
        image.save(FIXTURES / "scanned.png", optimize=True)
    mixed = make_pdf([ENGLISH])
    mixed.add_page()
    mixed.image(FIXTURES / "scanned.png", x=0, y=0, w=mixed.w, h=mixed.h)
    mixed.output(FIXTURES / "mixed.pdf")
    total = sum(path.stat().st_size for path in FIXTURES.iterdir())
    if total > 300_000:
        raise ValueError(f"Fixtures exceed 300 KB: {total} bytes")
    print(f"Generated six extraction fixtures: {total} bytes")


if __name__ == "__main__":
    main()
