"""Generate the Power BI project (PBIP: TMDL semantic model + report) and the Tableau
workbook (.twb) from the files in powerbi/ and tableau/.

    python scripts/build_bi_files.py

Outputs
    powerbi/DarkStore_Pulse.pbip  (+ .SemanticModel/ and .Report/ folders)  -> open in Power BI Desktop
    tableau/DarkStore_Pulse.twb                                             -> open in Tableau Desktop / Public
"""
import json
import random
import re
import shutil
import uuid
from pathlib import Path
from xml.sax.saxutils import quoteattr

ROOT = Path(__file__).resolve().parents[1]
PBI = ROOT / "powerbi"
TAB = ROOT / "tableau"
NAME = "DarkStore_Pulse"


def q(name):
    """TMDL object name, always quoted."""
    return "'" + name.replace("'", "''") + "'"


RNG = random.Random(42)  # fixed seed: rebuilding gives the same lineage tags, so git diffs stay small


def tag():
    return str(uuid.UUID(int=RNG.getrandbits(128), version=4))


def indent(text, n):
    return "\n".join(("\t" * n + line) if line.strip() else "" for line in text.strip("\n").splitlines())


# --------------------------------------------------------------------------- measures from measures.dax
def parse_measures():
    src = (PBI / "measures.dax").read_text(encoding="utf-8")
    out, folder, cur = [], None, None
    for line in src.splitlines():
        m = re.match(r"// Folder: (.+)", line)
        if m:
            folder = m.group(1).strip()
            continue
        if folder is None or line.startswith("//") or line.startswith("// ="):
            continue
        m = re.match(r"^([A-Za-z][^=]*?)\s*=\s*(.*)$", line)
        if m and not line.startswith((" ", "\t", "VAR ", "RETURN")):
            cur = {"name": m.group(1).strip(), "expr": [m.group(2)], "folder": folder}
            out.append(cur)
        elif cur is not None:
            cur["expr"].append(line)
    for m in out:
        lines = [re.sub(r"\s+//.*$", "", l).rstrip() for l in m["expr"]]
        while lines and not lines[-1].strip():
            lines.pop()
        while lines and not lines[0].strip():
            lines.pop(0)
        m["expr"] = "\n".join(lines)
    return out


def fmt(name):
    n = name.lower()
    if name in ("SLA Colour", "Page Subtitle", "SLA Headline"):
        return None
    if "%" in name or n.endswith(" rate") or n.endswith(" share"):
        return "0.0%"
    if "(pp)" in n:
        return "0.0"
    if any(w in n for w in ("min", "rider per day", "per customer")) and "revenue" not in n:
        return "0.0" if "min" in n or "rider" in n or "orders per customer" in n else "#,0"
    if "rating" in n and "share" not in n:
        return "0.00"
    if any(w in n for w in ("revenue", "gmv", "discount", "contribution", "aov", "profit")):
        return "₹#,0"
    if "per store per day" in n:
        return "0.0"
    return "#,0"


# --------------------------------------------------------------------------- Power Query (M) per table
def power_query():
    src = (PBI / "power_query.m").read_text(encoding="utf-8")
    blocks = re.split(r"// ---------------- (.+?) ----------------\n", src)[1:]
    return {blocks[i].strip(): blocks[i + 1].strip() for i in range(0, len(blocks), 2)}


