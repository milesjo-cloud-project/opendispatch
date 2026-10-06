# Demo run sheet: online booking to Paid

About 8 minutes. A customer books online, the office accepts and schedules it, the tech
works it, and the office takes it to Paid.

## Before the demo (10 minutes, once)

From the repo folder, on an up-to-date `main`:

```
git switch main
git pull
```

In `.env`, raise the booking limit. Every booking from your machine counts against one
address, and the default of 5 an hour runs out during rehearsals:

```
BOOKING_LIMIT_PER_HOUR=50
```

Start the app and bring the database up to date:

```
docker compose up -d --build
docker compose exec api alembic upgrade head
```

Make the demo company. Run it again with a new `--tag` before each rehearsal, so every
run starts clean:

```
python deploy/demo/seed_demo.py --tag demo
```

It prints the logins and the booking page link. Keep that output on screen or on paper.
Every login uses the password `demo-password-2026`.

Open two browser windows side by side:
- **Customer window:** the booking page link. A private window works best; make it
  narrow, like a phone.
- **Office window:** http://localhost:5173, signed in as the **dispatcher**.

## The demo

### 1. A customer books (customer window)

Fill in the booking page:
- What do you need done? **Water heater is leaking**
- Details: **Puddle under the tank since this morning**
- When works best? **Weekday mornings**
- Name **Pat Jones**, phone **555-0100**, address **12 River Rd**

Click **Send request**.

Point out:
- No login and no app for the customer: just a link the company puts on its site, flyers or truck.
- "Nothing is booked until they do." This is a request, not a confirmed slot.
- Spam protection works without a CAPTCHA: there's a hidden field that only bots fill in, plus a limit on how often one address can book.

### 2. The office sees it (office window)

Click **Refresh**. The **Requests** tab shows a badge of **3**.

Point out:
- The booking link panel at the top. Only the owner can turn it off or replace it; a dispatcher can copy it.
- Each request shows what they need, how to reach them, and when works best.

### 3. Decline the spam

On **CHEAP PILLS ONLINE**, click **Decline**, then OK.

Point out: spam never becomes a job or a customer, so the job history stays clean.

### 4. Accept a returning customer

On **Annual furnace check** (from "Dana"), click **Accept…**.

Point out:
- The suggestion: **Dana Lee** is listed under "Same phone or email", even though she typed her number differently.
- The office chooses; the system never links a request to a customer by itself, so nobody can attach junk to a real customer's history.

Pick **Dana Lee**, then click **Create job and schedule it**. The job opens as a Draft;
close it with **Close**. We'll focus on Pat's job.

### 5. Accept the new customer and schedule

On **Water heater is leaking**, click **Accept…**. Leave "New customer: Pat Jones",
then click **Create job and schedule it**.

Point out: Pat's details and "Preferred time: Weekday mornings" carried into the job.

In the editor, set Technician **Sam R.** and a time **tomorrow at 9:00 AM**, then click
**Schedule job**. The inbox is now empty and the badge is gone.

### 6. Dispatch, and give the customer a tracking link

Go to **Schedule**: Pat's job sits in Sam's lane tomorrow, next to Alex's faucet job.
Open it, then:
- Click **Dispatch to tech**.
- Click **Generate private link**, then **Copy**. Paste it into the customer window.

Point out: the customer can follow the job from "when is the tech coming" all the way
to paid, with no login. The page refreshes itself every 30 seconds.

### 7. The tech works it

In the office window, **Sign out**, then sign in as **Sam** (the tech login from the seed
output). Open the water heater job and click, in order:
**On my way → Start work → Mark complete**.

Point out:
- Techs only see their own jobs, and only the buttons that are theirs.
- Glance at the customer window: the status has moved along (within 30 seconds).

### 8. Invoice and get paid

**Sign out**, sign in as the **owner**. Go to **Jobs**, open the water heater job, then
click **Mark invoiced → Mark paid**.

Point out:
- Every step is recorded in the job's history.
- The quote is visible to the office but never to techs. Open Alex's faucet job to show a $320.00 quote.

## If something goes wrong

| What you see | What to do |
|---|---|
| "Too many booking requests" on the booking page | The booking limit is still 5. Set `BOOKING_LIMIT_PER_HOUR=50` in `.env`, then `docker compose up -d`. |
| The seed says "Too many sign-ups" | Each seed run signs up a company, and one address gets 5 an hour. Set `SIGNUP_LIMIT_PER_HOUR=50` in `.env`, then `docker compose up -d`. |
| "Online booking isn't available" | The link was replaced or turned off. Use the link the seed printed, or copy the current one from the Requests tab. |
| Can't sign in | Check the tag in the email matches the last seed run, and the password is `demo-password-2026`. |
| The Requests badge hasn't appeared | Click **Refresh**. The page checks by itself only once a minute. |
| Anything else odd | Run the seed again with a new `--tag` and sign in with the new logins. It takes a few seconds. |
