# Initial Data Audit: CORD v2

Stand: 15. September 2026  
Status: Vollständige Annotationsanalyse abgeschlossen

## Zweck

Diese Prüfung soll klären, ob CORD v2 grundsätzlich zu unserem gewünschten
Produktschema passt. Sie ersetzt noch keine vollständige explorative
Datenanalyse.

## Quelle und Lizenz

- Datensatz: `naver-clova-ix/cord-v2`
- Offizielles Projekt: <https://github.com/clovaai/cord>
- Dataset Viewer: <https://huggingface.co/datasets/naver-clova-ix/cord-v2>
- Lizenz: CC BY 4.0
- Offizielle Splits: 800 Training, 100 Validation, 100 Test

## Geprüfte Stichprobe

Die ersten 26 vom öffentlichen Dataset Viewer bereitgestellten Trainingsbelege
wurden auf Feldebene ausgewertet. Da es sich weder um eine Zufallsstichprobe
noch um den vollständigen Datensatz handelt, dürfen die Zahlen nicht als
abschließende Häufigkeiten oder Qualitätsmetriken interpretiert werden.

Diese Stichprobe wurde anschließend durch eine vollständige, reproduzierbare
Analyse aller 1.000 veröffentlichten Annotationen ersetzt. Sie bleibt hier
dokumentiert, weil sie zeigt, wie erste Annahmen vor der Implementierung geprüft
wurden.

### Dokumentfelder

| Feld | Vorhanden | Stichprobengröße |
|---|---:|---:|
| Gesamtpreis | 26 | 26 Dokumente |
| Zwischensumme | 20 | 26 Dokumente |
| Steuer | 14 | 26 Dokumente |

### Positionsfelder

| Feld | Vorhanden | Stichprobengröße |
|---|---:|---:|
| Beschreibung | 95 | 95 Positionen |
| Positionsgesamtpreis | 95 | 95 Positionen |
| Menge | 87 | 95 Positionen |
| Stückpreis | 20 | 95 Positionen |

## Beobachtete Varianten und Schwierigkeiten

- Eine einzelne Position wird im Ground-Truth-JSON teilweise als Objekt und
  mehrere Positionen als Liste dargestellt. Unser Adapter muss beides in eine
  einheitliche Liste normalisieren.
- Mengen erscheinen unter anderem als `1`, `1 x`, `x1` oder `1x`.
- Beträge verwenden Punkte und Kommata in unterschiedlichen Schreibweisen.
- Währungssymbole beziehungsweise Kürzel können direkt am Betrag stehen, sind
  aber nicht als eigenständiges Zielfeld annotiert.
- Ein Positionsgesamtpreis ist häufig vorhanden, auch wenn der Stückpreis
  fehlt.
- Unterpositionen und Modifikatoren können hierarchisch unter einer Position
  stehen.
- Steuer, Servicegebühr, Rabatt und andere Zuschläge sind nicht auf jedem Beleg
  vorhanden.

## Konsequenzen für das Produktschema

1. Beschreibung, Positionsgesamtpreis und Beleggesamtpreis bilden den kleinsten
   stabilen Kern des Benchmark-Schemas.
2. Menge, Stückpreis, Zwischensumme und Steuer sind optionale Werte.
3. `null` muss „nicht vorhanden oder nicht bestimmbar“ ausdrücken können; der
   Grund dafür wird separat erfasst.
4. Rohtext und normalisierter Wert werden getrennt gespeichert.
5. Währung bleibt Bestandteil des Produktschemas, benötigt für eine faire
   Evaluation aber ergänzende Daten.
6. Die erste Evaluation muss optionale Felder nur dort bewerten, wo Ground Truth
   vorhanden ist.
7. Hierarchische Unterpositionen werden im ersten MVP zunächst nicht vollständig
   modelliert. Sie werden als bekannte Limitation dokumentiert oder kontrolliert
   in die Positionsbeschreibung übernommen.

## Noch offene Datenprüfungen

- Bildqualität, Rotation, Auflösung und abgeschnittene Belege
- Eignung des offiziellen Test-Splits für unsere Metriken
- ergänzende Datenstrategie für Währung und europäische/deutsche Belege

## Vollständige Annotationsanalyse

Die Analyse wurde mit `scripts/analyze_cord_annotations.py` ausgeführt. Über
DuckDB wurde ausschließlich die Parquet-Spalte `ground_truth` gelesen. Dadurch
mussten die rund 2,3 GB umfassenden Parquet-Dateien mit den eingebetteten Bildern
nicht vollständig heruntergeladen werden.

