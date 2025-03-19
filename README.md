# calpilot
Generative AI copilot for your calendar.

> [!WARNING]
> This is a collection of utilities that I've written for my own personal needs at Wagestream. Some of these scripts do crazy things like delete all meetings within your Google Workspace account (i.e. delete everything for all employees). If you are an admin in your Google Workspace domain and you run this and it does terrible terrible things well.... shame on you.

# Local development 

1. Run `_build.sh` which will setup your virtual environment and install libraries
2. Copy your GCP project's credentials file into `.creds.gcp.json`. 
3. Copy your Gemini project's credentials file into `creds.gemini.json`

# Description of the scripts available
The following scripts all do different things. Once you've built your Python environment you can run them on the command line, and then schedule them with crontab.

| Script Name               | What it does                                                                                                                        |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `bot.py`                  | A Slack Bot that will run and respond to Direct Messages                                                                            |
| `function.py`             | A script that looks for users who have shared instructions, runs those instructions against their calendar, and emails the results  |
| `interval-vs-external.py` | A script that catalogs the total count of meetings in your organization, grouped by INTERNAL, EXTERNAL, PERSONAL, SOLO              |
| `nukem.py`                | A script that NUKES all future internal recurring meetings by changing their end date                                               |

# Google Workspace setup instructions

You must be a Workspace administrator to perform the following actions. You need to:

1. Create a new GCP project
2. Create a new Service Account within that project
3. Enable the correct APIs for that Service Account
4. Configure Domain-Wide Impersonation for that Service Account
5. Grant the correct scopes to Domain-Wide Impersonation

## 1. Create a new GCP project
- Sign into [Google Cloud Console](https://console.cloud.google.com/)
- Create a new project using [this deep link](https://console.cloud.google.com/projectcreate)
- Create a new project with the following values:
  * Project name = `Agentic Workspace`
  * Billing account = default
  * Organization = default
  * Location = default
- Your project has now been created. For subsequent steps, make sure it's selected in the top nav.

## 2. Create a new Service Account within that project
- Sign into [Google Cloud Console](https://console.cloud.google.com/)
- Ensure the project you created in Step 1 is showing in the top-nav bar
- Navigate to IAM & Admin > Service Accounts. Alternatively, if you named your project `agentic-workspace` in Step1, then [this deep link](https://console.cloud.google.com/iam-admin/serviceaccounts?project=agentic-workspace) should work.
- Click on "Create Service Account" and use the following values:
  * Display Name = `Google Agent`
  * Service Account ID = `google-agent`
  * Service Account Description = `Agent that performs task in Google Workspace (Gmail, GCal, etc)`
- The service account is now created, download the JSON keys by adding a Key under "Keys". Save this JSON file as `.creds.gcp.json`.
- Make a note of the ClientID, it will be a 21-digit number, and you will need it in Step 4

## 3. Enable the correct APIs for that Service Account 
- Sign into [Google Cloud Console](https://console.cloud.google.com/)
- Navigate to "APIs & Services" for the project you created in Step 1. If you named your project `agentic-workspace` in Step1, then [this deep link](https://console.cloud.google.com/apis/dashboard?project=agentic-workspace) should work
- You should see the following APIs in the table:
  * Google Calendar API
  * Google Docs API
  * Admin SDK API
  * Gmail API
  * Google Drive API
- If you do not, then click "+ Enable APIs and Services" at the top, and then search for each in turn and enable it.
- Yes, this is annoying.

## 4. Configure Domain-Wide Impersonation for that Service Account
- Sign into Google Workspace (note: Workspace, not GCP!)
- Navigate to [Security > Access and data control > API controls > Manage Domain Wide Delegation](https://admin.google.com/ac/owl/domainwidedelegation)
- Click "Add new" at the top
- Enter the "Client ID" (21 digits long) from Step 2
- Save

## 5. Grant the correct scopes
- Sign into Google Workspace (note: Workspace, not GCP!)
- Navigate to [Security > Access and data control > API controls > Manage Domain Wide Delegation](https://admin.google.com/ac/owl/domainwidedelegation)
- Find your service account in the list of API Clients added above.
- Edit the scopes and add all that are required for this project:
  * `https://www.googleapis.com/auth/calendar.readonly`
  * `https://www.googleapis.com/auth/calendar.events.owned`
  * `https://www.googleapis.com/auth/drive.readonly`
  * `https://www.googleapis.com/auth/docs.readonly`
  * `https://www.googleapis.com/auth/gmail.send`
  * `https://www.googleapis.com/auth/admin.directory.user.readonly`
