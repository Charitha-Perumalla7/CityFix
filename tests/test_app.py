import pytest
import sys
import os

# Add the main CityFix project folder to Python's import path
sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

import database


# Create a temporary test database
@pytest.fixture
def test_db(tmp_path, monkeypatch):

    db_path = tmp_path / "test.db"

    monkeypatch.setattr(database, "DB_PATH", db_path)

    database.init_db()

    yield


# Create a sample issue for testing
def create_test_issue():

    user_id = database.create_user(
        "Test User",
        "test@example.com",
        "password"
    )

    issue_id = database.create_issue(
        "Road Pothole",
        "Road Damage",
        "Large pothole",
        "12",
        "ABC Apartment",
        12.0,
        76.0,
        user_id
    )

    return issue_id, user_id


# Test duplicate issue detection
def test_duplicate_detection(test_db):

    issue_id, user_id = create_test_issue()

    duplicate = database.find_duplicate(
        "Road Damage",
        "12",
        "ABC Apartment",
        12.0001,
        76.0001
    )

    assert duplicate is not None
    assert duplicate["id"] == issue_id


# Test issue status flow
def test_status_flow(test_db):

    issue_id, user_id = create_test_issue()

    assert database.update_status(issue_id, "In Progress")

    assert database.update_status(issue_id, "Resolved")

    assert not database.update_status(issue_id, "Reported")


# Test that a user cannot upvote the same issue twice
def test_upvote_once(test_db):

    issue_id, user_id = create_test_issue()

    assert database.add_vote(user_id, issue_id)

    assert not database.add_vote(user_id, issue_id)