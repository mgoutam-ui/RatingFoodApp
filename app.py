import os
import re
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS restaurants (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    location TEXT NOT NULL,
    description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, restaurant_id)
);
"""

SAMPLE_RESTAURANTS = (
    (1, "The Bronco Cafe", "Cafe", "On Campus", "Coffee, sandwiches, and breakfast favorites between classes."),
    (2, "Campus Pizza", "Pizza", "On Campus", "Freshly baked pizza and quick, shareable meals."),
    (3, "Mission Tacos", "Mexican", "Near Campus", "Tacos, burritos, and quesadillas with bright, bold flavors."),
    (4, "Bronco Bowls", "Healthy", "On Campus", "Build-your-own grain bowls, salads, and fresh vegetables."),
    (5, "Palm Court Noodles", "Asian", "On Campus", "Comforting noodle bowls and dumplings for a quick lunch."),
    (6, "Santa Clara Sandwich Co.", "Sandwiches", "Near Campus", "Made-to-order sandwiches and soups just steps from campus."),
    (7, "Mission Bakery", "Bakery", "Near Campus", "Pastries, baked treats, and espresso for an afternoon pick-me-up."),
    (8, "Bronco Grill", "American", "On Campus", "Classic burgers, fries, and vegetarian grill options."),
)


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or (
            None if os.environ.get("K_SERVICE") else "local-development-key-change-me"
        ),
        DATABASE_BACKEND=os.environ.get("DATABASE_BACKEND") or (
            "firestore" if os.environ.get("K_SERVICE") else "sqlite"
        ),
        DATABASE=os.environ.get(
            "DATABASE_PATH", str(Path(app.instance_path) / "ratefood.sqlite3")
        ),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=bool(os.environ.get("K_SERVICE")),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("Set SECRET_KEY in the production environment.")
    if app.config["DATABASE_BACKEND"] not in {"sqlite", "firestore"}:
        raise RuntimeError("DATABASE_BACKEND must be either 'sqlite' or 'firestore'.")

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    init_database(app)
    app.teardown_appcontext(close_db)

    @app.before_request
    def load_logged_in_user():
        user_id = session.get("user_id")
        g.user = get_user_by_id(user_id) if user_id is not None else None
        if user_id is not None and g.user is None:
            session.clear()

    @app.route("/")
    def home():
        restaurants = get_restaurants()
        all_restaurants = restaurants
        all_reviews = get_reviews()
        review_stats = calculate_review_stats(all_reviews)

        for restaurant in restaurants:
            stats = review_stats.get(restaurant["id"], empty_stats())
            restaurant.update(stats)

        query = request.args.get("q", "").strip()
        category = request.args.get("category", "").strip()
        location = request.args.get("location", "").strip()
        restaurants = [
            restaurant for restaurant in restaurants
            if (not query or query.casefold() in " ".join(
                (restaurant["name"], restaurant["description"], restaurant["category"], restaurant["location"])
            ).casefold())
            and (not category or restaurant["category"] == category)
            and (not location or restaurant["location"] == location)
        ]
        restaurants.sort(
            key=lambda item: (
                item["review_count"] == 0,
                -item["average_rating"],
                -item["review_count"],
                item["name"].casefold(),
            )
        )
        return render_template(
            "home.html",
            restaurants=restaurants,
            categories=sorted({item["category"] for item in all_restaurants}),
            locations=sorted({item["location"] for item in all_restaurants}),
            search_query=query,
            selected_category=category,
            selected_location=location,
        )

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            error = validate_registration(username, password)
            if error:
                flash(error, "error")
            elif create_user(username, generate_password_hash(password)):
                flash("Your account is ready. Please log in.", "success")
                return redirect(url_for("login"))
            else:
                flash("That username is already taken.", "error")
            return render_template("register.html", username=username)
        return render_template("register.html", username="")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if not username or not password:
                flash("Username and password are required.", "error")
                return render_template("login.html", username=username)
            user = get_user_by_username(username)
            if user is None or not check_password_hash(user["password_hash"], password):
                flash("Invalid username or password.", "error")
                return render_template("login.html", username=username)
            session.clear()
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for("home"))
        return render_template("login.html", username="")

    @app.post("/logout")
    def logout():
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for("home"))

    @app.get("/restaurants/<int:restaurant_id>")
    def restaurant_detail(restaurant_id):
        restaurant = get_restaurant(restaurant_id)
        if restaurant is None:
            abort(404)
        reviews = get_reviews(restaurant_id)
        stats = calculate_review_stats(reviews).get(restaurant_id, empty_stats())
        user_review = (
            get_user_review(g.user["id"], restaurant_id) if g.user else None
        )
        return render_template(
            "restaurant.html",
            restaurant={**restaurant, **stats},
            reviews=reviews,
            user_review=user_review,
        )

    @app.post("/restaurants/<int:restaurant_id>/reviews")
    @login_required
    def save_review(restaurant_id):
        if get_restaurant(restaurant_id) is None:
            abort(404)
        rating, content, error = validate_review(
            request.form.get("rating", ""),
            request.form.get("content", ""),
        )
        if error:
            flash(error, "error")
            return redirect(url_for("restaurant_detail", restaurant_id=restaurant_id))
        existing = get_user_review(g.user["id"], restaurant_id)
        if existing:
            update_review(existing["id"], g.user["id"], rating, content)
            flash("Your review has been updated.", "success")
        else:
            create_review(g.user["id"], restaurant_id, rating, content)
            flash("Thanks for sharing your review!", "success")
        return redirect(url_for("restaurant_detail", restaurant_id=restaurant_id))

    @app.route("/reviews/<review_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_review(review_id):
        review = get_review(review_id)
        if review is None:
            abort(404)
        if review["user_id"] != g.user["id"]:
            abort(403)
        if request.method == "POST":
            rating, content, error = validate_review(
                request.form.get("rating", ""),
                request.form.get("content", ""),
            )
            if error:
                flash(error, "error")
                return render_template("edit_review.html", review=review)
            update_review(review["id"], g.user["id"], rating, content)
            flash("Your review has been updated.", "success")
            return redirect(
                url_for("restaurant_detail", restaurant_id=review["restaurant_id"])
            )
        return render_template("edit_review.html", review=review)

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template(
            "error.html",
            title="Not allowed",
            message="You can only edit your own reviews.",
        ), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template(
            "error.html",
            title="Page not found",
            message="We couldn't find the page or restaurant you requested.",
        ), 404

    @app.errorhandler(500)
    def server_error(_error):
        return render_template(
            "error.html",
            title="Something went wrong",
            message="Please try again in a little while.",
        ), 500

    return app


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(**kwargs)

    return wrapped_view


def validate_registration(username, password):
    if not username or not password:
        return "Username and password are required."
    if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
        return "Username must be 3–30 characters using letters, numbers, or underscores."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if len(password) > 128:
        return "Password must be 128 characters or fewer."
    return None


def validate_review(raw_rating, content):
    try:
        rating = int(raw_rating)
    except (TypeError, ValueError):
        return None, content, "Choose a rating from 1 to 5 stars."
    if str(rating) != raw_rating or not 1 <= rating <= 5:
        return None, content, "Choose a rating from 1 to 5 stars."
    content = content.strip()
    if len(content) < 10:
        return None, content, "Reviews must be at least 10 characters."
    if len(content) > 500:
        return None, content, "Reviews must be 500 characters or fewer."
    return rating, content, None


def empty_stats():
    return {
        "average_rating": 0.0,
        "review_count": 0,
        "distribution": {rating: 0 for rating in range(1, 6)},
    }


def calculate_review_stats(reviews):
    stats = {}
    for review in reviews:
        restaurant_id = review["restaurant_id"]
        row = stats.setdefault(restaurant_id, empty_stats())
        row["review_count"] += 1
        row["distribution"][review["rating"]] += 1
    for row in stats.values():
        row["average_rating"] = sum(
            rating * count for rating, count in row["distribution"].items()
        ) / row["review_count"]
    return stats


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_database(app):
    if app.config["DATABASE_BACKEND"] == "firestore":
        from google.cloud import firestore

        client = firestore.Client()
        app.extensions["firestore_client"] = client
        collection = client.collection("restaurants")
        for restaurant in SAMPLE_RESTAURANTS:
            doc_id = str(restaurant[0])
            if not collection.document(doc_id).get().exists:
                collection.document(doc_id).set({
                    "id": restaurant[0],
                    "name": restaurant[1],
                    "category": restaurant[2],
                    "location": restaurant[3],
                    "description": restaurant[4],
                })
        return

    database_path = app.config["DATABASE"]
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    connection.executemany(
        """INSERT OR IGNORE INTO restaurants
           (id, name, category, location, description) VALUES (?, ?, ?, ?, ?)""",
        SAMPLE_RESTAURANTS,
    )
    connection.commit()
    connection.close()


def get_db():
    if "db" not in g:
        connection = sqlite3.connect(current_app.config["DATABASE"])
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        g.db = connection
    return g.db


def get_firestore():
    return current_app.extensions["firestore_client"]


def get_user_by_id(user_id):
    if is_firestore():
        snapshot = get_firestore().collection("users").document(str(user_id)).get()
        return {"id": snapshot.id, **snapshot.to_dict()} if snapshot.exists else None
    row = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_username(username):
    if is_firestore():
        snapshot = get_firestore().collection("users").document(username.casefold()).get()
        return {"id": snapshot.id, **snapshot.to_dict()} if snapshot.exists else None
    row = get_db().execute(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
    ).fetchone()
    return dict(row) if row else None


def create_user(username, password_hash):
    created_at = now_utc()
    if is_firestore():
        from google.api_core.exceptions import AlreadyExists

        ref = get_firestore().collection("users").document(username.casefold())
        try:
            ref.create({
                "username": username,
                "password_hash": password_hash,
                "created_at": created_at,
            })
        except AlreadyExists:
            return False
        return True
    try:
        cursor = get_db().execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, created_at),
        )
        get_db().commit()
        return cursor.lastrowid is not None
    except sqlite3.IntegrityError:
        return False


def get_restaurants():
    if is_firestore():
        return sorted(
            [snapshot.to_dict() for snapshot in get_firestore().collection("restaurants").stream()],
            key=lambda row: row["id"],
        )
    rows = get_db().execute("SELECT * FROM restaurants").fetchall()
    return [dict(row) for row in rows]


def get_restaurant(restaurant_id):
    if is_firestore():
        snapshot = get_firestore().collection("restaurants").document(str(restaurant_id)).get()
        return snapshot.to_dict() if snapshot.exists else None
    row = get_db().execute(
        "SELECT * FROM restaurants WHERE id = ?", (restaurant_id,)
    ).fetchone()
    return dict(row) if row else None


def get_reviews(restaurant_id=None):
    if is_firestore():
        collection = get_firestore().collection("reviews")
        if restaurant_id is not None:
            collection = collection.where("restaurant_id", "==", restaurant_id)
        reviews = [snapshot.to_dict() for snapshot in collection.stream()]
        return sorted(reviews, key=lambda row: row["created_at"], reverse=True)
    if restaurant_id is None:
        rows = get_db().execute(
            """SELECT reviews.*, users.username
               FROM reviews JOIN users ON reviews.user_id = users.id
               ORDER BY reviews.created_at DESC"""
        ).fetchall()
    else:
        rows = get_db().execute(
            """SELECT reviews.*, users.username
               FROM reviews JOIN users ON reviews.user_id = users.id
               WHERE restaurant_id = ? ORDER BY reviews.created_at DESC""",
            (restaurant_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_user_review(user_id, restaurant_id):
    if is_firestore():
        review_id = f"{restaurant_id}_{user_id}"
        snapshot = get_firestore().collection("reviews").document(review_id).get()
        return {"id": snapshot.id, **snapshot.to_dict()} if snapshot.exists else None
    row = get_db().execute(
        "SELECT * FROM reviews WHERE user_id = ? AND restaurant_id = ?",
        (user_id, restaurant_id),
    ).fetchone()
    return dict(row) if row else None


def get_review(review_id):
    if is_firestore():
        snapshot = get_firestore().collection("reviews").document(review_id).get()
        if not snapshot.exists:
            return None
        review = {"id": snapshot.id, **snapshot.to_dict()}
        review.setdefault("username", get_user_by_id(review["user_id"])["username"])
        return review
    try:
        numeric_id = int(review_id)
    except ValueError:
        return None
    row = get_db().execute(
        """SELECT reviews.*, users.username FROM reviews
           JOIN users ON reviews.user_id = users.id WHERE reviews.id = ?""",
        (numeric_id,),
    ).fetchone()
    return dict(row) if row else None


def create_review(user_id, restaurant_id, rating, content):
    timestamp = now_utc()
    username = g.user["username"]
    if is_firestore():
        review_id = f"{restaurant_id}_{user_id}"
        from google.api_core.exceptions import AlreadyExists

        review_ref = get_firestore().collection("reviews").document(review_id)
        try:
            review_ref.create({
                "user_id": user_id,
                "username": username,
                "restaurant_id": restaurant_id,
                "rating": rating,
                "content": content,
                "created_at": timestamp,
                "updated_at": timestamp,
            })
        except AlreadyExists:
            update_review(review_id, user_id, rating, content)
        return
    get_db().execute(
        """INSERT INTO reviews
           (user_id, restaurant_id, rating, content, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, restaurant_id, rating, content, timestamp, timestamp),
    )
    get_db().commit()


def update_review(review_id, user_id, rating, content):
    timestamp = now_utc()
    if is_firestore():
        ref = get_firestore().collection("reviews").document(str(review_id))
        snapshot = ref.get()
        if not snapshot.exists or snapshot.to_dict()["user_id"] != user_id:
            abort(403)
        ref.update({"rating": rating, "content": content, "updated_at": timestamp})
        return
    try:
        numeric_id = int(review_id)
    except (TypeError, ValueError):
        abort(404)
    cursor = get_db().execute(
        """UPDATE reviews SET rating = ?, content = ?, updated_at = ?
           WHERE id = ? AND user_id = ?""",
        (rating, content, timestamp, numeric_id, user_id),
    )
    get_db().commit()
    if cursor.rowcount == 0:
        abort(403)


def is_firestore():
    return current_app.config["DATABASE_BACKEND"] == "firestore"


def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
