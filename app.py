
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import database

app = Flask(__name__)
app.secret_key = "cityfix-development-secret-change-before-deployment"

database.init_db()


def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.")
            return redirect(url_for("login"))
        return function(*args, **kwargs)
    return wrapper


def admin_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access required.")
            return redirect(url_for("login"))
        return function(*args, **kwargs)
    return wrapper


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if not name or not email or len(password) < 8:
            flash("Enter valid details. Password needs 8 characters.")
            return redirect(url_for("register"))

        if database.find_user(email):
            flash("Email already registered.")
            return redirect(url_for("register"))

        database.create_user(
            name, email, generate_password_hash(password)
        )

        flash("Registration successful!")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        user = database.find_user(email)

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]

            if user["role"] == "admin":
                return redirect(url_for("admin"))

            return redirect(url_for("home"))

        flash("Invalid email or password.")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/report", methods=["GET", "POST"])
@login_required
def report():
    if request.method == "POST":
        title = request.form["title"].strip()
        category = request.form["category"]
        description = request.form["description"].strip()
        ward = request.form["ward"].strip()
        location = request.form["location"].strip()

        if not all([title, category, description, ward, location]):
            flash("Please fill all required fields.")
            return redirect(url_for("report"))

        try:
            latitude = float(request.form.get("latitude") or 0) or None
            longitude = float(request.form.get("longitude") or 0) or None
        except ValueError:
            flash("Invalid coordinates.")
            return redirect(url_for("report"))

        if (latitude is None) != (longitude is None):
            flash("Enter both latitude and longitude, or leave both blank.")
            return redirect(url_for("report"))

        if latitude is not None and not (-90 <= latitude <= 90):
            flash("Invalid latitude.")
            return redirect(url_for("report"))

        if longitude is not None and not (-180 <= longitude <= 180):
            flash("Invalid longitude.")
            return redirect(url_for("report"))

        duplicate = database.find_duplicate(
            category, ward, location, latitude, longitude
        )

        if duplicate:
            flash("A possible duplicate was found. You can support the existing issue.")
            return redirect(
                url_for("issue_detail", issue_id=duplicate["id"])
            )

        database.create_issue(
            title, category, description, ward, location,
            latitude, longitude, session["user_id"]
        )

        flash("Your complaint has been submitted!")
        return redirect(url_for("issues"))

    return render_template("report.html")


@app.route("/issues")
def issues():
    return render_template(
        "issues.html",
        issues=database.get_issues()
    )


@app.route("/issue/<int:issue_id>")
def issue_detail(issue_id):
    issue = database.get_issue(issue_id)

    if not issue:
        flash("Complaint not found.")
        return redirect(url_for("issues"))

    return render_template("issue_detail.html", issue=issue)


@app.route("/upvote/<int:issue_id>", methods=["POST"])
@login_required
def upvote(issue_id):
    issue = database.get_issue(issue_id)

    if not issue:
        flash("Complaint not found.")
    elif database.add_vote(session["user_id"], issue_id):
        flash("Your upvote has been added!")
    else:
        flash("You have already upvoted this complaint.")

    return redirect(url_for("issue_detail", issue_id=issue_id))


@app.route("/admin")
@login_required
@admin_required
def admin():
    return render_template(
        "admin.html",
        issues=database.get_issues(),
        stats=database.get_statistics()
    )


@app.route("/admin/update/<int:issue_id>", methods=["POST"])
@login_required
@admin_required
def change_status(issue_id):
    status = request.form["status"]

    if database.update_status(issue_id, status):
        flash("Complaint status updated successfully.")
    else:
        flash("Invalid status change.")

    return redirect(url_for("admin"))


if __name__ == "__main__":
    app.run(debug=True)
