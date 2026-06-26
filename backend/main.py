import re
import csv
import io
import os
import uuid

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Transform → volume field mapping
TMAP = [
    ('translate(144.48 180.18) rotate(-90)', 'NBT'),
    ('translate(130.89 170.87) rotate(-90)', 'NBL'),
    ('translate(158.08 160.99) rotate(-90)', 'NBR'),
    ('translate(132.16 95.3)',               'WBL'),
    ('translate(132.16 81.4)',               'WBT'),
    ('translate(132.16 67.5)',               'WBR'),
    ('translate(52.64 132.04)',              'EBL'),
    ('translate(63.03 145.94)',              'EBT'),
    ('translate(63.03 159.85)',              'EBR'),
    ('translate(76.78 86.46) rotate(-90)',   'SBT'),
    ('translate(63.04 86.46) rotate(-90)',   'SBR'),
    ('translate(90.51 86.46) rotate(-90)',   'SBL'),
]


def prepare_template(raw: str) -> str:
    svg = re.sub(r'<\?xml[^?]*\?>\s*', '', raw).strip()
    # Fix WB text alignment
    for y in ['95.3', '81.4', '67.5']:
        old = f'transform="translate(132.16 {y})"><tspan x="0" y="0">'
        new = f'transform="translate(132.16 {y})" text-anchor="end"><tspan x="0" y="0">'
        svg = svg.replace(old, new)
    return svg


def splice_value(svg: str, transform: str, value: str) -> str:
    needle = f'transform="{transform}"><tspan x="0" y="0">'
    idx = svg.find(needle)
    if idx == -1:
        # try with text-anchor variant
        needle = f'transform="{transform}" text-anchor="end"><tspan x="0" y="0">'
        idx = svg.find(needle)
    if idx == -1:
        return svg
    vs = idx + len(needle)
    ve = svg.index('</tspan>', vs)
    return svg[:vs] + value + svg[ve:]


def set_int_number(svg: str, value: str) -> str:
    needle = 'cls-16" transform="translate(29.63 40.86)"><tspan x="0" y="0">'
    idx = svg.find(needle)
    if idx == -1:
        return svg
    vs = idx + len(needle)
    ve = svg.index('</tspan>', vs)
    return svg[:vs] + value + svg[ve:]


def set_ns_street(svg: str, value: str) -> str:
    needle = 'cls-13" transform="translate(199.4 203.51) rotate(-90)"><tspan x="0" y="0">'
    idx = svg.find(needle)
    if idx == -1:
        return svg
    vs = idx + len(needle)
    ve = svg.index('</tspan>', vs)
    return svg[:vs] + value + svg[ve:]


def set_ew_street(svg: str, value: str) -> str:
    # Replace entire cls-12 text element
    start_marker = '<text class="cls-12"'
    end_marker = '</text>'
    start = svg.find(start_marker)
    if start == -1:
        return svg
    end = svg.index(end_marker, start) + len(end_marker)
    replacement = f'<text class="cls-12" transform="translate(17.29 201.98)"><tspan x="0" y="0">{value}</tspan></text>'
    return svg[:start] + replacement + svg[end:]


def parse_am_pm(raw: str):
    raw = raw.strip()
    m = re.match(r'^(\d+)\s*\((\d+)\)', raw)
    if m:
        return m.group(1), m.group(2)
    # fallback — might be plain number
    digits = re.match(r'^(\d+)$', raw)
    if digits:
        return digits.group(1), digits.group(1)
    return '0', '0'


def populate_svg(template: str, volumes: dict, int_id: str, ns_street: str, ew_street: str) -> str:
    svg = template
    svg = set_int_number(svg, int_id)
    svg = set_ns_street(svg, ns_street)
    svg = set_ew_street(svg, ew_street)
    for transform, field in TMAP:
        val = volumes.get(field, '0')
        svg = splice_value(svg, transform, val)
    return svg


def build_svgs(template: str, row: dict):
    int_id = row['Intersection'].strip()
    ns = row['NS_Street'].strip()
    ew = row['EW_Street'].strip()

    fields = ['EBL', 'EBT', 'EBR', 'WBL', 'WBT', 'WBR', 'NBL', 'NBT', 'NBR', 'SBL', 'SBT', 'SBR']
    am_vols = {}
    pm_vols = {}
    for f in fields:
        raw = row.get(f, '0 (0)').strip()
        am, pm = parse_am_pm(raw)
        am_vols[f] = am
        pm_vols[f] = pm

    both_vols = {}
    for f in fields:
        both_vols[f] = f'{am_vols[f]}({pm_vols[f]})'

    svg_am = populate_svg(template, am_vols, int_id, ns, ew)
    svg_pm = populate_svg(template, pm_vols, int_id, ns, ew)
    svg_both = populate_svg(template, both_vols, int_id, ns, ew)

    return am_vols, pm_vols, svg_am, svg_pm, svg_both


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/upload")
async def upload(
    project_id: str = Form(...),
    svg_template: UploadFile = File(...),
    csv_file: UploadFile = File(...),
):
    raw_svg = (await svg_template.read()).decode("utf-8", errors="replace")
    template = prepare_template(raw_svg)

    raw_csv = (await csv_file.read()).decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(raw_csv))
    # strip whitespace from header keys
    rows = []
    for row in reader:
        rows.append({k.strip(): v for k, v in row.items()})

    # Delete existing intersections for this project (re-upload replaces all)
    supabase.table("intersections").delete().eq("project_id", project_id).execute()

    results = []
    for idx, row in enumerate(rows):
        am_vols, pm_vols, svg_am, svg_pm, svg_both = build_svgs(template, row)
        record = {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "int_id": row["Intersection"].strip(),
            "ns_street": row["NS_Street"].strip(),
            "ew_street": row["EW_Street"].strip(),
            "am_volumes": am_vols,
            "pm_volumes": pm_vols,
            "svg_am": svg_am,
            "svg_pm": svg_pm,
            "svg_both": svg_both,
            "x": 60 + (idx % 4) * 480,
            "y": 60 + (idx // 4) * 480,
            "sort_order": idx,
        }
        results.append(record)

    supabase.table("intersections").insert(results).execute()
    return {"inserted": len(results)}
