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
7. **HTTP-API** (`api.py`, FastAPI) - `POST /extract?approach=baseline|gemini`
   nimmt ein JPEG/PNG-Bild entgegen, läuft durch OCR → gewählten Ansatz →
   Validierung → Decision, gibt `ReceiptResult` zurück (Extraction +
   Validation Issues + Decision zusammen, wie in SCHEMA_DESIGN.md
   versprochen). `GET /health` für Deployment-Healthchecks. Reimplementiert
   keine Logik, ruft nur `baseline.py`/`ai_extraction.py`/`validation.py`
   auf. **PDF-Eingabe (in PROJECT_BRIEF.md erwähnt) ist noch nicht
   implementiert** - nur JPEG/PNG, bewusst dokumentierte Lücke statt
   stillschweigend falsch behandelt. Start: `uvicorn
   receipt_intelligence.api:app --reload`.

## Offener Punkt / nächster Schritt (Stand: 2026-09-24)

`GOOGLE_API_KEY` liegt in `.env` (gitignored, bereits vorhanden). Live-Smoke-
Test und ein erster 10-Belege-Vergleich (`scripts/compare_approaches.py`)
liefen erfolgreich. Wichtige Erkenntnisse aus diesem Lauf:

- **Aktuelles Default-Modell ist `gemini-3.1-flash-lite`, nicht mehr
  `gemini-3.6-flash`.** Grund: `gemini-3.6-flash`s Free-Tier-Kontingent lag
  bei nur 20 Requests/Tag (429 "generate_content_free_tier_requests",
  Reset um Mitternacht Pacific Time) - zu knapp für einen 100-Belege-
  Vergleich. Kontingente sind pro Modell getrennt. **Korrektur:**
  `gemini-3.1-flash-lite` hat mit **15 Requests/Tag sogar noch weniger**
  Kontingent als `gemini-3.6-flash` - Googles "günstiger/schneller"-
  Positionierung der Lite-Variante sagt nichts über das Free-Tier-Kontingent
  aus, das lässt sich nur empirisch prüfen. **Bei erneuten Modell- oder
  Quota-Fehlern prüfen, ob sich das wieder geändert hat** (Modellnamen UND
  Kontingente waren in dieser API-Generation schon mehrfach in Bewegung).
- **Bewusste Entscheidung (2026-09-24): kein Umstieg auf das kostenpflichtige
  Tier**, obwohl die tatsächlichen Kosten trivial wären (~$0,001/Beleg bei
  `gemini-3.1-flash-lite`). Begründung: für ein Portfolio-Proof-of-Concept
  bringt ein größeres Sample keinen Mehrwert, der die Free-Tier-Prämisse aus
  diesem Dokument aufwiegt - im Gegenteil, das dokumentierte
  Kontingent-Handling (Retry-Logik, Modellwechsel, ehrliche Dokumentation
  der Grenzen) ist selbst ein gutes Bewerbungs-Talking-Point. Stattdessen:
  Gemini-Sample über mehrere Tage auf ~30-50 Belege hochziehen
  (`--offset`/`--limit` in `compare_approaches.py`), und parallel an der
  API-Schicht weiterarbeiten (siehe Punkt 7 oben, inzwischen erledigt).
- `gemini_client.py` hat jetzt Retry-mit-Backoff (`with_retry()`) für
  transiente 503er ("high demand"). Bewusst **kein** Retry auf 429, da das
  hier ein Tageskontingent-Fehler war, kein kurzfristiges Rate-Limit -
  erneutes Versuchen hätte nur schneller das Restkontingent verbrannt.
- CORD-v2 `validation`-Split ist lokal unter
  `data/cord-v2/validation/0000.parquet` (231 MB, gitignored). `test`-Split
  bewusst noch nicht angerührt (siehe DATA_AUDIT.md, Eignungsentscheidung).
