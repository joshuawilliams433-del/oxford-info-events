# Oxford Info: live events feed (free, no database)

Once a day, GitHub runs `fetch_events.py`. It gathers events, filters out low-quality ones, and publishes a single `events.json` file. The app downloads that file and keeps a copy on the phone, so events load instantly and still work offline.

**Cost: £0.** It uses about 3 API calls a day, against a Ticketmaster limit of 5,000 a day. GitHub Actions and GitHub Pages are free for public repositories.

## Where the events come from

| Source | What you get | Key |
|---|---|---|
| `curated.json` | Your own hand-picked highlights, such as Evensong, the Christmas lights or May Morning. These always appear first. | none |
| Ticketmaster | Concerts, theatre and comedy at the New Theatre, O2 Academy and other venues | free, from developer.ticketmaster.com |
| Skiddle | Gigs, theatre, arts and festivals at smaller venues. **Non-commercial use only unless Skiddle approves it in writing:** email dev@skiddle.com before launch. | free, from skiddle.com/api |
| iCal feeds (`sources.json`) | Any venue, college, museum, Oxford Talks list or council calendar that offers an `.ics` link | none |

### How the quality filter works
- It only includes events within about 6 km of Carfax, in the next 45 days.
- It removes parking, VIP upgrades, vouchers, club nights and similar non-events.
- Well-known Oxford venues get a boost in the ranking (`QUALITY_VENUES` in the script).
- A show that runs for many nights becomes one pin with a date range. For example, a panto shows as "Fri 5 Dec – Sun 4 Jan".
- No venue gets more than 6 events. The total is capped at 80.
- Finished events disappear from the app automatically.

## Setup (about 10 minutes)

1. **Create a repository.** Make a new **public** repository on GitHub called `oxford-info-events`. Upload everything in this `events-feed` folder to it, including the hidden `.github` folder. In Finder, press ⌘⇧. to show hidden folders.
2. **Get a Ticketmaster key.** Sign up at developer.ticketmaster.com, then go to My Apps and copy the **Consumer Key**.
3. **Add the key to the repository.** Go to Settings → Secrets and variables → Actions → **New repository secret**. Name it `TICKETMASTER_API_KEY` and paste the key. If Skiddle approves you, add `SKIDDLE_API_KEY` the same way.
4. **Turn on GitHub Pages.** Go to Settings → Pages. Under Source, choose **Deploy from a branch**, then branch `main` and folder `/docs`.
5. **Run it once.** Open the **Actions** tab, choose "Update Oxford events" and click **Run workflow**.
6. **Connect the app.** Your feed is now live at `https://YOUR-GITHUB-NAME.github.io/oxford-info-events/events.json`. Paste that address into `feedURL` in `OxfordInfo/Services/EventsService.swift`.

After that it refreshes every morning by itself. To add a special event, edit `curated.json` on the GitHub website. The feed rebuilds within a minute.

## Adding more sources
- **Oxford Talks or a college calendar:** find the list on talks.ox.ac.uk, copy its **.ics** link and add it to `sources.json`, following the `_example` entry. Use `include` to keep only public-friendly talks.
- **The council, Experience Oxfordshire or venue websites:** if they offer an iCal or RSS link, add it to `sources.json`. If they don't, add their best events to `curated.json`.
