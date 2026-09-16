# Canonical Output Schema – fachlicher Entwurf

Stand: 15. September 2026  
Status: Version 0.1 in Python implementiert

## Warum ein kanonisches Schema?

OCR-Systeme, multimodale Modelle und LLM-Anbieter liefern unterschiedliche
Formate. Das restliche System soll davon unabhängig bleiben. Deshalb wird jede
Modellausgabe zunächst in ein eigenes, versioniertes Format übersetzt.

Das Schema trennt vier Verantwortlichkeiten:

1. **Model Prediction:** rohe Antwort eines Modells
2. **Canonical Extraction:** normalisierte Werte mit Fundstellen
3. **Validation:** technische und fachliche Prüfungen
4. **Decision:** automatisch akzeptieren oder manuell prüfen

Ein Modell entscheidet somit nicht selbst, ob sein Ergebnis akzeptiert wird.

## Entitäten

### ReceiptExtraction

| Feld | Typ | Pflicht | Bedeutung |
|---|---|---:|---|
| `schema_version` | String | ja | Version des Ausgabevertrags |
| `document_id` | String | ja | Interne ID, keine Originaldatei im Output |
| `line_items` | Liste | ja | Erkannte Positionen; kann leer sein |
| `subtotal` | Geldfeld | nein | Zwischensumme |
| `tax` | Geldfeld | nein | Steuerbetrag |
| `total` | Geldfeld | ja für Auto-Akzeptanz | Beleggesamtpreis |
| `currency` | Textfeld | ja für Auto-Akzeptanz | ISO-Währung, etwa `EUR` oder `IDR` |

### LineItem

| Feld | Typ | Pflicht | Bedeutung |
|---|---|---:|---|
| `description` | Textfeld | ja | Bezeichnung der Position |
| `quantity` | Zahlenfeld | nein | Menge, wenn explizit erkennbar |
| `unit_price` | Geldfeld | nein | Stückpreis, wenn explizit erkennbar |
| `line_total` | Geldfeld | ja | Gesamtpreis der Position |

### ExtractedField

Jedes extrahierte Feld enthält nicht nur einen Wert:

| Feld | Bedeutung |
|---|---|
| `value` | normalisierter Wert oder `null` |
| `raw_text` | Text genau wie im Dokument erkannt |
| `status` | Zustand des Feldes |
| `confidence` | optionaler, klar definierter Score; kein ungeprüftes Modellgefühl |
| `evidence` | Fundstelle im Dokument, sofern verfügbar |

Vorläufige Statuswerte:

- `extracted`: Wert wurde aus sichtbarem Dokumentinhalt extrahiert
- `not_present`: Feld ist auf dem Dokument nicht vorhanden
- `uncertain`: ein möglicher Wert wurde erkannt, ist aber nicht zuverlässig
- `unreadable`: relevanter Bereich ist technisch nicht lesbar
- `not_annotated`: nur für Referenzdaten; der Datensatz enthält für dieses Feld
  keine Ground Truth

`not_present` und `unreadable` dürfen in der echten Inferenz nicht leichtfertig
behauptet werden. Ob ein Feld wirklich nicht vorhanden ist, ist selbst eine
Vorhersage.

`not_annotated` ist kein regulärer Modelloutput. Der Status verhindert bei der
Evaluation, dass eine fehlende Datensatzannotation als Modellfehler oder als
„nicht auf dem Dokument vorhanden“ interpretiert wird.

### Evidence

Eine Fundstelle kann enthalten:

- Seitenzahl,
- erkannter Text,
- Bounding Box oder Polygon,
- Referenz auf den OCR-Block.

Damit kann die Review-Oberfläche später zeigen, woher ein Wert stammt.

### ValidationIssue

| Feld | Bedeutung |
|---|---|
| `code` | stabiler maschinenlesbarer Fehlercode |
| `severity` | Information, Warnung oder Fehler |
| `field_paths` | betroffene Felder |
| `message` | verständliche Beschreibung |

Beispielcodes:

- `MISSING_CRITICAL_FIELD`
- `LINE_TOTAL_MISMATCH`
- `DOCUMENT_TOTAL_MISMATCH`
- `AMBIGUOUS_NUMBER_FORMAT`
- `UNSUPPORTED_CURRENCY`
- `LOW_CONFIDENCE`

### ProcessingDecision

| Feld | Bedeutung |
|---|---|
| `requires_review` | ob ein Mensch prüfen muss |
| `reasons` | maschinenlesbare Gründe |
| `policy_version` | Version der verwendeten Entscheidungsregeln |

## Beispiel eines Systemergebnisses

```json
{
  "extraction": {
    "schema_version": "0.1.0",
    "document_id": "receipt-001",
    "line_items": [
      {
        "description": {
          "value": "Cappuccino",
          "raw_text": "CAPPUCCINO",
          "status": "extracted",
          "confidence": null,
          "evidence": []
        },
        "quantity": {
          "value": 2,
          "raw_text": "2 x",
          "status": "extracted",
          "confidence": null,
          "evidence": []
        },
        "unit_price": {
          "value": "3.50",
          "raw_text": "3,50",
          "status": "extracted",
          "confidence": null,
          "evidence": []
        },
        "line_total": {
          "value": "7.00",
          "raw_text": "7,00",
          "status": "extracted",
          "confidence": null,
          "evidence": []
        }
      }
    ],
    "subtotal": {
      "value": "7.00",
      "raw_text": "Zwischensumme 7,00",
      "status": "extracted",
      "confidence": null,
      "evidence": []
    },
    "tax": {
      "value": "1.12",
      "raw_text": "MwSt 1,12",
      "status": "extracted",
      "confidence": null,
      "evidence": []
    },
    "total": {
      "value": "8.12",
      "raw_text": "Gesamt 8,12",
      "status": "extracted",
      "confidence": null,
      "evidence": []
    },
    "currency": {
      "value": "EUR",
      "raw_text": "€",
      "status": "extracted",
      "confidence": null,
      "evidence": []
    }
  },
  "validation_issues": [],
  "decision": {
    "requires_review": false,
    "reasons": [],
    "policy_version": "0.1.0"
  }
}
```

## Noch nicht entschieden

- genaue Darstellung von Bounding Boxes
- Bedeutung und Kalibrierung von `confidence`
- ob Rabatt und Servicegebühr in Version 0.1 aufgenommen werden
- Rundungstoleranzen für Geldprüfungen
- Verhalten bei impliziter Menge `1`
- Umgang mit Positionen, die sich über mehrere Zeilen erstrecken
- internes Speichern von Beträgen als `Decimal` und Serialisierung als String

## Empfehlung für die Implementierung

Geldbeträge sollten intern mit `Decimal` und nicht mit `float` verarbeitet
werden. Binäre Gleitkommazahlen können Rundungsartefakte erzeugen, die bei
rechnerischen Validierungen unnötige Fehler verursachen.
