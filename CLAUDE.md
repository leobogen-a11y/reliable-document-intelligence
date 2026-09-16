# Reliable Document Intelligence - Kontext für Claude Code

Dieses Projekt ist ein **privates Portfolio-Projekt** von Leon (KI-Student,
Abschluss 10/2026), gedacht für Bewerbungen als AI Engineer. Entsprechend
wichtig sind neben sauberem Code auch: gute Dokumentation der
Design-Entscheidungen, ehrliche Limitationen, und am Ende eine
kostenlos gehostete Live-Demo. Budget-Prämisse: **möglichst kostenlos**
(kein bezahltes API-Tier, keine bezahlte Hosting-Lösung).

Lies zuerst `PROJECT_BRIEF.md` (Produktentscheidungen, MVP-Scope,
Erfolgskriterien), `SCHEMA_DESIGN.md` (kanonisches Datenschema) und
`DATA_AUDIT.md` (CORD-v2-Datensatzanalyse) - dort steht der fachliche
Hintergrund zu praktisch jeder Design-Entscheidung im Code.

## Aktueller Stand (Stand: dieser Commit)

Implementiert und vollständig getestet (`pytest`, aktuell alle Tests grün):

1. **Kanonisches Schema** (`src/receipt_intelligence/domain/models.py`) -
   Pydantic-Modelle für `ReceiptExtraction`, `LineItem`, `ExtractedField`
   (mit `FieldStatus`: extracted/not_present/uncertain/unreadable/
   not_annotated), `ValidationIssue`, `ProcessingDecision`.
2. **CORD-v2-Adapter** (`adapters/cord.py`) - übersetzt CORD-Ground-Truth in
   das kanonische Schema, für die Evaluation.
3. **Validierungslogik** (`validation.py`) - deterministische fachliche
   Prüfungen (Pflichtfelder, Arithmetik-Konsistenz, Confidence-Schwelle,
   optionale Währungs-Allowlist) plus `build_processing_decision()`
   (präzisionsorientierte Policy: im Zweifel Review statt Auto-Akzeptanz).
4. **Evaluationsharness** (`evaluation.py`) - vergleicht eine Vorhersage
   gegen Ground Truth, modellunabhängig: Field-Accuracy, Precision/Recall/
   F1 für Positionen (via Greedy-Matching), Coverage, False-Accept-Rate.
   Wurde bewusst VOR jedem Extraktionsansatz gebaut und gegen CORD selbst
   getestet (siehe PROJECT_BRIEF.md, Arbeitspaket 4).
5. **Ansatz 1 - einfache Baseline** (`ocr.py` + `baseline.py`) - Tesseract
   OCR (mit eigener Zeilen-Rekonstruktion aus Wort-Bounding-Boxes, da
   Tesseract Spalten sonst durcheinanderwürfelt) plus regelbasiertem Parser
   für deutsche Belege. Bewusst einfach, dokumentierte Limitationen (siehe
   Docstring in `baseline.py`).
6. **Ansatz 2 - AI-basiert** (`gemini_client.py` + `adapters/gemini.py` +
   `ai_extraction.py`) - nutzt denselben OCR-Text wie die Baseline (fairer
   Vergleich, spart Kosten: Text- statt Bild-Tokens) und schickt ihn mit
   schema-constrained Prompt an die **kostenlose Gemini-API-Stufe**.

## Offener Punkt / nächster Schritt

`GOOGLE_API_KEY` liegt in `.env` (gitignored, bereits vorhanden). Das
aktuelle Default-Modell ist `gemini-3.6-flash` (wurde live über die API
ermittelt, nachdem `gemini-2.5-flash` "no longer available to new users"
zurückgab - **bei erneuten Modell-Fehlern prüfen, ob sich der Modellname
wieder geändert hat**). `scripts/gemini_smoke_test.py` ist der Live-Check;
er lief zuletzt gegen einen 503 ("high demand", freie Stufe) - beim
nächsten Versuch nochmal ausführen, ggf. mit kurzer Retry-Logik in
`gemini_client.py` ausstatten, falls das öfter auftritt.

**Warum das hier und nicht vorher lief:** `generativelanguage.googleapis.com`
war aus der Cowork-Sandbox (Cloud-Container und die Mac-Bridge) über eine
Netzwerk-Allowlist blockiert. In einem normalen Terminal mit Claude Code
sollte das kein Problem sein.

## Geplante nächste Schritte (siehe PROJECT_BRIEF.md für den vollen Kontext)

1. Live-Smoke-Test erfolgreich durchlaufen lassen und Ergebnis prüfen.
2. Baseline vs. AI-Ansatz auf einem echten Testset vergleichen (Qualität,
   Coverage, False-Accept-Rate, Latenz, Kosten) - das liefert die
   Kennzahlen fürs Portfolio.
3. Für den Vergleich werden echte Belegbilder gebraucht - offene
   Entscheidung: synthetische/eigene Testbelege (schnell, kostenlos) vs.
   CORD-Bilder (großer Download, ~2.3GB, Indonesisch statt Deutsch -
   DATA_AUDIT.md nennt Details).
4. Dokumentierte API (kleine, z.B. FastAPI) um die beiden Ansätze.
5. Live-Demo: Ziel ist Hugging Face Spaces (kostenlos, CPU-Tier reicht, da
   die eigentliche Modell-Inferenz über die Gemini-API läuft, nicht lokal).
6. README-Politur, Architekturdiagramm, Vergleichs-Chart, Limitationen-
   Abschnitt - erst wenn die Ergebnisse feststehen (siehe
   PROJECT_BRIEF.md Erfolgskriterien).

## Entwicklungsumgebung

```bash
cd ~/Desktop/reliable-document-intelligence
source .venv/bin/activate
pip install -e ".[dev,baseline]"   # dev = pytest, baseline = pytesseract+pillow
pytest -q                           # sollte komplett grün sein
```

Tesseract-Binary muss separat installiert sein (`brew install tesseract`),
`pytesseract`/`pillow` kommen über die `baseline`-Extras.

## Code-Konventionen (bitte beibehalten)

- Alle Geldbeträge als `Decimal`, nie `float`.
- **Nie Werte erfinden**: Ein nicht erkanntes Feld wird als `not_present`/
  `uncertain`/`unreadable` markiert, nie als 0 oder geraten. Das zieht sich
  durch den gesamten Code (Adapter, Baseline, Gemini-Adapter, Validierung).
- Docstrings erklären *warum*, nicht nur *was* - besonders bei
  Design-Entscheidungen, die noch nicht endgültig sind (siehe "Noch nicht
  entschieden" in SCHEMA_DESIGN.md).
- Jede neue Regel/jeder neue Parser bekommt Tests für die Grenzfälle, nicht
  nur den Glücksfall - siehe z.B. `test_baseline.py` für bewusst
  dokumentiertes (statt verstecktes) Fehlverhalten.
- Commit-Messages sind bewusst ausführlich (Kontext für spätere Sessions/
  Tools) - das gerne fortführen.
