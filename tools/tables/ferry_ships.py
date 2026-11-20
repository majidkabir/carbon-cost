"""Builds the ferry crossings whose ships carbon-cost reads from the
operators' own documents (crossings-ships.json, for ferries/data), from

- POLSCA Baltic Ferries' timetables (Polferries and Unity Line, on
  unityline.eu; polsca-timetables.html and the PDFs it links,
  polsca-timetables-*.txt): each timetable has a column for each of its
  two ports ("ŚWINOUJŚCIE   YSTAD") and names the ferry of every
  departure; a ship with a departure in any of the listed timetables
  sails the crossing. A ship the page says is out of service
  ("the departures of the ferry Galileusz from 6.11.2026 until further
  notice have been cancelled") is left out;
- Bornholmslinjen's ferries page (bornholm-ferries.html): each ferry's
  crossing times ("Rønne - Køge", "Rønne-Ystad") and description ("på
  ruten mellem Rønne og Ystad") name its routes;
- Molslinjen's ferries page (mols-ferries.html), as Bornholmslinjen's: each
  ferry's crossing times ("Odden-Aarhus", "Odden-Ebeltoft");
- Destination Gotland's ferries page (gotland-ferries.html): each ferry's
  route ("M/S Drotten operates the Visby–Nynäshamn/Oskarshamn route"), its
  terminals on OpenStreetMap's lines (ferry-ships-osm.json). Gotland's port
  Visby is under the island derogation (Directive 2003/87/EC, Art.
  12(3-d)) for voyages to a port in Sweden until 31 December 2030;
- TT-Line's freight timetable (browser/ttline-timetable.txt: the site
  refuses scripted requests, so its text was read in Chrome): the ship of
  each departure, by its initials, which the page names ("PP = Peter
  Pan"). Its ships join POLSCA's on Świnoujście–Trelleborg;
- Stena Line Freight's route pages (stena-routes-<route>.html, linked
  from its route list): each page's heading names the ports ("Gdynia –
  Karlskrona") and its "Vessels" section the ships;
- Finnlines' route pages (finnlines-schedules-<route>.html, linked from its
  freight schedules page): the heading and "Ferries on the route"; for a
  route whose page has no such section, its master schedule
  (finnlines-schedules-*master-schedule*.txt: "Travemünde – Helsinki ...
  Finnstar/ Finnmaid/ Finnlady 7/7"). A route with a call on the way
  (Kapellskär–Långnäs–Naantali) isn't built;
- Irish Ferries Freight's route pages (irishferries-routes-<route>.html,
  linked from its home page): the ports in the page's address, the ships
  and their IMO numbers in its vessel specifications;
- P&O Freight's route pages (po-routes-<route>-freight.html, linked from
  its routes page): the ports in the page's address, the ships in its "Our
  Fleet" section (IMO numbers where it gives them); when its sailing tables
  name ships ("13:40 Pioneer"), only those;
- DFDS's freight route pages (dfds-routes-<route>.html, linked from its
  routes page) and their timetables (dfds-routes-<route>.json, DFDS's API
  for the 28 days from the fetch): the page's two terminals, the ship and
  its IMO number of each departure;
- Tallink's freight timetables and fleet page (tallink-fleet.html): each
  route's heading ("Tallinn-Helsinki") and its ships; Eckerö Line's cargo
  page (eckero-cargo.html): its ships' crossings, as its cargo CO2 figures
  name them ("M/S Finbo Cargo (Helsinki, Vuosaari – Tallinn, Muuga)");
- Color Line's routes page (colorline-routes.html): each route's ships ("The
  route Kiel – Oslo is operated by Color Magic and Color Fantasy");
- Fjord Line's ships page (fjordline-ships.html, its Markdown): a ship it
  puts between two ports ("Fjord FSTR ... between Hirtshals and
  Kristiansand");
- the Port of Helsinki's page on its Katajanokka terminal
  (helsinki-katajanokka.html): Viking Line's regular connections and their
  ships ("Viking XPRS to Tallinn");
- Wasaline's cargo page (wasaline-cargo.html): its route ("between Vaasa in
  Finland and Umeå in Sweden") and its ship;
- one operator's ships join another's on the same two ports (TT-Line's and
  Stena Line's on Rostock–Trelleborg);
- OpenStreetMap (polsca-osm.json, dk-bornholm-osm.json, ttline-osm.json):
  the terminals, as polsca.py and dk_bornholm.py place them; TT-Line's
  Travemünde and Rostock at the far end of its lines from Trelleborg;
  Stena Line's and Finnlines' (ferry-ships-osm.json, -osm-2, -3, -4: OSM_BOXES) at the
  ends of the ferry line whose name has both ports (the operator's, when it
  has one), each port at the end nearest its town (PORTS); a line trucks may take (hgv=yes) counts though cars may not. A
  route with no such line isn't built: no route can take it;
- Commission Implementing Decision (EU) 2023/2895, Annex I
  (ets-islands-2023-2895.html): Bornholm's port Rønne and Gotland's Visby are
  under the island derogation (Directive 2003/87/EC, Art. 12(3-d)) for
  voyages to a port in their country until 31 December 2030;
- the EU MRV reports' ship lists (ferries/data/mrv-ships-<year>.json): a
  ship's IMO number, by its name (letters such as Å read as A), when one
  ship of that name is listed.

- for the island ports of the Decision in Spain (Ibiza, Formentera,
  Menorca), Croatia (Rab's Mišnjak: Jadrolinija's ports are
  ets_islands.py's), Italy (Elba, Ischia, Procida, Capri, La Maddalena, San Pietro,
  Lipari, Pantelleria, Lampedusa, Favignana, Ustica, Ponza) and Malta
  (Gozo) that PORTS has (ISLANDS), and of Greece (GREECE, by the English
  names of OpenStreetMap's lines in gr-ferries-osm.json), the OpenStreetMap
  ferry lines between one of them and another port of its Member State: the
  ships aren't named; the derogation is in force until 31 December 2030;
- for ports outside the EU and the EEA (the UK, the Isle of Man, the
  Channel Islands, the Faroes; Morocco, Algeria, Tunisia, Albania,
  Montenegro and Turkey), the OpenStreetMap ferry lines between one of
  them and a port in PORTS: the ships aren't named, but the ports'
  countries give the share of the EU ETS (Directive 2003/87/EC, Art.
  3ga(1)): 50% with a port in the EU or the EEA, none between two outside.

Usage: python3 ferry_ships.py <fetched dir> <out dir>
       python3 ferry_ships.py --osm-query   (the Overpass queries for sources.json)
"""
import glob, html, json, os, re, sys, unicodedata

import dk_bornholm
import polsca
from ets_islands import DECISION, FROM, UNTIL, text
from ferry_osm import lines_of, port_places

HERE = os.path.dirname(os.path.abspath(__file__))
MRV = os.path.join(HERE, "..", "..", "ferries", "data")
COUNTRY = {"Świnoujście": "PL", "Gdańsk": "PL", "Ystad": "SE", "Trelleborg": "SE", "Nynäshamn": "SE", "Karlshamn": "SE",
           "Travemünde": "DE", "Rostock": "DE",
           "Rønne": "DK", "Køge": "DK", "Sassnitz": "DE"}
# (id, ports): the crossings, by the ports' names in polsca.PORTS and dk_bornholm.PORTS.
POLSCA = [("swinoujscie-ystad", ("Świnoujście", "Ystad")), ("swinoujscie-trelleborg", ("Świnoujście", "Trelleborg")),
          ("gdansk-nynashamn", ("Gdańsk", "Nynäshamn")), ("gdansk-karlshamn", ("Gdańsk", "Karlshamn"))]
BORNHOLM = [("koge-ronne", ("Køge", "Rønne")), ("ystad-ronne", ("Ystad", "Rønne")), ("sassnitz-ronne", ("Sassnitz", "Rønne"))]
# TT-Line: (id, ports, the timetable's route); its ports on its own lines.
TTLINE = [("travemunde-trelleborg", ("Travemünde", "Trelleborg"), "Travemünde - Trelleborg"),
          ("rostock-trelleborg", ("Rostock", "Trelleborg"), "Rostock - Trelleborg"),
          ("swinoujscie-trelleborg", ("Świnoujście", "Trelleborg"), "Świnoujście - Trelleborg")]
TTLINE_PORTS = {"Trelleborg": ("place", "Trelleborg"), "Travemünde": ("end", "Travemünde (D) – Trelleborg (SE)", "Trelleborg"),
                "Rostock": ("end", "Rostock (D) - Trelleborg (SE)", "Trelleborg")}
