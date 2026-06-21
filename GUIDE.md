# Revenue Recovery Desk — Complete User Guide

This guide explains exactly what to do, in order, and what happens after each
step. Read the **Golden Rule** first — it clears up the most common confusion.

---

## 🟡 The Golden Rule (read this first)

**This app never sends any message. You send it.**

The app is an *assistant*. It looks at your invoices, quotes and leads, decides
who to chase, writes a polite message for you, and waits. When you click
**Approve**, it does **not** message the customer. It just:

1. saves the message as "approved to send",
2. schedules the next follow-up date, and
3. records the decision.

**You then copy that message and send it yourself** from your own WhatsApp or
email. After you've sent it, you come back and click **Mark completed**.

Think of it like a smart assistant who hands you a ready-to-send note and says
*"here, send this"* — it never picks up the phone for you. (Automatic sending is
planned for version 2.)

---

## 🔁 The daily loop (the mental model)

Every working day you repeat this short loop:

```
1. UPLOAD / REFRESH   → app reviews everyone and builds a ranked plan
2. OPEN APPROVAL QUEUE → read the top items (most urgent first)
3. For each item:
      - read the reason + suggested message
      - edit the wording if you want
      - click APPROVE
      - COPY the message → send it from YOUR WhatsApp/email
      - click MARK COMPLETED
4. Done for today. The app schedules the next follow-up automatically.
```

That's the entire job. Everything else (Dashboard, Reports, etc.) is just
information around this loop.

---

## ⚙️ One-time setup (do this once)

Open **Settings** (left sidebar) and set:

- **Company name** and **Message signature** — these appear in every message.
- **Currency symbol** — e.g. `$`, `£`, `₹`.
- **High-value threshold** — invoices at or above this always need your approval
  and are flagged as sensitive (default 5000).
- **Follow-up days** — how long to wait before the next nudge.

Click **Save settings**. AI is **off by default** and the app works perfectly
without it — leave it off unless you've added an API key.

---

## 📄 What each page is for

| Page | What it's for | What you do here |
|------|---------------|------------------|
| **Dashboard** | The big picture | Just look. Money at risk, tasks due today, pending approvals. |
| **Upload Center** | Get any client's data in | Upload Excel/CSV (any layout), match columns, save a client profile, click **Process & analyze**. |
| **Mapping Profiles** | Per-client file layouts | Review/delete saved client mappings; see what the detector has learned. |
| **Daily Recovery Plan** | The ranked to-do list | Click **Rebuild plan**, see everyone ranked by urgency, export to Excel. |
| **Invoice / Quote / Lead Recovery** | Per-type detail | Review stored records and the recommendations for each type. |
| **Approval Queue** | ⭐ Where you work | Approve / edit / reject / postpone / complete each recommended action. |
| **Customer History** | One customer's full story | Pick a customer, see every record, message and decision. |
| **Saved Reports** | Excel downloads | Download any report (plan, messages, decision log, combined). |
| **Settings** | Configuration | Company info, thresholds, scheduler, AI toggle. |

---

## 🧩 Handling many clients with different file formats

Every client sends a different spreadsheet — different column names, date
styles, status words, even junk title rows. The app is built for this:

1. **Robust reading.** On upload it auto-detects the delimiter (`,` `;` tab),
   the encoding, the **header row** (skipping title/blank rows above the table),
   and lets you pick the **worksheet** in multi-sheet Excel files. You can
   override the sheet or header row if needed.
2. **Smart column matching.** It auto-maps their columns to the fields it needs
   (e.g. "Balance Outstanding" → amount). Anything unsure, you fix with a
   dropdown.
3. **Status wording.** Under *"Status wording"* you map a client's words to
   standard ones — e.g. `O/S` → unpaid, `Closed` → paid, `In Dispute` →
   disputed — so the agent reads them correctly.
4. **Save a Client Profile.** Give the layout the client's name and save it. **Next
   time that client's file arrives, the app recognises its column fingerprint and
   pre-fills everything automatically** — no re-mapping.
5. **It learns.** Every mapping you confirm teaches the detector new aliases, so
   auto-detection keeps improving for all clients. See progress on the **Mapping
   Profiles** page.

**Selling to a new client?** First file: spend 1 minute mapping + save a profile.
Every file after that: just upload and click analyze.

---

## ▶️ Step-by-step: from zero to chasing money

### Step 1 — Load your data (Upload Center)
1. Choose the **record type** (invoice, quote, or lead).
2. **Upload** your file, or click **Load matching sample** to try it.
3. Check the **Preview** table looks right.
4. Look at **Column mapping**. The app auto-detects columns (e.g. "Total Due" →
   `amount_due`). Fix any field set to `(none)` using the dropdowns.
