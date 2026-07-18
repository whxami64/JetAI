# Arbeitspapier 4.2 – Journal Entry Testing (JET), Prüfungsplanung

Mandant: Muster Verpackungen GmbH, Musterhausen · Abschlussstichtag 31.12.2025 · Referenz IDW PS 210 / ISA [DE] 240.

1. Grundgesamtheit. Vollständiger Hauptbuch-Journalexport (GDPdU) aus D365 mit 20258 Buchungszeilen für 01.01.–31.12.2025, einschließlich Eröffnungsschicht (Journal AB-2024). Vollständigkeit durch Exportprotokoll (SHA-256, Summe Buchungsbeträge 0,00 EUR) und IT-Bestätigung nachgewiesen.

2. Wesentlichkeit. Gesamtwesentlichkeit 400.000 EUR; Toleranzwesentlichkeit 300.000 EUR; Nichtaufgriffsgrenze JET 25.000 EUR.

3. Interne Kontrollen. Zahlungsfreigaben ab 10.000 EUR erfordern eine zweite Freigabe (Vier-Augen-Prinzip). Kreditoren-Neuanlagen und Bankdatenänderungen sind genehmigungspflichtig (Stammdatenänderungen\_2025.csv). Funktionstrennung zwischen Kreditoren-Stammdaten, Buchung und Zahlungslauf ist vorgesehen (Berechtigungsauswertung\_2025.xlsx).

4. Risikoorientierte Selektionskriterien: (K1) neue Kreditoren mit zeitnaher Zahlung; (K2) Zahlungen ohne Wareneingang/Vertragsbezug; (K3) Zugänge im Anlagevermögen mit reparaturtypischer Bezeichnung; (K4) Buchungen/Belege der Folgeperiode mit Leistungsdatum 2025 ohne Abgrenzung (Cut-off); (K5) mehrere Teilzahlungen an einen Kreditor knapp unter der Freigabegrenze; (K6) runde Beträge über Nichtaufgriffsgrenze; (K7) Buchungen außerhalb üblicher Zeiten / nach Festschreibung.

5. Datengrundlagen: Sachkontobuchungen.txt; Kreditoren/Debitoren; Anlagenbuchungen; Wareneingangs-/Warenausgangsliste; Fakturajournale; Buchungen\_Folgeperiode\_2026; Freigabe-Log; Stammdatenänderungen; Berechtigungsauswertung; OP-Listen; Saldenliste.