Der maschinenlesbare Ergebnisbericht liegt unter
`reports/cord_data_profile.json`.

### Umfang und Splits

| Kennzahl | Ergebnis |
|---|---:|
| Dokumente | 1.000 |
| Training | 800 |
| Validation (`valid` in den Annotationen) | 100 |
| Test | 100 |
| Positionen insgesamt | 2.577 |
| Positionen pro Beleg, Mittelwert | 2,577 |
| Positionen pro Beleg, Median | 2 |
| Positionen pro Beleg, 95. Perzentil | 7 |
| Positionen pro Beleg, Maximum | 22 |

### Dokumentfelder nach kanonischer Normalisierung

| Feld | Extrahiert | Nicht vorhanden | Wegen Annotation nicht bewertbar |
|---|---:|---:|---:|
| Zwischensumme | 660 | 338 | 2 |
| Steuer | 433 | 560 | 7 |
| Gesamtpreis | 971 | 28 | 1 |
| Währung | 0 | 0 | 1.000 |

### Positionsfelder nach kanonischer Normalisierung

| Feld | Extrahiert | Nicht vorhanden | Anteil extrahiert |
|---|---:|---:|---:|
| Beschreibung | 2.569 | 8 | 99,69 % |
| Positionsgesamtpreis | 2.559 | 18 | 99,30 % |
| Menge | 2.331 | 246 | 90,45 % |
| Stückpreis | 737 | 1.840 | 28,60 % |

### Strukturvarianten

- Bei 431 Belegen ist `menu` ein einzelnes JSON-Objekt.
- Bei 569 Belegen ist `menu` eine Liste.
- Es gibt zwischen einer und 22 Positionen pro Beleg.
- Geldwerte kommen mit Komma, Punkt, gemischten Trennzeichen und zusätzlichen
  Präfixen beziehungsweise Suffixen vor.
- Mengen sind überwiegend ganze Zahlen, erscheinen aber auch mit `x` vor oder
  nach der Zahl sowie in Dezimalschreibweise.

### Auffällige Ground-Truth-Fälle

Der erste strenge Adapter lehnte 26 Dokumente ab. Die Detailprüfung zeigte:

- Platzhalter wie `"-"` für eine nicht vorhandene Steuer,
- identische doppelte Betragsannotationen,
- mehrzeilige Beschreibungen als Liste,
- Listen mit genau einem parsebaren Mengenwert,
- widersprüchliche Mehrfachwerte für Steuer, Zwischensumme oder Gesamtpreis,
- und einen Beleg mit mehreren, nicht eindeutig zusammenführbaren
  `sub_total`-Objekten.

Die finale Regel lautet:

- sichere Duplikate werden zusammengeführt,
- mehrzeiliger Text wird nachvollziehbar verbunden,
- Platzhalter werden als `not_present` behandelt,
- widersprüchliche Annotationen werden nicht geraten, sondern als
  `not_annotated` von der Feldbewertung ausgeschlossen.

Damit lassen sich alle 1.000 Dokumente verarbeiten. Das bedeutet nicht, dass
alle Felder verwendbar sind: Mehrdeutige Einzelfelder bleiben explizit von der
Evaluation ausgeschlossen.

## Eignungsentscheidung

CORD v2 ist als primärer Benchmark geeignet für:

- Positionserkennung,
- Beschreibung,
- Positionsgesamtpreis,
- Menge auf der annotierten Teilmenge,
- Beleggesamtpreis,
- robuste Formatnormalisierung.

CORD v2 ist allein nicht ausreichend für:

- belastbare Währungserkennung,
- starke Evaluation des Stückpreises über den gesamten Datensatz,
- deutsche beziehungsweise europäische Zahlen- und Belegformate,
- vollständige Evaluation eines realen deutschen Buchhaltungsprozesses.

### Konsequenz für die Datenstrategie

1. CORD bleibt der reproduzierbare Hauptbenchmark für den stabilen Kern.
2. Stückpreis und Steuer werden nur auf tatsächlich annotierten Feldern
   bewertet.
3. Nicht annotierte Felder werden aus dem jeweiligen Metriknenner entfernt und
   nicht als korrekt oder falsch gezählt.
4. Für Währung und europäische Zahlenformate wird später ein kleiner separater,
   sauber dokumentierter Challenge-Datensatz benötigt.
5. Die Testdaten bleiben unangetastet, bis Modelle und Schwellenwerte anhand von
   Trainings- und Validierungsdaten festgelegt wurden.
