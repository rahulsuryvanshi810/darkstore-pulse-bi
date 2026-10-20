# Power BI report: DarkStore Pulse

A 6-page Power BI report on the quick-commerce data in `../data`. Everything you need is in this folder:

| File | What it is |
|---|---|
| `power_query.m` | Power Query (M) for all 6 tables, with data types set and blanks handled |
| `measures.dax` | Date table, calculated columns and **50+ DAX measures**, grouped by display folder |
| `theme/darkstore_pulse_theme.json` | Report theme (colour-blind-safe palette, card and page styling) |
| `DarkStore_Pulse.pbix` | The finished report (save it here after building) |
| `screenshots/` | One PNG per page, used in the main README |

Building it takes about 2 hours. You need **Power BI Desktop** (free, Microsoft Store).

---

## 1. Load the data (Power Query)

1. Power BI Desktop → **Transform data** → **Manage parameters → New**: name `DataFolder`, type Text,
   value = the full path to this repo's `data\` folder, ending in `\`.
2. For each block in `power_query.m`: **New Source → Blank query → Advanced Editor**, paste, and
   rename the query (`Orders`, `Order Items`, `Stores`, `Products`, `Customers`, `Riders`).
3. **Close & Apply**. Expected row counts: Orders 97,050 · Order Items 305,189 · Customers 20,436 ·
   Products 132 · Riders 100 · Stores 8.

What the queries do: set types with the `en-IN` locale, turn blank cells (cancelled orders) into nulls,
add `order_date` and `order_hour`, add a `location` column for the map and `margin_pct` on Products.

## 2. Data model (star schema)

Create the **Date** table from `measures.dax` (Modeling → New table), then **Mark as date table**.
Relationships, all single-direction, one → many:

```
              Date[Date] ───────────────┐
                                        ▼
 Stores[store_id] ──────────────► Orders ◄────────────── Customers[customer_id]
        │                     (fact, 1 row/order)
        └──► Riders[store_id]       ▲      │
 Riders[rider_id] ──────────────────┘      ▼
                                   Order Items[order_id] ◄── Products[product_id]
                                   (fact, 1 row/line)
```

| From (one) | To (many) |
|---|---|
| `Date[Date]` | `Orders[order_date]` |
| `Stores[store_id]` | `Orders[store_id]` |
| `Stores[store_id]` | `Riders[store_id]` |
| `Riders[rider_id]` | `Orders[rider_id]` (**set inactive** — two paths Stores→Orders would be ambiguous; use `USERELATIONSHIP` if needed) |
| `Customers[customer_id]` | `Orders[customer_id]` |
| `Orders[order_id]` | `Order Items[order_id]` |
| `Products[product_id]` | `Order Items[product_id]` |

Hide all ID and foreign-key columns from report view. Sort `Date[Month]` by `Month Start`
and `Date[Weekday]` by `Weekday No`.

## 3. Measures

1. **Enter data** → a table named `_Measures` with one blank column → load, then delete the column
   (Power BI moves it to the top as a measure table).
2. Paste every measure from `measures.dax`. Put them in display folders `1 Volume` … `7 Titles & labels`
   (Model view → select measure → Properties → Display folder).
3. Add the calculated columns (`Hour Band`, `Delay Band`, `Weather` on Orders; `Cohort Month` on
   Customers; `Months Since Signup` on Orders) and the helper table `Cohort Age`.
4. **What-if parameters** (Modeling → New parameter → Numeric range):
   - `SLA Target`: 5 to 20, step 1, default 10 → drives `SLA %`, so the whole report recalculates
     when a manager asks "what if we promised 12 minutes?"
   - `Top N`: 5 to 25, step 1, default 10 → drives the product ranking.
5. Formats: currency measures `₹#,0` (or `₹#,0.0,,"L"` for lakhs in cards), percentages `0.0%`.

## 4. Report pages

Canvas 1280 × 720. Apply the theme: **View → Themes → Browse for themes →** `theme/darkstore_pulse_theme.json`.
Every page has the same header row: title (text box), `[Page Subtitle]` in a card, and slicers for
**Date (between)**, **Store**, **Zone**. Sync the slicers across pages (View → Sync slicers).

### Page 1 · Executive overview
| Visual | Fields |
|---|---|
| 6 KPI cards (new card visual) | `Net Revenue`, `Total Orders`, `AOV`, `Contribution Margin %`, `SLA %`, `Cancellation Rate`; reference label = `Net Revenue MoM %` / `Orders MoM %` |
| Line chart | X `Date[Month Start]`, Y `Net Revenue`; add **Orders 7D Avg** on a separate small line (not a second axis) |
| Bar chart | Y `Stores[store_name]`, X `SLA %`, bar colour = **fx → Field value → `SLA Colour`**; constant line at 0.6 |
| Map (or Azure map) | Location `Stores[location]` (or lat/long), size `Total Orders`, tooltip `SLA %`, `AOV` |
| Card (text) | `SLA Headline` — the one-line story of the page |

