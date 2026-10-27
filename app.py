
from flask import Flask, render_template

app = Flask(__name__)

# Sample restaurant data for testing
restaurants = [
    {
        "id": 1,
        "name": "The Bronco Cafe",
        "category": "Cafe",
        "location": "On Campus",
        "rating": 4.5,
        "reviews": 24,
        "description": "Coffee, sandwiches, and breakfast."
    },
    {
        "id": 2,
        "name": "Campus Pizza",
        "category": "Pizza",
        "location": "On Campus",
        "rating": 4.2,
        "reviews": 18,
        "description": "Fresh pizza and quick meals."
    },
    {
        "id": 3,
        "name": "Mission Tacos",
        "category": "Mexican",
        "location": "Near Campus",
        "rating": 4.7,
        "reviews": 32,
        "description": "Tacos, burritos, and quesadillas."
    },
    {
        "id": 4,
        "name": "Bronco Bowls",
        "category": "Healthy",
        "location": "On Campus",
        "rating": 4.3,
        "reviews": 15,
        "description": "Rice bowls, salads, and fresh vegetables."
    }
]

@app.route("/")
def home():
    sorted_restaurants = sorted(
        restaurants,
        key=lambda restaurant: restaurant["rating"],
        reverse=True
    )

    return render_template(
        "home.html",
        restaurants=sorted_restaurants
    )

if __name__ == "__main__":
    app.run(debug=True)