# column name -> (TMDL dataType, formatString or None, summarizeBy)
COLS = {
    "Orders": [
        ("order_id", "string"), ("order_datetime", "dateTime"), ("store_id", "string"), ("customer_id", "string"),
        ("rider_id", "string"), ("status", "string"), ("cancel_reason", "string"), ("payment_method", "string"),
        ("is_first_order", "int64"), ("coupon_used", "int64"), ("is_rain_day", "int64"), ("festival", "string"),
        ("items_count", "int64"), ("item_total", "decimal"), ("discount", "decimal"), ("delivery_fee", "decimal"),
        ("cogs", "decimal"), ("rider_cost", "decimal"), ("distance_km", "double"), ("delivery_minutes", "double"),
        ("rating", "int64"), ("had_stockout", "int64"), ("sla_met", "int64"), ("net_revenue", "decimal"),
        ("contribution", "decimal"), ("order_date", "dateTime"), ("order_hour", "int64")],
    "Order Items": [("order_id", "string"), ("product_id", "string"), ("quantity", "int64"), ("mrp", "decimal"),
                    ("unit_cost", "decimal"), ("fulfilled", "int64")],
    "Stores": [("store_id", "string"), ("store_name", "string"), ("zone", "string"), ("latitude", "double"),
               ("longitude", "double"), ("open_date", "dateTime"), ("riders", "int64"), ("city", "string"),
               ("sla_minutes", "int64"), ("location", "string")],
    "Products": [("product_id", "string"), ("category", "string"), ("product_name", "string"), ("mrp", "decimal"),
                 ("unit_cost", "decimal"), ("shelf_life", "string"), ("margin_pct", "double")],
    "Customers": [("customer_id", "string"), ("home_store_id", "string"), ("signup_date", "dateTime"),
                  ("acquisition_channel", "string")],
    "Riders": [("rider_id", "string"), ("store_id", "string"), ("vehicle_type", "string"), ("join_date", "dateTime")],
}
HIDDEN = {"order_id", "store_id", "customer_id", "rider_id", "product_id", "home_store_id"}
CAT = {"latitude": "Latitude", "longitude": "Longitude", "location": "Place", "city": "City"}

CALC_COLS = {
    "Orders": [
        ("Hour Band", "string", '''SWITCH (
	TRUE (),
	Orders[order_hour] < 10, "1 Morning (6-10)",
	Orders[order_hour] < 17, "2 Daytime (10-17)",
	Orders[order_hour] < 23, "3 Evening rush (17-23)",
	"4 Late night (23+)"
)'''),
        ("Delay Band", "string", '''SWITCH (
	TRUE (),
	ISBLANK ( Orders[delivery_minutes] ), "Cancelled",
	Orders[delivery_minutes] <= 10, "1 On time (<=10)",
	Orders[delivery_minutes] <= 12, "2 10-12 min",
	Orders[delivery_minutes] <= 15, "3 12-15 min",
	Orders[delivery_minutes] <= 20, "4 15-20 min",
	"5 20+ min"
)'''),
        ("Weather", "string", 'IF ( Orders[is_rain_day] = 1, "Rain day", "Dry day" )'),
        ("Months Since Signup", "int64",
         "DATEDIFF ( RELATED ( Customers[Cohort Month] ), Orders[order_date], MONTH )"),
    ],
    "Customers": [("Cohort Month", "dateTime",
                   "DATE ( YEAR ( Customers[signup_date] ), MONTH ( Customers[signup_date] ), 1 )")],
}

DATE_DAX = '''VAR _start = DATE ( 2025, 10, 1 )
VAR _end = DATE ( 2026, 9, 30 )
RETURN
	ADDCOLUMNS (
		CALENDAR ( _start, _end ),
		"Year", YEAR ( [Date] ),
		"Month No", MONTH ( [Date] ),
		"Month", FORMAT ( [Date], "MMM yyyy" ),
		"Month Start", DATE ( YEAR ( [Date] ), MONTH ( [Date] ), 1 ),
		"Week Start", [Date] - WEEKDAY ( [Date], 2 ) + 1,
		"Weekday", FORMAT ( [Date], "ddd" ),
		"Weekday No", WEEKDAY ( [Date], 2 ),
		"Is Weekend", IF ( WEEKDAY ( [Date], 2 ) >= 6, "Weekend", "Weekday" )
	)'''
DATE_COLS = [("Date", "dateTime", "d mmm yyyy"), ("Year", "int64", "0"), ("Month No", "int64", "0"),
             ("Month", "string", None), ("Month Start", "dateTime", "mmm yyyy"), ("Week Start", "dateTime", "d mmm yyyy"),
             ("Weekday", "string", None), ("Weekday No", "int64", "0"), ("Is Weekend", "string", None)]

RELS = [("Orders", "order_date", "Date", "Date", True), ("Orders", "store_id", "Stores", "store_id", True),
        ("Riders", "store_id", "Stores", "store_id", True), ("Orders", "rider_id", "Riders", "rider_id", False),
        ("Orders", "customer_id", "Customers", "customer_id", True),
        ("Order Items", "order_id", "Orders", "order_id", True),
        ("Order Items", "product_id", "Products", "product_id", True)]


