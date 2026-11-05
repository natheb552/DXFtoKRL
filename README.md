# DXFtoKRL

Wandelt DXF-Zeichnungen in KUKA-KRL-Programme (`.src` + `.dat`) für die **KR C2** um –
für **Plasmaschneiden** und **Fräsen**. Läuft unter Windows und Linux.

> ⚠ Erzeugte Programme immer zuerst in **T1 mit reduzierter Geschwindigkeit** (oder in
> KUKA.Sim) testen. Das Programm kennt weder die Zelle noch Achsgrenzen oder Störkonturen.

## Download

Fertige Programme für Windows (`.exe`) und Linux gibt es unter
[Releases](https://github.com/natheb552/DXFtoKRL/releases/latest) – ohne Python-Installation.

## Aus dem Quellcode starten

- **Linux:** `./start.sh` (optional mit DXF-Datei als Argument)
- **Windows:** `start.bat` doppelklicken (Python 3.10+ muss installiert sein)

Beim ersten Start wird automatisch eine Python-Umgebung mit PySide6 und ezdxf angelegt.

## Bedienung

1. DXF öffnen (Strg+O) oder ins Fenster ziehen.
2. Links Layer und einzelne Konturen an-/abwählen, Reihenfolge mit ▲▼ ändern,
   Richtung mit ⇄ umkehren. Klick in der Vorschau wählt eine Kontur.
3. Rechts Profil (Plasma/Fräsen) und Parameter einstellen. Der KRL-Code ist in den
   Reitern „KRL .src/.dat“ sofort sichtbar.
4. „KRL exportieren“ (Strg+E) → Ordner wählen → `NAME.src` und `NAME.dat`.

Vorschau: grün = Startpunkt + Richtung, Zahl = Reihenfolge, gestrichelt = Leerfahrt,
orangenes Kreuz = Nullpunkt der BASE.

## Was erzeugt wird

- Standard-INI der KR C2 (`BAS(#INITMOV,0)`, `IR_STOPM`), danach `$BASE`/`$TOOL`,
  `$ORI_TYPE = #CONSTANT`, `$APO.CDIS`, `$ADVANCE = 3`.
- Linien → `LIN`, Bögen/Kreise → `CIRC` (große Bögen werden in Stücke < 180° geteilt),
  Splines/Ellipsen → kurze `LIN`-Stücke. Innerhalb einer Kontur wird überschliffen
  (`C_DIS`), am Konturende wird exakt angehalten.
- Konstante Werkzeugausrichtung A/B/C (Standard B=90°: Werkzeug-X zeigt nach −Z der BASE).
- Geschwindigkeiten werden in mm/min eingegeben und als `$VEL.CP` in m/s ausgegeben.

**Plasma, je Kontur:** Sicherheitshöhe → Durchstechhöhe → `ARC_ON()` (Brenner ein, Warten
auf „Lichtbogen OK“ mit Timeout; bei Fehlschlag Brenner aus + `HALT`, Start = neuer
Versuch) → Durchstechzeit → Absenken auf Schneidhöhe → Höhenregelung ein → Kontur →
Höhenregelung aus → `ARC_OFF()` → Sicherheitshöhe.

**Fräsen:** Spindel ein + Hochlaufzeit, je Kontur Eilgang bis Annäherungsabstand,
Eintauchen, Kontur in mehreren Zustellungen (geschlossene Konturen ohne Abheben),
Sicherheitshöhe; am Ende Spindel aus.

## Grenzen (Stand: Ausbaustufe 1)

- Bahn = Werkzeugmitte: **keine** Fräserradius- oder Schnittspaltkorrektur.
- Keine An-/Abfahrbahnen (Lead-in/out).
- Reihenfolge: nächster Nachbar – Innenkonturen werden noch **nicht** automatisch vor
  Außenkonturen gelegt (bei Plasma bitte von Hand prüfen).
- `PTP` auf kartesische Punkte ohne Status/Turn (S/T aus aktueller Stellung).
- Kopf von `.src`/`.dat` entspricht dem KUKA-Standard; ggf. an die eigene Anlage anpassen.

## Entwicklung

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest
.venv/bin/python tools/make_example.py   # erzeugt examples/beispiel.dxf
```

Neuer Release: Version in `dxftokrl/__init__.py` erhöhen, dann `git tag v0.x.y && git push --tags` –
GitHub Actions baut Windows- und Linux-Programm und legt den Release an.

Aufbau: `dxftokrl/dxf_import.py` (DXF lesen), `paths.py` (Konturen verbinden, Reihenfolge),
`krl.py` (KRL erzeugen), `settings.py`, `gui/` (Oberfläche).