TTLINE_FILE = os.path.join(HERE, "browser", "ttline-timetable.txt")
# The ports: country, the names OpenStreetMap's lines give them, and where
# the town is (lat, lon, to tell a line's ends apart: the end nearest it,
# within 40 km).
PORTS = {
    # Stena Line's and Finnlines' routes
    "Belfast": ("GB", ["Belfast"], (54.60, -5.93)), "Cairnryan": ("GB", ["Cairnryan"], (54.97, -5.02)),
    "Heysham": ("GB", ["Heysham"], (54.03, -2.91)), "Liverpool": ("GB", ["Liverpool", "Birkenhead"], (53.41, -3.00)),
    "Dublin": ("IE", ["Dublin"], (53.35, -6.26)), "Holyhead": ("GB", ["Holyhead"], (53.31, -4.63)),
    "Gdynia": ("PL", ["Gdynia"], (54.52, 18.53)), "Karlskrona": ("SE", ["Karlskrona"], (56.16, 15.59)),
    "Gothenburg": ("SE", ["Göteborg", "Gothenburg"], (57.71, 11.97)), "Kiel": ("DE", ["Kiel"], (54.32, 10.13)),
    "Frederikshavn": ("DK", ["Frederikshavn"], (57.44, 10.54)),
    "Hoek van Holland": ("NL", ["Hoek van Holland", "Hook of Holland"], (51.98, 4.13)), "Harwich": ("GB", ["Harwich"], (51.94, 1.28)),
    "Immingham": ("GB", ["Immingham", "Killingholme"], (53.62, -0.22)), "Ventspils": ("LV", ["Ventspils"], (57.39, 21.56)),
    "Rosslare": ("IE", ["Rosslare"], (52.25, -6.34)), "Fishguard": ("GB", ["Fishguard"], (51.99, -4.98)),
    "Rotterdam": ("NL", ["Rotterdam", "Europoort", "Maasvlakte", "Vlaardingen"], (51.92, 4.30)),
    "Liepāja": ("LV", ["Liepāja", "Liepaja"], (56.51, 21.01)), "Malmö": ("SE", ["Malmö"], (55.60, 13.00)),
    "Helsinki": ("FI", ["Helsinki"], (60.17, 24.94)), "Nynäshamn": ("SE", ["Nynäshamn"], (58.90, 17.95)),
    "Travemünde": ("DE", ["Travemünde"], (53.96, 10.87)), "Rostock": ("DE", ["Rostock"], (54.09, 12.13)),
    "Trelleborg": ("SE", ["Trelleborg"], (55.38, 13.16)), "Świnoujście": ("PL", ["Świnoujście"], (53.91, 14.25)),
    # DFDS's routes
    "Klaipėda": ("LT", ["Klaipėda", "Klaipeda"], (55.71, 21.13)), "Karlshamn": ("SE", ["Karlshamn"], (56.17, 14.86)),
    "Fredericia": ("DK", ["Fredericia"], (55.57, 9.75)), "Køge": ("DK", ["Køge"], (55.46, 12.18)),
    "Paldiski": ("EE", ["Paldiski"], (59.35, 24.05)), "Kapellskär": ("SE", ["Kapellskär"], (59.72, 19.07)),
    "Muuga": ("EE", ["Muuga"], (59.50, 24.96)), "Tallinn": ("EE", ["Tallinn"], (59.44, 24.77)),
    "Stockholm": ("SE", ["Stockholm", "Värtahamnen"], (59.33, 18.07)),
    "Vaasa": ("FI", ["Vaasa", "Vasa"], (63.10, 21.62)), "Umeå": ("SE", ["Umeå", "Holmsund"], (63.83, 20.26)),
    "Odden": ("DK", ["Odden", "Sjællands Odde"], (55.97, 11.37)), "Aarhus": ("DK", ["Aarhus", "Århus"], (56.15, 10.21)),
    "Ebeltoft": ("DK", ["Ebeltoft"], (56.19, 10.68)),
    "Larvik": ("NO", ["Larvik"], (59.05, 10.03)), "Kristiansand": ("NO", ["Kristiansand"], (58.15, 8.00)),
    "Oslo": ("NO", ["Oslo"], (59.91, 10.75)), "Sandefjord": ("NO", ["Sandefjord"], (59.13, 10.22)),
    "Strömstad": ("SE", ["Strömstad", "Strømstad"], (58.94, 11.17)), "Turku": ("FI", ["Turku", "Åbo"], (60.45, 22.27)), "Vuosaari": ("FI", ["Vuosaari"], (60.21, 25.19)), "Ghent": ("BE", ["Gent", "Ghent"], (51.05, 3.72)),
    "Brevik": ("NO", ["Brevik"], (59.05, 9.70)), "Fredrikstad": ("NO", ["Fredrikstad"], (59.22, 10.93)),
    "Cuxhaven": ("DE", ["Cuxhaven"], (53.87, 8.70)), "Visby": ("SE", ["Visby"], (57.64, 18.29)),
    "Oskarshamn": ("SE", ["Oskarshamn"], (57.26, 16.45)),
    # Island ports under the derogation (ISLANDS) and the ports across from them
    "Eivissa": ("ES", ["Eivissa", "Ibiza"], (38.91, 1.44)), "Sant Antoni": ("ES", ["Sant Antoni de Portmany", "Sant Antoni", "San Antonio"], (38.98, 1.30)),
    "La Savina": ("ES", ["La Savina", "Formentera"], (38.73, 1.42)), "Ciutadella": ("ES", ["Ciutadella", "Ciudadela", "Ciutadella de Menorca"], (40.00, 3.84)),
    "Maó": ("ES", ["Maó", "Mahón", "Mahon", "Maó-Mahón"], (39.89, 4.27)), "Dénia": ("ES", ["Dénia", "Denia"], (38.84, 0.11)),
    "Palma": ("ES", ["Palma", "Palma de Mallorca"], (39.57, 2.65)), "Alcúdia": ("ES", ["Alcúdia", "Alcudia"], (39.85, 3.12)),
    "Portoferraio": ("IT", ["Portoferraio"], (42.81, 10.32)), "Rio Marina": ("IT", ["Rio Marina"], (42.81, 10.43)),
    "Cavo": ("IT", ["Cavo"], (42.86, 10.42)), "Piombino": ("IT", ["Piombino"], (42.93, 10.53)),
    "Ischia": ("IT", ["Ischia", "Ischia Porto", "Porto d'Ischia"], (40.74, 13.94)), "Casamicciola": ("IT", ["Casamicciola", "Casamicciola Terme"], (40.75, 13.91)),
    "Forio": ("IT", ["Forio"], (40.74, 13.86)), "Procida": ("IT", ["Procida"], (40.76, 14.03)), "Capri": ("IT", ["Capri"], (40.56, 14.24)),
    "Napoli": ("IT", ["Napoli", "Naples"], (40.84, 14.25)), "Pozzuoli": ("IT", ["Pozzuoli"], (40.82, 14.12)),
    "La Maddalena": ("IT", ["La Maddalena"], (41.21, 9.41)), "Palau": ("IT", ["Palau"], (41.18, 9.38)),
    "Carloforte": ("IT", ["Carloforte"], (39.14, 8.31)), "Portovesme": ("IT", ["Portovesme"], (39.20, 8.39)), "Calasetta": ("IT", ["Calasetta"], (39.11, 8.37)),
    "Lipari": ("IT", ["Lipari"], (38.47, 14.96)), "Milazzo": ("IT", ["Milazzo"], (38.22, 15.24)),
    "Pantelleria": ("IT", ["Pantelleria"], (36.83, 11.94)), "Lampedusa": ("IT", ["Lampedusa"], (35.50, 12.61)),
    "Porto Empedocle": ("IT", ["Porto Empedocle"], (37.29, 13.53)), "Favignana": ("IT", ["Favignana"], (37.93, 12.33)),
    "Isola del Giglio": ("IT", ["Isola del Giglio", "Giglio Porto"], (42.36, 10.92)), "Porto Santo Stefano": ("IT", ["Porto Santo Stefano"], (42.44, 11.12)),
    "Ustica": ("IT", ["Ustica"], (38.71, 13.19)), "Ponza": ("IT", ["Ponza"], (40.90, 12.96)), "Formia": ("IT", ["Formia"], (41.26, 13.61)),
    "Mišnjak": ("HR", ["Mišnjak"], (44.71, 14.86)), "Stinica": ("HR", ["Stinica"], (44.72, 14.89)),
    "Mġarr": ("MT", ["Mġarr", "Mgarr", "Imġarr"], (36.02, 14.30)), "Ċirkewwa": ("MT", ["Ċirkewwa", "Cirkewwa"], (35.99, 14.33)), "Vilagarcía": ("ES", ["Vilagarcía", "Vilagarcia", "Vilagarcía de Arousa"], (42.60, -8.77)),
    # ports outside the EU and the EEA, and the ports across from them
    "Dover": ("GB", ["Dover", "Douvres"], (51.12, 1.33)), "Newhaven": ("GB", ["Newhaven"], (50.79, 0.05)),
    "Portsmouth": ("GB", ["Portsmouth"], (50.81, -1.09)), "Poole": ("GB", ["Poole"], (50.71, -1.98)),
    "Plymouth": ("GB", ["Plymouth"], (50.37, -4.14)), "Hull": ("GB", ["Hull", "Kingston upon Hull"], (53.74, -0.33)),
    "Newcastle": ("GB", ["Newcastle", "North Shields"], (55.00, -1.50)), "Tilbury": ("GB", ["Tilbury"], (51.46, 0.36)),
    "Purfleet": ("GB", ["Purfleet"], (51.48, 0.24)), "Teesport": ("GB", ["Teesport", "Middlesbrough"], (54.60, -1.16)),
    "Felixstowe": ("GB", ["Felixstowe"], (51.96, 1.33)), "Pembroke": ("GB", ["Pembroke", "Pembroke Dock"], (51.69, -4.94)),
    "Larne": ("GB", ["Larne"], (54.85, -5.82)), "Aberdeen": ("GB", ["Aberdeen"], (57.14, -2.09)),
    "Lerwick": ("GB", ["Lerwick"], (60.15, -1.14)), "Kirkwall": ("GB", ["Kirkwall"], (58.98, -2.96)),
    "Douglas": ("IM", ["Douglas"], (54.15, -4.48)), "St Helier": ("JE", ["St Helier", "Saint Helier"], (49.18, -2.11)),
    "St Peter Port": ("GG", ["St Peter Port", "Saint Peter Port"], (49.46, -2.53)),
    "Tórshavn": ("FO", ["Tórshavn", "Torshavn"], (62.01, -6.77)), "Cork": ("IE", ["Cork", "Ringaskiddy"], (51.83, -8.32)),
    "Calais": ("FR", ["Calais"], (50.96, 1.86)), "Dunkerque": ("FR", ["Dunkerque", "Dunkirk", "Loon-Plage"], (51.03, 2.30)),
    "Dieppe": ("FR", ["Dieppe"], (49.93, 1.08)), "Le Havre": ("FR", ["Le Havre"], (49.49, 0.11)),
    "Caen": ("FR", ["Ouistreham", "Caen"], (49.28, -0.25)), "Cherbourg": ("FR", ["Cherbourg", "Cherbourg-en-Cotentin"], (49.64, -1.62)),
    "Saint-Malo": ("FR", ["Saint-Malo", "St Malo", "St-Malo"], (48.65, -2.01)), "Roscoff": ("FR", ["Roscoff"], (48.72, -3.97)),
    "IJmuiden": ("NL", ["IJmuiden", "Amsterdam"], (52.46, 4.61)), "Zeebrugge": ("BE", ["Zeebrugge"], (51.33, 3.20)),
    "Santander": ("ES", ["Santander"], (43.46, -3.80)), "Bilbao": ("ES", ["Bilbao", "Santurtzi"], (43.35, -3.04)),
    "Esbjerg": ("DK", ["Esbjerg"], (55.47, 8.44)), "Hirtshals": ("DK", ["Hirtshals"], (57.59, 9.96)),
    "Seyðisfjörður": ("IS", ["Seyðisfjörður", "Seydisfjordur"], (65.26, -14.01)),
    # the Mediterranean: Morocco, Algeria, Tunisia, Albania, Montenegro and
    # Turkey, and the EU ports across from them
    "Tanger Med": ("MA", ["Tanger Med", "Tanger-Med", "Tangier Med", "Ksar Sghir"], (35.89, -5.50)),
    "Tanger": ("MA", ["Tanger", "Tangier", "Tánger", "Tangeri", "Tanger Ville"], (35.78, -5.81)),
    "Nador": ("MA", ["Nador", "Beni Ansar", "Beni Enzar"], (35.20, -2.93)), "Al Hoceima": ("MA", ["Al Hoceima"], (35.25, -3.93)),
    "Alger": ("DZ", ["Alger", "Algiers", "Algeri"], (36.77, 3.06)), "Oran": ("DZ", ["Oran"], (35.70, -0.64)),
    "Béjaïa": ("DZ", ["Béjaïa", "Bejaia"], (36.75, 5.08)), "Skikda": ("DZ", ["Skikda"], (36.88, 6.91)),
    "Annaba": ("DZ", ["Annaba"], (36.90, 7.76)), "Mostaganem": ("DZ", ["Mostaganem"], (35.93, 0.09)),
    "Ghazaouet": ("DZ", ["Ghazaouet"], (35.10, -1.86)),
    "Tunis": ("TN", ["Tunis", "Tunisi", "La Goulette", "Halq al Wadi"], (36.81, 10.25)), "Zarzis": ("TN", ["Zarzis"], (33.50, 11.11)),
    "Durrës": ("AL", ["Durrës", "Durres", "Durazzo"], (41.31, 19.45)), "Vlorë": ("AL", ["Vlorë", "Vlora", "Valona"], (40.47, 19.49)),
    "Bar": ("ME", ["Bar"], (42.10, 19.09)),
    "Çeşme": ("TR", ["Çeşme", "Cesme"], (38.32, 26.30)), "Ayvalık": ("TR", ["Ayvalık", "Ayvalik"], (39.32, 26.69)),
    "Pendik": ("TR", ["Pendik"], (40.87, 29.25)), "Ambarlı": ("TR", ["Ambarlı", "Ambarli"], (40.97, 28.69)),
    "Mersin": ("TR", ["Mersin"], (36.80, 34.63)), "Yalova": ("TR", ["Yalova"], (40.66, 29.27)),
    "Martaş": ("TR", ["Martaş", "Martas"], (40.97, 27.96)), "Damietta": ("EG", ["Damietta", "Dumyat"], (31.42, 31.81)),
    "Algeciras": ("ES", ["Algeciras"], (36.13, -5.44)), "Tarifa": ("ES", ["Tarifa"], (36.01, -5.60)),
    "Almería": ("ES", ["Almería", "Almeria"], (36.83, -2.46)), "Motril": ("ES", ["Motril"], (36.72, -3.52)),
    "Málaga": ("ES", ["Málaga", "Malaga"], (36.72, -4.42)), "Barcelona": ("ES", ["Barcelona"], (41.38, 2.17)),
    "Valencia": ("ES", ["Valencia", "València"], (39.45, -0.33)), "Alicante": ("ES", ["Alicante", "Alacant"], (38.34, -0.48)),
    "Sète": ("FR", ["Sète", "Sete"], (43.40, 3.70)), "Marseille": ("FR", ["Marseille", "Marsiglia"], (43.30, 5.37)),
    "Toulon": ("FR", ["Toulon"], (43.12, 5.93)),
    "Genova": ("IT", ["Genova", "Genoa", "Gênes"], (44.41, 8.92)), "Civitavecchia": ("IT", ["Civitavecchia"], (42.09, 11.79)),
    "Salerno": ("IT", ["Salerno"], (40.68, 14.76)), "Palermo": ("IT", ["Palermo"], (38.12, 13.36)),
    "Trapani": ("IT", ["Trapani"], (38.02, 12.51)), "Bari": ("IT", ["Bari"], (41.12, 16.87)),
    "Ancona": ("IT", ["Ancona"], (43.62, 13.51)), "Brindisi": ("IT", ["Brindisi"], (40.64, 17.94)),
    "Trieste": ("IT", ["Trieste"], (45.65, 13.77)), "Igoumenitsa": ("GR", ["Igoumenitsa", "Ηγουμενίτσα"], (39.50, 20.26)),
    "Patras": ("GR", ["Patras", "Patra", "Πάτρα"], (38.25, 21.73)), "Lavrio": ("GR", ["Lavrio", "Λαύριο"], (37.71, 24.06)),
    "Chios": ("GR", ["Chios", "Χίος"], (38.37, 26.14)), "Mytilene": ("GR", ["Mytilene", "Lesvos", "Μυτιλήνη"], (39.10, 26.55)),
}
# Greece's ports, by the English names OpenStreetMap's lines give them
# (name:en, "Chios (Mesta) - Lavrio"): {port: ([names], (lat, lon) of the
# port, (island, port) of the Decision's list for Greece or None)}. A
# line is read port by port, each part of its name one of these names; a
# part naming another of an island's ports ("Corfu", "Kos (Kardamaina)")
# isn't one of these, and its line isn't built.
GREECE = {
    # ports on the mainland, on Crete and on Evia (not in the list)
    "Piraeus": (["Piraeus"], (37.94, 23.63), None), "Rafina": (["Rafina"], (38.02, 24.01), None),
    "Kavala": (["Kavala"], (40.93, 24.41), None), "Keramoti": (["Keramoti"], (40.86, 24.70), None),
    "Thessaloniki": (["Thessaloniki"], (40.63, 22.93), None), "Alexandroupolis": (["Alexandroupolis", "Alexandroupoli"], (40.84, 25.87), None),
    "Volos": (["Volos"], (39.36, 22.94), None), "Agios Konstantinos": (["Agios Konstantinos"], (38.76, 22.86), None),
    "Kymi": (["Kymi"], (38.63, 24.12), None), "Mantoudi": (["Mantoudi"], (38.80, 23.48), None), "Glyfa": (["Glyfa"], (38.94, 22.95), None),
    "Kyllini": (["Kyllini"], (37.94, 21.15), None), "Astakos": (["Astakos"], (38.53, 21.08), None),
    "Neapoli": (["Neapoli"], (36.51, 23.06), None), "Gythio": (["Gythio"], (36.76, 22.57), None),
    "Heraklion": (["Heraklion"], (35.34, 25.14), None), "Souda": (["Chania (Souda)", "Souda"], (35.49, 24.07), None),
    "Sitia": (["Sitia"], (35.21, 26.10), None), "Kissamos": (["Kissamos"], (35.50, 23.66), None), "Rethymno": (["Rethymno"], (35.37, 24.48), None),
    "Perama": (["Perama"], (37.96, 23.57), None), "Perama Megaridos": (["Perama Megaridos"], (37.97, 23.40), None),
    "Methana": (["Methana"], (37.58, 23.39), None), "Ermioni": (["Ermioni"], (37.39, 23.25), None), "Galatas": (["Galatas"], (37.50, 23.45), None),
    "Kosta": (["Kosta"], (37.29, 23.13), None), "Marmari": (["Marmari"], (38.05, 24.32), None), "Nea Styra": (["Nea Styra"], (38.17, 24.23), None),
    # island ports in the list
    "Aegina": (["Aegina"], (37.75, 23.43), ("AEGINA", "AEGINA")), "Souvala": (["Aegina (Souvala)"], (37.76, 23.48), ("AEGINA", "SOUVALA")),
    "Agia Marina (Aegina)": (["Aegina (Agia Marina)"], (37.74, 23.53), ("AEGINA", "AGIA MARINA, AEGINA")),
    "Agathonisi": (["Agathonisi"], (37.46, 26.97), ("AGATHONISI", "AGATHONISI")),
    "Agios Efstratios": (["Agios Efstratios"], (39.53, 24.99), ("AGIOS EFSTRATIOS", "AGIOS EFSTRATIOS")),
    "Alonnisos": (["Alonnisos", "Alonnissos"], (39.15, 23.87), ("ALONNISOS", "ALONNISOS")),
    "Katapola": (["Amorgos", "Amorgos (Katapola)"], (36.83, 25.86), ("AMORGOS", "KATAPOLA")),
    "Aegiali": (["Amorgos (Aegiale)", "Amorgos (Aigiali)"], (36.90, 25.98), ("AMORGOS", "AGIALI")),
    "Anafi": (["Anafi"], (36.35, 25.77), ("ANAFI", "ANAFI")), "Gavrio": (["Andros", "Andros (Gavrio)"], (37.89, 24.73), ("ANDROS", "GAVRIO")),
    "Antikythira": (["Antikythira"], (35.89, 23.30), ("ANTIKYTHIRA", "POTAMOS, ANTIKYTHIRA")),
    "Astypalaia": (["Astypalaia", "Astypalea", "Astypalaia (Agios Andreas)", "Astypalea (Agios Andreas)"], (36.55, 26.35), ("ASTYPALAIA", "ASTYPALAIA")),
    "Chalki": (["Chalki"], (36.22, 27.61), ("HALKI", "HALKI")), "Mesta": (["Chios (Mesta)"], (38.26, 25.93), ("CHIOS", "MESTA")),
    "Donousa": (["Donousa"], (37.10, 25.81), ("DONOUSA", "DONOUSA")), "Folegandros": (["Folegandros"], (36.62, 24.92), ("FOLEGANDROS", "FOLEGANDROS")),
    "Fournoi": (["Fournoi", "Fourni"], (37.58, 26.48), ("FOURNI KORSEON", "FOURNI KORSEON")), "Gavdos": (["Gavdos"], (34.84, 24.12), ("GAVDOS", "GAVDOS")),
    "Agios Kirykos": (["Ikaria (Agios Kirykos)"], (37.61, 26.30), ("IKARIA", "EVDILOS / AGIOS KYRIKOS")),
    "Evdilos": (["Ikaria (Evdilos)"], (37.63, 26.18), ("IKARIA", "EVDILOS / AGIOS KYRIKOS")),
    "Ios": (["Ios"], (36.72, 25.28), ("IOS", "IOS")), "Irakleia": (["Irakleia"], (36.84, 25.45), ("IRAKLEIA", "IRAKLEIA")),
    "Frikes": (["Ithaca (Frikes)"], (38.46, 20.66), ("ITHAKI", "FRIKES")), "Pisaetos": (["Ithaca (Pisaetos)"], (38.38, 20.64), ("ITHAKI", "PISAETOS")),
    "Kalymnos": (["Kalymnos"], (36.95, 26.98), ("KALYMNOS", "KALYMNOS")), "Karpathos": (["Karpathos"], (35.51, 27.21), ("KARPATHOS", "KARPATHOS")),
    "Kasos": (["Kasos"], (35.42, 26.92), ("KASOS", "KASOS")), "Kastos": (["Kastos"], (38.57, 20.91), ("KASTOS", "KASTOS")),
    "Kea": (["Kea"], (37.66, 24.32), ("KEA", "KEA")),
    "Sami": (["Cephalonia (Sami)", "Kefalonia (Sami)"], (38.25, 20.65), ("KEFALLONIA", "SAMI")),
    "Poros (Kefallonia)": (["Cephalonia (Poros)", "Kefalonia (Poros)"], (38.15, 20.77), ("KEFALLONIA", "POROS, KEFALLONIA")),
    "Lefkimmi": (["Corfu (Lefkimmi)"], (39.42, 20.07), ("KERKYRA", "LEFKIMI")), "Kimolos": (["Kimolos"], (36.79, 24.57), ("KIMOLOS", "KIMOLOS")),
    "Kos": (["Kos"], (36.89, 27.29), ("KOS", "KOS")), "Mastichari": (["Kos (Mastichari)"], (36.85, 27.08), ("KOS", "MASTICHARI")),
    "Koufonisi": (["Koufonisi"], (36.93, 25.60), ("KOUFONISI", "KOUFONISIA, CYCLADES")), "Kythnos": (["Kythnos"], (37.39, 24.43), ("KYTHNOS", "KYTHNOS")),
    "Lakki": (["Leros"], (37.13, 26.85), ("LEROS", "LAKKI, LEROS")), "Myrina": (["Lemnos"], (39.87, 25.06), ("LIMNOS", "MYRINA")),
    "Lipsi": (["Leipsoi", "Lipsi"], (37.30, 26.76), ("LIPSI", "LIPSI")), "Meganisi": (["Meganisi (Spilia)"], (38.66, 20.78), ("MEGANISI", "MEGANISI")),
    "Kastelorizo": (["Kastelorizo"], (36.15, 29.59), ("MEGISTI", "KASTELORIZO")), "Adamantas": (["Milos"], (36.73, 24.43), ("MILOS", "ADAMANTAS")),
    "Mykonos": (["Mykonos"], (37.45, 25.33), ("MYKONOS", "MYKONOS")), "Naxos": (["Naxos"], (37.11, 25.37), ("NAXOS", "NAXOS")),
    "Nisyros": (["Nisyros"], (36.61, 27.16), ("NISYROS", "NISYROS")), "Oinousses": (["Oinousses"], (38.51, 26.22), ("INOUSSES", "INOUSSES")),
    "Paros": (["Paros"], (37.09, 25.15), ("PAROS", "PAROS")), "Paxoi": (["Paxoi"], (39.20, 20.19), ("PAXI", "PAXI")),
    "Patmos": (["Patmos"], (37.32, 26.55), ("PATMOS", "PATMOS")), "Poros": (["Poros"], (37.50, 23.46), ("POROS", "POROS, TRIZINIA")),
    "Psara": (["Psara"], (38.54, 25.56), ("PSARA", "PSARA")), "Rhodes": (["Rhodes"], (36.45, 28.23), ("RHODES", "RHODES")),
    "Paloukia": (["Salamina (Paloukia)"], (37.96, 23.55), ("SALAMINA", "PALOUKIA")),
    "Faneromeni": (["Salamina (Faneromeni)"], (37.97, 23.43), ("SALAMINA", "FANEROMENI")),
    "Vathy": (["Samos", "Samos (Vathy)"], (37.76, 26.98), ("SAMOS", "VATHY")), "Karlovasi": (["Samos (Karlovasi)"], (37.80, 26.70), ("SAMOS", "KARLOVASI")),
    "Pythagoreio": (["Samos (Pythagoreio)"], (37.69, 26.95), ("SAMOS", "PYTHAGOREIO")),
    "Samothraki": (["Samothrace"], (40.47, 25.47), ("SAMOTHRAKI", "SAMOTHRAKI")), "Schoinousa": (["Schoinousa"], (36.87, 25.52), ("SCHINOUSSA", "SCHINOUSSA")),
    "Serifos": (["Serifos"], (37.14, 24.51), ("SERIFOS", "SERIFOS")), "Kamares": (["Sifnos"], (36.97, 24.68), ("SIFNOS", "KAMARES, SIFNOS")),
    "Sikinos": (["Sikinos"], (36.68, 25.12), ("SIKINOS", "SIKINOS")), "Skiathos": (["Skiathos"], (39.16, 23.49), ("SKIATHOS", "SKIATHOS")),
    "Glossa": (["Skopelos (Glossa)", "Glossa"], (39.17, 23.62), ("SKOPELOS", "GLOSSA/AGNONTAS")),
    "Agnontas": (["Skopelos (Agnontas)"], (39.08, 23.71), ("SKOPELOS", "GLOSSA/AGNONTAS")),
    "Linaria": (["Skyros"], (38.84, 24.54), ("SKYROS", "LINARIA")), "Spetses": (["Spetses"], (37.26, 23.16), ("SPETSES", "SPETSES")),
    "Symi": (["Symi"], (36.62, 27.84), ("SYMI", "SYMI")), "Ermoupoli": (["Syros"], (37.44, 24.94), ("SYROS", "ERMOUPOLI")),
    "Prinos": (["Thassos (Prinos)"], (40.76, 24.60), ("THASOS", "PRINOS")), "Thasos": (["Thassos (Limenas)"], (40.78, 24.71), ("THASOS", "THASOS")),
    "Athinios": (["Santorini (Athinios)"], (36.39, 25.43), ("THIRA", "THIRA")), "Thymaina": (["Thymaina"], (37.58, 26.51), ("THYMAINA", "THYMAINA")),
    "Tilos": (["Tilos"], (36.42, 27.38), ("TILOS", "TILOS")), "Tinos": (["Tinos"], (37.54, 25.16), ("TINOS", "TINOS")),
    "Hydra": (["Hydra"], (37.35, 23.47), ("YDRA", "YDRA")), "Zakynthos": (["Zakynthos", "Zante"], (37.78, 20.90), ("ZAKYNTHOS", "ZAKYNTHOS")),
}
# The island ports of Implementing Decision (EU) 2023/2895, Annex I, that
# PORTS has: (Member State, island, port) as the Decision lists them.
ISLANDS = {"Eivissa": ("SPAIN", "IBIZA", "EIVISSA"), "Sant Antoni": ("SPAIN", "IBIZA", "SANT ANTONI DE PORTMANY"),
           "La Savina": ("SPAIN", "FORMENTERA", "LA SAVINA"), "Ciutadella": ("SPAIN", "MENORCA", "CIUDADELA"),
           "Maó": ("SPAIN", "MENORCA", "MAÓ"), "Portoferraio": ("ITALY", "ISOLA D’ELBA", "PORTOFERRAIO"),
           "Rio Marina": ("ITALY", "ISOLA D’ELBA", "RIO MARINA"), "Cavo": ("ITALY", "ISOLA D’ELBA", "CAVO"),
           "Ischia": ("ITALY", "ISOLA DI ISCHIA", "ISCHIA"), "Casamicciola": ("ITALY", "ISOLA DI ISCHIA", "CASAMICCIOLA TERME"),
           "Forio": ("ITALY", "ISOLA DI ISCHIA", "FORIO"), "Procida": ("ITALY", "PROCIDA", "PROCIDA"),
           "Capri": ("ITALY", "CAPRI", "CAPRI MARINA GRANDE"), "La Maddalena": ("ITALY", "LA MADDALENA", "LA MADDALENA"),
           "Carloforte": ("ITALY", "ISOLA DI SAN PIETRO", "CARLOFORTE"), "Lipari": ("ITALY", "LIPARI", "LIPARI"),
           "Pantelleria": ("ITALY", "PANTELLERIA", "PANTELLERIA"), "Lampedusa": ("ITALY", "LAMPEDUSA", "LAMPEDUSA"),
           "Favignana": ("ITALY", "FAVIGNANA", "FAVIGNANA"), "Isola del Giglio": ("ITALY", "ISOLA DEL GIGLIO", "ISOLA DEL GIGLIO"),
           "Ustica": ("ITALY", "USTICA", "USTICA"), "Ponza": ("ITALY", "PONZA", "PONZA"), "Mġarr": ("MALTA", "GOZO", "MGARR"),
           "Mišnjak": ("CROATIA", "RAB", "MIŠNJAK"), "Chios": ("GREECE", "CHIOS", "CHIOS"), "Mytilene": ("GREECE", "LESVOS", "MYTILINI")}
