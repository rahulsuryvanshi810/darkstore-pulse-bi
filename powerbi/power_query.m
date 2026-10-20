// =====================================================================
// DarkStore Pulse - Power Query (M)
// 1. Home -> Transform data -> New parameter: DataFolder (Text),
//    value = full path of this repo's data folder, ending with "\"
//    e.g. C:\Users\you\darkstore-pulse-bi\data\
// 2. For each query below: New Source -> Blank query -> Advanced Editor,
//    paste the block, rename the query to the name in the header.
// =====================================================================


// ---------------- Orders ----------------
let
    Source   = Csv.Document(File.Contents(DataFolder & "orders.csv"),
                 [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers  = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    // cancelled orders have blank minutes / rating / sla_met / reason -> null
    Blanks   = Table.ReplaceValue(Headers, "", null, Replacer.ReplaceValue,
                 {"delivery_minutes", "rating", "sla_met", "cancel_reason"}),
    Typed    = Table.TransformColumnTypes(Blanks, {
        {"order_id", type text}, {"order_datetime", type datetime}, {"store_id", type text},
        {"customer_id", type text}, {"rider_id", type text}, {"status", type text},
        {"cancel_reason", type text}, {"payment_method", type text},
        {"is_first_order", Int64.Type}, {"coupon_used", Int64.Type}, {"is_rain_day", Int64.Type},
        {"festival", type text}, {"items_count", Int64.Type},
        {"item_total", Currency.Type}, {"discount", Currency.Type}, {"delivery_fee", Currency.Type},
        {"cogs", Currency.Type}, {"rider_cost", Currency.Type}, {"distance_km", type number},
        {"delivery_minutes", type number}, {"rating", Int64.Type}, {"had_stockout", Int64.Type},
        {"sla_met", Int64.Type}, {"net_revenue", Currency.Type}, {"contribution", Currency.Type}},
        "en-IN"),
    AddDate  = Table.AddColumn(Typed, "order_date", each DateTime.Date([order_datetime]), type date),
    AddHour  = Table.AddColumn(AddDate, "order_hour", each Time.Hour([order_datetime]), Int64.Type)
in
    AddHour


// ---------------- Order Items ----------------
let
    Source  = Csv.Document(File.Contents(DataFolder & "order_items.csv"),
                [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed   = Table.TransformColumnTypes(Headers, {
        {"order_id", type text}, {"product_id", type text}, {"quantity", Int64.Type},
        {"mrp", Currency.Type}, {"unit_cost", Currency.Type}, {"fulfilled", Int64.Type}}, "en-IN")
in
    Typed


// ---------------- Stores ----------------
let
    Source  = Csv.Document(File.Contents(DataFolder & "stores.csv"),
                [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed   = Table.TransformColumnTypes(Headers, {
        {"store_id", type text}, {"store_name", type text}, {"zone", type text},
        {"latitude", type number}, {"longitude", type number}, {"open_date", type date},
        {"riders", Int64.Type}, {"city", type text}, {"sla_minutes", Int64.Type}}, "en-IN"),
    // "Kothrud, Pune" geocodes reliably in the map visual
    AddLoc  = Table.AddColumn(Typed, "location", each [store_name] & ", Pune, India", type text)
in
    AddLoc


// ---------------- Products ----------------
let
    Source  = Csv.Document(File.Contents(DataFolder & "products.csv"),
                [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed   = Table.TransformColumnTypes(Headers, {
        {"product_id", type text}, {"category", type text}, {"product_name", type text},
        {"mrp", Currency.Type}, {"unit_cost", Currency.Type}, {"shelf_life", type text}}, "en-IN"),
    AddMargin = Table.AddColumn(Typed, "margin_pct", each ([mrp] - [unit_cost]) / [mrp], Percentage.Type)
in
    AddMargin


// ---------------- Customers ----------------
let
    Source  = Csv.Document(File.Contents(DataFolder & "customers.csv"),
                [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed   = Table.TransformColumnTypes(Headers, {
        {"customer_id", type text}, {"home_store_id", type text}, {"signup_date", type date},
        {"acquisition_channel", type text}}, "en-IN")
in
    Typed


// ---------------- Riders ----------------
let
    Source  = Csv.Document(File.Contents(DataFolder & "riders.csv"),
                [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed   = Table.TransformColumnTypes(Headers, {
        {"rider_id", type text}, {"store_id", type text}, {"vehicle_type", type text},
        {"join_date", type date}}, "en-IN")
in
    Typed
