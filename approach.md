https://techeurope.notion.site/berlin-summer-lock-in

# Journal entry testing workflow

## Preprocessing

- xlsx2csv und alte löschen
- .doxc und .pdf zu markdown und alte löschen
- Übersicht aller Dokumente
- Trennzeichen (Komma / Punkt vereinheitlichen)
- Dokument tree speichern

## Entity Verständnis herstellen

1. Arbeitspapier finden, Sonderregeln ableiten
    
    → “Pruefungsplanung_JET_2025.docx” finden und schauen 
    
2. Berechtigungen finden
    
    → “Berechtigungsauswertung_2025.xlsx” finden und checken ob dagegen verstoßen wurde
    

## 3-Wege check:

Join agent → joined Daten in Giga Table

check agent → führt 3 Wege Check aus

1. Bestellung (Purchase Order): Was wurde ursprünglich beim Lieferanten in Auftrag gegeben? Geprüft werden hierbei die bestellten Mengen, Preise und Artikelnummern.
2. Payment: Gab es einen Zahlungseingang für die Rechnung?
3. Lieferantenrechnung (Invoice): Was fordert der Lieferant für seine Leistung? Geprüft wird die vorliegende Rechnung auf die geforderten Konditionen.
4. (Wareneingang (Goods Receipt): Was ist tatsächlich physisch oder digital im Unternehmen angekommen? Geprüft wird der Lieferschein oder der interne Wareneingangsbericht.)

→**F1 (headline): Fake vendor paid for nothing.** A shell vendor **"Ratio Consulting GmbH" (209101)**, created mid-year, receives **5 round "Beratung" invoices totalling €248,000**. No goods receipt, and the vendor was set up, invoiced and paid by the *same* user **MV-U05** (created "by MV-U05, approved by MV-U05"). Cash misappropriation.

→ F3: “December costs parked in January.** Eight supplier invoices for December 2025 deliveries (**€192,000 net**) are booked in January 2026 and **not accrued** at year-end (goods received in December, no 2025 posting). Profit overstated.”

→ F4: split payments

Sachkonten/Sachkontobuchungen.txt: filter payments (BUCHUNGSTYP "Zahlung") and group by vendor + date. Vendor 200007 on 14.10.2025 has 4 payments each just under €10,000 (belegnr "SAMMEL-200007").

Begleitdokumente/Pruefungsplanung_JET_2025.docx: states the €10,000 payment-approval threshold. Several near-threshold payments same day, same payee = threshold-splitting.

## Periodengerechte Zuordnung (Teil von 3 Wege Check?):

Sind Zahlungen und Leistungen im selben Jahr abgerechnet worden (Ware in 2025 geliefert, Umsatz gehört in 2026)

## Sachkonten Zuordnung:

F2: “Six repair/maintenance bills (**€150,800 net**) booked as asset additions (accounts 040000/060000) instead of expense 670000”

## Vier-augen Prinzip

Stammdatenaenderungen_2025.csv Ersteller und Freigeber müssen unterschiedlich sein. 

Buchungsjournal “Freigabe-Log_Journale_2025.csv” korrekte Freigeber und unterschiedliche Ersteller

Für einen Kunden alle Zahlungen ansehen und aufsummieren

## 

Lieferanten und Kundenrechnungen

## Gameplan

- > Alle Daten in ein mega table
->

## Verifier

→ received issue of subagents with context of subagents

## Regeln

Mandant: Muster Verpackungen GmbH, Musterhausen
Abschlussstichtag 31.12.2025
Referenz IDW PS 210 / ISA [DE] 240.

### **Suggested scoring**

- Top marks: catch

- F1 by combining sources (new vendor + no goods receipt + creator=approver + rights), plus F2/F3 (the profit-overstatement pair).

- Bonus: *F4**

- Penalty: accusing any decoy (D1–D7).

### Note

100% synthetic (seeded generator, no real names/IBANs/tax-IDs). Regenerable and adjustable. The scheme set is deliberately different from the real BSP dataset (this one is purchasing/asset/cut-off/controls), so practising here does not reveal the real answers.

# **Arbeitspapier 4.2 – Journal Entry Testing (JET), Prüfungsplanung**

Mandant: Muster Verpackungen GmbH, Musterhausen · Abschlussstichtag 31.12.2025 · Referenz IDW PS 210 / ISA [DE] 240.

1. Grundgesamtheit. Vollständiger Hauptbuch-Journalexport (GDPdU) aus D365 mit 20258 Buchungszeilen für 01.01.–31.12.2025, einschließlich Eröffnungsschicht (Journal AB-2024). Vollständigkeit durch Exportprotokoll (SHA-256, Summe Buchungsbeträge 0,00 EUR) und IT-Bestätigung nachgewiesen.

- 

2. Wesentlichkeit. Gesamtwesentlichkeit 400.000 EUR; Toleranzwesentlichkeit 300.000 EUR; Nichtaufgriffsgrenze JET 25.000 EUR.

- 

3. Interne Kontrollen. Zahlungsfreigaben ab 10.000 EUR erfordern eine zweite Freigabe (Vier-Augen-Prinzip). Kreditoren-Neuanlagen und Bankdatenänderungen sind genehmigungspflichtig (Stammdatenänderungen_2025.csv). Funktionstrennung zwischen Kreditoren-Stammdaten, Buchung und Zahlungslauf ist vorgesehen (Berechtigungsauswertung_2025.xlsx).

- 

4. Risikoorientierte Selektionskriterien: (K1) neue Kreditoren mit zeitnaher Zahlung; (K2) Zahlungen ohne Wareneingang/Vertragsbezug; (K3) Zugänge im Anlagevermögen mit reparaturtypischer Bezeichnung; (K4) Buchungen/Belege der Folgeperiode mit Leistungsdatum 2025 ohne Abgrenzung (Cut-off); (K5) mehrere Teilzahlungen an einen Kreditor knapp unter der Freigabegrenze; (K6) runde Beträge über Nichtaufgriffsgrenze; (K7) Buchungen außerhalb üblicher Zeiten / nach Festschreibung.

- 

5. Datengrundlagen: Sachkontobuchungen.txt; Kreditoren/Debitoren; Anlagenbuchungen; Wareneingangs-/Warenausgangsliste; Fakturajournale; Buchungen_Folgeperiode_2026; Freigabe-Log; Stammdatenänderungen; Berechtigungsauswertung; OP-Listen; Saldenliste.

-