QUERIED = set(PORTS)  # the ports whose names ferry-ships-osm and -osm-2 ask for
PORTS["Mytilene"][1].extend(["Mytilini", "Lesvos (Mytilene)"])
for _p, (_names, _at, _listed) in GREECE.items():
    PORTS[_p] = ("GR", _names, _at)
    if _listed:
        ISLANDS[_p] = ("GREECE",) + _listed
# The UK nation of the UK ports where the UK ETS's rules differ: Northern
# Ireland (50% to and from Great Britain) and Scotland (its ferry services
# between points in Scotland are outside).
REGION = {"Belfast": "GB-NIR", "Larne": "GB-NIR", "Cairnryan": "GB-SCT", "Aberdeen": "GB-SCT", "Kirkwall": "GB-SCT",
          "Lerwick": "GB-SCT"}
# Other names the pages give a port.
PAGE_PORT = {"gothenburg masthugget": "Gothenburg", "hoek van holland": "Hoek van Holland", "jersey": "St Helier"}
# The EU and the EEA EFTA states (ferries.go's eea).
EEA = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
       "PL", "PT", "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO"}
UPPER = "A-ZĄĆĘŁŃÓŚŹŻÅÄÖ"
SHIP = re.compile(rf"(?:^|\s{{2,}})([{UPPER}][^\W\d_]+(?: [{UPPER}][^\W\d_]+)*)\s{{2,}}(?=\d\d[.:]\d\d|-{{3,}}|stoppage)")


