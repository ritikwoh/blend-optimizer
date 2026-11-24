# Blend optimiser (demo)

Lowest-cost raw material blend for one batch that meets a target chemical composition.
AI tools assisted in writing this code.

## Install
Needs Python 3.10 or newer.

    pip install -r requirements.txt

## Usage
Run every command from this job folder (the folder with cli.py). `demo.db` is created in the current folder.

    python cli.py demo.db import-materials materials.csv
    python cli.py demo.db select pig_iron,steel_scrap,hms_scrap,ferro_manganese,ferro_silicon,carburiser
    python cli.py demo.db composition steel1 "C=0.8:1.2,Mn=0.6:1.5"
    python cli.py demo.db run steel1 100

`run` prints kg per material, total cost, achieved composition (%) and any precheck warnings.
CSV header: `name,cost,<element>,...` with cost per kg (>= 0) and element values in % (0..100); an optional `max_share` column (0..1) caps a material's share. Duplicate material names are an error.
Re-importing clears the selection (a note is printed): run `select` again.
`select` replaces the previous selection. Element names in `composition` match case-insensitively; unknown names are an error.
Elements without a range in the composition are unconstrained (0..100 %); `run` lists them.
If no blend is feasible, `run` names the element whose range cannot be met, or the binding elements of a combined conflict.
Exit codes: 0 ok, 1 no feasible blend (infeasible), 2 input error (message starts with `error:`).
Batch size must be between 0.001 and 1e9 kg. Numbers must be finite (nan/inf are rejected).
The CSV may come from Excel 'CSV UTF-8' (BOM is fine) but must be comma-separated, not semicolon-separated.
Element names in a composition or CSV header must be unique (case-insensitive). If the max_share caps of the selected
materials add up to less than 100 %, `run` says so; if only the caps block a blend, `run` says to loosen them.

Tests: `python -m pytest -q -p no:cacheprovider` (if the system temp folder is locked, add `--basetemp=logs/pytest_tmp`)

## Model
    x_i  = kg of material i, B = batch kg, pct_ij = % of element j in material i
    minimise   sum_i cost_i * x_i
    subject to sum_i x_i = B
               lo_j * B <= sum_i x_i * pct_ij / 100 <= hi_j * B   (each element j, lo/hi in %)
               0 <= x_i <= max_share_i * B   (linear program, SciPy HiGHS)

## Known limitations (found by independent review, round 3, not fixed)
- `import-materials` is additive: importing a second file with different element columns keeps the old materials and elements, and a material that has no value for an element is treated as 0% of it. Import one complete price list per database, or delete `demo.db` first.
- Material names containing a comma can be imported but not selected (`select` splits on commas).
- A blank header cell is accepted as an element with an empty name; a CSV with only `name,cost` imports but has no elements.
- Printed kg values are rounded to 3 decimals, so they can differ from the batch size by a few grams.
- A locked database makes each command wait about 9 seconds before it reports the lock.
