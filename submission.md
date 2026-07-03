# Mixtape Bug Hunt — Submission

## AI Usage

I used Claude as an assistant during this project. Here is specifically how, and
where I had to check its work myself.

**1. Initial exploration.** Before touching any bug, I asked Claude to give me an
overview of the project structure, explain the three levels of the app
(routes → services → models), and walk me through one example flow end to end.
This helped me focus on how each part of the project works and kept me from
getting lost in unfamiliar files. I used this to build my codebase map, but I
confirmed the details by reading the files themselves.

**2. Refining my reproductions and my `submission.md` explanations.** For the
bugs I reproduced and for the write-ups, I formed my own answer first and then
had Claude check whether my reasoning was accurate — for example, confirming that
`datetime.weekday()` returns 6 for Sunday, and that my line-by-line comparison of
`add_to_playlist` vs `rate_song` was correct. It helped me tighten the wording so
the explanations were precise rather than vague.

## Project Map

### Main Files

#### `app.py`
The Flask **application factory**. `create_app()` builds the app, sets the
SQLite database URI, initializes SQLAlchemy (`db.init_app`), registers the four
blueprints (`songs`, `playlists`, `users`, `feed`) under their URL prefixes, and
calls `db.create_all()` to create tables. The `db = SQLAlchemy()` object lives
here and is imported by every other module — this is why the app must be started
with `flask run` (factory pattern) rather than `python app.py`, which would
import the module twice and register models against two different `db` objects.

#### `models.py`
Defines all SQLAlchemy models and relationships:
- **`User`** — has `listening_streak` and `last_listened_at` columns, plus a
  self-referential many-to-many `friends` relationship via the `friendships` table.
- **`Song`** — shared by a user (`shared_by` FK), has ratings, listening events, and tags.
- **`Tag`** — song genres/labels, linked to songs via the `song_tags` join table.
- **`ListeningEvent`** — one row each time a user listens to a song (`listened_at`).
- **`Rating`** — a user's 1–5 score for a song, with a `UniqueConstraint` on
  `(user_id, song_id)` so a user can rate a song only once.
- **`Playlist`** — songs are attached through the `playlist_entries` join table,
  which adds a **`position`** column (explicit ordering), plus `added_by` and `added_at`.
- **`Notification`** — a message for a user with a `notification_type`, `body`,
  and `read` flag.

Three association tables carry extra data: `friendships`, `song_tags`, and
`playlist_entries` (the last one stores per-entry `position`/`added_by`/`added_at`).

#### `routes/`
The HTTP layer — four blueprints (`songs`, `playlists`, `users`, `feed`). Each
route parses request input, does basic validation, delegates to a service
function, and formats the JSON response. No business logic lives here.

#### `services/`
The business-logic layer. One file per feature area:
- `streak_service.py` — records listening events and updates day-over-day streaks.
- `feed_service.py` — "Friends Listening Now" (recent, 24h cutoff) and the activity feed.
- `search_service.py` — song search by title/artist with tags.
- `notification_service.py` — creates/retrieves notifications; also holds `rate_song()`.
- `playlist_service.py` — playlist creation and ordered song retrieval.

#### `seed_data.py`
Populates the database with test users, songs, friendships, listening events,
ratings, and playlists so the endpoints return real data.

### Data Flow Example — Rating a song and getting notified

1. `POST /songs/<song_id>/rate` in `routes/songs.py` reads `user_id` and `score`.
2. The route calls `notification_service.rate_song(user_id, song_id, score)`.
3. `rate_song()` validates the score is 1–5, looks up the `Song` and `User`, then
   checks whether a `Rating` already exists for that `(user_id, song_id)` pair.
4. If one exists it updates the score; otherwise it creates a new `Rating`.
5. It commits and returns the `Rating`, which the route serializes to JSON.