5. Click **✅ Process and analyze**.

➡️ The app now reads every row, calculates who's overdue / cold / hot, ranks
them, and adds recommended actions to the **Approval Queue**.

> Repeat for each of the three types (invoices, quotes, leads).

### Step 2 — Look at the plan (Daily Recovery Plan)
Click **🔄 Rebuild plan from active records**. You'll see everyone ranked, most
urgent at the top, with the reason and suggested action. This is your "who to
chase first" list. You can **export it to Excel** here.

### Step 3 — Work the Approval Queue ⭐ (this is the main screen)
This is where you actually do the work.

1. Keep the filter on **pending**.
2. Each item is a card showing:
   - **Priority** and **amount** in the title,
   - **Reason** (why the app is recommending this),
   - **Recommended action**,
   - **Suggested message** (editable text box),
   - **Next follow-up date**.
3. **Edit the message** if you'd like (it's just a text box — change anything).
4. Click one of the buttons:

| Button | What it does |
|--------|--------------|
| **Approve** | Marks the message approved-to-send, schedules the next follow-up, logs it. **Does not send.** |
| **Reject** | Discards this recommendation (you decided not to chase). |
| **Save edit** | Saves your edited wording without approving yet. |
| **Postpone** | Pushes the follow-up to a date you pick. |
| **Mark completed** | Use this **after you've actually sent the message** (see Step 4). |

### Step 4 — ⭐ THE BIT PEOPLE MISS: actually send it
After you click **Approve**:

1. Use the **📋 Copy-ready version** box and click the **copy icon** in its
   top-right corner (one click copies the whole message).
2. Open **your own** WhatsApp / WhatsApp Web / email.
3. Paste it, check it, and **send it to the customer yourself**.
4. Come back to the app and click **🏁 Mark completed** on that item.

That's the full loop for one customer. The app has now recorded that you
contacted them and scheduled when to follow up next.

### Step 5 — Come back next time
- The **Dashboard** shows **Tasks due today** and **Overdue tasks**.
- When a follow-up date arrives, rebuild the plan (or let the scheduler do it)
  and the customer reappears in the queue for the next nudge.

---

## 💰 "The customer paid / accepted the quote — how do I update that?"

**Easiest way (no re-upload):** Go to the matching page — **Invoice Recovery**,
**Quote Recovery**, or **Lead Recovery** — and under *"Update an outcome"* pick
the record and click **💰 Mark Paid**, **🎉 Mark Won**, or **🌟 Mark Converted**
(there's also a **Lost** option). The app then:
- stops chasing that record and tidies its items out of the queue,
- updates the Dashboard's "Recovered revenue" / "Won" / "Converted" numbers,
- celebrates the win 🎉.

This is the one place a status changes by hand — and it's deliberately a
*human-only* button (the agents never flip a payment status themselves).

**Alternative (bulk):** re-upload an updated file in the Upload Center with the
new statuses (e.g. `Paid`, `Accepted`, `Won`). Good for syncing many records at
once from your accounting tool.

---

## 🛟 Safety: what the app will never do without you

The supervisor blocks these from ever happening automatically — they always wait
for you:

- Final escalation on a very overdue invoice (it only writes an **internal draft**).
- Anything on a **disputed** invoice.
- **High-value** contacts (above your threshold).
- Changing a **payment status**.
- Any legal threat or aggressive wording (the templates never contain these).

---

## 📊 Reports & exports

**Saved Reports** gives one-click Excel downloads:
- Daily recovery plan, Approval queue, Message history,
- Invoice / Quote / Lead reports, Agent decision log,
- **Combined recovery report** (everything in one workbook).

Use these for your records or to share with a colleague/accountant.

---

## ⏰ Optional: automatic daily review

In **Settings → Scheduled daily analysis** you can **Start scheduler** so the app
rebuilds the recovery plan every day at the time you set (default 08:00) while
the app is open. It still **only prepares** items — it never sends. You can also
click **Run analysis now** any time.

---

## ❓ Quick FAQ

**Q: I approved several items — did the customers get messaged?**
No. Approving never sends. Copy each approved message and send it yourself, then
click *Mark completed*.

**Q: Where do I see what I already did?**
Approval Queue (filter = *approved* / *completed*), Customer History, or
Saved Reports → Agent decision log.

**Q: The queue is empty / nothing happened after upload.**
Make sure required columns were mapped (the app warns you in yellow), then click
*Process and analyze*. Paid/won/lost/dead records correctly produce **no** action.

**Q: Do I need an AI key?**
No. The app uses reliable built-in message templates. AI only polishes wording if
you choose to enable it.

**Q: Is my data sent anywhere?**
No. Everything is stored locally in `data\recovery_desk.db` on your own machine.
