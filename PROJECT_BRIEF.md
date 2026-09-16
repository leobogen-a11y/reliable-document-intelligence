# Project Brief: Reliable Document Intelligence

Stand: 15. September 2026  
Phase: 1 – Problem & Product Definition  
Arbeitstitel: **Reliable Document Intelligence**

## Problem

Belege enthalten strukturierte Informationen, liegen aber als Bilder oder PDFs
in sehr unterschiedlichen Layouts und Qualitäten vor. Eine falsche Extraktion
kann zu fehlerhaften Buchungen führen. Ein produktives System darf deshalb
nicht nur Werte vorhersagen: Es muss seine Ausgaben validieren, Unsicherheit
sichtbar machen und unklare Fälle kontrolliert zur Prüfung weitergeben.

## Zielnutzer

Eine fiktive Mitarbeiterin in der vorbereitenden Buchhaltung oder im
Expense-Management, die regelmäßig Belege in ein strukturiertes System
übertragen und fehlerhafte Ergebnisse schnell erkennen muss.

## Job to be done

> Wenn ich einen Beleg erhalte, möchte ich die relevanten Positionen und Summen
> automatisch als validierte, strukturierte Daten erhalten, damit ich nur noch
> unsichere oder widersprüchliche Felder manuell prüfen muss.

## Bestätigte Produktentscheidungen

### Fehlerkosten

Ein falsch automatisch akzeptierter Beleg ist schwerwiegender als ein korrekt
extrahierter Beleg, der unnötig zur Prüfung weitergeleitet wird. Das System wird
daher **präzisionsorientiert** entworfen:

- Im Zweifel wird ein Beleg nicht automatisch akzeptiert.
- Kritische Felder werden einzeln und auf Dokumentebene validiert.
- Die Automatisierungsrate wird nicht auf Kosten unbemerkter Fehler maximiert.
- Confidence allein genügt nicht; auch fachliche Prüfregeln beeinflussen die
  Review-Entscheidung.

### Gewünschte Informationen

Das fachliche Zielschema soll enthalten:

- Beschreibung einer Position,
- Anzahl beziehungsweise Menge,
- Stückpreis,
- Gesamtpreis der Position,
- Gesamtpreis des Belegs,
- Steuer,
- Währung.

Fehlende Angaben dürfen nicht erfunden werden. Anzahl, Stückpreis, Steuer und
Währung können je nach Beleg explizit vorhanden, implizit oder unbekannt sein.
Das Schema muss diese Zustände voneinander unterscheiden können.

### Nutzenhypothese

Der Nutzen wird durch Qualität **und** eingesparte menschliche Bearbeitungszeit
gemessen. Ein sinnvoller Vergleich berücksichtigt nicht nur die Laufzeit des
Modells, sondern den gesamten Prozess einschließlich manueller Prüfung und
Korrektur.

## Produktversprechen

Das System liefert nicht einfach JSON. Es trennt zwischen:

- extrahierten Werten,
- Belegen beziehungsweise Fundstellen im Dokument,
- technischer Schema-Validierung,
- fachlicher Konsistenzprüfung,
- Unsicherheit,
- und der Entscheidung „automatisch akzeptieren“ oder „manuell prüfen“.

## Vorläufiger MVP

### Eingabe

- ein einzelner Beleg als JPEG, PNG oder einseitige PDF-Datei
- zunächst ein Dokument pro Verarbeitungsvorgang

### Ausgabe

- normalisierte Positionen mit Beschreibung, Menge, Stückpreis und
  Positionsgesamtpreis, soweit vorhanden
- Zwischensumme, Steuer und Gesamtbetrag des Belegs, soweit vorhanden
- Währung, sofern zuverlässig bestimmbar
- Validierungsstatus pro Feld
- Unsicherheits- oder Konfidenzinformation
- Liste erkannter Widersprüche
- Gesamtentscheidung: automatisch akzeptierbar oder manuelle Prüfung notwendig

### Fachliche Validierung

Beispiele für deterministische Prüfungen:

- Summe der Positionen ist mit der Gesamtsumme vereinbar
- Zwischensumme plus Steuer entspricht ungefähr dem Gesamtbetrag
- Geldbeträge lassen sich eindeutig normalisieren
- Pflichtfelder sind vorhanden
- erkannte Währung und Betragsformat widersprechen sich nicht

