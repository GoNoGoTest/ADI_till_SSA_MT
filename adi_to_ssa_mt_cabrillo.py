#!/usr/bin/env python3
"""
Konvertera ADI-exporter till Cabrillo-format för SSA Månadstest.

Scriptet är avsiktligt byggt för att vara enkelt, förutsägbart och lätt att
sprida vidare. Fokus ligger därför på:

- En specifik export för SSA Månadstest (inte en generell Cabrillo-export)
- Tydliga promptar på svenska
- En enkel config-sektion högst upp
- Cabrillo-header och QSO-rader som följer fungerande exempeldata
- Ett fast utfilnamnsformat
- En tydlig varning innan en befintlig fil skrivs över
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# CONFIG-SEKTION
# ---------------------------------------------------------------------------
#
# Tanken med denna sektion är att du enkelt ska kunna sätta dina vanligaste
# förval högst upp i filen.
#
# Om du vill dela scriptet vidare kan du antingen:
# - lämna variablerna tomma, eller
# - byta ut dem mot mer generiska värden.
#
# Om ett värde här är tomt visas inget personligt förval i prompten
# (undantag: datum får dagens datum om DEFAULT_QSO_DATE är tomt).
# ---------------------------------------------------------------------------

DEFAULT_MY_GRID = ""
DEFAULT_CONTEST_CALL = ""
DEFAULT_OPERATOR_CALL = ""
DEFAULT_CLUB_CALL = ""
DEFAULT_QSO_DATE = ""  # Format: YYYYMMDD. Lämna tom för att använda dagens datum.
DEFAULT_POWER_CLASS = "LOW"
DEFAULT_MODE = "SSB"


# ---------------------------------------------------------------------------
# KONSTANTER FÖR SCRIPTET
# ---------------------------------------------------------------------------
CREATED_BY_VALUE = "ADI-TO-SSA-MT"


# ---------------------------------------------------------------------------
# DATAMODELL FÖR ETT QSO
# ---------------------------------------------------------------------------
@dataclass
class QSO:
    """Representerar ett QSO efter att ADI-posten har normaliserats.

    Fälten här motsvarar den information vi faktiskt behöver för att skapa en
    korrekt Cabrillo-rad för SSA Månadstest.
    """

    index: int
    band: str
    call: str
    qso_date: str
    time_on: str
    rst_sent: str
    stx: int
    rst_rcvd: str
    srx: int
    gridsquare: str
    freq: Optional[str] = None

    @property
    def hhmm(self) -> str:
        """Returnerar tid i HHMM-format utifrån TIME_ON.

        ADI kan innehålla sekunder, t.ex. 143334. För SSA MT-raden använder vi
        bara HHMM, alltså 1433.
        """
        time_digits = re.sub(r"\D", "", self.time_on or "")
        if len(time_digits) < 4:
            raise ValueError(
                f"QSO #{self.index} ({self.call}) har ogiltig TIME_ON: {self.time_on!r}"
            )
        return time_digits[:4]


# ---------------------------------------------------------------------------
# HJÄLPFUNKTIONER FÖR PROMPTAR
# ---------------------------------------------------------------------------
def format_default_suffix(default: Optional[str]) -> str:
    """Visar förval på ett konsekvent och tydligt sätt i promptarna."""
    return f" [förval: {default}]" if default else ""


def prompt_nonempty(label: str, default: Optional[str] = None) -> str:
    """Frågar användaren efter ett icke-tomt värde.

    Om ett förval finns räcker det att trycka Enter för att använda det.
    """
    suffix = format_default_suffix(default)
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default:
            return default
        print("Måste anges.")


def prompt_optional(label: str, default: Optional[str] = None) -> str:
    """Frågar användaren efter ett valfritt värde.

    Om användaren bara trycker Enter returneras förvalet om det finns,
    annars en tom sträng.
    """
    suffix = format_default_suffix(default)
    value = input(f"{label}{suffix}: ").strip()
    if value:
        return value
    return default or ""


def prompt_choice(label: str, choices: List[str], default: Optional[str] = None) -> str:
    """Frågar efter ett val från en fördefinierad lista.

    Returnerar alltid versal form, t.ex. LOW eller SSB.
    """
    normalized = {c.upper(): c.upper() for c in choices}
    default_upper = default.upper() if default else None
    suffix = format_default_suffix(default_upper)
    pretty = "/".join(choices)

    while True:
        value = input(f"{label} ({pretty}){suffix}: ").strip().upper()
        if not value and default_upper:
            return default_upper
        if value in normalized:
            return normalized[value]
        print(f"Ogiltigt val. Ange ett av: {pretty}")


def prompt_yes_no(label: str, default: bool = False) -> bool:
    """En enkel ja/nej-prompt med tydlig default-markering."""
    suffix = " [J/n]" if default else " [j/N]"
    value = input(f"{label}{suffix}: ").strip().lower()
    if not value:
        return default
    return value in {"j", "ja", "y", "yes"}


def prompt_power_class(default: str) -> str:
    """Specialprompt för effektklass.

    Här visas wattgränserna tydligt, men användaren ska fortfarande skriva just
    QRP, LOW eller HIGH.
    """
    label = (
        "Effektklass (QRP/LOW/HIGH) – "
        "QRP=max 5 W, LOW=max 100 W, HIGH=max 1000 W"
    )
    return prompt_choice(label, ["QRP", "LOW", "HIGH"], default)


# ---------------------------------------------------------------------------
# ADI-PARSNING
# ---------------------------------------------------------------------------
def parse_adif_text(text: str) -> List[Dict[str, str]]:
    """Läser ADI-text och returnerar en lista av poster (dictar).

    Vi gör en avsiktligt enkel och robust parsning:
    - först hittar vi <EOH>
    - sedan delar vi på <EOR>
    - därefter läser vi ADIF-taggar av typen <FIELD:LENGTH>value

    Det räcker väl för vanliga ADI-exporter från loggprogram.
    """
    upper = text.upper()
    eoh_match = re.search(r"<EOH>", upper)
    if not eoh_match:
        raise ValueError("Hittade inte <EOH> i ADI-texten.")

    body = text[eoh_match.end():]
    entries: List[Dict[str, str]] = []
    chunks = re.split(r"<EOR>", body, flags=re.IGNORECASE)

    field_pattern = re.compile(
        r"<([^:>\s]+):(\d+)(?::[^>]*)?>(.*?)",
        re.IGNORECASE | re.DOTALL,
    )

    for chunk in chunks:
        if not chunk.strip():
            continue

        fields: Dict[str, str] = {}
        pos = 0

        while True:
            match = field_pattern.search(chunk, pos)
            if not match:
                break

            name = match.group(1).upper()
            length = int(match.group(2))
            value_start = match.end()
            value = chunk[value_start:value_start + length]
            fields[name] = value.strip()
            pos = value_start + length

        if fields:
            entries.append(fields)

    if not entries:
        raise ValueError("Hittade inga QSO-poster i ADI-texten.")

    return entries


# ---------------------------------------------------------------------------
# NORMALISERING OCH VALIDERING
# ---------------------------------------------------------------------------
def normalize_band_to_freq_khz(band: str, fallback_freq: Optional[str]) -> str:
    """Översätter band till Cabrillo-frekvens i kHz.

    För SSA Månadstest brukar fasta "representativa" frekvenser fungera bra,
    vilket också stämmer med din fungerande exempel-Cabrillo.

    Om bandet inte finns i vår tabell försöker vi använda ADI-fältet FREQ.
    """
    mapping = {
        "160M": "1800",
        "80M": "3700",
        "40M": "7100",
        "20M": "14200",
        "15M": "21300",
        "10M": "28400",
    }

    key = band.strip().upper()
    if key in mapping:
        return mapping[key]

    if fallback_freq:
        try:
            freq_mhz = float(fallback_freq)
            return str(int(round(freq_mhz * 1000)))
        except ValueError:
            pass

    raise ValueError(
        f"Kan inte översätta band/frekvens till Cabrillo-frekvens: band={band!r}, freq={fallback_freq!r}"
    )


def build_qsos(entries: List[Dict[str, str]]) -> List[QSO]:
    """Bygger QSO-objekt från ADI-poster och gör nödvändig validering."""
    qsos: List[QSO] = []

    for fields in entries:
        stx = (fields.get("STX") or "").strip()
        srx = (fields.get("SRX") or "").strip()
        call = (fields.get("CALL") or "").upper().strip()

        if not stx:
            raise ValueError(f"QSO saknar STX. CALL={call or '(okänd)'}")
        if not srx:
            raise ValueError(f"QSO #{stx} ({call or '(okänd)'}) saknar SRX.")
        if not call:
            raise ValueError(f"QSO #{stx} saknar CALL.")

        try:
            stx_num = int(stx)
        except ValueError:
            raise ValueError(
                f"QSO med CALL={call or '(okänd)'} har ogiltig STX={stx!r}. "
                "STX måste vara numeriskt serienummer."
            ) from None

        try:
            srx_num = int(srx)
        except ValueError:
            raise ValueError(
                f"QSO #{stx_num} ({call or '(okänd)'}) har ogiltig SRX={srx!r}. "
                "SRX måste vara numeriskt serienummer."
            ) from None

        qso = QSO(
            index=stx_num,
            band=(fields.get("BAND") or "").upper().strip(),
            call=call,
            qso_date=(fields.get("QSO_DATE") or "").strip(),
            time_on=(fields.get("TIME_ON") or "").strip(),
            rst_sent=(fields.get("RST_SENT") or "59").strip(),
            stx=stx_num,
            rst_rcvd=(fields.get("RST_RCVD") or "59").strip(),
            srx=srx_num,
            gridsquare=((fields.get("GRIDSQUARE") or fields.get("SRX_STRING") or "").upper().strip()),
            freq=(fields.get("FREQ") or "").strip() or None,
        )

        if not qso.band:
            raise ValueError(f"QSO #{qso.index} ({qso.call}) saknar BAND.")
        if not qso.qso_date:
            raise ValueError(f"QSO #{qso.index} ({qso.call}) saknar QSO_DATE.")
        if not qso.gridsquare:
            raise ValueError(
                f"QSO #{qso.index} ({qso.call}) saknar motstationens lokator (GRIDSQUARE/SRX_STRING)."
            )

        qsos.append(qso)

    # Sortera konsekvent på datum, tid och serienummer.
    qsos.sort(key=lambda q: (q.qso_date, q.hhmm, q.index))
    return qsos


# ---------------------------------------------------------------------------
# CABRILLO-RENDERING
# ---------------------------------------------------------------------------
def build_header(
    power_class: str,
    qth_locator: str,
    contest_call: str,
    operator_call: str,
    club_call: str,
    mode: str,
) -> List[str]:
    """Bygger Cabrillo-headern.

    Headern speglar den fungerande .cbr-fil du gav som mall.
    """
    contest_name = f"SSA-MT-{mode.upper()}"
    lines = [
        "START-OF-LOG: 3.0",
        f"CONTEST: {contest_name}",
        f"CALLSIGN: {contest_call}",
        "CATEGORY-OPERATOR: SINGLE-OP",
        "CATEGORY-BAND: ALL",
        f"CATEGORY-POWER: {power_class}",
        "CATEGORY-STATION:",
        "CATEGORY-TRANSMITTER:",
        "CATEGORY-OVERLAY:",
        f"OPERATORS: {operator_call}",
        f"GRID-LOCATOR: {qth_locator}",
        f"CREATED-BY: {CREATED_BY_VALUE}",
    ]
    if club_call:
        lines.insert(-1, f"CLUB: {club_call}")
    return lines


def format_qso_line(qso: QSO, contest_call: str, qth_locator: str, contest_mode: str) -> str:
    """Formaterar en enda Cabrillo-rad.

    Vi använder exakt den spacing-stil som matchar din fungerande Cabrillo-fil.
    contest_mode avgör om vi skriver PH eller CW.
    """
    freq_khz = normalize_band_to_freq_khz(qso.band, qso.freq)
    date_fmt = f"{qso.qso_date[:4]}-{qso.qso_date[4:6]}-{qso.qso_date[6:8]}"
    mode_code = "CW" if contest_mode.upper() == "CW" else "PH"

    return (
        f"QSO:  {freq_khz:<5} {mode_code:<2} {date_fmt} {qso.hhmm}  "
        f"{contest_call.upper():<15} {qso.rst_sent:<3} {qso.stx:03d} {qth_locator.upper():<6}  "
        f"{qso.call:<15} {qso.rst_rcvd:<3} {qso.srx:03d} {qso.gridsquare:<6}"
    )


def render_cabrillo(
    qsos: List[QSO],
    power_class: str,
    qth_locator: str,
    mode: str,
    contest_call: str,
    operator_call: str,
    club_call: str,
) -> str:
    """Bygger hela Cabrillo-filen som text."""
    if not qsos:
        raise ValueError("Inga QSO att skriva ut.")

    header = build_header(
        power_class=power_class,
        qth_locator=qth_locator,
        contest_call=contest_call,
        operator_call=operator_call,
        club_call=club_call,
        mode=mode,
    )

    lines = header + [
        format_qso_line(q, contest_call, qth_locator, mode) for q in qsos
    ] + ["END-OF-LOG:"]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# IN/UT OCH FILNAMN
# ---------------------------------------------------------------------------
def read_input_text(path: Optional[Path]) -> str:
    """Läser ADI-text antingen från fil eller stdin."""
    if path:
        return path.read_text(encoding="utf-8")

    print("Klistra in ADI-loggen. Avsluta med Ctrl-D (macOS/Linux) eller Ctrl-Z följt av Enter (Windows).")
    return sys.stdin.read()


def build_output_filename(mode: str, qso_date: str, contest_call: str) -> Path:
    """Bygger utfilnamn i exakt önskat format.

    Format:
    SSA-MT-[MODE]-[YYYY-MM-DD]-[CALLSIGN].cbr
    """
    safe_call = re.sub(r"[^A-Z0-9]", "", contest_call.upper()) or "LOG"
    date_fmt = f"{qso_date[:4]}-{qso_date[4:6]}-{qso_date[6:8]}"
    return Path(f"SSA-MT-{mode.upper()}-{date_fmt}-{safe_call}.cbr")


def config_default(value: str) -> str:
    """Returnerar ett städat config-värde eller tom sträng.

    Viktigt: vi faller inte tillbaka till ADI-data här. Tanken är att
    config-sektionen ensam ska styra vilka personliga förval som visas.
    """
    return value.strip() if value and value.strip() else ""


# ---------------------------------------------------------------------------
# HUVUDFLÖDE
# ---------------------------------------------------------------------------
def main() -> int:
    """Scriptets huvudflöde."""
    parser = argparse.ArgumentParser(description="Konvertera ADI till Cabrillo för SSA Månadstest.")
    parser.add_argument("input", nargs="?", type=Path, help="ADI-fil att läsa")
    parser.add_argument("-o", "--output", type=Path, help="Utfil för Cabrillo (om du vill skriva över standardnamnet)")
    args = parser.parse_args()

    try:
        text = read_input_text(args.input)
        entries = parse_adif_text(text)

        # Bygg faktiska förval från config-sektionen.
        # För personliga uppgifter faller vi inte tillbaka till ADI-data, eftersom
        # du uttryckligen vill kunna dela scriptet utan att ADI-innehåll automatiskt
        # dyker upp som förval i promptarna.
        #
        # Datum beter sig annorlunda: om inget datum är satt i config-sektionen
        # använder vi dagens datum som förval.
        today_yyyymmdd = date.today().strftime("%Y%m%d")
        default_qso_date = config_default(DEFAULT_QSO_DATE) or today_yyyymmdd
        default_grid = config_default(DEFAULT_MY_GRID).upper()
        default_contest_call = config_default(DEFAULT_CONTEST_CALL).upper()
        default_operator_call = config_default(DEFAULT_OPERATOR_CALL).upper()
        default_club_call = config_default(DEFAULT_CLUB_CALL).upper()
        default_power_class = (config_default(DEFAULT_POWER_CLASS) or "LOW").upper()
        default_mode = (config_default(DEFAULT_MODE) or "SSB").upper()

        print("\nAnge SSA-fälten:\n")

        qso_date = prompt_nonempty("QSO datum (YYYYMMDD)", default_qso_date)
        power_class = prompt_power_class(default_power_class)
        qth_locator = prompt_nonempty("QTH-lokator", default_grid).upper()
        mode = prompt_choice("Mode", ["CW", "SSB"], default_mode)
        contest_call = prompt_nonempty("Anropssignal i testen", default_contest_call).upper()
        operator_call = prompt_nonempty("Anropssignal Operatör", default_operator_call).upper()
        club_call = prompt_optional("Anropssignal Klubb", default_club_call).upper()

        # Bygg QSO-lista. STX/SRX valideras som numeriska serienummer.
        qsos = build_qsos(entries)

        # Tvinga in valt datum på alla QSO-rader, eftersom användaren uttryckligen
        # kan vilja skriva samma logg med ett annat datum än det som råkar finnas i
        # ADI-filen.
        for q in qsos:
            q.qso_date = qso_date

        cabrillo = render_cabrillo(
            qsos=qsos,
            power_class=power_class,
            qth_locator=qth_locator,
            mode=mode,
            contest_call=contest_call,
            operator_call=operator_call,
            club_call=club_call,
        )

        # Om användaren inte explicit angivit -o bygger vi filnamnet exakt enligt
        # önskat standardformat.
        output_path = args.output if args.output else build_output_filename(mode, qso_date, contest_call)

        # Varnar tydligt innan en befintlig fil skrivs över.
        if output_path.exists():
            print(f"\nVarning: filen finns redan och kommer att skrivas över: {output_path}")
            if not prompt_yes_no("Vill du fortsätta och skriva över filen?", False):
                print("Ingen fil skrevs.")
                return 0

        output_path.write_text(cabrillo, encoding="utf-8")

        print(f"\nSkrev Cabrillo till: {output_path}")
        print("\nFörhandsvisning:\n")
        print(cabrillo)
        return 0

    except KeyboardInterrupt:
        print("\nAvbrutet.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Fel: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
