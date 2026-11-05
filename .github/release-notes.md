DXF → KUKA KRL (KR C2) für **Plasmaschneiden** und **Fräsen**.

## Download

| System | Datei | Start |
|---|---|---|
| Windows | `DXFtoKRL-windows.exe` | Doppelklick. Windows-SmartScreen meldet evtl. „Unbekannter Herausgeber“ → *Weitere Informationen* → *Trotzdem ausführen* (die Datei ist nicht signiert). |
| Linux | `DXFtoKRL-linux.tar.gz` | Entpacken, dann `./DXFtoKRL` |

`beispiel.dxf` ist eine Testzeichnung zum Ausprobieren.

## Stand: Ausbaustufe 1

- DXF lesen: Linien, Bögen, Kreise, Polylinien, Splines, Ellipsen, Blöcke; Einheiten → mm
- Konturen automatisch verbinden, Reihenfolge optimieren, von Hand sortieren/umkehren/abwählen
- Vorschau mit Startpunkt, Richtung, Reihenfolge und Leerfahrten
- KRL für KR C2: `LIN`/`CIRC`, Überschleifen, BASE/TOOL, konstante Ausrichtung
- Plasma: Zündung mit „Lichtbogen OK“ + Timeout, Durchstechhöhe/-zeit, Schneidhöhe, Höhenregelung-Ausgang
- Fräsen: Spindel, Eintauchen, mehrere Zustellungen

**Noch nicht enthalten:** Fräserradius-/Schnittspaltkorrektur, An-/Abfahrbahnen, automatisch Innen- vor Außenkonturen.

⚠ Erzeugte Programme immer zuerst in **T1 mit reduzierter Geschwindigkeit** testen.
