# RateFood — SCU Food Ratings

RateFood is a Flask app for discovering fictional demonstration restaurants around
Santa Clara University and sharing ratings and reviews. Python 3.10+ is
recommended.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8080`. The app creates its SQLite database at
`instance/ratefood.sqlite3` on first run. Set `DATABASE_PATH` to use another
local database file. Initial restaurant listings are fictional demo data;
reviews are contributed by registered users.

## Test

```bash
pytest
```

## Cloud Run and Firestore

Cloud Run instances have an ephemeral local filesystem. For a durable
deployment, configure `DATABASE_BACKEND=firestore`; the app uses the Firestore
client's Application Default Credentials and does not store credentials in the
repository. Configure a long, random `SECRET_KEY` using Secret Manager. The
production app refuses to start without it and automatically selects Firestore
on Cloud Run unless `DATABASE_BACKEND` is explicitly set.

Before provisioning anything, check the selected Google Cloud project and
account, and inspect current IAM grants. The commands below are read-only:

```bash
gcloud config get-value project
gcloud auth list
PROJECT_ID="$(gcloud config get-value project)"
gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)"
gcloud builds get-default-service-account --project "$PROJECT_ID"
gcloud projects get-iam-policy "$PROJECT_ID" \
  --flatten="bindings[].members" \
  --format="table(bindings.role,bindings.members)"
```

The previous project was `my-signup62804`; do not assume it is still active.
Check the Cloud Build service account and its existing roles before a source
deployment. The service account may be the legacy
`PROJECT_NUMBER@cloudbuild.gserviceaccount.com` or the project's configured
default build identity. If a required permission is missing, stop and obtain
approval before changing IAM. Creating/enabling Firestore, Secret Manager,
Cloud Build, or Cloud Run resources can incur charges; do not proceed without
the project owner's approval.

After confirming the active project, service-account permissions, billing,
Firestore database availability, and the Secret Manager secret
`ratefood-session-secret`, deploy with:

```bash
gcloud run deploy ratefood \
  --source . \
  --project "$PROJECT_ID" \
  --region us-west1 \
  --allow-unauthenticated \
  --set-env-vars DATABASE_BACKEND=firestore \
  --set-secrets SECRET_KEY=ratefood-session-secret:latest
```

`--allow-unauthenticated` makes restaurant browsing public; review creation and
editing remain login-protected. Cloud Run supplies `PORT`, and Gunicorn binds
to it. The Firestore runtime service account must already have the appropriate
Firestore data access role. Deployment is intentionally not automated by this
project.