def ascii(s):
    return unicodedata.normalize("NFKD", s.replace("ø", "o").replace("Ø", "O").replace("ı", "i")).encode("ascii", "ignore").decode().lower()


def ship_names():
    """{IMO number: name} of the MRV ship lists (the latest year's name)."""
    names = {}
    for p in sorted(glob.glob(os.path.join(MRV, "mrv-ships-*.json"))):
        names.update({s["imo"]: s["name"] for s in json.load(open(p, encoding="utf-8"))["ships"]})
    return names


def imos():
    """{name: IMO number} of the names the MRV ship lists give one IMO number."""
    seen = {}
    for p in sorted(glob.glob(os.path.join(MRV, "mrv-ships-*.json"))):
        for s in json.load(open(p, encoding="utf-8"))["ships"]:
            seen.setdefault(ascii(s["name"]).upper(), set()).add(s["imo"])
    return {n: next(iter(i)) for n, i in seen.items() if len(i) == 1}


def timetable(t, path):
    """(ports, {ships}) of a POLSCA timetable, weekly or by date (the
    Christmas ones): the ports are the first line naming two in capitals
    ("ŚWINOUJŚCIE   YSTAD", "DATE / DATA FERRY / PROM ŚWINOUJŚCIE   YSTAD");
    a ship is a name followed by a time or "-------" with a time on its
    line ("Polonia   06.30   10.30 ...", "JANTAR UNITY   05.00 - 09.45 ...")."""
    names = {ascii(p).upper(): p for p in COUNTRY}
    ports = None
    for line in t.splitlines():
        found = [names[ascii(w).upper()] for w in re.findall(r"[^\W\d_]{3,}", line) if w == w.upper() and ascii(w).upper() in names]
        if len(found) == 2 and found[0] != found[1]:
            ports = tuple(found)
            break
    if not ports:
        sys.exit(f"ferry ships: {path}: the ports' columns not read")
    ships = set()
    for line in t.splitlines():
        for m in SHIP.finditer(line):
            if re.search(r"\d\d[.:]\d\d", line[m.end():]):
                ships.add(m.group(1).upper())
    if not ships:
        sys.exit(f"ferry ships: {path}: no ships read")
    return ports, ships


