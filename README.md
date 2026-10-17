# JobFlow – Smart Job Application Tracker

**JobFlow** is a web application that helps job seekers manage their job applications, track application statuses, and organize follow-up dates in one place.


📂 **Source Code:** [GitHub Repository](https://github.com/Swapnila13/JobFlow)

## Features

- Add, view, edit, and delete job applications.
- Track statuses: Applied, Online Assessment, Interview, Selected, and Rejected.
- Identify overdue, due-today, and upcoming follow-ups.
- Validate application details and dates.
- Manage applications through REST API endpoints.
- Store records using SQLite.
- Run automated tests using Python's `unittest` framework.

## Tech Stack

- **Backend:** Python, Flask
- **Database:** SQLite
- **Frontend:** HTML, CSS, JavaScript
- **API:** REST API
- **Testing:** Python `unittest`
- **Deployment:** Render
- **Version Control:** Git and GitHub

## Run Locally

1. Clone the repository:

   ```bash
   git clone https://github.com/Swapnila13/ApplyTrack.git
   cd ApplyTrack
   ```

2. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Start the application:

   ```bash
   python app.py
   ```

5. Open `http://127.0.0.1:5000` in your browser.

## Automated Tests

Run the tests with:

```bash
python -m unittest discover -s tests -v
```

The project currently has 10 automated tests passing in the local development environment.

## Future Improvements

- User authentication and individual accounts.
- Application statistics and job-search analytics.
- Enhanced follow-up notifications.

## Author

**Swapnila**

[GitHub Profile](https://github.com/Swapnila13)


