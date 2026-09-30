import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = path.resolve("outputs/datadeck-fixtures");
const outputPath = path.join(outputDir, "berufsberatung_kundendaten_realistisch.xlsx");

const firstNames = [
  "Anna", "Ben", "Clara", "David", "Elif", "Felix", "Greta", "Hannes", "Ida", "Jonas",
  "Kira", "Leon", "Mara", "Noah", "Paula", "Quirin", "Rana", "Simon", "Tara", "Yusuf",
];
const lastNames = [
  "Weber", "Schmidt", "Fischer", "Wagner", "Becker", "Hoffmann", "Klein", "Richter",
  "Wolf", "Schroeder", "Neumann", "Krause", "Lehmann", "Schwarz", "Zimmermann",
];
const cities = [
  ["Hamburg", "Nord"], ["Berlin", "Ost"], ["Koeln", "West"], ["Muenchen", "Sued"],
  ["Frankfurt", "Mitte"], ["Stuttgart", "Sued"], ["Dresden", "Ost"], ["Bremen", "Nord"],
];
const services = [
  { name: "Erstberatung Karriere", category: "Einzelberatung", price: 149, cost: 42, sessions: 1 },
  { name: "Bewerbungsunterlagen Check", category: "Dokumentenservice", price: 189, cost: 68, sessions: 1 },
  { name: "LinkedIn Profiloptimierung", category: "Dokumentenservice", price: 249, cost: 86, sessions: 1 },
  { name: "Interviewtraining", category: "Einzelberatung", price: 349, cost: 128, sessions: 2 },
  { name: "Berufliche Neuorientierung", category: "Coaching-Paket", price: 890, cost: 355, sessions: 5 },
  { name: "Outplacement Begleitung", category: "Premium-Paket", price: 1890, cost: 790, sessions: 8 },
  { name: "Assessment Center Training", category: "Workshop", price: 520, cost: 210, sessions: 3 },
  { name: "Azubi Berufsorientierung", category: "Junge Talente", price: 129, cost: 58, sessions: 1 },
  { name: "Studienwahl Beratung", category: "Junge Talente", price: 219, cost: 95, sessions: 2 },
  { name: "Fuehrungskraefte Coaching", category: "Premium-Paket", price: 1450, cost: 520, sessions: 6 },
];
const channels = ["Google Suche", "Empfehlung", "LinkedIn", "Arbeitsagentur", "Unternehmenspartner", "Website"];
const statuses = ["abgeschlossen", "abgeschlossen", "abgeschlossen", "in_bearbeitung", "storniert"];
const paymentMethods = ["Karte", "SEPA", "Rechnung", "PayPal"];
const advisors = ["L. Berger", "M. Stein", "A. Voigt", "S. Keller"];

function pseudoRandom(seed) {
  let value = seed % 2147483647;
  return () => {
    value = (value * 48271) % 2147483647;
    return value / 2147483647;
  };
}

const random = pseudoRandom(20260926);

function pick(list) {
  return list[Math.floor(random() * list.length)];
}

function round2(value) {
  return Math.round(value * 100) / 100;
}

function dateForIndex(index) {
  const start = Date.UTC(2024, 0, 3);
  const dayOffset = Math.floor(index * 1.8 + random() * 8);
  return new Date(start + dayOffset * 24 * 60 * 60 * 1000);
}

function makeCustomer(index) {
  const first = pick(firstNames);
  const last = pick(lastNames);
  const [city, region] = pick(cities);
  const type = random() > 0.82 ? "Firmenkunde" : "Privatkunde";
  const domain = type === "Firmenkunde" ? "firma-beispiel.de" : "mail-beispiel.de";
  return {
    id: `K-${String(index).padStart(5, "0")}`,
    first,
    last,
    city,
    region,
    type,
    email: `${first.toLowerCase()}.${last.toLowerCase()}${index}@${domain}`,
    phone: `+49 1${Math.floor(500000000 + random() * 399999999)}`,
    targetRole: pick(["Marketing Manager", "Controller", "Software Developer", "HR Specialist", "Vertrieb", "Teamleitung", "Ausbildung", "Studium"]),
  };
}

const customers = Array.from({ length: 420 }, (_, i) => makeCustomer(i + 1));