- Erster Befund aus dem 10-Belege-Lauf: Tesseract liest auf diesem
  Beleg-Font kaum Buchstaben (nur Ziffern) - trifft Baseline und Gemini
  gleichermaßen, da beide denselben OCR-Text bekommen. Ausführlich
  dokumentiert in DATA_AUDIT.md, Abschnitt "Erster Baseline/AI-Vergleich".

**Warum das früher nicht lief:** `generativelanguage.googleapis.com` war aus
der Cowork-Sandbox (Cloud-Container und die Mac-Bridge) über eine
Netzwerk-Allowlist blockiert. In einem normalen Terminal mit Claude Code ist
das kein Problem.

## Geplante nächste Schritte (siehe PROJECT_BRIEF.md für den vollen Kontext)

1. ~~Live-Smoke-Test erfolgreich durchlaufen lassen~~ ✅ erledigt.
2. ~~Für den Vergleich Entscheidung treffen: eigene Testbelege vs. CORD~~ ✅
   CORD gewählt, validation-Split heruntergeladen.
3. Baseline vs. AI-Ansatz auf einem größeren Sample vergleichen - aktuell
   Baseline n=50, Gemini n=2 (Ungleichgewicht ist das eigentliche Problem,
   nicht die absolute Größe). Ziel: Gemini schrittweise auf ~30-50 balanciert
   hochziehen, über mehrere Tage verteilt (15 Requests/Tag-Kontingent bei
   `gemini-3.1-flash-lite`). Kein Umstieg auf kostenpflichtiges Tier (siehe
   oben, bewusste Entscheidung 2026-09-24).
4. ~~Dokumentierte API (kleine, z.B. FastAPI) um die beiden Ansätze~~ ✅
   erledigt (`api.py`, siehe Punkt 7 oben). PDF-Input fehlt noch.
5. Live-Demo: Ziel ist Hugging Face Spaces (kostenlos, CPU-Tier reicht, da
   die eigentliche Modell-Inferenz über die Gemini-API läuft, nicht lokal).
   Noch nicht begonnen.
6. README-Politur, Architekturdiagramm, Vergleichs-Chart, Limitationen-
   Abschnitt (inkl. des Tesseract-Buchstaben-Befunds) - erst wenn die
   Ergebnisse auf dem balancierten Sample feststehen (siehe PROJECT_BRIEF.md
   Erfolgskriterien).

## Entwicklungsumgebung

```bash
cd ~/Desktop/reliable-document-intelligence
source .venv/bin/activate
pip install -e ".[dev,baseline,analysis,api]"   # dev = pytest+httpx, baseline = pytesseract+pillow, analysis = duckdb, api = fastapi+uvicorn
pytest -q                                        # sollte komplett grün sein
uvicorn receipt_intelligence.api:app --reload    # API lokal starten (http://127.0.0.1:8000/health)
```

Tesseract-Binary muss separat installiert sein (`brew install tesseract`,
inzwischen erledigt - nur "eng"+"osd"-Sprachdaten, siehe DATA_AUDIT.md zum
Buchstaben-Erkennungs-Befund), `pytesseract`/`pillow` kommen über die
`baseline`-Extras, `duckdb` über `analysis` (wird für
`scripts/analyze_cord_annotations.py` und `scripts/compare_approaches.py`
gebraucht, um die CORD-Parquet-Dateien zu lesen), `fastapi`/`uvicorn`/
`python-multipart` über `api`.

**Falls der Projektordner mal verschoben/umbenannt wird:** `.venv` neu
aufsetzen (`rm -rf .venv && python3.11 -m venv .venv && pip install -e
".[dev,baseline,analysis,api]"`) - die editable-Install-Pointer-Datei enthält
den absoluten Pfad zum Erstellungszeitpunkt und bricht sonst still (Symptom:
`pip` selbst meldet "bad interpreter", `pytest` läuft aber trotzdem weiter,
weil es `--import-mode=importlib` nutzt statt der editable-Install - das hat
uns am 2026-09-16 kurz verwirrt).

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
