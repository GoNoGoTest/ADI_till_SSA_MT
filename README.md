# ADI till SSA MT

Litet Python-script för att konvertera ADI-logg till Cabrillo för **SSA Månadstest**.

- Contestinfo: https://hfcontest.ssa.se/ssa-mt/
- Uppladdning/robot: https://hfcontest.ssa.se/ssa-mt/robot/

## Snabbstart

```bash
python3 adi_to_ssa_mt_cabrillo.py minlogg.adi
```

Eller ange eget utfilnamn:

```bash
python3 adi_to_ssa_mt_cabrillo.py minlogg.adi -o minlogg.cbr
```

## Viktiga antaganden i scriptet

- Scriptet är gjort specifikt för SSA MT.
- Hela exporten skrivs som antingen **SSB** eller **CW** (globalt val i prompten).
- Ett och samma **QSO-datum** används för hela exporten.
- **STX/SRX** ska vara numeriska serienummer.
- Personliga förval i promptarna kommer från config-sektionen i scriptet.
- Klubbsignal är valfri; lämnas den tom skrivs ingen `CLUB:`-rad i Cabrillo.

## ADI-fält som behöver finnas

Minst dessa fält behöver finnas per QSO:

- `CALL`
- `BAND`
- `QSO_DATE`
- `TIME_ON`
- `STX`
- `SRX`
- `GRIDSQUARE` (eller `SRX_STRING`)

## Output

Standardfilnamn:

`SSA-MT-[MODE]-[YYYY-MM-DD]-[CALLSIGN].cbr`
