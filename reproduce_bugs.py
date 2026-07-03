from datetime import datetime, timezone
from app import create_app, db
from models import User, Song, Playlist, playlist_entries
from services.streak_service import update_listening_streak
from services.notification_service import rate_song, get_notifications
from services.playlist_service import get_playlist_songs

app = create_app()
with app.app_context():

    # --- Issue #1: streak resets on Sundays ---
    saturday = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)  # weekday 5
    sunday = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)    # weekday 6
    u = User(username="tester", email="t@x.app", listening_streak=5,
             last_listened_at=saturday)
    update_listening_streak(u, sunday)
    print(f"#1 streak: Sat->Sun gave {u.listening_streak} (want 6) ->",
          "OK" if u.listening_streak == 6 else "BUG")

    # --- Issue #4: rating a song creates no notification ---
    song = db.session.query(Song).filter_by(title="Crown Heights Anthem").first()
    rater = db.session.query(User).filter(User.id != song.shared_by).first()
    before = len(get_notifications(song.shared_by))
    rate_song(rater.id, song.id, 5)
    after = len(get_notifications(song.shared_by))
    print(f"#4 notify: sharer notifications {before}->{after} after rating ->",
          "OK" if after > before else "BUG")

    # --- Issue #5: last song in a playlist is dropped ---
    pl = db.session.query(Playlist).filter_by(name="Late Night Vibes").first()
    entries = db.session.execute(
        playlist_entries.select().where(playlist_entries.c.playlist_id == pl.id)
    ).fetchall()
    returned = get_playlist_songs(pl.id)
    print(f"#5 playlist: {len(entries)} entries, {len(returned)} returned ->",
          "OK" if len(returned) == len(entries) else "BUG")