def nuxt(page):
    """The page's Nuxt data: its flat array of values."""
    m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        sys.exit("ferry ships: Bornholmslinjen's page has no Nuxt data")
    return json.loads(m.group(1))


def bornholm(page):
    """{ferry: {ports}} from Bornholmslinjen's ferries page."""
    return nuxt_routes(page, "Rønne", ("Ystad", "Køge", "Sassnitz"))


def nuxt_routes(page, hub, others):
    """{ferry: {ports}} from a ferries page of Molslinjen's sites
    (Bornholmslinjen's, Molslinjen's): each ferry's crossing times ("Rønne
    - Køge", "Odden-Aarhus") and description ("på ruten mellem Rønne og
    Ystad") name the ports it sails to from the hub."""
    a = nuxt(page)
    port = "(" + "|".join(others) + ")"
    routes = {}

    def strings(i, depth=0):
        v = a[i] if isinstance(i, int) and 0 <= i < len(a) else None
        if depth > 6 or v is None:
            return
        if isinstance(v, str):
            yield v
        elif isinstance(v, list):
            for x in v:
                yield from strings(x, depth + 1)
        elif isinstance(v, dict):
            for x in v.values():
                yield from strings(x, depth + 1)

    for v in a:
        if not isinstance(v, dict):
            continue
        if "ferrySpecifications" in v and "erpId" in v:
            name = a[v["name"]]
            for s in strings(v["ferrySpecifications"]):
                m = re.fullmatch(rf"{hub} ?[-–] ?{port}", s.strip())
                if m:
                    routes.setdefault(name, set()).add(m.group(1))
        if "ferry" in v and "description" in v:
            ferry = [x for x in strings(v["ferry"]) if x in {a[w["name"]] for w in a if isinstance(w, dict) and "erpId" in w}]
            for s in strings(v["description"]):
                for m in re.finditer(rf"{hub} ?- ?{port}|{hub} og {port}", html.unescape(re.sub(r"<[^>]+>", " ", s))):
                    for f in ferry[:1]:
                        routes.setdefault(f, set()).add(m.group(1) or m.group(2))
    return routes


def gotland(page):
    """{ferry: {(mainland port, Visby)}} from Destination Gotland's ferries
    page ("M/S Drotten operates the Visby–Nynäshamn/Oskarshamn route")."""
    flat = re.sub(r"\s+", " ", page_text(re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)))
    routes = {}
    for m in re.finditer(r"M/S (\w[\w ]*?) operates the (\w+)\s*[–-]\s*(\w+(?:\s*/\s*\w+)*) route", flat):
        island = port_of(m.group(2), "gotland-ferries.html")
        routes.setdefault(m.group(1), set()).update((port_of(p, "gotland-ferries.html"), island) for p in re.split(r"\s*/\s*", m.group(3)))
    if not routes:
        sys.exit("ferry ships: Destination Gotland's page names no ferry's route")
    return routes


def ttline(t):
    """({route: {ships}}, page URL, day read) from the capture of TT-Line's timetable."""
    legend = dict(re.findall(r"([A-Z]{2}) = ([A-Z][\w ]+?)(?=;|$)", next((l for l in t.splitlines() if " = " in l), ""), re.M))
    url = re.search(r"^# Page: (\S+)", t, re.M)
    day = re.search(r"read on (\d{4}-\d\d-\d\d)", t)
    if not legend or not url or not day:
        sys.exit("ferry ships: TT-Line's capture: the header not read")
    routes = {}
    for line in t.splitlines():
        m = re.search(r"\d{1,2}:\d\d ([A-Z]{2}) (\S+ - \S+) ", line)
        if m and not line.startswith("#"):
            if m.group(1) not in legend:
                sys.exit(f"ferry ships: TT-Line's capture: {m.group(1)} not named")
            routes.setdefault(m.group(2), set()).add(legend[m.group(1)].upper())
    return routes, url.group(1), day.group(1)


def port_of(name, where):
    """The port of a name, or of one of its other names (PORTS: Dunkirk is
    Dunkerque, Vuosaari Helsinki)."""
    k = ascii(name).strip()
    for p in PORTS:
        if ascii(p) == k:
            return p
    if k in PAGE_PORT:
        return PAGE_PORT[k]
    for p, (_, names, _) in PORTS.items():
        if k in {ascii(x) for x in names}:
            return p
    sys.exit(f"ferry ships: {where}: the port {name!r} isn't known (PORTS)")


def page_text(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()


def stena(pages):
    """[(ports, {ships}, heading, file)] from Stena Line Freight's route pages."""
    out = []
    for path, t in pages:
        h1 = re.findall(r"<h1[^>]*>(.*?)</h1>", t, re.S)
        parts = re.split(r"\s+[–-]\s+", page_text(h1[0])) if h1 else []
        i = t.find('id="vessels"')
        ships = [page_text(x) for x in re.findall(r'<h3 class="heading">([^<]+)<', t[i:t.find("</section>", i)])] if i >= 0 else []
        if len(parts) != 2 or not ships:
            sys.exit(f"ferry ships: {os.path.basename(path)}: the route or its vessels not read")
        out.append((tuple(port_of(p, os.path.basename(path)) for p in parts), set(ships), page_text(h1[0]), path))
    return out


def finnlines(pages, schedule):
    """[(ports, {ships}, heading, file)] from Finnlines' route pages, and the
    master schedule for a page that doesn't name its ferries."""
    out = []
    for path, t in pages:
        h1 = re.findall(r"<h1[^>]*>(.*?)</h1>", t, re.S)
        parts = re.split(r"\s*[–-]\s*", page_text(h1[0])) if h1 else []
        name = os.path.basename(path)
        if len(parts) > 2:
            print(f"ferry ships: {name}: {page_text(h1[0])} calls on the way: not built")
            continue
        if len(parts) != 2:
            sys.exit(f"ferry ships: {name}: the route not read")
        ports = tuple(port_of(p, name) for p in parts)
        ships = set()
        i = t.find("Ferries on the route")
        if i >= 0:
            # The ferries' headings follow, up to the first that isn't a
            # ship's name ("Latest offers on the route").
            for h in re.findall(r"<h[2-4][^>]*>(.*?)</h[2-4]>", t[i:], re.S):
                names = re.split(r"\s*&\s*", page_text(h))
                if not all(re.fullmatch(r"[A-Z][\w-]*(?: [A-Z][\w-]*){0,2}", s) for s in names):
                    break
                ships.update(names)
        else:
            lines = schedule.splitlines()
            for k, line in enumerate(lines):
                m = re.fullmatch(r"\s*(\S[^–]*?)\s+–\s+(\S.*?)\s*", line)
                if m and {ascii(x) for x in m.groups()} == {ascii(p) for p in ports}:
                    for nxt in lines[k + 1:k + 10]:
                        f = re.search(r"([A-Z][a-z]+(?:\s*/\s*[A-Z][a-z]+)+)\s+\d/7", nxt)
                        if f:
                            ships = {s.strip() for s in f.group(1).split("/")}
                            break
                    break
        if not ships:
            sys.exit(f"ferry ships: {name}: no ferries named for {page_text(h1[0])}")
        out.append((ports, ships, page_text(h1[0]), path))
    return out


def fold(s):
    """Lower case without accents, other scripts kept (Πάτρα: πατρα)."""
    s = unicodedata.normalize("NFKD", s.replace("ø", "o").replace("Ø", "O").replace("ı", "i"))
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower()


def spans(name, p):
    """Where the port's names stand in a line's name, as words."""
    return [m.span() for x in PORTS[p][1] for m in re.finditer(rf"(?<!\w){re.escape(fold(x))}(?!\w)", fold(name))]


def named(name, p):
    """Whether a line's name has one of the port's names (as a word)."""
    return bool(spans(name, p))


def named_ports(name):
    """The ports a line's name has; a name inside another port's longer
    name (Tanger in Tanger Med) doesn't count."""
    found = {p: spans(name, p) for p in PORTS}
    found = {p: s for p, s in found.items() if s}
    return [p for p, ss in found.items() if not all(any(q != p and a <= x and y <= b and (b - a) > (y - x)
                                                        for q, qs in found.items() for a, b in qs) for x, y in ss)]


def irishferries(pages):
    """[(ports, {ship: IMO number}, heading, file)] from Irish Ferries
    Freight's route pages: the ports from the page's address
    (route-information/dover-calais/), the ships and their IMO numbers from
    its vessel specifications ("ISLE OF INISHMORE Vessel IMO 9142605")."""
    out = []
    for path, t in pages:
        name = os.path.basename(path)
        slug = re.sub(r"^irishferries-routes-|\.html$", "", name)
        parts = slug.split("-")
        flat = re.sub(r"\s+", " ", page_text(t))
        i = flat.find("Vessel Specification")
        ships = dict(re.findall(r"([A-Z][A-Z.' ]+?) Vess(?:el|le) IMO (\d{7})", flat[i:])) if i >= 0 else {}
        if len(parts) != 2 or not ships:
            sys.exit(f"ferry ships: {name}: the route or its vessels not read")
        ports = tuple(port_of(p, name) for p in parts)
        out.append((ports, {s.strip(): imo for s, imo in ships.items()}, "–".join(ports), path))
    return out


def poferries(pages):
    """[(ports, {ship: IMO number or None}, heading, file)] from P&O Freight's
    route pages: the ports from the page's address (route/dover-calais-freight),
    the ships from its "Our Fleet" section, with the IMO numbers it gives
    ("IMO Number - 9244116"). When the page's sailing tables name ships
    ("13:40 Pioneer"), only those: the section also names ships no longer on
    the route."""
    out = []
    for path, t in pages:
        name = os.path.basename(path)
        parts = re.sub(r"^po-routes-|-freight\.html$", "", name).split("-")
        i = t.find('id="accordionFerries"')
        fleet = {}
        for card in re.split(r"(?=<button[^>]*data-target=\"#collapse-)", t[i:])[1:] if i >= 0 else []:
            names = [x.strip() for x in re.split(r"\s+(?:and|&)\s+", page_text(card[card.find(">") + 1:card.find("</button>")])) if x.strip()]
            imo = re.search(r"IMO (?:Number|number)\s*-\s*(\d{7})", page_text(card).replace("\xa0", " "))
            fleet.update({n: imo.group(1) if imo and len(names) == 1 else None for n in names})
        tables = " ".join(page_text(x) for x in re.findall(r"<table\b.*?</table>", t, re.S)).replace("\xa0", " ")
        short = lambda n: re.sub(r"^P&O\s+", "", n)
        sailing = {n: imo for n, imo in fleet.items() if re.search(rf"(?<!\w){re.escape(fold(short(n)))}(?!\w)", fold(tables))}
        if len(parts) != 2 or not fleet:
            sys.exit(f"ferry ships: {name}: the route or its fleet not read")
        ports = tuple(port_of(p, name) for p in parts)
        heading = "–".join(ports) + (", its ferries in its sailing tables" if sailing else "")
        if "Space Charter" in tables:
            heading += " (its Space Charter sailings' ships not named)"
        out.append((ports, sailing or fleet, heading, path))
    return out


def imo_number(s):
    """Whether s is an IMO ship number: 7 digits, the last the check digit."""
    return bool(re.fullmatch(r"\d{7}", s or "")) and sum(int(s[i]) * (7 - i) for i in range(6)) % 10 == int(s[6])


def dfds(pages, names):
    """[(ports, {ship: IMO number}, heading, file)] from DFDS's freight route
    pages and their timetables (dfds-routes-<route>.html and .json): the
    page's terminals ("portOfLoading": {"name": "Klaipeda", "terminalId":
    "LTKLJ"}) and the ship and IMO number of each departure in the
    timetable (DFDS's API: "vehicleName", "vehicleId"); a departure without
    them (a space charter partner's sailing on Dover–Calais) is left out,
    and a ship the timetable gives only by IMO number is named as the MRV
    ship lists name it (names). The terminals' own names stand for their
    ports (Muuga, Vuosaari, not Tallinn and Helsinki: OpenStreetMap's lines
    between the cities are the passenger ferries')."""
    out = []
    for path, t in pages:
        name = os.path.basename(path)
        m = re.search(r'"route":\{"portOfDischarge":\{.*?"name":"([^"]+)","terminalId":"[A-Z0-9]{5}"\},'
                      r'"portOfLoading":\{.*?"name":"([^"]+)","terminalId":"[A-Z0-9]{5}"\}', t.replace('\\"', '"'))
        tt = path[:-len(".html")] + ".json"
        if not m or not os.path.exists(tt):
            print(f"ferry ships: {name}: no route or timetable: not built")
            continue
        ships, unnamed = {}, 0
        for d in json.load(open(tt, encoding="utf-8")):
            imo, ship = d.get("vehicleId"), (d.get("vehicleName") or "").strip() or names.get(d.get("vehicleId"))
            if imo_number(imo) and ship:
                ships[ship] = imo
            else:
                unnamed += 1
        if not ships:
            print(f"ferry ships: {name}: no ship in its timetable: not built")
            continue
        ports = (port_of(m.group(2), name), port_of(m.group(1), name))
        heading = "–".join(ports) + ", its ferries in its timetable" + (" (its sailings without a named ship left out)" if unnamed else "")
        out.append((ports, ships, heading, path))
    return out


def tallink(page):
    """[(ports, {ships}, heading, file)] from Tallink's freight timetables and
    fleet page: each route's heading ("Tallinn-Helsinki") and its ships'
    headings after it."""
    out = []
    path, t = page
    for m in re.finditer(r"<h3[^>]*>([^<]+)</h3>(.*?)(?=<h3|$)", t, re.S):
        parts = re.split(r"\s*[–-]\s*", page_text(m.group(1)))
        ships = {page_text(x) for x in re.findall(r"<h4[^>]*>([^<]+)</h4>", m.group(2))}
        if len(parts) == 2 and ships:
            out.append((tuple(port_of(p, os.path.basename(path)) for p in parts), ships, page_text(m.group(1)), path))
    if not out:
        sys.exit("ferry ships: Tallink's fleet page names no route's ships")
    return out


def colorline(page):
    """[(ports, {ships}, heading, file)] from Color Line's routes page ("The
    route Hirtshals – Larvik/Kristiansand is operated by SuperSpeed 1 and
    2"): a route to two ports ("Larvik/Kristiansand") is a crossing to each,
    with the route's ships."""
    path, t = page
    flat = re.sub(r"\s+", " ", page_text(re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)))
    out = []
    for m in re.finditer(r"The route (\w+) [–-] (\w+(?:/\w+)*) is operated by ([^.]+)\.", flat):
        names = re.split(r"\s*,\s*|\s+and\s+", m.group(3).strip())
        # "SuperSpeed 1 and 2": the second is SuperSpeed 2.
        names = [n if not re.fullmatch(r"\d+", n) else re.sub(r"\d+$", n, names[0]) for n in names]
        a = port_of(m.group(1), os.path.basename(path))
        for b in m.group(2).split("/"):
            out.append(((a, port_of(b, os.path.basename(path))), set(names), f"{m.group(1)} – {m.group(2)}", path))
    if not out:
        sys.exit("ferry ships: Color Line's routes page names no route's ships")
    return out