## Nicht Bestandteil des ersten MVP

- vollständiges Buchhaltungssystem
- Zahlungsabwicklung
- Benutzer- und Rollenverwaltung
- mehrere Dokumenttypen gleichzeitig
- produktive Verarbeitung personenbezogener oder vertraulicher Belege
- RAG
- Agenten-Orchestrierung
- Kubernetes oder verteilte Microservices
- eigenes Training eines großen Vision-Language-Modells

## Zu vergleichende Ansätze

Mindestens zwei Ansätze sollen auf demselben Testset verglichen werden:

1. **Einfache Baseline:** OCR plus deterministische Normalisierung und Regeln.
2. **AI-basierter Ansatz:** multimodales Modell oder OCR plus Sprachmodell mit
   schema-validierter strukturierter Ausgabe.

Ein spezialisiertes lokales Document-AI-Modell ist eine spätere Option, aber
keine Voraussetzung für den MVP.

## Evaluationsfragen

1. Wie korrekt werden einzelne Felder und Positionen extrahiert?
2. Wie oft ist die erzeugte Ausgabe formal valide?
3. Welche Fehler erkennt die fachliche Validierung?
4. Wie zuverlässig trennt das System sichere von unsicheren Fällen?
5. Welcher Anteil kann bei einem vorgegebenen Qualitätsziel automatisch
   verarbeitet werden?
6. Wie unterscheiden sich die Ansätze bei Qualität, Latenz und Kosten?
7. Wie viel menschliche Bearbeitungszeit spart das Gesamtsystem nach Einbezug
   der Review- und Korrekturzeit?

## Vorläufige Metriken

- Exact Match und normalisierter Stringvergleich pro Feld
- Precision, Recall und F1 für extrahierte Positionen
- Schema-valid rate
- arithmetic consistency rate
- Fehlerquote der automatisch akzeptierten Dokumente
- Coverage bei definierten Qualitätsgrenzen
- Latenz pro Dokument
- Kosten pro Dokument bei externen Modellen
- manuelle Extraktionszeit als kleine Human-Baseline
- menschliche Review- und Korrekturzeit für vom System vorbereitete Belege
- geschätzte End-to-End-Zeitersparnis pro Dokument beziehungsweise 100 Belege

Die endgültigen Metriken werden erst nach Sichtung der Annotationen und einer
Baseline festgelegt.

Für die Review-Logik werden mindestens zwei Größen getrennt betrachtet:

- **False-Accept-Rate:** Anteil automatisch akzeptierter Belege, die kritische
  Fehler enthalten.
- **Coverage/Automation Rate:** Anteil aller Belege, die automatisch akzeptiert
  werden können.

Ziel ist eine möglichst hohe Coverage unter einer strengen Grenze für falsche
Akzeptanzen. Die numerische Grenze wird erst festgelegt, wenn Größe und Qualität
des Testsets bekannt sind.

## Datenhypothese

Als primäre Ausgangsbasis wird **CORD v2** geprüft. Der Datensatz umfasst 1.000
annotierte Belege mit festem Train-/Validation-/Test-Split und ist unter
CC BY 4.0 verfügbar. Seine hierarchischen Annotationen enthalten insbesondere
Positionen und Summen.

Vorteile:

- reproduzierbarer öffentlicher Benchmark
- Ground Truth für objektive Evaluation
- überschaubare Größe
- kein eigenes großflächiges Labeling zum Projektstart

Bekannte Einschränkungen:

- überwiegend indonesische Belege
- begrenzte Übertragbarkeit auf deutsche Belege
- einige ursprünglich vorhandene Feldklassen wurden aus rechtlichen Gründen
  aus der öffentlichen Version entfernt
- Währung und bestimmte Steuerfelder sind nicht durchgängig als Ground Truth
  vorhanden; gewünschtes Geschäftsschema und evaluierbares Benchmark-Schema
  müssen deshalb getrennt betrachtet werden
- der Datensatz bildet keinen realen deutschen Buchhaltungsprozess vollständig
  ab

Die Daten werden nicht ungeprüft in das Git-Repository aufgenommen. Download,
Lizenzhinweis, Version und Split müssen reproduzierbar dokumentiert werden.

Als mögliche sekundäre Datenbasis wird SROIE geprüft. Eine Kombination beider
Datensätze erfolgt nur, wenn deren unterschiedliche Schemas den MVP nicht
unnötig verkomplizieren.

