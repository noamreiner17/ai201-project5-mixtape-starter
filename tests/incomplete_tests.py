"""
tests/incomplete_tests.py — Mixtape

Boundary-condition tests for the two issues flagged in project feedback:

  1. Notification service (Issue #4): rate_song must notify the song's
     original sharer, mirroring add_to_playlist. It must NOT notify when a
     user rates their own song.

  2. Streak logic: consecutive-day increments must work regardless of the
     day of week (the old `today.weekday() != 6` Sunday check wrongly blocked
     legitimate increments).
"""

import pytest
from datetime import datetime, timezone
from app import create_app, db
from models import User, Song, Notification
from services.notification_service import rate_song
from services.streak_service import update_listening_streak


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def sharer_and_song(app):
    """A user who shared a song, plus a separate friend who can rate it."""
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        friend = User(username="friend", email="friend@example.com")
        db.session.add_all([sharer, friend])
        db.session.flush()

        song = Song(title="Test Track", artist="Test Artist", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()
        yield {"sharer": sharer, "friend": friend, "song": song}


# --------------------------------------------------------------------------
# Issue #4 — notification on rate_song
# --------------------------------------------------------------------------

def test_rating_a_friends_song_notifies_the_sharer(app, sharer_and_song):
    """When a friend rates a song, the original sharer gets a 'song_rated' notification."""
    with app.app_context():
        sharer = sharer_and_song["sharer"]
        friend = sharer_and_song["friend"]
        song = sharer_and_song["song"]

        rate_song(user_id=friend.id, song_id=song.id, score=4)

        notes = db.session.query(Notification).filter_by(user_id=sharer.id).all()
        assert len(notes) == 1
        assert notes[0].notification_type == "song_rated"
        assert "friend" in notes[0].body
        assert "4/5" in notes[0].body


def test_rating_your_own_song_creates_no_notification(app, sharer_and_song):
    """Boundary: a user rating their own song should NOT notify themselves."""
    with app.app_context():
        sharer = sharer_and_song["sharer"]
        song = sharer_and_song["song"]

        rate_song(user_id=sharer.id, song_id=song.id, score=5)

        notes = db.session.query(Notification).filter_by(user_id=sharer.id).all()
        assert notes == []


# --------------------------------------------------------------------------
# Streak logic — day-of-week boundary
# --------------------------------------------------------------------------

def test_streak_increments_saturday_to_sunday(app):
    """
    Boundary: Sat -> Sun is a consecutive day and must increment the streak.
    The removed `weekday() != 6` check used to wrongly block this.
    """
    with app.app_context():
        u = User(username="listener", email="listener@example.com")
        db.session.add(u)
        db.session.commit()

        saturday = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)  # weekday() == 5
        sunday = datetime(2024, 6, 16, 12, 0, 0, tzinfo=timezone.utc)    # weekday() == 6

        update_listening_streak(u, saturday)
        assert u.listening_streak == 1

        update_listening_streak(u, sunday)
        assert u.listening_streak == 2


def test_streak_increments_sunday_to_monday(app):
    """Boundary: Sun -> Mon (week rollover) must also increment, not reset."""
    with app.app_context():
        u = User(username="listener2", email="listener2@example.com")
        db.session.add(u)
        db.session.commit()

        sunday = datetime(2024, 6, 16, 12, 0, 0, tzinfo=timezone.utc)  # weekday() == 6
        monday = datetime(2024, 6, 17, 12, 0, 0, tzinfo=timezone.utc)  # weekday() == 0

        update_listening_streak(u, sunday)
        assert u.listening_streak == 1

        update_listening_streak(u, monday)
        assert u.listening_streak == 2
