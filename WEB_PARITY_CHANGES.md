# Bails Ledger — iPhone app changes to bring to the web app

This document lists every feature added to the iPhone app across the last two working sessions, written so the same behaviour can be built into the web version (bails-ledger.onrender.com). For each feature it gives what the user sees, the rules, the formulas, and any data or SQL changes.

Both apps share the same Neon database. The new settings keys and SQL below were chosen so the website keeps working unchanged until it adopts them.

---

## Contents

1. [Summary](#1-summary)
2. [Dashboard](#2-dashboard)
3. [Export ledger and backup by period](#3-export-ledger-and-backup-by-period)
4. [Excel workbook format](#4-excel-workbook-format)
5. [Ground calendar](#5-ground-calendar)
6. [Partners: add, edit, remove](#6-partners-add-edit-remove)
7. [Send mail](#7-send-mail)
8. [Net profit labels](#8-net-profit-labels)
9. [Assistant](#9-assistant)
10. [Revenue forecast](#10-revenue-forecast)
11. [Data, settings and SQL changes](#11-data-settings-and-sql-changes)
12. [Acceptance checks](#12-acceptance-checks)

---

## 1. Summary

| # | Feature | Where in the app |
|---|---|---|
| 1 | Opening and closing balance for the selected period, smaller KPI tiles | Dashboard |
| 2 | Month-by-month opening/closing balances when the period is longer than a month | Dashboard |
| 3 | Income vs expenses card: graph **or** table (one replaces the other) | Dashboard |
| 4 | Export ledger (Excel/CSV), download backup, by Monthly / Quarterly / Yearly / All | More → Export screen |
| 5 | Excel export with the website's colours, plus a Ground Calendar sheet | All exports and mail |
| 6 | Calendar: visible Unblock, Re-block after unblocking, edit a block, unblock whole day | Calendar → day |
| 7 | Calendar export (Excel/CSV); "Blocked this month" list removed | Calendar, Export screen |
| 8 | Partners: add, rename, change equity, activate/deactivate, remove; live amounts | Partners → Edit partners |
| 9 | Send mail with the period's Excel attached, auto subject/body, editable recipients | More, Dashboard |
| 10 | "Net Profit (Monthly)", "Net Loss (Quarterly)", etc. | Everywhere net is shown |
| 11 | Assistant: plain-English commands and questions, confirm-before-save | Sparkles button on Dashboard, Ledger, Calendar |
| 12 | Revenue forecast by financial year, with ₹60,000/month rent from April 2027 | Dashboard card, More → Revenue forecast |

---

## 2. Dashboard

### 2.1 KPI tiles (smaller, two rows)

The four large tiles were replaced by five compact tiles so the whole period fits on one screen.

| Row | Tile | Value | Caption |
|---|---|---|---|
| 1 | **Opening balance** | Balance brought into the period (formula below) | `Brought forward to {start date, e.g. 01 Oct}`, or `Starting balance` for All time |
| 1 | **Closing balance** | Balance at the period's end (unchanged formula) | `As of {end date}`, or `All entries` |
| 2 | **Income** | Period income | `Credit` |
| 2 | **Expenses** | Period expenses | `Debit` |
| 2 | **Net Profit (Monthly)** / **Net Loss (…)** | Income − expenses | `{margin}% margin`, or `No income` |

Compact style: caption-2 uppercase title, sub-headline bold value, 10 px padding, 3 px coloured left edge.

Colours, unchanged from the web brand:
- Opening: `#17593C`. In dark mode, `#7FD8A8`.
- Closing: `#2CAA70`.
- Income: `#17876A`.
- Expense: `#D72228`.
- Net: `#273076`.

**Opening balance formula**

```
opening_for_period = opening_balance_setting + Σ signed(entry) for every entry dated before period.start
                     (All time: just opening_balance_setting)
signed(entry) = +amount for income, −amount for expense
```

### 2.2 Month-by-month card

Shown only when the period spans more than one calendar month (quarter, year, all time, or a long custom range).

| Month | Opening | Net | Closing |
|---|---|---|---|
| Oct 2026 | ₹1,500 | +₹3,800 (green) | ₹5,300 |
| Nov 2026 | ₹5,300 | ₹0 | ₹5,300 |
| Dec 2026 | ₹5,300 | −₹300 (red) | ₹5,000 |

Rules:
- **First month:** opening = the balance on the day before the period's first day, using the same formula as above.
- **Every month:** closing = opening + income − expenses.
- **Later months:** each month's opening is the previous month's closing.
- **Open-ended periods** (All time) cover the months from the first to the last entry.
- **Custom ranges starting mid-month** carry in the balance before the range's first day. That first month counts only the range's own entries.

### 2.3 Income vs expenses: graph or table

The existing 12-month chart card now shows **either** the chart **or** the table, never both.

- **Chart showing:** the button reads "View as table". The Net legend is shown.
- **Table showing:** the button reads "View as graph". Table columns: Month, Income, Expenses, Net.

### 2.4 Other dashboard additions

- **Send mail** in the toolbar overflow menu opens the Export screen on the mail section ([§7](#7-send-mail)).
- **Revenue forecast card** below the chart. It shows the next financial year's income, expenses (running costs + rent) and net, and links to the forecast screen ([§10](#10-revenue-forecast)).

---

## 3. Export ledger and backup by period

More → **Export ledger…**, **Export calendar…**, **Download backup…** and **Send mail…** all open one Export screen, set to the same period as the rest of the app. A custom range opens as its last month.

### 3.1 Period picker

- **Period type:** a segmented control with **Monthly / Quarterly / Yearly / All**.
- **Previous / next arrows** step one month, quarter or year.
- **Label** for the selected period, e.g. `Oct 2026`, `Q4 2026 (Oct–Dec)`, `Year 2026`.
- **Preview** of opening balance, income, expenses and closing balance, plus "{n} entries in {period}".

### 3.2 Actions

| Section | Action | File name |
|---|---|---|
| Export ledger | Export ledger as **Excel** | `BailsLedger-{Kind}-{Label}.xlsx`, e.g. `BailsLedger-Monthly-Oct-2026.xlsx`, `BailsLedger-Quarterly-Q4-2026-Oct-Dec.xlsx` |
| Export ledger | Export ledger as **CSV** | same stem, `.csv` (unchanged CSV columns) |
| Export calendar | Export calendar as **Excel** | `BailsCalendar-{Kind}-{Label}.xlsx` |
| Export calendar | Export calendar as **CSV** | `BailsCalendar-{Kind}-{Label}.csv` |
| Backup | Download backup · {period} | `bails-ledger-backup-{Label}-{YYYY-MM-DD}.json` |
| Backup | Download full backup (only when a period is selected) | `bails-ledger-backup-{YYYY-MM-DD}.json` |

`{Label}` is the period label with every non-letter/digit replaced by `-` and repeats collapsed.

### 3.3 Period backup rules

A period backup uses the same JSON format (**format 8**) with these differences:

- **`transactions`:** only entries dated inside the period.
- **`ground_bookings`:** only bookings dated inside the period.
- **`ground_payments`:** only payments with a date inside the period. Undated payments are left out.
- **Unchanged:** partners, watchmen, ex-partners (sellers) and other settings are included in full.
- **`settings.opening_balance`:** set to the **balance brought forward** into the period ([§2.1](#21-kpi-tiles-smaller-two-rows) formula), so a restored period backup still shows the correct closing balance.
- **New top-level field `"period": "Oct 2026"`:** the period label. It is absent on full backups. Readers that don't know it must ignore it.

**Restore warning:** if the file has `period`, the confirmation says:

> "This backup only holds {period}. Every entry, partner, watchman, booking and payment … is replaced by it, so entries outside {period} will be gone. Download a full backup first if you might need them."

---

## 4. Excel workbook format

The app's Excel export now matches the website's coloured export.

**Full workbook** (Export ledger as Excel, and the Send mail attachment), four sheets:

1. **Dashboard**
2. **Transaction Ledger**
3. **Partner Profit**
4. **Ground Calendar**

**Calendar-only workbook:** just the **Ground Calendar** sheet.

### 4.1 Palette and shared styles

| Use | Fill | Font |
|---|---|---|
| Title banner (merged across the sheet, 2 rows, row height 22) | `#17593C` | bold 15, white, centred |
| Table header row | `#17593C` | bold 10, white, centred, wrap; thin border `#D3DAD0` |
| Table cell | none | 11; thin border `#D3DAD0` |
| TOTAL row | `#FDF4A3` (cream) | bold |
| Section heading ("Month by month", "All bookings") | none | bold 12, `#17593C` |
| Shaded row (opening balance) | `#F1F4EF` | 11 |
| Income text | | `#2CAA70` (bold for the Type column) |
| Expense / negative | | `#D72228` |
| Highlighted figure | | bold `#273076` |
| Muted text ("Free", "Inactive") | | `#7C8780` |

**Number formats:**
- Money: `#,##0.00` (Dashboard uses `#,##0`).
- Dates: `dd mmm yyyy`.
- Months: `mmm yyyy`.
- Equity: `0.00%`.

Dates are written as real Excel dates and amounts as numbers, so they sort and total. Gridlines are off on Dashboard, Partner Profit and Ground Calendar.

### 4.2 Dashboard sheet

| Rows | Content |
|---|---|
| 1–2 | Banner "BAILS CRICKET GROUND — LEDGER DASHBOARD" (A:F) |
| 4 | **Selected Period** · `{label}` (italic) |
| 5 | **Generated** · date and time (italic) |
| 7–9 | Three cards, each 2 columns wide: label band (bold 9, white on colour) over a merged 2-row value (bold 18, colour on `#F1F4EF`, `#,##0`): **INCOME (CREDIT)** green `#17593C` · **EXPENSE (DEBIT)** red `#D72228` · **NET PROFIT (MONTHLY)** navy `#273076` |
| 11–13 | Second row of cards: **OPENING BALANCE** `#17876A` · **CLOSING BALANCE** `#17593C` · **ENTRIES** `#5B6660` |
| next | Section "Month by month": header **Month · Opening · Income · Expense · Net · Closing**, one row per month (Net green/red), cream **TOTAL** row (first opening, sums, last closing) |
| next | "Income by category": **Category · Amount**, rows, TOTAL |
| next | "Expenses by category": same |

Column widths: 24, 16, 16, 16, 16, 16.

### 4.3 Transaction Ledger sheet

- **Header frozen** (row 1).
- **Columns:** Date · Day · Type · Category · Description · Slot · Party · Income · Expense · Net · Running Balance · Notes · Watchman.
- **Opening row** (shaded `#F1F4EF`):
  - Date: the period start, or the first entry for All time.
  - Type: "Opening Balance". Category: "Opening balance". Description: "Starting balance for {label}".
  - Income, Expense and Net: 0. Running Balance: the balance brought forward.
- **Entry rows:**
  - Type: **Income** in bold `#2CAA70`, or **Expense** in bold `#D72228`.
  - Net: +amount (green) for income, −amount (red) for expenses.
  - Running Balance: cumulative from the opening.
- **TOTAL row** (cream): "TOTAL"; period label in the Party column; total income, total expense, net and closing balance.
- **Day names** are fixed English (Monday…).
- **Column widths:** 13, 11, 15, 22, 34, 12, 20, 13, 13, 13, 16, 30, 16.

### 4.4 Partner Profit sheet

- **Banner:** "PARTNER PROFIT SHARE", or "PARTNER SHARE OF LOSS".
- **Period** row.
- **Distributable net profit** (or loss) in bold navy.
- **Header:** Partner · Equity % · Share of net profit · Status.
- **Rows:** every partner, including inactive ones. Inactive partners show share 0, and Status "Inactive" in grey. Active partners show "Active" in bold green.
- **TOTAL row** (cream): active equity total as a percentage, and the allocated total.

### 4.5 Ground Calendar sheet

- **Banner:** "GROUND CALENDAR — BLOCKED SLOTS" (A:H). Header row 9 frozen.
- **Rows 4–7:**
  - Period.
  - Days with bookings.
  - Full days blocked.
  - "Slots blocked (a full day = 3)".
  - Counts are in bold navy, column D.
- **Grid header:** Date · Day (Mon…) · 7:00 AM · 10:45 AM · 2:30 PM · Full Day · Booked by · Note.
- **One row per day with any block:**
  - **Full day** (Full Day blocked, or all 3 slots blocked): all four slot cells show **Blocked**, bold red on `#F7D4D5`.
  - **Partial day:** each blocked slot shows **Blocked**, bold black on cream `#FDF4A3`. Free slots, and the Full Day column, show **Free** in grey `#7C8780`.
  - **Booked by:** unique names joined with ", ".
  - **Note:** unique notes joined with "; ".
- **Empty period:** a muted "Nothing blocked in this period."
- **"All bookings" section:** header Date · Day · Slot · Booked by · Note. One row per block, with Full Day in bold red.

### 4.6 Calendar CSV

`Date,Day,Status,Slot,Booked by,Note`: one row per block.
- **Date** is ISO.
- **Status** is "Full day" or "Some slots".
- Same formula-escaping as the ledger CSV.

---

## 5. Ground calendar

### 5.1 Month view

- **Removed:** the "Blocked this month" list. The calendar grid and the two tiles (Full days, Slots blocked) remain.
- **Added:** **Export calendar** in the toolbar overflow. It opens the Export screen on the month being viewed.

### 5.2 Day sheet (tap a day): Admin

| Control | Behaviour |
|---|---|
| **Unblock** button on every blocked slot | Removes that block immediately. Also available as a swipe action. |
| **Unblock the whole day** | Shown when the day has 2 or more blocks. Removes them all. |
| **Just unblocked** list | Every slot unblocked from this sheet stays listed with its booked-by and note, and a **Re-block** button that recreates it with the same details. This is the "re-entry". It uses the normal block validation, so it fails cleanly if the slot was taken meanwhile. |
| Tap a blocked slot → **Edit block** | Change the slot (7:00 AM / 10:45 AM / 2:30 PM / Full Day), booked by and note. Validated against the day's *other* blocks with the normal rules: no double-booking, and Full Day can't mix with slots. |
| Block slots | Unchanged |

Partners (view-only) still see blocks but no buttons.

**Edit block SQL**

```sql
-- check against the day's other blocks first
SELECT slot FROM ground_bookings WHERE booking_date = $1::date AND id <> $2::int;
UPDATE ground_bookings SET slot = $1, booked_by = $2, note = $3, updated_at = now() WHERE id = $4::int;
```

---

## 6. Partners: add, edit, remove

Partners → **Edit partners** (Admin), previously "Edit split":

- **Summary at the top:** the period's net profit or loss, and the ground lease value.
- **Per partner:**
  - Name, Equity %, Active toggle.
  - **Live amounts**, recalculated as you type:
    - **Profit share** = net × equity / 100, or "Inactive".
    - **Lease split** = lease × equity / 100.
    - **Paid toward ground** = Σ that partner's ground payments, with "{lease split − paid} left".
- **Add partner:** a new row with blank name, equity 0, active.
- **Remove partner:** only for partners with **no ground payments**. Otherwise the footer says: "Has ground payments, so can't be removed. Turn off Active to stop sharing profit."
- **Validation (unchanged):** names can't be blank or duplicated (case-insensitive). Equity must be 0–100. The active equity total is shown, in orange when it isn't 100%.

After saving, every amount that depends on equity (profit shares, ground contributions) recalculates automatically.

**SQL, in one transaction, in this order**

```sql
DELETE FROM partners WHERE id = $1::int;                                   -- each removed partner
UPDATE partners SET name = '__bails_tmp_{id}__' WHERE id = $1::int;        -- park names (as before)
UPDATE partners SET name = $1, equity_pct = $2::numeric, is_active = $3::boolean WHERE id = $4::int;
INSERT INTO partners (name, equity_pct, sort_order, is_active)
VALUES ($1, $2::numeric, $3::int, $4::boolean);                            -- each new partner, sort_order = max + 1, +2…
```

> ⚠️ The app inserts only `name, equity_pct, sort_order, is_active`. If the website's `partners` table has other NOT NULL columns without defaults, give them defaults, or the app's "Add partner" will fail.

---

## 7. Send mail

Available from More → **Send mail…**, the Dashboard toolbar, the Export screen, and the assistant ("send mail for last month").

### 7.1 Recipients

- **Defaults:** `bailscricketground@gmail.com`, `medallion76@gmail.com`.
- **Editing:** Admin manages the list under More → Settings → **Mail recipients** (or "Edit recipients…" on the Export screen). Admin can add one or more addresses (separated by `;` or `,`), swipe to remove, or "Restore default recipients".
- **Validation:** `^[^@\s;,]+@[^@\s;,]+\.[^@\s;,]{2,}$`. Addresses are stored lowercase, with duplicates ignored.
- **Storage:** the app keeps the list **on the phone**, not in the shared database. On the web this could be a per-user setting, or a settings row if everyone should share it.

### 7.2 Message

**Attachment:** the full workbook for the selected period ([§4](#4-excel-workbook-format)), e.g. `BailsLedger-Monthly-Oct-2026.xlsx`.

**Subject**

```
Bails Cricket Ground · {Monthly|Quarterly|Yearly|All time} ledger & calendar · {period label}
```

**Body** (plain text). The ground calendar is in the spreadsheet only, **not** in the body.

```
Hello,

Please find attached the Bail's Cricket Ground {monthly} ledger for {Oct 2026}.

Summary — {Oct 2026}
• Opening balance: ₹…
• Income (credit): ₹…
• Expenses (debit): ₹…
• Net Profit (Monthly): ₹… (xx.xx% margin)
• Closing balance: ₹…
• Entries: n

Month by month (opening → closing)          ← only when the period has 2+ months
• Oct 2026: ₹… → ₹…

Partner profit share                         ← "Partner share of loss" when negative
• {Name} ({equity}%): ₹…

The attached spreadsheet ({file name}) has the summary, every transaction with its running balance, and month-by-month balances.

Regards,
Bail's Cricket Ground Ledger
```

### 7.3 How it's sent (app)

- **Send mail:** opens the phone's mail composer with recipients, subject, body and attachment filled in. It uses whichever account is set up in Mail, which can be Gmail.
- **Share to Gmail app:** attaches the file in the Gmail app and copies the recipients to the clipboard, because Gmail can't be handed recipients by another app.

The web version could send directly from the server with the same subject, body and attachment.

---

## 8. Net profit labels

Every "Net profit" / "Net loss" label now names the period type:

```
Net Profit (Monthly) · Net Loss (Quarterly) · Net Profit (Yearly) · Net Profit (All time) · Net Profit (Custom)
```

This applies on the Dashboard tile, the Partners tile ("… to share"), the partner editor, the Excel summary and the mail body.

---

## 9. Assistant

A chat screen opened with the ✨ button on the Dashboard, Ledger and Calendar. People type or dictate. Everything is answered from the ledger.

### 9.1 Principles

1. **Nothing changes without confirmation.** Any add, block, unblock or delete shows a card with every field, plus **Confirm** and **Cancel**.
2. **Permissions:** Partner (view-only) users can ask questions. They can't add, block, unblock or delete; they get "Only Admin can …".
3. **The app does all the maths.** A language model is used to *understand* free phrasing, never to compute figures. In testing, the on-device model sometimes stated wrong conclusions or invented totals.
4. **Follow-up questions:** if something required is missing, the assistant asks and remembers the half-finished command. For example, "add an expense for fuel today" gets "What's the amount?", and the reply "1500" completes it.
5. **Defaults:** a missing date means today, and the card says "(no date given, so today)". A missing period for a question means this month.

### 9.2 Processing order (per message)

```
1. Built-in parser (deterministic, instant) → intent + fields
2. If the parser is unsure (unknown intent / income-or-expense unclear / a vague "summary"),
   ask the LLM to read the sentence into the same structured fields (guided JSON output), then
   normalise its dates/amounts/slots/categories with the built-in parser again.
   Merge: parser wins for amount, date, slots, category, period; model wins for intent when the parser was unsure;
   party = parser's, else model's; description only if the model's is ≤ 40 chars with no digits.
3. If there's a pending follow-up, fill its missing fields from this message.
4. Known intent → exact answer or a confirmation card.
5. Still unknown → last resort: LLM answers in its own words using read-only "tools" (§9.7),
   labelled "— Worded by Apple Intelligence from your ledger. Check important figures on the Dashboard."
```

LLM timeouts: 15 s to read a command, 45 s for a free answer, 60 s to explain the forecast. On timeout or error the assistant falls back to the parser's result.

### 9.3 Intents and example phrases

| Intent | Example phrases | Result |
|---|---|---|
| Add income | "Add an income from Ravi ECL booking for 7 am slot on 12 Nov for 17000", "received 6500 from Customer for 10:45 slot yesterday", "1.5 lakh tournament income on 20 Oct from Dussera Cup" | Entry card |
| Add expense | "spent 1500 on fuel for roller today", "electricity bill Rs. 2,450 paid on 3 Nov", "paid 500 water bill" | Entry card |
| Petty cash | "petty cash 300 to Watchman 1 for phone recharge", "gave 500 to Mallaiah for market", "Shiva petty cash 1500 for fuel for grass cutter yesterday" | Expense card tagged to the watchman (§9.5) |
| Block | "block full day next Sunday for HCA", "block 7am and 2:30pm on 15 Nov booked by ECL note finals" | Block card |
| Unblock | "unblock 2:30 pm on Saturday" | Unblock card |
| Availability | "is 7 am free tomorrow?", "what's booked on 14 Nov" | Answer |
| Totals | "net profit this month", "income in October", "how much did we spend last month", "closing balance" | Answer + figures card (opening, income, expenses, net, closing; the asked figure highlighted) |
| Compare | "October vs November", "Did October beat November?", "is November better than October", "compare this month with last month", "are we spending more on fuel lately?" | Side-by-side income/expenses/net with change ₹ and %, and a verdict |
| Best/worst month | "what was our best month so far?", "worst month by expenses" | Ranked months |
| Top payers / payees | "who paid us the most in October?", "which of our clients brings in the most money?", "who did we pay the most" | Ranked parties |
| Averages | "average monthly expenses", "average monthly profit", "average income per month on ECL" | Per-month averages over complete months |
| List entries | "last 5 expenses", "show me the last 3 ECL bookings", "list fuel expenses last month" | Newest first, with count and total |
| Top categories | "biggest expenses this month", "top 3 income categories in October", "where did the money go last quarter" | Category split with % |
| Partner shares | "partner shares last month", "what's Bhanu's share this month", "how much does Aravind get" | Shares by equity |
| Watchmen dues | "how much do we owe the watchmen", "watchman salary due this month" | Salary − petty cash per watchman, total |
| Ground purchase | "how much is left to pay for the ground" | Lease, paid, remaining, per-partner split/paid/remaining |
| Booking counts | "how many bookings this month", "how many full days in October" | Days with bookings, full days, slots blocked, next 5 upcoming |
| Overview | "how's business", "give me a quick picture of how we're doing" | This month's totals + change vs last month + next-FY outlook |
| Forecast | "forecast revenue for next year", "what will profit be after the rent starts", "yoy growth" | Next 3 FYs: income − expenses (running + rent) = net, + "Open forecast" |
| Delete last | "delete the last entry", "undo" | Card showing the most recently *created* entry → Confirm deletes it |
| Send mail / Export | "send mail for last month", "email the quarterly report", "export Q3 2026" | Opens the mail/export screen on that period |
| Help | "help", "what can you do" | List of examples |

### 9.4 Parsing rules (the built-in parser)

Processed in this order. Each match is **removed** from the text before the next step, so the "7" of "7 am" or the "12" of "12 Nov" is never read as the amount.

**1. Watchman.**
- **Full name:** e.g. "Watchman 2 Shiva & Babitha".
- **Numbered:** "watchman 2" or "groundsman 2", matching the watchman whose name contains "Watchman 2".
- **Distinctive word:** any word of 4 or more letters in a watchman's name, excluding watchman/groundsman/petty/cash/wages/salary. For example "Mallaiah" or "Shiva".

**2. Slots**
| Pattern | Slot |
|---|---|
| full/whole/entire/all day, all (three) slots | Full Day (replaces any others) |
| 7 am, 7:00, 7.00, at 7, 7 o'clock, seven am | 7:00 AM |
| 10:45, 10.45, 10 45 am | 10:45 AM |
| 2:30, 2.30, 14:30, 2 30 pm, two thirty | 2:30 PM |
| 6 pm, 18:00 | 6:00 PM (entry slot only) |

**3. Date.** The first match wins:
- **Relative words:** today/tonight, yesterday, tomorrow (tmr/tmrw), day before yesterday, day after tomorrow.
- **ISO:** `2026-11-12`.
- **Day then month:** `12 Nov`, `12th of November 2026`.
- **Month then day:** `Nov 12`, `November 12th 2026`.
- **Numeric, day first (Indian order):** `12/11/2026`, `12-11`, `12.11.26`.
- **Weekdays** (full names or exact abbreviations; "month" must not read as "mon"):
  - **next / coming** = the next one, never today.
  - **last / previous** = the most recent past one, never today.
  - **this** = this week's, today included.
  - **Bare weekday:** points *ahead* for booking-type commands (block, reserve, availability) and *back* for money already received or spent.
- **Day of this month:** `on the 12th`.
- **Default year:** the current year.

**4. Period** (for questions):
- all time / overall / so far.
- `Q1`–`Q4` (+ year).
- this/last quarter, this/last year, this/last month, monthly, quarterly, yearly.
- Month name (+ year). A month later than the current one with no year means last year's. "May" counts only with a year or "in/for/of May".
- `in/of/year 2026`.
- **Every period named** is collected in order for comparisons, e.g. "October vs November".

**5. Count.** "last 5", "top 3" set the list length and aren't amounts.

**6. Amount.**
- **Score order:**
  1. a currency prefix (`₹`, `Rs`, `INR`, rupees);
  2. a unit suffix (`k`/thousand ×1,000; `L`/lakh/lac ×1,00,000; `cr`/crore ×1,00,00,000);
  3. `…rs` / `/-`;
  4. a bare number.
- **Several bare numbers:** the largest wins.
- **Ignored:** years that belong to a period ("Q3 2026", "October 2026", "in 2025", only 2020–2039). "for 2000" is kept, because that's how amounts are said.
- **Limits:** must be > 0 and < ₹10,00,00,000.

**7. Intent.** Keywords are checked in this order:
1. help;
2. undo/delete last;
3. forecast;
4. mail;
5. export;
6. unblock;
7. block;
8. booking counts;
9. availability;
10. **if no amount:** overview → compare → best/worst month → top party → average → watchmen dues → ground purchase → partner share → top categories → list entries;
11. then add income / add expense (income words: income, received, credit, earned, collected, got; expense words: expense, spent, paid, debit, bought, purchase, bill, petty cash, gave, given, advance);
12. else summary.

Refinements:
- **Amount plus a category but no kind:** the kind comes from the category's list.
- **Watchman named plus an amount:** always an expense.
- **Two periods named** with nothing else understood: a comparison.

**8. Category.** An exact catalog name first, then everyday words:

| Words | Category |
|---|---|
| ecl | ECL booking |
| tournament, cup, league | Tournament |
| net practice, nets | Net practice |
| canteen, cafeteria | Cafeteria (income) / Cafeteria supplies (expense, "supplies") |
| rental, hire | Equipment rental |
| floodlight, lights | Floodlight charges |
| booking, slot, match | Ground booking |
| market | Market expenses |
| salary, chit | Salary / chit payment |
| wage, groundsman, watchman | Groundsman wages |
| pitch | Pitch maintenance |
| fuel, petrol, diesel, grass, roller, maintenance | Ground maintenance |
| electricity, current bill, power, eb bill | Electricity |
| water | Water |
| repair, mechanic | Repairs |
| equipment, balls, bat | Equipment purchase |
| rent, lease | Rent / lease |
| misc | Miscellaneous |

**9. Party.**
- **Income:** after "received from", "from", "paid by", "by", "party", "customer", "client", or a capitalised name after "for".
- **Expense:** after "paid to", "party", "vendor", "shop", or a capitalised name after "to".
- **Blocks:** booked-by comes after "booked by", "booking for", "by", "for", "team".
- **Where the name stops:** at a stop word, a number, punctuation, or (for money entries) a category word such as "ECL". Maximum 5 words.

**10. Note and description.** Note: after "note"/"notes"/"remark". Description: after "description"/"details".

### 9.5 Entry card defaults

| Field | Rule |
|---|---|
| Category | Parsed, else **Ground booking** (income with a slot) / **Other income** (income) / **Miscellaneous** (expense) |
| Slot | The slot(s) said, joined with ", "; Full Day or all three slots → "All slots" |
| Description | Parsed, else "{slot} slot" when a slot was said |
| Date | Parsed, else today |
| **Also block on calendar** | For an income with booking slots: a toggle, **on** by default if those slots are free that day. If they're taken, the card shows a warning instead. Confirming saves the entry, then blocks the slots with booked-by = party and note = category. |

**Petty cash** (a watchman named in an expense):

| Field | Value |
|---|---|
| Watchman tag | The watchman (so it's deducted on the Watchmen screen) |
| Party | The watchman's full name |
| Description | What it was for: words after "for / towards / toward / as", up to a stop word or number, leading articles dropped, first letter capitalised (e.g. "Phone recharge"). Otherwise "Petty cash". |
| Category | From the reason (fuel → Ground maintenance, market → Market expenses, water → Water, salary → Salary / chit payment), else **Groundsman wages** |

### 9.6 Answer formats (exact, computed by the app)

- **Compare** "A vs B":
  - Income, expenses and net lines, each "₹x → ₹y, up/down ₹d (±p%)".
  - **Search word given:** only matching entries count, and Net is omitted.
  - **Verdict** "{period} had the higher {spending | income | net profit}":
    - Spending if expense words were used, or the search matches only expenses.
    - Income if income words were used, or the search matches only income.
    - Net profit otherwise.
  - **Defaults:** one period named means it vs the previous one. None named, or "lately", means last month vs this month.
- **Best/worst months:**
  - Months ranked by net. With income or expense words, by that instead.
  - For expenses, "best" means lowest.
  - The current month is marked "(so far)". Shows the top 3 by default.
- **Top payers/payees:** grouped by party with total and entry count. "we pay" / "did we pay" / expense words switch to payees.
- **Averages:**
  - Over **complete** months only, from the first entry month to last month. If none are complete yet, this month so far.
  - For averages, "monthly" / "per month" describe the average and are not a period.
- **Watchmen dues:** per active watchman, salary × months in period − petty cash = due, then the total.
- **Free answers** (last resort only): labelled as model-worded.

### 9.7 Read-only tools for the LLM (last-resort free answers)

Each tool returns the same text the app shows. The model must use these and never compute figures itself.

| Tool | Arguments | Returns |
|---|---|---|
| `ledgerTotals` | period words | "{period}: TOTAL income ₹…, TOTAL expenses ₹…, net profit ₹…, opening balance ₹…, closing balance ₹…, n entries. Margin x%." Described as "The ONLY source for totals; call once per period when comparing." |
| `categoryBreakdown` | kind (income/expense/any), period | Category split with %; "never use for totals" |
| `findEntries` | kind, search words, period, limit 1–10 | Newest matching entries + count and total |
| `groundCalendar` | a date, or a period | The day's blocks/free slots, or the period's counts + next bookings |
| `people` | topic (partnerShares / watchmen / groundPurchase), period, partner name | As in §9.6 |
| `revenueForecast` | years 1–5 | Per FY: income, expenses (running + rent), net, YoY, 80% range, notes |

System instructions for free answers:
- Give today's date and the financial year (April–March).
- Say to always use the tools, and never invent, estimate or add up numbers.
- Answers should be 1–4 sentences.
- The model can't change data, and should suggest the command phrasing instead.

**On the web:** any server-side LLM with tool/function calling works here, e.g. the Claude API with these six functions. Port the deterministic parser so most questions never reach the model.

---

## 10. Revenue forecast

Screen: Dashboard → **Revenue forecast** card, or More → **Revenue forecast**. It's refitted from the whole history every time it opens.

### 10.1 Inputs

- **Monthly history,** from the month of the first entry up to the current month:
  - **income[m]** = Σ income entries.
  - **running[m]** = Σ expense entries, **excluding** "Rent / lease" entries dated on or after the rent start month (those are the scheduled rent, kept apart so it's never counted twice).
  - **rentPaid[m]** = Σ those excluded rent entries.
- **Fitting window:** only **complete** months, i.e. those before the current month. The current month is in progress.
- **Scheduled cost:** **Ground rent ₹60,000 per month from April 2027** (₹7,20,000 a year), recorded category "Rent / lease". Admin can change it on the forecast screen. It's stored in settings (§11).

### 10.2 Model (exponential smoothing, ETS / Holt–Winters family)

Income and running expenses are fitted **separately**, with the same method.

| Complete months | Model | Notes |
|---|---|---|
| 0 | none | All forecasts 0 |
| 1–2 | Average month | level = mean, no trend; σ = max(sample sd, 25% of mean) |
| 3–5 | Simple exponential smoothing | α ∈ {0.05, 0.10 … 0.95} |
| 6–23 | Holt's **damped** trend | α as above, β ∈ {0.05 … 0.50}, φ ∈ {0.80, 0.85, 0.90, 0.95} (capped at 0.95 so short histories don't compound) |
| 24+ | Holt–Winters additive, damped trend, 12-month seasonality | + γ ∈ {0.05, 0.10, 0.20, 0.30}, φ up to 0.98 |

Parameters are chosen by **grid search, minimising one-step-ahead squared error**.

**Recursions** (error-correction form, e = actual − forecast):

```
Simple:        l ← l + α·e
Holt damped:   ŷ = l + φ·b;    l ← ŷ + α·e;   b ← φ·b + α·β·e
               init: l₀ = y₀,  b₀ = (y_min(3,n−1) − y₀) / min(3, n−1)
Holt–Winters:  ŷ = l + φ·b + s[t−12];  l ← l + φ·b + α·e;  b ← φ·b + α·β·e;  s[t] ← s[t−12] + γ·e
               init: l = mean(year 1), b = (mean(year 2) − mean(year 1)) / 12, s[i] = y[i] − mean(year 1)
```

**h months ahead** (h ≥ 1, h = 1 is the current month):

```
mean_h = l + (φ + φ² + … + φʰ)·b + s(h)                         (clamped at ≥ 0)
var_h  = σ² · [1 + Σ_{j=1}^{h−1} (α + α·β·(φ + … + φʲ) + γ·[j mod 12 = 0])²]
σ      = √(SSE / max(n_errors − k, 1)),  but at least 10% of the average month   (k = parameter count)
80% range = mean ± 1.2816·sd   (income low end clamped at 0)
```

### 10.3 Month-by-month projection

For every month from the start of the first financial year with data to the end of the last year asked for (1, 2, 3 or 5 years ahead):

| Month type | Income | Running expenses | Rent | Marked |
|---|---|---|---|---|
| Before the ledger began | 0 | 0 | 0 | (hidden) |
| Complete past month | actual | actual | actual rent recorded | Actual ✓ |
| Current month | max(forecast, recorded so far) | max(forecast, recorded so far) | max(scheduled, recorded) | Forecast |
| Future month | forecast | forecast | ₹60,000 if on/after Apr 2027 | Forecast |

**Net = income − running expenses − rent.** Expenses (total) = running + rent.

### 10.4 Yearly roll-up

- **Indian financial year (April–March)** by default, e.g. **FY 2026-27**. A toggle switches to calendar years.
- **Per year:** Σ income, Σ running, Σ rent, Σ expenses, net, and a basis of Actual / Actual + forecast / Forecast.
- **Year ranges:** income sd = √Σ monthly variance; net sd = √(Σ income var + Σ expense var); 80% range = net ± 1.2816·sd.
- **YoY growth** = (income − previous year's income) / previous year's income. It's only shown when the **previous year is a complete 12-month year of ledger data**. The year the ledger started is marked as partial, e.g. "Actual + forecast · 6 mo".

### 10.5 Screen contents

1. **Controls:** years ahead (1/2/3/5); Financial year (Apr–Mar) or Calendar year.
2. **Next forecast year tiles:**
   - Income, with YoY.
   - **Expenses**, captioned "Running ₹… + rent ₹…".
   - Net, with its 80% range.
3. **Chart:** monthly income (green) and expenses incl. rent (red). Actual months use solid lines and forecast months dashed lines. The income band is shaded as the 80% range. An orange dotted "Rent" marker sits at April 2027.
4. **Year on year table:** Year (basis · YoY) · Income · Running · Rent · Net.
5. **Month by month:** an expandable group per year showing Month · Income · Running · Rent · Net. Actual months are ticked; forecast months are greyed.
6. **Projected monthly expenses:** what the running costs are made of. Each expense category's average over the complete months, scaled so the categories add up to the forecast's next running month. Then **Ground rent (from Apr 2027) ₹60,000 / mo**, then **Total once rent starts**.
7. **Known future costs:** "Ground rent ₹60,000 / month from Apr 2027". Admin can use **Change rent** to set the amount and start month; 0 means no rent.
8. **In plain words:** an optional "Explain this forecast" button. An LLM writes 4–5 sentences (trend, rent effect, risk shown by the range, one suggestion) from the forecast text only.
9. **How it's calculated:** the method name and notes, e.g.:
   - "Only 1 complete month of history, so the forecast assumes every month looks like the average so far…"
   - "FY 2026-27 covers only 6 months because the ledger starts mid-year…"
   - "Ground rent of ₹60,000 a month is added from Apr 2027."

### 10.6 Worked example (the real ledger, 15 Nov 2026)

History: Oct 2026 income ₹1,86,000, expenses ₹1,23,676 (complete); Nov in progress.

| Year | Income | Running | Rent | Net |
|---|---|---|---|---|
| FY 2026-27 (Actual + forecast · 6 mo) | ₹11,16,000 | ₹7,42,056 | — | ₹3,73,944 |
| FY 2027-28 | ₹22,32,000 | ₹14,84,112 | ₹7,20,000 | ₹27,888 |
| FY 2028-29 | ₹22,32,000 | ₹14,84,112 | ₹7,20,000 | ₹27,888 |

- **Monthly:** net is ₹62,324 per month until March 2027, then ₹2,324 per month once the rent starts.
- **Running costs per month:**

  | Category | Per month |
  |---|---|
  | Miscellaneous | ₹32,580 |
  | Salary / chit payment | ₹31,000 |
  | Groundsman wages | ₹21,980 |
  | Electricity | ₹13,479 |
  | Ground maintenance | ₹13,017 |
  | Market expenses | ₹7,020 |
  | Repairs | ₹4,600 |
  | **Total** | **₹1,23,676** |

---

## 11. Data, settings and SQL changes

### 11.1 New settings keys (`settings` table, key/value)

| Key | Example | Meaning |
|---|---|---|
| `forecast_rent_monthly` | `60000.00` | Monthly scheduled rent for the forecast. Absent = 60000. `0` = no rent. |
| `forecast_rent_start` | `2027-04` | First month of that rent (`YYYY-MM`). Absent = 2027-04. |

Saved in one transaction with the existing upsert:

```sql
INSERT INTO settings (key, value) VALUES ($1, $2)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
```

### 11.2 Backup format

- **Still format 8.**
- **New optional top-level field `period`** (string), present only on period backups ([§3.3](#33-period-backup-rules)).
- **On a period backup:** `settings.opening_balance` holds the balance brought forward.

### 11.3 New or changed SQL

| Feature | SQL |
|---|---|
| Edit a block | §5.2 |
| Add / remove partners | §6 |
| Save settings | §11.1 |

No table or column changes.

---

## 12. Acceptance checks

These all passed in the app and are worth reusing as web tests.

**Commands**
| Input (today = Sun 8 Nov 2026) | Expected |
|---|---|
| "Add an income from Ravi ECL booking for 7 am slot on 12 Nov for 17000" | Income ₹17,000 · 12 Nov 2026 · ECL booking · slot 7:00 AM · party Ravi · description "7:00 AM slot" · "Also block 7:00 AM" on |
| "income 17k ECL 2.30 pm saturday" | Income ₹17,000 · 7 Nov (bare weekday, money → past) · 2:30 PM |
| "block full day next sunday for HCA" | Block Full Day · 15 Nov · booked by HCA |
| "petty cash 300 to Watchman 1 for phone recharge on 5th" | Expense ₹300 · 5 Nov · Groundsman wages · party "Watchman 1 Mallaiah" · description "Phone recharge" · tagged to Watchman 1 |
| "petty cash 250 to watchman 2 for the water can today" | Category Water · description "Water can" |
| "export Q3 2026" | Export, Q3 2026 (no amount read from "2026") |
| "net profit this month" | No stray date (the word "month" is not Monday) |
| "block full day on 11 Nov" when 7:00 AM is blocked that day | Refused: "11 Nov 2026 already has 7:00 AM blocked — remove those first to block the full day." |

**Questions** (ledger: Oct income ₹17,000 ECL + ₹6,500 ground booking; Oct expenses ₹1,500 fuel + ₹4,600 repairs; Nov income ₹9,000 ECL, expense ₹2,200 fuel)
| Input | Expected |
|---|---|
| "Which month had more income, October or November?" | ₹23,500 → ₹9,000, down ₹14,500 (−62%) · "Oct 2026 had the higher income." |
| "Are we spending more on fuel lately?" | ₹1,500 → ₹2,200, up ₹700 (+47%) · "Nov 2026 had the higher spending." |
| "Who paid us the most in October?" | ECL ₹17,000 · Customer ₹6,500 |
| "average monthly expenses" (Sep ₹1,000, Oct ₹4,600 complete) | ₹2,800 over 2 months |

**Forecast**
| Input | Expected |
|---|---|
| 29 months with planted Jun–Sep dip and Dec–Jan peak | Holt–Winters chosen; forecast reproduces the dip and peaks |
| History Oct only (₹1,86,000 / ₹1,23,676), rent ₹60,000 from Apr 2027 | Table in §10.6; FY 2026-27 marked partial; no YoY into FY 2027-28 |