const transactionHeaders = [
  "Buchungs-ID", "Datum", "Kunden-ID", "Kundentyp", "Region", "Stadt", "Leistung",
  "Segment", "Zielrolle", "Kanal", "Berater", "Status", "Zahlungsstatus",
  "Zahlungsart", "Sitzungen", "Umsatz", "Kosten", "Gewinn",
  "Marge", "Rabatt", "Kunden-E-Mail", "Kunden-Telefon", "Notiz",
];
const transactionRows = [];
for (let i = 1; i <= 2400; i += 1) {
  const customer = pick(customers);
  const service = pick(services);
  const date = dateForIndex(i);
  const status = pick(statuses);
  const discount = random() > 0.78 ? round2(service.price * (0.05 + random() * 0.15)) : 0;
  const volumeFactor = customer.type === "Firmenkunde" ? 1 + Math.floor(random() * 4) * 0.35 : 1;
  const cancelledFactor = status === "storniert" ? 0.25 : 1;
  const revenue = round2((service.price * volumeFactor - discount) * cancelledFactor);
  const variableLoad = 0.86 + random() * 0.28;
  const cost = round2((service.cost * volumeFactor * variableLoad + (status === "in_bearbeitung" ? 24 : 0)) * cancelledFactor);
  const profit = round2(revenue - cost);
  const margin = revenue > 0 ? round2(profit / revenue) : null;
  const paid = status === "storniert" ? "erstattet" : (random() > 0.08 ? "bezahlt" : "offen");
  transactionRows.push([
    `B-${String(i).padStart(6, "0")}`,
    date,
    customer.id,
    customer.type,
    customer.region,
    customer.city,
    service.name,
    service.category,
    customer.targetRole,
    pick(channels),
    pick(advisors),
    status,
    paid,
    pick(paymentMethods),
    service.sessions,
    revenue,
    cost,
    profit,
    margin,
    discount,
    customer.email,
    customer.phone,
    status === "storniert"
      ? "Synthetischer Testfall mit Storno, keine echte Person."
      : "Synthetischer Beratungsfall fuer DataDeck Tests, keine echte Person.",
  ]);
}

const customerHeaders = [
  "Kunden-ID", "Vorname", "Nachname", "Kundentyp", "Stadt", "Region",
  "E-Mail", "Telefon", "Zielrolle",
];
const customerRows = customers.map((customer) => [
  customer.id,
  customer.first,
  customer.last,
  customer.type,
  customer.city,
  customer.region,
  customer.email,
  customer.phone,
  customer.targetRole,
]);

const totalRevenue = round2(transactionRows.reduce((sum, row) => sum + row[15], 0));
const totalCost = round2(transactionRows.reduce((sum, row) => sum + row[16], 0));
const totalProfit = round2(transactionRows.reduce((sum, row) => sum + row[17], 0));
const totalMargin = totalRevenue > 0 ? round2(totalProfit / totalRevenue) : 0;

const workbook = Workbook.create();
const transactions = workbook.worksheets.add("Buchungen");
const summary = workbook.worksheets.add("Zusammenfassung");
const customerSheet = workbook.worksheets.add("Kundenstamm");
const notes = workbook.worksheets.add("Annahmen");

transactions.getRange("A1:W1").values = [transactionHeaders];
transactions.getRangeByIndexes(1, 0, transactionRows.length, transactionHeaders.length).values = transactionRows;
transactions.freezePanes.freezeRows(1);
transactions.showGridLines = false;
transactions.getRange("A1:W1").format.fill.color = "#24324A";
transactions.getRange("A1:W1").format.font.color = "#FFFFFF";
transactions.getRange("A1:W1").format.font.bold = true;
transactions.getRange("A1:W1").format.horizontalAlignment = "center";
transactions.getRange("A:W").format.font.name = "Arial";
transactions.getRange("B:B").setNumberFormat("yyyy-mm-dd");
transactions.getRange("O:O").setNumberFormat("#,##0");
transactions.getRange("P:R").setNumberFormat('"€"#,##0.00');
transactions.getRange("S:S").setNumberFormat("0.0%");
transactions.getRange("T:T").setNumberFormat('"€"#,##0.00');
transactions.getRange("A:W").format.autofitColumns();
transactions.getRange("W:W").format.columnWidth = 42;
transactions.getRange("W:W").format.wrapText = true;

customerSheet.getRange("A1:I1").values = [customerHeaders];
customerSheet.getRangeByIndexes(1, 0, customerRows.length, customerHeaders.length).values = customerRows;
customerSheet.freezePanes.freezeRows(1);
customerSheet.showGridLines = false;
customerSheet.getRange("A1:I1").format.fill.color = "#24324A";
customerSheet.getRange("A1:I1").format.font.color = "#FFFFFF";
customerSheet.getRange("A1:I1").format.font.bold = true;
customerSheet.getRange("A:I").format.font.name = "Arial";
customerSheet.getRange("A:I").format.autofitColumns();