Compare this with the **playlist-add** flow in the same service:
`add_to_playlist()` appends the song to the playlist **and then calls
`create_notification(...)`** to tell the song's original sharer. `rate_song()`
sits right next to it but does *not* create a notification — a structural
contrast worth remembering (relevant to Issue #4).

### Patterns I Noticed

- **Route → service → model** layering: routes do HTTP, services do logic,
  models define data. Bugs are expected in `services/`.
- **Association tables with payload columns**: `playlist_entries` carries
  `position`, so playlist song order is explicit, not insertion order.
- **`create_notification()` is the single choke point** for notifications — any
  feature that should notify a user has to call it. Working notifications
  (playlist adds) call it; missing ones (ratings) don't.
- Tests live at the service layer (`test_streaks`, `test_search`, `test_playlists`),
  matching where the fixes are meant to go.

## The Five Open Issues (from README)

| # | Symptom | Service |
|---|---------|---------|
| 1 | Listening streak keeps resetting | `streak_service.py` |
| 2 | "Friends Listening Now" shows people from yesterday | `feed_service.py` |
| 3 | Same song shows up twice in search | `search_service.py` |
| 4 | Notified on playlist-add but not on rating | `notification_service.py` |
| 5 | Last song in a playlist never shows up | `playlist_service.py` |

## Bugs I'm Fixing (chosen 3): #1, #4, #5

> Note on Issue #3: I attempted it first but could not reproduce the duplicate.
> `search_songs` returns ORM `Song` entities, and SQLAlchemy de-duplicates
> entities by primary key, so the `outerjoin` on `song_tags` does **not** produce
> duplicate rows for multi-tag songs (verified: searching titles of the 3-tag
> seed songs returned each exactly once). Per the milestone guidance, I swapped
> to Issue #1, which I could reproduce cleanly. (AI assistant helped me confirm
> the ORM de-duplication behavior.)

### Milestone 2 — Reproductions (verified before any fix)

All three were reproduced against the seeded database using small harness scripts
that call the service functions directly.

**Issue #1 — Streak resets on Sundays**
*How I reproduced it:* Created a user with `listening_streak=5` and
`last_listened_at` = Saturday 2026-07-04. Called `update_listening_streak(user, now)`
with `now` = Sunday 2026-07-05 (a genuine consecutive day). Expected streak 6;
**got 1**. A control run (listened Sunday, then Monday) correctly produced 6.
The trigger condition is specifically that the *new* listening day falls on a
Sunday (`weekday() == 6`).

**Issue #4 — Rating a song sends no notification**
*How I reproduced it:* Took a seeded song ("Crown Heights Anthem", shared by
simone), counted the sharer's notifications (0), then called
`rate_song(other_user, song, 5)` and re-counted. Still **0** — no notification
was created. Compare with `add_to_playlist`, which does call `create_notification`.

**Issue #5 — Last song in a playlist is missing**
*How I reproduced it:* Playlist "Late Night Vibes" has **7** rows in
`playlist_entries`, but `get_playlist_songs(playlist_id)` returned only **6**
songs. The highest-`position` song is always dropped.

## Milestone 3 — Root Cause Analysis

### Issue #1 — My listening streak keeps resetting

**How I reproduced it:** The repo ships a test, `test_streak_increments_on_sunday`,
that listens on Saturday (streak → 1) then Sunday and asserts the streak becomes
2. Before any change it failed with `assert 1 == 2` — the streak reset instead of
incrementing. I confirmed the same in `reproduce_bugs.py`: a user with
`last_listened_at` = Saturday who listens on Sunday came back with streak 1
instead of 6. A control (Sunday → Monday) incremented correctly, which pinned the
trigger to *the new listening day being a Sunday*.

**How I found the root cause:** The README maps streaks to
`services/streak_service.py`. The only function that mutates `listening_streak`
is `update_listening_streak`, whose increment-vs-reset decision is a three-way
branch on `days_since_last` (lines 70–76). Line 73 read
`elif days_since_last == 1 and today.weekday() != 6:`. Seeing an explicit
`weekday() != 6` test — combined with my repro proving the reset happened *only*
on Sundays — is the moment I was confident this was the exact cause, not just a
suspicious area.

**The root cause:** Python's `datetime.weekday()` returns 6 for Sunday. The
`elif` that should fire on any consecutive day carried a spurious extra clause,
`and today.weekday() != 6`. On a Sunday that clause evaluates to `False`, so the
whole `elif` is `False` and execution falls through to the `else`, which resets
the streak to 1. The documented streak rules say nothing about weekdays — a
consecutive day should always increment — so the weekday guard should not have
been there at all. It was not a mis-typed comparison; it was an entire condition
that shouldn't exist.

**My fix and side-effect check:** I removed the ` and today.weekday() != 6`
clause so line 73 reads `elif days_since_last == 1:`, restoring the documented
behavior. Side-effect check: I ran the full `tests/test_streaks.py` suite — new
user, consecutive day, same-day no-double-count, skipped-day reset, and the
Sunday case. All 5 pass, confirming both sides of the boundary still hold
(skipped days still reset to 1, same-day still no-ops, consecutive days including
Sunday now increment).

