from werkzeug.security import check_password_hash

from tests.conftest import login, register


def test_home_shows_fictional_restaurants_and_search_filters(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"The Bronco Cafe" in response.data
    assert b"Fictional demo listings" in response.data
    assert b"Mission Tacos" in client.get("/?q=tacos").data
    assert b"The Bronco Cafe" not in client.get("/?q=tacos").data
    assert b"Campus Pizza" in client.get("/?category=Pizza").data


def test_registration_hashes_password_and_rejects_duplicate_username(app, client):
    response = register(client)
    assert response.status_code == 200
    assert b"account is ready" in response.data
    with app.app_context():
        from app import get_db

        user = get_db().execute(
            "SELECT username, password_hash FROM users"
        ).fetchone()
        assert user["username"] == "bronco"
        assert user["password_hash"] != "secure-pass-123"
        assert check_password_hash(user["password_hash"], "secure-pass-123")

    duplicate = client.post(
        "/register",
        data={"username": "BRONCO", "password": "secure-pass-123"},
    )
    assert b"username is already taken" in duplicate.data


def test_registration_validates_required_fields_and_password_length(client):
    missing = client.post("/register", data={"username": "", "password": ""})
    assert b"Username and password are required" in missing.data
    short_password = client.post(
        "/register", data={"username": "student", "password": "short"}
    )
    assert b"at least 8 characters" in short_password.data


def test_login_logout_and_protected_review_route(client):
    register(client)
    wrong_password = client.post(
        "/login",
        data={"username": "bronco", "password": "incorrect-password"},
    )
    assert b"Invalid username or password" in wrong_password.data
    protected = client.post(
        "/restaurants/1/reviews",
        data={"rating": "5", "content": "A lovely place for breakfast."},
    )
    assert protected.status_code == 302
    assert "/login" in protected.headers["Location"]

    login(client)
    response = client.post(
        "/restaurants/1/reviews",
        data={"rating": "5", "content": "A lovely place for breakfast."},
        follow_redirects=True,
    )
    assert b"Thanks for sharing your review" in response.data
    logged_out = client.post("/logout", follow_redirects=True)
    assert b"You have been logged out" in logged_out.data


def test_review_validation_and_average_distribution_update(client):
    register(client)
    login(client)
    invalid_rating = client.post(
        "/restaurants/1/reviews",
        data={"rating": "6", "content": "This review is long enough."},
        follow_redirects=True,
    )
    assert b"Choose a rating from 1 to 5 stars" in invalid_rating.data
    too_short = client.post(
        "/restaurants/1/reviews",
        data={"rating": "4", "content": "Too short"},
        follow_redirects=True,
    )
    assert b"at least 10 characters" in too_short.data

    client.post(
        "/restaurants/1/reviews",
        data={"rating": "4", "content": "A lovely place for breakfast."},
    )
    detail = client.get("/restaurants/1")
    assert b"4.0" in detail.data
    assert b"bronco" in detail.data
    assert b"A lovely place for breakfast." in detail.data
    assert b"Rating breakdown" in detail.data

    updated = client.post(
        "/restaurants/1/reviews",
        data={"rating": "2", "content": "Updating my rating after another visit."},
        follow_redirects=True,
    )
    assert b"Your review has been updated" in updated.data
    assert b"2.0" in updated.data
    assert b"1 review" in updated.data
    assert b"Updating my rating" in updated.data


def test_user_cannot_edit_another_users_review(app, client):
    register(client, "alice")
    login(client, "alice")
    client.post(
        "/restaurants/1/reviews",
        data={"rating": "5", "content": "Alice's review is long enough."},
    )
    with app.app_context():
        from app import get_db

        review_id = get_db().execute("SELECT id FROM reviews").fetchone()["id"]

    client.post("/logout")
    register(client, "bobby")
    login(client, "bobby")
    response = client.get(f"/reviews/{review_id}/edit")
    assert response.status_code == 403
    assert b"only edit your own reviews" in response.data
    with app.app_context():
        from app import get_db

        review = get_db().execute(
            "SELECT rating, content FROM reviews WHERE id = ?", (review_id,)
        ).fetchone()
        assert review["rating"] == 5
        assert review["content"] == "Alice's review is long enough."


def test_nonexistent_restaurant_and_page_return_friendly_404(client):
    assert client.get("/restaurants/9999").status_code == 404
    response = client.get("/a-page-that-does-not-exist")
    assert response.status_code == 404
    assert b"Page not found" in response.data
    assert b"Traceback" not in response.data


def test_only_one_review_per_user_and_restaurant(client, app):
    register(client)
    login(client)
    for rating in ("3", "5"):
        client.post(
            "/restaurants/2/reviews",
            data={"rating": rating, "content": f"My updated rating is {rating} stars."},
        )
    with app.app_context():
        from app import get_db

        count = get_db().execute(
            "SELECT COUNT(*) FROM reviews WHERE restaurant_id = 2"
        ).fetchone()[0]
        assert count == 1