summary.getRange("A1").values = [["Berufsberatung Testdaten"]];
summary.getRange("A2").values = [["Synthetische, realistische Buchungsdaten fuer DataDeck Importtests. Keine echten Personen oder Unternehmen."]];
summary.getRange("A4:B10").values = [
  ["Kennzahl", "Wert"],
  ["Buchungen", transactionRows.length],
  ["Kunden", customers.length],
  ["Umsatz", totalRevenue],
  ["Kosten", totalCost],
  ["Gewinn", totalProfit],
  ["Marge", totalMargin],
];
summary.getRange("A12:D22").values = [
  ["Spalte", "Bedeutung", "Datentyp", "DataDeck Erwartung"],
  ["datum", "Buchungsdatum", "Datum", "Zeitverlauf"],
  ["leistung", "Beratungsprodukt", "Text", "Kategorie"],
  ["segment", "Produktgruppe", "Text", "Kategorie"],
  ["Umsatz", "Netto-Umsatz je Buchung", "Zahl", "Umsatz"],
  ["Kosten", "Direkte Kosten je Buchung", "Zahl", "Kosten"],
  ["Gewinn", "Umsatz minus Kosten", "Zahl", "Gewinn"],
  ["Marge", "Gewinn geteilt durch Umsatz", "Prozent", "Optional"],
  ["Kunden-E-Mail", "Synthetische E-Mail", "Text", "DSGVO-Scanner"],
  ["Kunden-Telefon", "Synthetische Telefonnummer", "Text", "DSGVO-Scanner"],
  ["Status", "Bearbeitungsstatus", "Text", "Filter/Segment"],
];
summary.showGridLines = false;
summary.getRange("A1").format.font.bold = true;
summary.getRange("A1").format.font.size = 16;
summary.getRange("A4:B4").format.fill.color = "#24324A";
summary.getRange("A4:B4").format.font.color = "#FFFFFF";
summary.getRange("A4:B4").format.font.bold = true;
summary.getRange("A12:D12").format.fill.color = "#24324A";
summary.getRange("A12:D12").format.font.color = "#FFFFFF";
summary.getRange("A12:D12").format.font.bold = true;
summary.getRange("B7:B9").setNumberFormat('"€"#,##0.00');
summary.getRange("B10").setNumberFormat("0.0%");
summary.getRange("A:D").format.font.name = "Arial";
summary.getRange("A:D").format.autofitColumns();
summary.getRange("B:B").format.columnWidth = 64;
summary.getRange("B:B").format.wrapText = true;

notes.getRange("A1:B9").values = [
  ["Annahme", "Wert"],
  ["Datentyp", "Synthetische Beratungsbuchungen"],
  ["Zeitraum", "2024-01 bis 2035-10"],
  ["Branche", "Berufsberatung und Karriere-Coaching"],
  ["Personenbezug", "Alle Namen, E-Mails und Telefonnummern sind synthetisch"],
  ["Umsatzlogik", "Leistungspreis minus Rabatt, bei Firmenkunden volumenadjustiert"],
  ["Kostenlogik", "Direkte Beraterzeit, Material- und Plattformkosten"],
  ["Gewinnlogik", "umsatz_eur minus kosten_eur"],
  ["Quelle", "Von DataDeck generierte Testdaten"],
];
notes.showGridLines = false;
notes.getRange("A1:B1").format.fill.color = "#24324A";
notes.getRange("A1:B1").format.font.color = "#FFFFFF";
notes.getRange("A1:B1").format.font.bold = true;
notes.getRange("A:B").format.font.name = "Arial";
notes.getRange("A:B").format.autofitColumns();
notes.getRange("B:B").format.columnWidth = 72;
notes.getRange("B:B").format.wrapText = true;

await fs.mkdir(outputDir, { recursive: true });

const preview = await workbook.inspect({
  kind: "table",
  sheetId: "Buchungen",
  range: "A1:W8",
  include: "values",
  tableMaxRows: 8,
  tableMaxCols: 23,
  maxChars: 6000,
});
console.log(preview.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

const rendered = await workbook.render({ sheetName: "Zusammenfassung", range: "A1:D22", scale: 1 });
const renderedBytes = new Uint8Array(await rendered.arrayBuffer());
await fs.writeFile(path.join(outputDir, "berufsberatung_preview.png"), renderedBytes);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, rows: transactionRows.length, customers: customers.length, totalRevenue, totalCost, totalProfit }));