def fjordline(page):
    """[(ports, {ships}, heading, file)] from Fjord Line's ships page (its
    Markdown: "- [Fjord FSTR](...): ... between Hirtshals and
    Kristiansand"): a ship the page puts between two ports sails that
    crossing; one it puts between more ("routes between Hirtshals,
    Kristiansand, Stavanger and Bergen") isn't placed on any of them."""
    path, t = page
    routes = {}
    for m in re.finditer(r"^- \[([^\]]+)\]\([^)]*\): .*?\bbetween ([^.]+)\.", t, re.M):
        parts = re.split(r",\s*|\s+and\s+", m.group(2).strip())
        if len(parts) == 2:
            ship = re.sub(r"^MS ", "", m.group(1))
            routes.setdefault(tuple(port_of(p, os.path.basename(path)) for p in parts), set()).add(ship)
    if not routes:
        sys.exit("ferry ships: Fjord Line's ships page puts no ship on a crossing")
    return [(ports, ships, "–".join(ports), path) for ports, ships in sorted(routes.items())]


def katajanokka(page):
    """[(ports, {ships}, heading, file)] from the Port of Helsinki's page on
    Viking Line at its Katajanokka terminal ("Katajanokka Terminal has a
    regular ferry connections: Viking XPRS to Tallinn and MS Gabriella and
    Viking Cinderella to Stockholm"): the regular connections only, not the
    summer's added sailings."""
    path, t = page
    flat = re.sub(r"\s+", " ", page_text(re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)))
    m = re.search(r"regular ferry connections: ([^.]+)\.", flat)
    out = []
    for ships, city in re.findall(r"(.+?) to (\w+)(?: and |$)", m.group(1)) if m else []:
        names = {re.sub(r"^(?:MS|M/S) ", "", n.strip()) for n in re.split(r"\s+and\s+", ships)}
        out.append((("Helsinki", port_of(city, os.path.basename(path))), names, f"Helsinki–{city}, its ferries as the Port of Helsinki's Katajanokka terminal page names its regular connections", path))
    if not out:
        sys.exit("ferry ships: the Port of Helsinki's Katajanokka page names no regular connection")
    return out


def wasaline(page):
    """[(ports, {ships}, heading, file)] from Wasaline's cargo page ("We
    operate the route between Vaasa in Finland and Umeå in Sweden ...
    Aurora Botnia is tailored for cargo transportation")."""
    path, t = page
    flat = re.sub(r"\s+", " ", page_text(re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)))
    route = re.search(r"the route between (\w+) in \w+ and (\w+) in \w+", flat)
    ships = set(re.findall(r"([A-Z]\w+ [A-Z]\w+) is tailored for cargo", flat))
    if not route or not ships:
        sys.exit("ferry ships: Wasaline's cargo page names no route or ship")
    ports = tuple(port_of(p, os.path.basename(path)) for p in route.groups())
    return [(ports, ships, "–".join(ports), path)]


def eckero(page):
    """[(ports, {ships}, heading, file)] from Eckerö Line's cargo page: its
    ships' crossings in its cargo CO2 figures ("M/S Finbo Cargo (Helsinki,
    Vuosaari – Tallinn, Muuga)"), a terminal named after its port
    (Vuosaari, Muuga) standing for it, else the city."""
    path, t = page
    flat = re.sub(r"\s+", " ", page_text(re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)))
    routes = {}
    for m in re.finditer(r"M/S (\w[\w ]*?) \((\w+), ([^–()]+?) – (\w+), ([^()]+?)\)", flat):
        ports = []
        for city, terminal in ((m.group(2), m.group(3)), (m.group(4), m.group(5))):
            k = ascii(terminal.strip())
            ports.append(next((p for p in PORTS if k in {ascii(x) for x in PORTS[p][1]}), None) or port_of(city, os.path.basename(path)))
        routes.setdefault(tuple(ports), set()).add(m.group(1))
    if not routes:
        sys.exit("ferry ships: Eckerö Line's cargo page names no ship's crossing")
    return [(ports, ships, "–".join(ports), path) for ports, ships in sorted(routes.items())]


# The Overpass queries' boxes (south, west, north, east): the North Sea, the
# Channel and the Baltic; the western and the eastern Mediterranean; the
# Gulf of Bothnia. Each asks for the lines named after a port within 4
# degrees of it (a line to a port further off, Santander or Tórshavn, is
# named after the port in the box it comes from too); several smaller
# queries, as one large one times out on Overpass.
OSM_BOXES = [("ferry-ships-osm", (49.0, -11.0, 61.0, 26.0)), ("ferry-ships-osm-2", (30.0, -10.0, 46.5, 12.0)),
             ("ferry-ships-osm-3", (61.0, 14.0, 66.0, 26.0)), ("ferry-ships-osm-4", (30.0, 12.0, 46.5, 36.0))]


def osm_query():
    """The Overpass queries of OSM_BOXES' sources, as sources.json has them."""
    import urllib.parse
    out = []
    for _, (s, w, n, e) in OSM_BOXES:
        near = lambda at: s - 4 <= at[0] <= n + 4 and w - 4 <= at[1] <= e + 4
        names = "|".join(sorted({x for p, (_, xs, at) in PORTS.items() if p in QUERIED and near(at) for x in xs
                                 if (p, x) not in (("Mytilene", "Mytilini"), ("Mytilene", "Lesvos (Mytilene)"))}))
        q = '[out:json][timeout:300];way["route"="ferry"]["name"~"' + names + f'"]({s},{w},{n},{e});out geom tags;'
        out.append("https://overpass-api.de/api/interpreter?data=" + urllib.parse.quote(q, safe=""))
    return out


