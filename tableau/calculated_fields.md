# Tableau calculated fields

Field names match the columns of `darkstore_orders_flat.csv`. Paste each formula into
**Analysis → Create Calculated Field**. Names in **bold** are the field names to use.

## Row-level fields

**Order Date**
```
DATE([order_datetime])
```

**Order Hour**
```
DATEPART('hour', [order_datetime])
```

**Is Delivered**
```
[status] = "Delivered"
```

**Weather**
```
IF [is_rain_day] = 1 THEN "Rain day" ELSE "Dry day" END
```

**Hour Band**
```
IF [Order Hour] < 10 THEN "Morning (6-10)"
ELSEIF [Order Hour] < 17 THEN "Daytime (10-17)"
ELSEIF [Order Hour] < 23 THEN "Evening rush (17-23)"
ELSE "Late night (23+)"
END
```

**Delay Band**
```
IF NOT [Is Delivered] THEN "Cancelled"
ELSEIF [delivery_minutes] <= 10 THEN "1. On time (<=10)"
ELSEIF [delivery_minutes] <= 12 THEN "2. 10-12 min"
ELSEIF [delivery_minutes] <= 15 THEN "3. 12-15 min"
ELSEIF [delivery_minutes] <= 20 THEN "4. 15-20 min"
ELSE "5. 20+ min"
END
```

**Within SLA** (follows the `p.SLA Target` parameter)
```
IF [Is Delivered] AND [delivery_minutes] <= [p.SLA Target] THEN 1 ELSE 0 END
```

## KPIs (aggregate)

**Total Orders**
```
COUNTD([order_id])
```

**Delivered Orders**
```
SUM(IF [Is Delivered] THEN 1 ELSE 0 END)
```

**SLA %**
```
SUM([Within SLA]) / [Delivered Orders]
```

**Cancellation Rate**
```
1 - [Delivered Orders] / [Total Orders]
```

**Net Revenue**
```
SUM([net_revenue])
```

**AOV**
```
[Net Revenue] / [Delivered Orders]
```

**Contribution Margin %**
```
SUM([contribution]) / [Net Revenue]
```

**Avg Delivery Min**
```
AVG([delivery_minutes])
```

**Avg Rating**
```
AVG([rating])
```

**Low Rating Share**
```
SUM(IF [rating] <= 2 THEN 1 ELSE 0 END) / COUNT([rating])
```

**Selected Metric** (for the `p.Metric` switch)
```
CASE [p.Metric]
WHEN "Net Revenue" THEN [Net Revenue]
WHEN "Orders" THEN [Total Orders]
WHEN "SLA %" THEN [SLA %]
WHEN "Contribution Margin %" THEN [Contribution Margin %]
END
```

## LOD expressions

**City SLA %** (benchmark that ignores the store dimension in the view)
```
{FIXED : SUM([Within SLA])} / {FIXED : SUM(IF [Is Delivered] THEN 1 ELSE 0 END)}
```

**SLA vs City (pp)**
```
([SLA %] - MIN([City SLA %])) * 100
```

**Signup Month** (cohort)
```
DATE(DATEPARSE("yyyy-MM", [signup_month]))
```

**Months Since Signup**
```
DATEDIFF('month', [Signup Month], DATETRUNC('month', [order_datetime]))
```

**Cohort Size**
```
{FIXED [Signup Month] : COUNTD([customer_id])}
```

**Retention %**
```
COUNTD([customer_id]) / MIN([Cohort Size])
```

**Customer Orders**
```
{FIXED [customer_id] : COUNTD([order_id])}
```

**Customer Type**
```
IF [Customer Orders] > 1 THEN "Repeat" ELSE "One-time" END
```

**Orders per Customer**
```
[Total Orders] / COUNTD([customer_id])
```

**Revenue per Customer**
```
[Net Revenue] / COUNTD([customer_id])
```

**Normal Orders per Store-Day**
```
{FIXED : SUM(IF [festival] = "No Festival" THEN 1 ELSE 0 END)}
/ {FIXED : COUNTD(IF [festival] = "No Festival" THEN STR([Order Date]) + [store_id] END)}
```

**Festival Lift %**
```
([Total Orders] / COUNTD(STR([Order Date]) + [store_id])) / MIN([Normal Orders per Store-Day]) - 1
```

## Table calculations

**Running Net Revenue** (compute using Order Date)
```
RUNNING_SUM([Net Revenue])
```

**Net Revenue MoM %** (compute using month of Order Date)
```
(ZN([Net Revenue]) - LOOKUP(ZN([Net Revenue]), -1)) / ABS(LOOKUP(ZN([Net Revenue]), -1))
```

**Orders 7-day Avg** (on a daily axis)
```
WINDOW_AVG([Total Orders], -6, 0)
```

**Store Rank by SLA**
```
RANK([SLA %], 'desc')
```

**Show Top N** (filter = True)
```
[Store Rank by SLA] <= [p.Top N Stores]
```

## Sets

**Selected Channel**: right-click `acquisition_channel` → Create → Set → (leave empty).
Used by the set action on dashboard D3. Put `IN/OUT(Selected Channel)` on the cohort sheet's
Filter shelf and keep `IN`; set the action to "Clearing the selection will: Add all values to set".