### Issue #4 — Notified on a playlist-add but not on a rating

**How I reproduced it:** In `reproduce_bugs.py` I took a seeded song
("Crown Heights Anthem"), counted its original sharer's notifications, then had a
different user rate the song 5/5 and counted again. The count stayed the same
(`0 → 0`) — rating a song produced no notification for the sharer. By contrast,
the seed data already contains a working `song_added_to_playlist` notification,
so I knew notifications worked in general and only the rating path was silent.

**How I found the root cause:** The README maps notifications to
`services/notification_service.py`. I put the two interaction handlers
side by side: `add_to_playlist` (line 35) and `rate_song` (line 73).
`add_to_playlist` ends with a guarded `create_notification(...)` call that tells
the song's sharer. Reading `rate_song` top to bottom, it validates the score,
loads the song and user, creates or updates the `Rating`, commits, and returns —
with no `create_notification` call anywhere. The absence of the call in a
function that otherwise closely parallels `add_to_playlist` is what made me
confident this was the exact cause. This matches the issue hint that the root
cause is architectural, not a typo.

**The root cause:** `rate_song` was missing the entire notification step.
Notifications in this app all go through the single `create_notification` choke
point; `add_to_playlist` calls it, but `rate_song` never did. So a rating was
persisted correctly yet nobody was ever told about it. The defect is a missing
step in the function, not a wrong value or comparison.

**My fix and side-effect check:** After the `db.session.commit()` in `rate_song`
I added a block modeled on `add_to_playlist`: if the rater is not the song's
original sharer (`song.shared_by != user_id`), call `create_notification` with
`user_id=song.shared_by`, `notification_type="song_rated"`, and a body naming the
rater, song title, and score. The guard prevents self-notification when a user
rates their own song. Side-effect check: `reproduce_bugs.py` now shows the
sharer's notification count increasing after a rating. I specifically checked
that the existing rating behavior was untouched — a repeat rating still updates
the same `Rating` row rather than creating a second one (the `UniqueConstraint`
on `(user_id, song_id)` still holds), and the notification is only created for a
*different* user, not when someone re-rates their own song. Running the full
`tests/` suite, nothing related to ratings or notifications regressed; the only
failures at the time were the two `test_playlists.py` tests, which belonged to
the separate, still-unfixed Issue #5 (now also fixed — the suite is 13/13).

**AI usage:** I used an AI assistant to confirm my line-by-line comparison of the
two functions and to check the placement of the new block; I verified the fix by
reading the code and running the reproduction myself.

### Issue #5 — The last song in a playlist never shows up

**How I reproduced it:** In `reproduce_bugs.py` I compared the raw row count in
the `playlist_entries` join table against what `get_playlist_songs` returned for
the seeded playlist "Late Night Vibes": 7 entries existed but only 6 songs came
back. The repo's own `tests/test_playlists.py` confirmed it — both
`test_playlist_returns_all_songs` (`assert 4 == 5`) and
`test_playlist_returns_songs_in_order` (missing "Track 5") failed before the fix.

**How I found the root cause:** The README maps playlists to
`services/playlist_service.py`. In `get_playlist_songs` the query joins
`playlist_entries`, filters by `playlist_id`, and orders ascending by `position`
— that part is correct, and the returned songs were in the right order, just one
short. That told me the query was fine and the defect had to be in how the result
was returned. The `return` line read
`return [song.to_dict() for song in songs[:-1]]`. The `[:-1]` slice is what made
me certain: it excludes the last element of the list.

**The root cause:** The list comprehension sliced `songs[:-1]`, which returns
every element except the last one. Because the query is ordered ascending by
`position`, the last element is always the highest-position song, so that song
was silently dropped from every playlist. It is a classic off-by-one on the
return value, not a problem with the query or the ordering.

**My fix and side-effect check:** I removed the truncating slice so the
comprehension iterates the full `songs` list and returns all entries. Side-effect
check: `reproduce_bugs.py` now reports "7 entries, 7 returned", and the full
`tests/` suite passes 13/13 — including both playlist tests, which verify the
total count and the position order, confirming the first and last songs are both
present and the ordering is unchanged.

**AI usage:** I used an AI assistant to help me focus on the `return` line once I
had established the query was correct; I confirmed the off-by-one and the fix by
reading the code and running the tests myself.