def osm_place(osm, a, b, operator):
    """{port: (lat, lon)}: the ends of the ferry line (for cars or trucks)
    whose name has both ports (the operator's, if one is), each port at the
    end nearest its town (PORTS); None when OpenStreetMap has no such line,
    or one that doesn't come within 40 km of a port's town."""
    from ferry_osm import km
    car = {i for i, _ in lines_of(osm)[0]} | {w["id"] for w in osm.get("elements", []) if w.get("tags", {}).get("hgv") in ("yes", "designated")}
    has = lambda name, p: named(name, p)
    ways = [w for w in osm.get("elements", []) if w["type"] == "way" and w["id"] in car and has(w.get("tags", {}).get("name", ""), a)
            and has(w.get("tags", {}).get("name", ""), b)]
    own = [w for w in ways if ascii(operator) in ascii(w.get("tags", {}).get("operator", ""))]
    ways = own or ways
    if not ways:
        print(f"ferry ships: {a}–{b}: OpenStreetMap has no ferry line named after both")
        return None
    ends = [(g["lat"], g["lon"]) for w in ways for g in (w["geometry"][0], w["geometry"][-1])]
    pos = {}
    for p in (a, b):
        best = min((km(e, PORTS[p][2]), e) for e in ends)
        if best[0] > 40:
            print(f"ferry ships: {a}–{b}: OpenStreetMap's line doesn't reach {p}")
            return None
        pos[p] = best[1]
    if pos[a] == pos[b]:
        print(f"ferry ships: {a}–{b}: both ports at one end of OpenStreetMap's line")
        return None
    return pos


def crossing(cid, ports, pos, operator, ships, source, ids, exemptions=()):
    return {"id": cid, "name": "–".join(ports), "operator": operator,
            "terminals": [{"name": p, "lat": round(pos[p][0], 6), "lon": round(pos[p][1], 6), "country": COUNTRY[p],
                           **({"region": REGION[p]} if p in REGION else {})} for p in ports],
            "ships": [{**({"imo": ids[ascii(s).upper()]} if ascii(s).upper() in ids else {}), "name": s.upper()} for s in sorted(ships)],
            **({"exemptions": list(exemptions)} if exemptions else {}), "source": source}