### Erste Prüfung des CORD-v2-Schemas

| Gewünschtes Geschäftsfeld | CORD-v2-Annotation | Erste Einschätzung |
|---|---|---|
| Beschreibung | `menu.nm` | direkt evaluierbar |
| Anzahl/Menge | `menu.cnt` | evaluierbar, aber nicht durchgängig vorhanden und unterschiedlich formatiert |
| Stückpreis | `menu.unitprice` | evaluierbar, aber häufig nicht explizit vorhanden |
| Positionsgesamtpreis | `menu.price` | direkt evaluierbar |
| Beleg-Zwischensumme | `subtotal.subtotal_price` | optional evaluierbar |
| Steuer | `subtotal.tax_price` | optional evaluierbar |
| Beleg-Gesamtpreis | `total.total_price` | direkt evaluierbar, sofern im Beleg vorhanden |
| Währung | keine eigene verlässliche Annotation | nicht direkt mit CORD evaluierbar |

Konsequenzen:

- Das interne Produktschema darf Währung enthalten, aber CORD allein kann die
  Währungserkennung nicht objektiv bewerten.
- Fehlende Menge oder fehlender Stückpreis bedeuten nicht automatisch einen
  Modellfehler. Ground Truth und Metriken müssen zwischen „nicht angegeben“ und
  „nicht erkannt“ unterscheiden.
- Positionspreis und Beleg-Gesamtpreis müssen im Schema eindeutig getrennt
  werden.
- Steuer wird als optionales Feld modelliert; das System darf bei fehlender
  Angabe keinen Wert erfinden.

## Vorläufige Erfolgskriterien

Ein erster MVP gilt als fachlich vollständig, wenn:

- ein neuer Beleg über eine dokumentierte API verarbeitet werden kann,
- die Ausgabe einem versionierten Schema entspricht,
- mindestens zwei Extraktionsansätze reproduzierbar verglichen wurden,
- ein unverändertes Testset für alle Vergleiche verwendet wird,
- Qualitäts-, Latenz- und gegebenenfalls Kostenmetriken vorliegen,
- unsichere Ergebnisse nicht stillschweigend als korrekt ausgegeben werden,
- wichtige Komponenten automatisiert getestet sind,
- das System lokal auf einem Apple-M1-Mac gestartet werden kann,
- und Limitationen sowie typische Fehler anhand realer Beispiele dokumentiert
  sind.

Numerische Qualitätsgrenzen werden nicht erfunden. Sie werden nach der ersten
Baseline festgelegt.

## Wichtigste Lernziele

- zuverlässige strukturierte AI-Ausgaben
- Evaluationsdesign für Information Extraction
- Confidence, Calibration und Abstention
- Kombination probabilistischer Modelle mit deterministischen Regeln
- produktionsnahe Python- und API-Architektur
- Teststrategie für nichtdeterministische AI-Komponenten
- Modellwahl anhand von Qualität, Latenz und Kosten
- Docker, CI/CD und grundlegende Observability

## Offene Entscheidungen

1. Bleiben Belege die endgültige Dokumentdomäne?
2. Welche gewünschten Felder sind mit CORD objektiv evaluierbar und für welche
   benötigen wir zusätzliche oder eigene annotierte Testdaten?
3. Welche OCR-Lösung läuft stabil und reproduzierbar auf Apple Silicon?
4. Wird für den zweiten Ansatz zunächst eine API oder ein kleines lokales Modell
   verwendet?
5. Wie wird Confidence definiert, wenn ein Modell keine kalibrierte
   Wahrscheinlichkeit liefert?
6. Benötigt der MVP bereits eine kleine Review-Oberfläche oder reicht zunächst
   eine API plus automatisch erzeugter Ergebnisbericht?

## Nächste Arbeitspakete

1. CORD-v2-Dataset-Card, Lizenz, Schema und Beispielannotationen prüfen.
2. 20–30 Beispiele visuell und strukturell untersuchen.
3. Ein minimales kanonisches Ausgabeschema entwerfen.
4. Evaluationslogik zunächst unabhängig vom Modell implementieren und testen.
5. Eine einfache OCR-/Regel-Baseline erstellen.
6. Erst anhand dieser Erkenntnisse die Systemarchitektur festlegen.