### Page 2 · Delivery & SLA
| Visual | Fields |
|---|---|
| Matrix heatmap | Rows `Date[Weekday]`, columns `Orders[order_hour]`, values `SLA %`; background colour = gradient (blue scale) |
| Slider | `SLA Target` what-if parameter |
| Column chart | X `Orders[Delay Band]`, Y `Avg Rating` — shows ratings collapse after 15 minutes |
| Clustered bar | Y `store_name`, X `SLA %`, legend `Orders[Weather]` (dry vs rain) |
| Decomposition tree | Analyse `SLA Breaches`, explain by store → `Hour Band` → `Weather` → `festival` |
| Key influencers | Analyse `Orders[sla_met]` = 0, explain by `distance_km`, `Hour Band`, `Weather`, `store_name`, `items_count` |
| KPI cards | `Avg Delivery Min`, `P90 Delivery Min`, `Rain SLA Gap (pp)`, `Deliveries per Rider per Day` |

### Page 3 · Customers & retention
| Visual | Fields |
|---|---|
| Matrix (cohort triangle) | Rows `Customers[Cohort Month]`, columns `Cohort Age[Month No]`, values `Retention %`; background = blue gradient |
| Stacked column | X `Date[Month Start]`, Y `New Customers`, legend `Customers[acquisition_channel]` |
| Table | `acquisition_channel`, `Active Customers`, `Orders per Customer`, `Revenue per Customer` (data bars on the last) |
| Cards | `Repeat Customer %`, `Active Customers`, `Orders per Customer` |
| Bar | `payment_method` vs `Cancellation Rate` |

### Page 4 · Products & inventory
| Visual | Fields |
|---|---|
| Scatter | Details `Products[category]`, X `Item Revenue`, Y `Item Margin %`, size `Units Sold` |
| Table (Top N) | `product_name`, `category`, `Item Revenue`, `Units Sold`, `Item Margin %`; visual filter `Show in Top N` = 1 |
| Bar | `category` vs `Item Stockout Rate` |
| Line | X `Date[Month Start]`, Y `Item Revenue`, filter category = Sweets & Festive (festival spikes) |
| Slicer | `Top N` |

### Page 5 · Store drill-through
Drill-through field `Stores[store_name]` (right-click any store on any page → Drill through).
Cards comparing the store with the city (`CALCULATE([SLA %], ALL(Stores))`), daily `Total Orders`
with `Orders 7D Avg`, rider table (`rider_id`, `vehicle_type`, `Delivered Orders`, `Avg Delivery Min`
using `USERELATIONSHIP(Riders[rider_id], Orders[rider_id])`), and cancellation reasons.

### Page 6 · Tooltip page (hidden)
Page size **Tooltip**, *Allow use as tooltip* on. A small line of `Total Orders` by month plus
`SLA %` and `AOV` cards. Set it as the report-page tooltip of the store bar chart and the map.

### Interactivity
- **Bookmarks** + two buttons on Page 1: *Revenue view* (revenue visuals shown) / *Operations view*
  (SLA visuals shown) using the Selection pane.
- **Edit interactions**: the KPI cards should not cross-filter each other.
- **Field parameter** (Modeling → New parameter → Fields) with `Net Revenue`, `Total Orders`,
  `Contribution`, `SLA %` so one chart can switch metric.
- Buttons for page navigation in the header.

## 5. Row-level security (store managers)

Modeling → **Manage roles**:

| Role | Table | DAX filter |
|---|---|---|
| `East Zone Manager` | Stores | `[zone] = "East"` |
| `North-West Zone Manager` | Stores | `[zone] = "North-West"` |

Test with **View as → role**. (In the Power BI Service, assign people to the roles.)

## 6. Save & publish

1. Save as `powerbi/DarkStore_Pulse.pbix` in this repo.
2. Export a PNG of each page (or Snipping Tool) into `powerbi/screenshots/` named
   `1_overview.png` … `5_drillthrough.png`.
3. Optional: **Publish** to the Power BI Service (free account) and paste the link in the main README.
4. Check the numbers against `../outputs/kpi_summary.csv`: Net Revenue ₹4.98 Cr, 97,050 orders,
   SLA 54.1%, cancellation 5.1%, AOV ₹541. If they match, the model is right.