def main(fetched, out):
    try:
        page = open(os.path.join(fetched, "polsca-timetables.html"), encoding="utf-8").read()
        tts = {p: open(p, encoding="utf-8").read() for p in sorted(glob.glob(os.path.join(fetched, "polsca-timetables-*.txt")))}
        bpage = open(os.path.join(fetched, "bornholm-ferries.html"), encoding="utf-8").read()
        posm = json.load(open(os.path.join(fetched, "polsca-osm.json"), encoding="utf-8"))
        bosm = json.load(open(os.path.join(fetched, "dk-bornholm-osm.json"), encoding="utf-8"))
        decision = text(os.path.join(fetched, "ets-islands-2023-2895.html"))
        tosm = json.load(open(os.path.join(fetched, "ttline-osm.json"), encoding="utf-8"))
        gpage = open(os.path.join(fetched, "gotland-ferries.html"), encoding="utf-8").read()
        mpage = open(os.path.join(fetched, "mols-ferries.html"), encoding="utf-8").read()
        grosm = json.load(open(os.path.join(fetched, "gr-ferries-osm.json"), encoding="utf-8"))
        tcap = open(TTLINE_FILE, encoding="utf-8").read()
        spages = [(p, open(p, encoding="utf-8").read()) for p in sorted(glob.glob(os.path.join(fetched, "stena-routes-*.html")))]
        fpages = [(p, open(p, encoding="utf-8").read()) for p in sorted(glob.glob(os.path.join(fetched, "finnlines-schedules-*.html")))]
        ipages = [(p, open(p, encoding="utf-8").read()) for p in sorted(glob.glob(os.path.join(fetched, "irishferries-routes-*.html")))]
        ppages = [(p, open(p, encoding="utf-8").read()) for p in sorted(glob.glob(os.path.join(fetched, "po-routes-*.html")))]
        dpages = [(p, open(p, encoding="utf-8").read()) for p in sorted(glob.glob(os.path.join(fetched, "dfds-routes-*.html")))]
        tpage = (os.path.join(fetched, "tallink-fleet.html"), open(os.path.join(fetched, "tallink-fleet.html"), encoding="utf-8").read())
        epage = (os.path.join(fetched, "eckero-cargo.html"), open(os.path.join(fetched, "eckero-cargo.html"), encoding="utf-8").read())
        cpage = (os.path.join(fetched, "colorline-routes.html"), open(os.path.join(fetched, "colorline-routes.html"), encoding="utf-8").read())
        jpage = (os.path.join(fetched, "fjordline-ships.html"), open(os.path.join(fetched, "fjordline-ships.html"), encoding="utf-8").read())
        wpage = (os.path.join(fetched, "wasaline-cargo.html"), open(os.path.join(fetched, "wasaline-cargo.html"), encoding="utf-8").read())
        kpage = (os.path.join(fetched, "helsinki-katajanokka.html"), open(os.path.join(fetched, "helsinki-katajanokka.html"), encoding="utf-8").read())
        fsched = "".join(open(p, encoding="utf-8").read() for p in sorted(glob.glob(os.path.join(fetched, "finnlines-schedules-*master-schedule*.txt"))))
        gosm, seen = {"elements": []}, set()
        for sid, _ in OSM_BOXES:
            for e in json.load(open(os.path.join(fetched, sid + ".json"), encoding="utf-8"))["elements"]:
                if (e["type"], e["id"]) not in seen:
                    seen.add((e["type"], e["id"]))
                    gosm["elements"].append(e)
        urls = {f["file"]: f["url"] for f in json.load(open(os.path.join(fetched, "manifest.json")))["files"]}
    except (OSError, ValueError) as e:
        print(f"ferry ships: not built ({e})")
        return
    if not tts:
        sys.exit("ferry ships: no POLSCA timetables")
    src = {s["id"]: s for s in json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))["sources"]}
    ids = imos()
    crossings = []

    # POLSCA
    flat = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))
    out_of_service = {m.group(1): m.group(2) for m in re.finditer(r"departures of the ferry (\w[\w ]*?) from (\d{1,2}\.\d{1,2}\.\d{4}) until further notice have been cancelled", flat)}
    by_route = {}
    for p, t in tts.items():
        ports, ships = timetable(t, os.path.basename(p))
        by_route.setdefault(frozenset(ports), set()).update(ships)
    lines, _ = lines_of(posm)
    pos = port_places(posm, lines, polsca.PORTS)
    for cid, ports in POLSCA:
        ships = by_route.get(frozenset(ports), set()) - {s.upper() for s in out_of_service}
        if not ships:
            sys.exit(f"ferry ships: no POLSCA timetable for {'–'.join(ports)}")
        if any(p not in pos for p in ports):
            sys.exit(f"ferry ships: {'–'.join(ports)}: ports not placed")
        gone = "".join(f"; {s} left out, its departures cancelled from {d} until further notice" for s, d in sorted(out_of_service.items())
                       if s.upper() in by_route.get(frozenset(ports), set()))
        crossings.append(crossing(cid, ports, pos, "POLSCA Baltic Ferries (Polferries, Unity Line)", ships,
                                  {"title": f"POLSCA Baltic Ferries: timetables (the ferry of each departure){gone}", "url": src["polsca-timetables"]["url"]}, ids))

    # Bornholmslinjen
    dk = decision[decision.find(" DENMARK "):decision.find(" GREECE ")]
    if "List of islands and ports as referred to in Article 12(3-d)" not in decision or "BORNHOLM ROENNE" not in dk:
        sys.exit("ferry ships: the Decision doesn't list Bornholm, Rønne")
    routes = bornholm(bpage)
    lines, _ = lines_of(bosm)
    pos = port_places(bosm, lines, dk_bornholm.PORTS)
    for cid, ports in BORNHOLM:
        ships = {f for f, r in routes.items() if ports[0] in r}
        if not ships:
            sys.exit(f"ferry ships: Bornholmslinjen names no ferry on {'–'.join(ports)}")
        if any(p not in pos for p in ports):
            sys.exit(f"ferry ships: {'–'.join(ports)}: ports not placed")
        ex = [{"from": FROM, "until": UNTIL, "law": f"{DECISION[0]} (Denmark: Bornholm, Rønne)", "url": DECISION[1]}] if {COUNTRY[p] for p in ports} == {"DK"} else []
        crossings.append(crossing(cid, ports, pos, "Bornholmslinjen", ships,
                                  {"title": "Bornholmslinjen: the ferries (each one's crossings)", "url": src["bornholm-ferries"]["url"]}, ids, ex))

    # Destination Gotland
    if " SWEDEN GOTLAND VISBY " not in decision[decision.find(" SWEDEN "):]:
        sys.exit("ferry ships: the Decision doesn't list Gotland, Visby")
    groutes = gotland(gpage)
    for ports in sorted({ps for r in groutes.values() for ps in r}):
        ships = {f for f, r in groutes.items() if ports in r}
        pos = osm_place(gosm, *ports, "Destination Gotland")
        if not pos:
            sys.exit(f"ferry ships: {'–'.join(ports)}: no OpenStreetMap line between its ports")
        COUNTRY.update({p: PORTS[p][0] for p in ports})
        cid = "-".join(re.sub(r"[^a-z0-9]+", "-", ascii(p)).strip("-") for p in ports)
        ex = [{"from": FROM, "until": UNTIL, "law": f"{DECISION[0]} (Sweden: Gotland, Visby)", "url": DECISION[1]}] if {COUNTRY[p] for p in ports} == {"SE"} else []
        crossings.append(crossing(cid, ports, pos, "Destination Gotland", ships,
                                  {"title": "Destination Gotland: our ferries (each one's route)", "url": src["gotland-ferries"]["url"]}, ids, ex))

    # Molslinjen
    mroutes = nuxt_routes(mpage, "Odden", ("Aarhus", "Ebeltoft"))
    for other in ("Aarhus", "Ebeltoft"):
        ships = {f for f, r in mroutes.items() if other in r}
        if not ships:
            sys.exit(f"ferry ships: Molslinjen names no ferry on Odden–{other}")
        ports = ("Odden", other)
        pos = osm_place(gosm, *ports, "Molslinjen")
        if not pos:
            sys.exit(f"ferry ships: Odden–{other}: no OpenStreetMap line between its ports")
        COUNTRY.update({p: PORTS[p][0] for p in ports})
        crossings.append(crossing("-".join(ascii(p) for p in ports), ports, pos, "Molslinjen", ships,
                                  {"title": "Molslinjen: the ferries (each one's crossings)", "url": src["mols-ferries"]["url"]}, ids))

    # TT-Line
    troutes, turl, tday = ttline(tcap)
    lines, _ = lines_of(tosm)
    pos = port_places(tosm, lines, TTLINE_PORTS)
    have = {c["id"]: c for c in crossings}
    title = f"TT-Line: freight timetable, the ship of each departure (read in Chrome on {tday}, tools/tables/browser/ttline-timetable.txt)"
    for cid, ports, route in TTLINE:
        ships = troutes.get(route)
        if not ships:
            sys.exit(f"ferry ships: TT-Line's capture has no {route}")
        if cid in have:
            c = have[cid]
            c["operator"] += "; TT-Line"
            c["ships"] = crossing(cid, ports, {p: (0, 0) for p in ports}, "", {s["name"] for s in c["ships"]} | ships, None, ids)["ships"]
            c["source"]["title"] += f"; {title}"
            continue
        if any(p not in pos for p in ports):
            sys.exit(f"ferry ships: {'–'.join(ports)}: ports not placed")
        crossings.append(crossing(cid, ports, pos, "TT-Line", ships, {"title": title, "url": turl}, ids))

    # Stena Line and Finnlines
    if not spages or not fpages or not ipages or not ppages or not dpages:
        sys.exit(f"ferry ships: {len(spages)} Stena Line, {len(fpages)} Finnlines, {len(ipages)} Irish Ferries, {len(ppages)} P&O Freight "
                 f"and {len(dpages)} DFDS route pages")
    have = {frozenset(t["name"] for t in c["terminals"]): c for c in crossings}
    for operator, routes in (("Stena Line", stena(spages)), ("Finnlines", finnlines(fpages, fsched)), ("Irish Ferries", irishferries(ipages)),
                             ("P&O Ferries", poferries(ppages)), ("DFDS", dfds(dpages, ship_names())), ("Tallink", tallink(tpage)),
                             ("Eckerö Line", eckero(epage)), ("Color Line", colorline(cpage)), ("Fjord Line", fjordline(jpage)),
                             ("Wasaline", wasaline(wpage)), ("Viking Line", katajanokka(kpage))):
        for ports, ships, heading, path in routes:
            if isinstance(ships, dict):
                # the page gives the IMO numbers
                ids = {**ids, **{ascii(s).upper(): imo for s, imo in ships.items() if imo}}
                ships = set(ships)
            url = urls.get(os.path.basename(path), "")
            title = f"{operator}: {heading}" + ("" if "its ferries" in heading else ", its ferries")
            c = have.get(frozenset(ports))
            if c:
                c["operator"] += f"; {operator}"
                c["ships"] = crossing(c["id"], ports, {p: (0, 0) for p in ports}, "", {s["name"] for s in c["ships"]} | {s.upper() for s in ships}, None, ids)["ships"]
                c["source"]["title"] += f"; {title} ({url})"
                continue
            pos = osm_place(gosm, *ports, operator)
            if not pos:
                print(f"ferry ships: {'–'.join(ports)}: not built (no OpenStreetMap line between its ports)")
                continue
            COUNTRY.update({p: PORTS[p][0] for p in ports})
            cid = "-".join(re.sub(r"[^a-z0-9]+", "-", ascii(p)).strip("-") for p in ports)
            c = crossing(cid, ports, pos, operator, ships, {"title": title, "url": url}, ids)
            crossings.append(c)
            have[frozenset(ports)] = c

    car = {i for i, _ in lines_of(gosm)[0]} | {w["id"] for w in gosm["elements"] if w.get("tags", {}).get("hgv") in ("yes", "designated")}

    # Crossings between an island port under the derogation and another
    # port of its Member State, by OpenStreetMap's lines (a line naming two
    # ports; one naming more calls on the way and isn't built): their ships
    # aren't named; the derogation is in force until 31 December 2030.
    states = {}
    for p, (state, island, port) in ISLANDS.items():
        part = decision[decision.find(f" {state} "):]
        part = part[:min([i for i in (part.find(f" {x} ", 2) for x in ("GREECE", "SPAIN", "CROATIA", "ITALY", "MALTA", "SWEDEN", "ANNEX II")) if i > 0] or [len(part)])]
        if f" {island} " not in part + " " or f" {port} " not in part + " ":
            sys.exit(f"ferry ships: the Decision doesn't list {state}: {island}, {port}")
        states[p] = state
    islands = {}
    for w in gosm["elements"]:
        if w["type"] != "way" or w["id"] not in car:
            continue
        ports = named_ports(w.get("tags", {}).get("name", ""))
        if len(ports) == 2 and any(p in ISLANDS for p in ports) and PORTS[ports[0]][0] == PORTS[ports[1]][0] != "GR":
            islands.setdefault(frozenset(ports), []).append(w)
    for key, ways in sorted(islands.items(), key=lambda kv: sorted(kv[0])):
        if key in have:
            continue
        a, b = sorted(key, key=lambda p: (p in ISLANDS, p))
        trucks = [w for w in ways if w["tags"].get("motor_vehicle") in ("yes", "designated") or w["tags"].get("hgv") in ("yes", "designated")]
        pos = osm_place({"elements": trucks or ways}, a, b, "")
        if not pos:
            continue
        COUNTRY.update({p: PORTS[p][0] for p in (a, b)})
        ex = [{"from": FROM, "until": UNTIL, "law": f"{DECISION[0]} ({ISLANDS[p][0].title()}: {ISLANDS[p][1]}, {ISLANDS[p][2]})", "url": DECISION[1]}
              for p in (a, b) if p in ISLANDS][:1]
        ops = sorted({w["tags"]["operator"] for w in trucks or ways if w["tags"].get("operator")})
        cid = "-".join(re.sub(r"[^a-z0-9]+", "-", ascii(p)).strip("-") for p in (a, b))
        c = crossing(cid, (a, b), pos, "; ".join(ops), set(), {
            "title": "OpenStreetMap: " + "; ".join(sorted({w["tags"]["name"] for w in trucks or ways})) + " (its ships not named)",
            "url": f"https://www.openstreetmap.org/way/{min(w['id'] for w in trucks or ways)}"}, ids, ex)
        crossings.append(c)
        have[key] = c

    # Greece: OpenStreetMap's lines (gr-ferries-osm) by their English names,
    # each part of the name one of a port's names in GREECE.
    folded = {fold(x): p for p in GREECE for x in PORTS[p][1]} | {fold(x): p for p in ("Chios", "Mytilene", "Lavrio", "Igoumenitsa", "Patras")
                                                                  for x in PORTS[p][1]}
    en = {"elements": [{**w, "tags": {**w.get("tags", {}), "name": w.get("tags", {}).get("name:en") or w.get("tags", {}).get("name", "")}}
                       for w in grosm.get("elements", []) if w["type"] == "way"]}
    gcar = {i for i, _ in lines_of(en)[0]} | {w["id"] for w in en["elements"] if w["tags"].get("hgv") in ("yes", "designated")}
    gr = {}
    for w in en["elements"]:
        parts = [folded.get(fold(x.strip())) for x in re.split(r"\s+[-–]\s+", w["tags"]["name"])]
        if w["id"] in gcar and len(parts) == 2 and all(parts) and parts[0] != parts[1] and any(p in ISLANDS for p in parts):
            gr.setdefault(frozenset(parts), []).append(w)
    for key, ways in sorted(gr.items(), key=lambda kv: sorted(kv[0])):
        if key in have:
            continue
        a, b = sorted(key, key=lambda p: (p in ISLANDS, p))
        trucks = [w for w in ways if w["tags"].get("motor_vehicle") in ("yes", "designated") or w["tags"].get("hgv") in ("yes", "designated")]
        pos = osm_place({"elements": trucks or ways}, a, b, "")
        if not pos:
            continue
        COUNTRY.update({p: PORTS[p][0] for p in (a, b)})
        ex = [{"from": FROM, "until": UNTIL, "law": f"{DECISION[0]} (Greece: {ISLANDS[p][1]}, {ISLANDS[p][2]})", "url": DECISION[1]}
              for p in (b, a) if p in ISLANDS][:1]
        ops = sorted({w["tags"]["operator"] for w in trucks or ways if w["tags"].get("operator")})
        cid = "-".join(re.sub(r"[^a-z0-9]+", "-", ascii(p)).strip("-") for p in (a, b))
        c = crossing(cid, (a, b), pos, "; ".join(ops), set(), {
            "title": "OpenStreetMap: " + "; ".join(sorted({w["tags"]["name"] for w in trucks or ways})) + " (its ships not named)",
            "url": f"https://www.openstreetmap.org/way/{min(w['id'] for w in trucks or ways)}"}, ids, ex)
        crossings.append(c)
        have[key] = c

    # Crossings to and from ports outside the EU and the EEA, by
    # OpenStreetMap's lines: their ships aren't named, but the ports' countries
    # give the share of the emissions under the EU ETS.
    pairs = {}
    for w in gosm["elements"]:
        if w["type"] != "way" or w["id"] not in car:
            continue
        name = w.get("tags", {}).get("name", "")
        ports = named_ports(name)
        if len(ports) != 2 or all(PORTS[p][0] in EEA for p in ports):
            continue
        pairs.setdefault(frozenset(ports), []).append(w)
    for key, ways in sorted(pairs.items(), key=lambda kv: sorted(kv[0])):
        if key in have:
            # An operator's page named this crossing's ships: say which other
            # operators OpenStreetMap's lines name, whose ships aren't in it.
            ops = sorted({o.strip() for w in ways for o in re.split(r"[;/,]", w["tags"].get("operator", "")) if o.strip()})
            same = lambda x: re.sub(r"\s*&\s*", "&", fold(x))
            others = [o for o in ops if not any(same(x) in same(o) or same(o) in same(x) for x in re.split(r";\s*", have[key]["operator"]))]
            if others and "also name" not in have[key]["source"]["title"]:
                have[key]["source"]["title"] += f"; OpenStreetMap's lines also name {', '.join(others)}, whose ships aren't in it"
            continue
        a, b = sorted(key, key=lambda p: (PORTS[p][0] in EEA, p))
        pos = osm_place(gosm, a, b, "")
        if not pos:
            continue
        COUNTRY.update({p: PORTS[p][0] for p in (a, b)})
        ops = sorted({w["tags"]["operator"] for w in ways if w["tags"].get("operator")})
        cid = "-".join(re.sub(r"[^a-z0-9]+", "-", ascii(p)).strip("-") for p in (a, b))
        c = crossing(cid, (a, b), pos, "; ".join(ops), set(), {
            "title": "OpenStreetMap: " + "; ".join(sorted({w["tags"]["name"] for w in ways})) + " (its ships not named; the ports' countries)",
            "url": f"https://www.openstreetmap.org/way/{min(w['id'] for w in ways)}"}, ids)
        crossings.append(c)
        have[key] = c

    crossings.sort(key=lambda c: c["id"])
    os.makedirs(out, exist_ok=True)
    doc = {"note": "Ferry crossings with the ships their operators' timetables and pages name, built by tools/tables/ferry_ships.py; "
                   "IMO numbers from the EU MRV reports' ship lists.", "crossings": crossings}
    path = os.path.join(out, "crossings-ships.json")
    json.dump(doc, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(crossings), "crossings")


if __name__ == "__main__":
    if sys.argv[1:] == ["--osm-query"]:
        print("\n".join(osm_query()))
    else:
        main(*sys.argv[1:])
