
from datetime import date
import json
import os


from dotenv import load_dotenv
from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request, url_for
)
from werkzeug.exceptions import BadRequest

from database import init_db, get_connection

load_dotenv()

VALID_STATUSES = [
    "Applied",
    "Online Assessment",
    "Interview",
    "Selected",
    "Rejected",
]
DATE_FIELDS = ("application_date", "follow_up_date")


def create_app(test_config=None):
    app = Flask(__name__)

    app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-this-secret"),
    DATABASE=os.environ.get("DATABASE_URL"),
    )
    if test_config:
        app.config.update(test_config)
    database_path = app.config["DATABASE"]
    if not database_path or not database_path.startswith(
        ("postgresql://", "postgres://")
    ):
        raise RuntimeError(
            "DATABASE_URL must be set to a PostgreSQL connection URL."
    )

    def execute(connection, query, params=()):
        return connection.execute(query.replace("?", "%s"), params)

    init_db(database_path)

    def validate_payload(data, partial=False):
        if not isinstance(data, dict):
            return None, "Request body must be a JSON object."

        allowed = {
            "company_name", "job_role", "application_date", "status",
            "job_url", "notes", "follow_up_date",
        }

        unknown = set(data) - allowed
        if unknown:
            return None, (
                f"Unsupported field(s): {', '.join(sorted(unknown))}."
            )

        if not partial:
            for field in (
                "company_name", "job_role", "application_date", "status"
            ):
                if field not in data:
                    return None, f"'{field}' is required."

        cleaned = {}

        for field in ("company_name", "job_role", "status", "job_url", "notes"):
            if field in data:
                value = data[field]

                if value is None:
                    value = ""

                if not isinstance(value, str):
                    return None, f"'{field}' must be a string."

                value = value.strip()

                if field in ("company_name", "job_role", "status") and not value:
                    return None, f"'{field}' cannot be empty."

                if field == "status" and value not in VALID_STATUSES:
                    return None, (
                        "Invalid status. Choose one of: "
                        f"{', '.join(VALID_STATUSES)}."
                    )

                cleaned[field] = value

        for field in DATE_FIELDS:
            if field in data:
                value = data[field]

                if value in (None, ""):
                    cleaned[field] = None
                elif not isinstance(value, str):
                    return None, f"'{field}' must be a YYYY-MM-DD date string."
                else:
                    try:
                        parsed = date.fromisoformat(value)
                    except ValueError:
                        return None, f"'{field}' must be a valid YYYY-MM-DD date."

                    if parsed.isoformat() != value:
                        return None, f"'{field}' must use YYYY-MM-DD format."

                    cleaned[field] = value

        if not partial and not cleaned.get("application_date"):
            return None, "'application_date' is required."

        return cleaned, None

    def row_to_dict(row):
        item = dict(row)
        item["follow_up_status"] = classify_follow_up(
            item.get("follow_up_date"),
            item.get("status"),
        )
        return item

    def fetch_all(search_text="", status_filter=""):
        query = "SELECT * FROM applications WHERE 1=1"
        params = []

        if search_text:
            query += " AND (company_name LIKE ? OR job_role LIKE ?)"
            pattern = f"%{search_text}%"
            params.extend([pattern, pattern])

        if status_filter:
            query += " AND status = ?"
            params.append(status_filter)

        query += " ORDER BY application_date DESC, id DESC"

        with get_connection(database_path) as connection:
            rows = execute(connection, query, params).fetchall()

        return [row_to_dict(row) for row in rows]

    def insert_application(connection, cleaned):
        query = """
            INSERT INTO applications
                (company_name, job_role, application_date, status,
                 job_url, notes, follow_up_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            cleaned.get("company_name", ""),
            cleaned.get("job_role", ""),
            cleaned.get("application_date"),
            cleaned.get("status", "Applied"),
            cleaned.get("job_url", ""),
            cleaned.get("notes", ""),
            cleaned.get("follow_up_date"),
        )
        row = execute(
            connection,
            query + " RETURNING id",
            params,
        ).fetchone()

        application_id = row["id"]

        return execute(
            connection,
            "SELECT * FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()

    def update_application(connection, cleaned, application_id):
        query = """
            UPDATE applications
            SET company_name=?, job_role=?, application_date=?, status=?,
                job_url=?, notes=?, follow_up_date=?
            WHERE id=?
        """

        params = (
            cleaned.get("company_name", ""),
            cleaned.get("job_role", ""),
            cleaned.get("application_date"),
            cleaned.get("status", "Applied"),
            cleaned.get("job_url", ""),
            cleaned.get("notes", ""),
            cleaned.get("follow_up_date"),
            application_id,
        )

        execute(connection, query, params)

    @app.get("/")
    def dashboard():
        search_text = request.args.get("q", "").strip()
        status_filter = request.args.get("status", "").strip()

        if status_filter and status_filter not in VALID_STATUSES:
            flash("Unsupported status filter was ignored.", "error")
            status_filter = ""

        applications = fetch_all(search_text, status_filter)
        all_applications = fetch_all()

        active = [
            a for a in all_applications
            if a["status"] not in ("Selected", "Rejected")
        ]

        reminders = [
            a for a in active
            if a["follow_up_status"] in ("Overdue", "Due today", "Upcoming")
        ]

        counts = {
            "total": len(all_applications),
            "in_progress": sum(
                a["status"] in ("Applied", "Online Assessment", "Interview")
                for a in all_applications
            ),
            "interviews": sum(
                a["status"] == "Interview" for a in all_applications
            ),
            "selected": sum(
                a["status"] == "Selected" for a in all_applications
            ),
            "rejected": sum(
                a["status"] == "Rejected" for a in all_applications
            ),
            "follow_ups": sum(
                a["follow_up_status"] in ("Overdue", "Due today")
                for a in active
            ),
        }

        return render_template(
            "dashboard.html",
            applications=applications,
            counts=counts,
            reminders=reminders,
            statuses=VALID_STATUSES,
            search_text=search_text,
            status_filter=status_filter,
        )

    @app.route("/applications/new", methods=["GET", "POST"])
    def add_application():
        if request.method == "POST":
            data = {
                key: request.form.get(key, "")
                for key in (
                    "company_name", "job_role", "application_date",
                    "status", "job_url", "notes", "follow_up_date",
                )
            }

            cleaned, error = validate_payload(data)

            if error:
                flash(error, "error")
                return render_template(
                    "add_application.html",
                    application=data,
                    statuses=VALID_STATUSES,
                ), 400

            with get_connection(database_path) as connection:
                insert_application(connection, cleaned)

            flash("Application added successfully.", "success")
            return redirect(url_for("dashboard"))

        return render_template(
            "add_application.html",
            application={
                "application_date": date.today().isoformat(),
                "status": "Applied",
            },
            statuses=VALID_STATUSES,
        )

    @app.route("/applications/<int:application_id>/edit", methods=["GET", "POST"])
    def edit_application(application_id):
        with get_connection(database_path) as connection:
            row = execute(
                connection,
                "SELECT * FROM applications WHERE id = ?",
                (application_id,),
            ).fetchone()

        if row is None:
            abort(404)

        application = dict(row)

        if request.method == "POST":
            data = {
                key: request.form.get(key, "")
                for key in (
                    "company_name", "job_role", "application_date",
                    "status", "job_url", "notes", "follow_up_date",
                )
            }

            cleaned, error = validate_payload(data)

            if error:
                flash(error, "error")
                return render_template(
                    "edit_application.html",
                    application={**application, **data},
                    statuses=VALID_STATUSES,
                ), 400

            with get_connection(database_path) as connection:
                update_application(connection, cleaned, application_id)

            flash("Application updated successfully.", "success")
            return redirect(url_for("dashboard"))

        return render_template(
            "edit_application.html",
            application=application,
            statuses=VALID_STATUSES,
        )

    @app.post("/applications/<int:application_id>/delete")
    def delete_application(application_id):
        with get_connection(database_path) as connection:
            cursor = execute(
                connection,
                "DELETE FROM applications WHERE id = ?",
                (application_id,),
            )

        if cursor.rowcount == 0:
            abort(404)

        flash("Application deleted.", "success")
        return redirect(url_for("dashboard"))

    @app.get("/api/applications")
    def api_list_applications():
        return jsonify(fetch_all()), 200

    @app.get("/api/applications/<int:application_id>")
    def api_get_application(application_id):
        with get_connection(database_path) as connection:
            row = execute(
                connection,
                "SELECT * FROM applications WHERE id = ?",
                (application_id,),
            ).fetchone()

        if row is None:
            return jsonify(error="Application not found."), 404

        return jsonify(row_to_dict(row)), 200

    def read_json_body():
        if not request.is_json:
            return None, (
                jsonify(error="Content-Type must be application/json."),
                415,
            )

        try:
            data = request.get_json(silent=False)
        except (BadRequest, ValueError, json.JSONDecodeError):
            return None, (
                jsonify(error="Request body contains invalid JSON."),
                400,
            )

        if not isinstance(data, dict):
            return None, (
                jsonify(error="Request body must be a JSON object."),
                400,
            )

        return data, None

    @app.post("/api/applications")
    def api_create_application():
        data, response = read_json_body()

        if response:
            return response

        cleaned, error = validate_payload(data)

        if error:
            return jsonify(error=error), 400

        with get_connection(database_path) as connection:
            row = insert_application(connection, cleaned)

        return jsonify(row_to_dict(row)), 201

    @app.patch("/api/applications/<int:application_id>")
    def api_update_application(application_id):
        data, response = read_json_body()

        if response:
            return response

        cleaned, error = validate_payload(data, partial=True)

        if error:
            return jsonify(error=error), 400

        if not cleaned:
            return jsonify(
                error="Provide at least one supported field to update."
            ), 400

        with get_connection(database_path) as connection:
            existing = execute(
                connection,
                "SELECT * FROM applications WHERE id = ?",
                (application_id,),
            ).fetchone()

            if existing is None:
                return jsonify(error="Application not found."), 404

            updated = dict(existing)
            updated.update(cleaned)

            merged, error = validate_payload({
                key: updated.get(key)
                for key in (
                    "company_name", "job_role", "application_date",
                    "status", "job_url", "notes", "follow_up_date",
                )
            })

            if error:
                return jsonify(error=error), 400

            update_application(connection, merged, application_id)

            row = execute(
                connection,
                "SELECT * FROM applications WHERE id = ?",
                (application_id,),
            ).fetchone()

        return jsonify(row_to_dict(row)), 200

    @app.delete("/api/applications/<int:application_id>")
    def api_delete_application(application_id):
        with get_connection(database_path) as connection:
            cursor = execute(
                connection,
                "DELETE FROM applications WHERE id = ?",
                (application_id,),
            )

        if cursor.rowcount == 0:
            return jsonify(error="Application not found."), 404

        return jsonify(message="Application deleted successfully."), 200

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith("/api/"):
            return jsonify(error="Resource not found."), 404
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.exception("Unexpected application error: %s", error)

        if request.path.startswith("/api/"):
            return jsonify(
                error="An unexpected server error occurred."
            ), 500

        return render_template("500.html"), 500

    return app


def classify_follow_up(follow_up_date, status, today=None):
    """Return Overdue, Due today, Upcoming, or None for a follow-up date."""
    if status in ("Selected", "Rejected") or not follow_up_date:
        return None

    try:
        follow_up = date.fromisoformat(str(follow_up_date))
    except (TypeError, ValueError):
        return None

    today = today or date.today()

    if follow_up < today:
        return "Overdue"
    if follow_up == today:
        return "Due today"
    return "Upcoming"


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