def column(name, dtype, fmt_=None, hidden=False, source=None, expr=None, sort_by=None, category=None, key=False):
    head = f"\tcolumn {q(name)}" + (" =\n" + indent(expr, 3) if expr else "")
    props = [f"dataType: {dtype}"]
    if fmt_:
        props.append(f"formatString: {fmt_}")
    if hidden:
        props.append("isHidden")
    if key:
        props.append("isKey")
    props.append(f"lineageTag: {tag()}")
    if category:
        props.append(f"dataCategory: {category}")
    props.append("summarizeBy: " + ("sum" if dtype in ("decimal", "double") and not category else "none"))
    if source:
        props.append(f"sourceColumn: {source}")
    if sort_by:
        props.append(f"sortByColumn: {q(sort_by)}")
    return head + "\n" + "\n".join("\t\t" + p for p in props) + "\n"


def build_pbip():
    out = PBI / "DarkStore_Pulse"
    if out.exists():
        shutil.rmtree(out)
    sm = out / f"{NAME}.SemanticModel"
    rp = out / f"{NAME}.Report"
    (sm / "definition" / "tables").mkdir(parents=True)
    rp.mkdir(parents=True)

    (out / f"{NAME}.pbip").write_text(json.dumps({
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True}}, indent=2), encoding="utf-8")
    (sm / "definition.pbism").write_text(json.dumps({"version": "4.0", "settings": {}}, indent=2), encoding="utf-8")
    (rp / "definition.pbir").write_text(json.dumps({
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}}, indent=2),
        encoding="utf-8")

    d = sm / "definition"
    (d / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1567\n\n", encoding="utf-8")

    tables = ["_Measures", "Orders", "Order Items", "Stores", "Products", "Customers", "Riders", "Date",
              "SLA Target", "Top N", "Cohort Age"]
    model = ["model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
             "\tsourceQueryCulture: en-IN", "\tdataAccessOptions", "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull",
             ""] + [f"ref table {q(t)}" for t in tables] + ["", "ref expression DataFolder", ""]
    (d / "model.tmdl").write_text("\n".join(model) + "\n", encoding="utf-8")

    data_dir = str(ROOT / "data") + "\\"
    (d / "expressions.tmdl").write_text(
        f'expression DataFolder = "{data_dir}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
        f"\tlineageTag: {tag()}\n\n", encoding="utf-8")

    rels = []
    for ft, fc, tt, tc, active in RELS:
        r = f"relationship {tag()}\n"
        if not active:
            r += "\tisActive: false\n"
        r += f"\tfromColumn: {q(ft)}.{q(fc)}\n\ttoColumn: {q(tt)}.{q(tc)}\n"
        rels.append(r)
    (d / "relationships.tmdl").write_text("\n".join(rels), encoding="utf-8")

    mq = power_query()
    for t, cols in COLS.items():
        body = [f"table {q(t)}", f"\tlineageTag: {tag()}", ""]
        for c, dt in cols:
            f = "0.00" if c in ("distance_km", "delivery_minutes", "margin_pct") else (
                "₹#,0.00" if dt == "decimal" else ("d mmm yyyy" if dt == "dateTime" and c != "order_datetime" else
                                                         ("d mmm yyyy hh:mm" if c == "order_datetime" else
                                                          ("0" if dt == "int64" else None))))
            if c == "margin_pct":
                f = "0.0%"
            body.append(column(c, dt, f, hidden=c in HIDDEN, source=c, category=CAT.get(c)))
        for name, dt, expr in CALC_COLS.get(t, []):
            body.append(column(name, dt, "mmm yyyy" if dt == "dateTime" else ("0" if dt == "int64" else None),
                               expr=expr))
        body.append(f"\tpartition {q(t)} = m\n\t\tmode: import\n\t\tsource =\n{indent(mq[t], 4)}\n")
        body.append("\tannotation PBI_ResultType = Table\n")
        (d / "tables" / f"{t}.tmdl").write_text("\n".join(body) + "\n", encoding="utf-8")

    # Date table (calculated, marked as date table)
    body = ["table Date", "\tdataCategory: Time", f"\tlineageTag: {tag()}", ""]
    for c, dt, f in DATE_COLS:
        sort = {"Month": "Month Start", "Weekday": "Weekday No"}.get(c)
        body.append(column(c, dt, f, source=f"[{c}]", sort_by=sort, key=(c == "Date")))
    body.append(f"\tpartition Date = calculated\n\t\tmode: import\n\t\tsource =\n{indent(DATE_DAX, 4)}\n")
    (d / "tables" / "Date.tmdl").write_text("\n".join(body) + "\n", encoding="utf-8")

    # what-if / helper tables
    for t, col, dax, default in [("SLA Target", "SLA Target", "GENERATESERIES ( 5, 20, 1 )", 10),
                                 ("Top N", "Top N", "GENERATESERIES ( 5, 25, 1 )", 10),
                                 ("Cohort Age", "Month No", "GENERATESERIES ( 0, 11, 1 )", None)]:
        body = [f"table {q(t)}", f"\tlineageTag: {tag()}", "",
                column(col, "int64", "0", source="[Value]")]
        body.append(f"\tpartition {q(t)} = calculated\n\t\tmode: import\n\t\tsource = {dax}\n")
        (d / "tables" / f"{t}.tmdl").write_text("\n".join(body) + "\n", encoding="utf-8")

    # measure table
    measures = parse_measures()
    body = ["table _Measures", f"\tlineageTag: {tag()}", ""]
    for m in measures:
        expr = m["expr"]
        head = f"\tmeasure {q(m['name'])} = " + (expr.strip() if "\n" not in expr else "\n" + indent(expr, 3))
        props = [f"lineageTag: {tag()}"]
        f = fmt(m["name"])
        if f:
            props.append(f"formatString: {f}")
        props.append(f"displayFolder: {m['folder']}")
        body.append(head + "\n" + "\n".join("\t\t" + p for p in props) + "\n")
    body.append(column("Value", "int64", hidden=True, source="[Value]"))
    body.append("\tpartition _Measures = calculated\n\t\tmode: import\n\t\tsource = { 0 }\n")
    (d / "tables" / "_Measures.tmdl").write_text("\n".join(body) + "\n", encoding="utf-8")

    build_report(rp)
    return len(measures)


# --------------------------------------------------------------------------- report (legacy report.json)
def _field(kind, entity, prop, alias):
    return {kind: {"Expression": {"SourceRef": {"Source": alias}}, "Property": prop}, "Name": f"{entity}.{prop}"}


def visual(vid, vtype, x, y, w, h, roles, title=None):
    """roles: {role: [(kind 'Measure'|'Column', entity, property)]}"""
    aliases, frm, select, proj = {}, [], [], {}
    for role, fields in roles.items():
        proj[role] = []
        for kind, ent, prop in fields:
            if ent not in aliases:
                aliases[ent] = f"t{len(aliases)}"
                frm.append({"Name": aliases[ent], "Entity": ent, "Type": 0})
            sel = _field(kind, ent, prop, aliases[ent])
            if sel["Name"] not in [s["Name"] for s in select]:
                select.append(sel)
            proj[role].append({"queryRef": f"{ent}.{prop}"})
    sv = {"visualType": vtype, "projections": proj,
          "prototypeQuery": {"Version": 2, "From": frm, "Select": select}, "drillFilterOtherVisuals": True}
    if title:
        sv["vcObjects"] = {"title": [{"properties": {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "text": {"expr": {"Literal": {"Value": "'" + title.replace("'", "''") + "'"}}}}}]}
    cfg = {"name": vid, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": 0, "width": w, "height": h}}],
           "singleVisual": sv}
    return {"x": x, "y": y, "z": 0, "width": w, "height": h, "config": json.dumps(cfg), "filters": "[]"}


M = lambda p: ("Measure", "_Measures", p)
C = lambda e, p: ("Column", e, p)


def page(name, display, visuals, ordinal):
    return {"name": name, "displayName": display, "displayOption": 1, "width": 1280, "height": 720,
            "ordinal": ordinal, "config": "{}", "filters": "[]", "visualContainers": visuals}


def build_report(rp):
    slicers = lambda p: [
        visual(f"{p}s1", "slicer", 20, 16, 300, 60, {"Values": [C("Date", "Date")]}, "Date"),
        visual(f"{p}s2", "slicer", 340, 16, 300, 60, {"Values": [C("Stores", "store_name")]}, "Store"),
        visual(f"{p}s3", "slicer", 660, 16, 300, 60, {"Values": [C("Stores", "zone")]}, "Zone"),
    ]
    cards = [("Net Revenue", "Net revenue"), ("Total Orders", "Orders"), ("AOV", "Avg order value"),
             ("Contribution Margin %", "Contribution margin"), ("SLA %", "On-time (<=10 min)"),
             ("Cancellation Rate", "Cancellation rate")]
    p1 = slicers("a") + [visual(f"ac{i}", "card", 20 + i * 207, 92, 197, 100, {"Values": [M(m)]}, t)
                         for i, (m, t) in enumerate(cards)] + [
        visual("aline", "lineChart", 20, 208, 760, 290,
               {"Category": [C("Date", "Month Start")], "Y": [M("Net Revenue")]}, "Monthly net revenue"),
        visual("abar", "clusteredBarChart", 796, 208, 464, 290,
               {"Category": [C("Stores", "store_name")], "Y": [M("SLA %")]}, "On-time rate by store"),
        visual("adiv", "clusteredColumnChart", 20, 514, 760, 190,
               {"Category": [C("Orders", "festival")], "Y": [M("Orders per Store per Day")]},
               "Orders per store per day by festival"),
        visual("apay", "clusteredBarChart", 796, 514, 464, 190,
               {"Category": [C("Orders", "payment_method")], "Y": [M("Cancellation Rate")]},
               "Cancellation rate by payment method"),
    ]
    p2 = slicers("b") + [
        visual("bslider", "slicer", 980, 16, 280, 60, {"Values": [C("SLA Target", "SLA Target")]}, "SLA target (min)"),
        visual("bheat", "pivotTable", 20, 92, 760, 300,
               {"Rows": [C("Date", "Weekday")], "Columns": [C("Orders", "order_hour")], "Values": [M("SLA %")]},
               "On-time rate by weekday and hour"),
        visual("brain", "clusteredBarChart", 796, 92, 464, 300,
               {"Category": [C("Stores", "store_name")], "Series": [C("Orders", "Weather")], "Y": [M("SLA %")]},
               "On-time rate: dry vs rain days"),
        visual("bdelay", "clusteredColumnChart", 20, 408, 620, 296,
               {"Category": [C("Orders", "Delay Band")], "Y": [M("Avg Rating")]}, "Average rating by delivery time"),
        visual("bk1", "card", 656, 408, 296, 140, {"Values": [M("Avg Delivery Min")]}, "Avg delivery minutes"),
        visual("bk2", "card", 964, 408, 296, 140, {"Values": [M("P90 Delivery Min")]}, "90th percentile minutes"),
        visual("bk3", "card", 656, 564, 296, 140, {"Values": [M("Rain SLA Gap (pp)")]}, "Rain SLA gap (points)"),
        visual("bk4", "card", 964, 564, 296, 140, {"Values": [M("Deliveries per Rider per Day")]},
               "Deliveries per rider per day"),
    ]
    p3 = slicers("c") + [
        visual("ccoh", "pivotTable", 20, 92, 760, 400,
               {"Rows": [C("Customers", "Cohort Month")], "Columns": [C("Cohort Age", "Month No")],
                "Values": [M("Retention %")]}, "Customer retention by signup month"),
        visual("cch", "tableEx", 796, 92, 464, 240,
               {"Values": [C("Customers", "acquisition_channel"), M("Active Customers"), M("Orders per Customer"),
                           M("Revenue per Customer")]}, "Value by acquisition channel"),
        visual("ck1", "card", 796, 348, 226, 144, {"Values": [M("Repeat Customer %")]}, "Repeat customers"),
        visual("ck2", "card", 1034, 348, 226, 144, {"Values": [M("Orders per Customer")]}, "Orders per customer"),
        visual("ccat", "clusteredBarChart", 20, 508, 760, 196,
               {"Category": [C("Products", "category")], "Y": [M("Item Revenue")]}, "Revenue by category"),
        visual("cstk", "clusteredBarChart", 796, 508, 464, 196,
               {"Category": [C("Products", "category")], "Y": [M("Item Stockout Rate")]}, "Stockout rate by category"),
    ]
    report = {
        "config": json.dumps({"version": "5.43", "themeCollection": {}, "activeSectionIndex": 0,
                              "defaultDrillFilterOtherVisuals": True, "settings": {"useStylableVisualContainerHeader": True}}),
        "layoutOptimization": 0,
        "resourcePackages": [],
        "sections": [page("ReportSection1", "1 Executive overview", p1, 0),
                     page("ReportSection2", "2 Delivery & SLA", p2, 1),
                     page("ReportSection3", "3 Customers & products", p3, 2)],
    }
    (rp / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- Tableau workbook
TCOLS = [("order_id", "string"), ("order_datetime", "datetime"), ("store_id", "string"), ("customer_id", "string"),
         ("rider_id", "string"), ("status", "string"), ("cancel_reason", "string"), ("payment_method", "string"),
         ("is_first_order", "integer"), ("coupon_used", "integer"), ("is_rain_day", "integer"), ("festival", "string"),
         ("items_count", "integer"), ("item_total", "real"), ("discount", "real"), ("delivery_fee", "real"),
         ("cogs", "real"), ("rider_cost", "real"), ("distance_km", "real"), ("delivery_minutes", "real"),
         ("rating", "integer"), ("had_stockout", "integer"), ("sla_met", "integer"), ("net_revenue", "real"),
         ("contribution", "real"), ("store_name", "string"), ("zone", "string"), ("latitude", "real"),
         ("longitude", "real"), ("acquisition_channel", "string"), ("signup_month", "string")]


def parse_tableau_calcs():
    src = (TAB / "calculated_fields.md").read_text(encoding="utf-8")
    return [(n, f.strip()) for n, f in re.findall(r"\*\*(.+?)\*\*[^\n]*\n```\n(.*?)\n```", src, re.S)]


def build_twb():
    calcs = parse_tableau_calcs()
    params = {"p.SLA Target": ("integer", "10", ("range", 5, 20, 1)),
              "p.Top N Stores": ("integer", "5", ("range", 3, 8, 1)),
              "p.Metric": ("string", '"Net Revenue"', ("list", ["Net Revenue", "Orders", "SLA %", "Contribution Margin %"]))}
    x = ["<?xml version='1.0' encoding='utf-8' ?>",
         "<workbook source-build='2024.2.0 (20242.24.0807.0327)' source-platform='win' version='18.1' "
         "xmlns:user='http://www.tableausoftware.com/xml/user'>",
         "  <preferences />", "  <datasources>",
         "    <datasource hasconnection='false' inline='true' name='Parameters' version='18.1'>",
         "      <aliases enabled='yes' />"]
    for n, (dt, val, dom) in params.items():
        if dom[0] == "range":
            x.append(f"      <column caption={quoteattr(n)} datatype='{dt}' name={quoteattr('[' + n + ']')} "
                     f"param-domain-type='range' role='measure' type='quantitative' value='{val}'>")
            x.append(f"        <calculation class='tableau' formula='{val}' />")
            x.append(f"        <range granularity='{dom[3]}' max='{dom[2]}' min='{dom[1]}' />")
        else:
            x.append(f"      <column caption={quoteattr(n)} datatype='string' name={quoteattr('[' + n + ']')} "
                     f"param-domain-type='list' role='measure' type='nominal' value={quoteattr(val)}>")
            x.append(f"        <calculation class='tableau' formula={quoteattr(val)} />")
            x.append("        <members>")
            for mbr in dom[1]:
                x.append(f"          <member value={quoteattr(chr(34) + mbr + chr(34))} />")
            x.append("        </members>")
        x.append("      </column>")
    x.append("    </datasource>")
    x += ["    <datasource caption='DarkStore Orders' inline='true' name='federated.darkstore0001' version='18.1'>",
          "      <connection class='federated'>", "        <named-connections>",
          "          <named-connection caption='darkstore_orders_flat' name='textscan.darkstore0001'>",
          f"            <connection class='textscan' directory={quoteattr(str(TAB).replace(chr(92), '/'))} "
          "filename='darkstore_orders_flat.csv' password='' server='' />",
          "          </named-connection>", "        </named-connections>",
          "        <relation connection='textscan.darkstore0001' name='darkstore_orders_flat.csv' "
          "table='[darkstore_orders_flat#csv]' type='table'>",
          "          <columns character-set='UTF-8' header='yes' locale='en_IN' separator=','>"]
    for i, (c, dt) in enumerate(TCOLS):
        x.append(f"            <column datatype='{dt}' name='{c}' ordinal='{i}' />")
    x += ["          </columns>", "        </relation>", "      </connection>", "      <aliases enabled='yes' />"]
    x.append("      <column datatype='real' name='[latitude]' role='dimension' semantic-role='[Geographical].[Latitude]' type='quantitative' />")
    x.append("      <column datatype='real' name='[longitude]' role='dimension' semantic-role='[Geographical].[Longitude]' type='quantitative' />")
    aggregate = re.compile(r"\b(SUM|AVG|COUNT|COUNTD|MIN|MAX|ATTR|RUNNING_SUM|LOOKUP|WINDOW_AVG|RANK|ZN)\s*\(")
    names = {n for n, _ in calcs}
    for n, f in calcs:
        f = re.sub(r"\[(p\.[^\]]+)\]", r"[Parameters].[\1]", f)
        is_agg = bool(aggregate.search(f)) or any(f"[{o}]" in f for o in names if o != n and o in
                                                 ("Total Orders", "Delivered Orders", "SLA %", "Net Revenue"))
        if n in ("Is Delivered", "Show Top N"):
            dt, role, typ = "boolean", "dimension", "nominal"
        elif n in ("Weather", "Hour Band", "Delay Band", "Customer Type"):
            dt, role, typ = "string", "dimension", "nominal"
        elif n in ("Order Date", "Signup Month"):
            dt, role, typ = "date", "dimension", "ordinal"
        elif n in ("Order Hour", "Months Since Signup"):
            dt, role, typ = "integer", "dimension", "ordinal"
        elif n == "Within SLA" or n == "Customer Orders" or n == "Cohort Size":
            dt, role, typ = "integer", "measure", "quantitative"
        else:
            dt, role, typ = "real", "measure", "quantitative"
        x.append(f"      <column caption={quoteattr(n)} datatype='{dt}' name={quoteattr('[' + n + ']')} "
                 f"role='{role}' type='{typ}'>")
        x.append(f"        <calculation class='tableau' formula={quoteattr(f)} />")
        x.append("      </column>")
    x += ["    </datasource>", "  </datasources>", "  <worksheets>"]
    for ws in ["Start here - drag fields from the Data pane"]:
        x += [f"    <worksheet name={quoteattr(ws)}>", "      <table>", "        <view>",
              "          <datasources />", "          <aggregation value='true' />", "        </view>",
              "        <style />", "        <panes>", "          <pane selection-relaxation-option='selection-relaxation-allow'>",
              "            <view>", "              <breakdown value='auto' />", "            </view>",
              "            <mark class='Automatic' />", "          </pane>", "        </panes>",
              "        <rows />", "        <cols />", "      </table>",
              f"      <simple-id uuid='{{{tag().upper()}}}' />", "    </worksheet>"]
    x += ["  </worksheets>", "</workbook>", ""]
    (TAB / f"{NAME}.twb").write_text("\n".join(x), encoding="utf-8")
    return len(calcs)


if __name__ == "__main__":
    import sys
    # The committed PBIP has since been opened and saved by Power BI Desktop (PBIR report format),
    # so it is the master copy; only regenerate it on purpose.
    if (PBI / "DarkStore_Pulse").exists() and "--force" not in sys.argv:
        print("Power BI: powerbi/DarkStore_Pulse exists (saved by Power BI Desktop), skipped; use --force to rebuild")
    else:
        n = build_pbip()
        print(f"Power BI: powerbi/DarkStore_Pulse/{NAME}.pbip ({n} measures)")
    k = build_twb()
    print(f"Tableau:  tableau/{NAME}.twb ({k} calculated fields, 3 parameters)")
