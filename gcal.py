#pylint: disable=C0301
"""Uses GenAI to analyze my calendar and find issues"""

from datetime import datetime, timedelta, date, time
import json
import os
import re
import base64
import tempfile
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email import encoders
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
import google.generativeai as genai
import boto3

class GoogleCalendarAgent:
    """An agent that analyzes a calendar, finds issues, and sends an email to the user"""

    # Hard-coded constants
    PROMPT_FILE = "prompt.txt"
    PROMPT_GDOC_FILENAME = "PROMPT.AI_AGENT.GCAL"
    CUSTOM_PROMPT_FILE = "custom-prompt.txt"
    SCOPES = [
        'https://www.googleapis.com/auth/calendar.readonly',
        'https://www.googleapis.com/auth/drive.readonly',
        'https://www.googleapis.com/auth/docs.readonly',
        'https://www.googleapis.com/auth/admin.directory.user.readonly'
    ]
    CACHE_FILE_PROMPT = ".cache.prompt.txt"
    DAYS_IN_FUTURE = 21
    DEFAULT_SECRET_REGION = "eu-west-2"
    ADMIN_EMAIL = "admin@wagestream.co.uk" # A Google Workspace Admin user who will have permissions to read the directory of all users
    EXCLUDED_DOMAINS = set(['resource.calendar.google.com', 'hibob.io', 'assistant.gong.io'])
    INTERNAL_DOMAINS = set(['wagestream.co.uk', 'wagestream.com', 'resource.calendar.google.com', 'assistant.gong.io'])
    PERSONAL_DOMAINS = set(['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'icloud.com', 'yahoo.co.uk'])

    def __init__(self):
        """Initialize the agent"""
        self.gcp_creds = self._read_setting("gcp")
        self.gemini_creds = self._read_setting("gemini")
        self.model = self.setup_model()

    def _read_setting(self, key):
        """Read a setting. Order of precedence: file, envvar, secret."""
        # first, try to read from local file
        filename = f".creds.{key.lower()}.json"
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                self._log(f"Read {key} from file: {filename}")
                return json.load(f)
        # second, try to read from environment variable
        envvar = f"GCAL_{key.upper()}"
        envvar_val = os.getenv(envvar)
        if envvar_val:
            self._log(f"Read {key} from envvar: {envvar}")
            return json.loads(envvar_val)
        # third, try to read from AWS Secrets Manager
        secretkey = f"prod/calpilot/{key.lower()}"
        session = boto3.session.Session()
        client = session.client(
            service_name='secretsmanager',
            region_name=self.DEFAULT_SECRET_REGION
        )
        response = client.get_secret_value(SecretId=secretkey)
        secret = response['SecretString']
        if secret:
            self._log(f"Read {key} from AWS Secrets Manager: {secretkey}")
            return json.loads(secret)
        # if we get this far, then we didn't have any settings in file, envvar, or AWS
        raise ValueError(f"No {key} settings found in file, envvar, or AWS")

    def _log(self, message):
        """Logs to stdout."""
        print(f"[{datetime.now().isoformat()}] {message}")

    def setup_model(self):
        """Setup the model."""
        api_key = self.gemini_creds.get("API_KEY")
        model_name = self.gemini_creds.get("DEFAULT_MODEL_NAME")
        genai.configure(api_key=api_key)
        genai_config = {
            "temperature": 0.5,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 8192,
            "response_mime_type": "text/plain",
        }
        model = genai.GenerativeModel(model_name, generation_config=genai_config)
        return model

    def get_services(self, user=None):
        """Get Google services (Calendar, Drive, Docs, Directory - in that order). If a user is provided, use delegated credentials."""
        creds = service_account.Credentials.from_service_account_info(self.gcp_creds, scopes=self.SCOPES)
        if user:
            creds_to_use = creds.with_subject(user)
        else:
            creds_to_use = creds
        svc_calendar = build('calendar', 'v3', credentials=creds_to_use)
        svc_drive = build('drive', 'v3', credentials=creds_to_use)
        svc_docs = build('docs', 'v1', credentials=creds_to_use)
        svc_directory = build('admin', 'directory_v1', credentials=creds_to_use)
        return svc_calendar, svc_drive, svc_docs, svc_directory

    def send_mail(self, sender, replyto, recipient, subject, text_body, html_body, attachments=None, cc=None):
        """Sends an email via the service account"""
        credentials = service_account.Credentials.from_service_account_info(
            self.gcp_creds,
            scopes=['https://www.googleapis.com/auth/gmail.send'],
            subject=sender
        )
        service = build('gmail', 'v1', credentials=credentials)
        message = MIMEMultipart()
        message['to'] = recipient
        message['from'] = sender
        message['subject'] = subject
        message.add_header("reply-to", replyto)
        if cc:
            if isinstance(cc, str):  # Handle single CC address
                message['cc'] = cc
            elif isinstance(cc, list): # Handle list of CC addresses
                message['cc'] = ', '.join(cc) #join the list of CC addresses with commas
            else:
                raise TypeError("cc must be a string or a list of strings")
        msg_alternative = MIMEMultipart('alternative') # needed to create alternative content
        msg_alternative.attach(MIMEText(text_body, 'plain'))
        msg_alternative.attach(MIMEText(html_body, 'html'))
        message.attach(msg_alternative)
        if attachments and isinstance(attachments, list):
            for attachment in attachments:
                try:
                    filename = os.path.basename(attachment)
                    with open(attachment, 'rb') as f:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        part.add_header('Content-Disposition', f"attachment; filename={filename}")
                        message.attach(part)
                except Exception as e: # pylint: disable=broad-exception-caught
                    self._log(f"Error attaching file {attachment}: {e}")
        apimsg = {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
        response = (service.users().messages().send(userId='me', body=apimsg).execute()) # pylint: disable=no-member
        msgid = response.get('id')
        return msgid

    def get_single_event(self, user, event_id):
        """Get a single event from the calendar"""
        svc_calendar, _, _, _ = self.get_services(user)

        # Get the current user's calendar ID (or specify a user's email)
        calendar_id = 'primary'
        
        # Retrieve events from the calendar
        self._log('Retrieving events from calendar...')
        params = {
            'calendarId': calendar_id,
            'eventId': event_id,
        }
        try:
            event = svc_calendar.events().get(**params).execute() # pylint: disable=no-member
            this_event_id = event.get('id', '')
            if this_event_id == event_id:
                self._log(f"Found event {event_id}")
                return event
            return None
        except HttpError as e:
            if e.reason == 'The user must be signed up for Google Calendar.':
                self._log(f"Warning: {user} is not signed up for GCal")
                return []
            raise        

    def get_calendar_events(self, user, start_date=None, end_date=None, expand_recurring_events=True):
        """Get the calendar events for a given user"""
        svc_calendar, _, _, _ = self.get_services(user)

        # Get the current user's calendar ID (or specify a user's email)
        calendar_id = 'primary'
        
        # Set the date range.
        if isinstance(start_date, date) and isinstance(end_date, date):
            # Make them datetime objects with time set to 00:00:00 and 23:59:59
            start_at = datetime.combine(start_date, time.min)
            end_at = datetime.combine(end_date, time.max)
        else:
            start_at = datetime.utcnow()
            end_at = datetime.utcnow() + timedelta(days=self.DAYS_IN_FUTURE)
        # We need to convert the dates to ISOFORMAT + 'Z' datetimes
        time_min = start_at.isoformat() + 'Z'
        time_max = end_at.isoformat() + 'Z'
       
        # Retrieve events from the calendar
        self._log('Retrieving events from calendar...')
        params = {
            'calendarId': calendar_id,
            'timeMin': time_min,
            'timeMax': time_max,
            'maxResults': 2500,  # Adjust as needed
            'singleEvents': expand_recurring_events,
            'orderBy': 'startTime' if expand_recurring_events else 'updated'
        }
        try:
            events = svc_calendar.events().list(**params).execute().get('items', []) # pylint: disable=no-member

            # Google calendar has "workingLocation" events; let's filter those out
            events = [e for e in events if e.get('eventType') != 'workingLocation']

            # There are also events where the eventType is "fromGmail"; filter those out
            events = [e for e in events if e.get('eventType') != 'fromGmail']

            self._log(f"Found {len(events)} event between {time_min} and {time_max}")
            return events
        except HttpError as e:
            if e.reason == 'The user must be signed up for Google Calendar.':
                self._log(f"Warning: {user} is not signed up for GCal")
                return []
            raise
    
    def get_instructions(self, file_id):
        """Gets the prompt instructions from Google Drive"""
        _, _, docs_service, _ = self.get_services()
        document = docs_service.documents().get(documentId=file_id).execute() # pylint: disable=no-member
        content = ""
        if 'body' in document and 'content' in document['body']:
            for element in document['body']['content']:
                if 'paragraph' in element and 'elements' in element['paragraph']:
                    for text_element in element['paragraph']['elements']:
                        if 'textRun' in text_element and 'content' in text_element['textRun']:
                            content += "".join(text_element['textRun']['content'])
        return content

    def parse_xml_response(self, xml_string):
        """Extract answer and contemplator tags from string using regex."""
        contemplator_pattern = r'<contemplator>(.*?)</contemplator>'
        answer_pattern = r'<answer>(.*?)</answer>'
        contemplator_match = re.search(contemplator_pattern, xml_string, re.DOTALL)
        answer_match = re.search(answer_pattern, xml_string, re.DOTALL)
        contemplator_text = contemplator_match.group(1).strip() if contemplator_match else None
        answer_text = answer_match.group(1).strip() if answer_match else None
        return answer_text, contemplator_text

    def prompt_against_calendar(self, calendar_events, instructions):
        """Prompt the calendar events against the model"""
        jsondata = json.dumps(calendar_events, indent=4, sort_keys=True, default=str)
        prompt_text = open(self.PROMPT_FILE, 'r', encoding='utf-8').read()
        prompt_text = prompt_text.replace("{events}", jsondata)
        prompt_text = prompt_text.replace("{instructions}", instructions)
        with open(self.CACHE_FILE_PROMPT, 'w', encoding='utf-8') as f:
            f.write(prompt_text)
        self._log('Prompt ready. Sending prompt to Gemini...')
        response = self.model.generate_content([prompt_text])
        answer, contemplator = self.parse_xml_response(response.text)
        self._log('Gemini response received')
        return answer, contemplator
    
    def custom_prompt_against_calendar(self, calendar_events, instructions):
        """Prompt the calendar events against the model"""
        jsondata = json.dumps(calendar_events, indent=4, sort_keys=True, default=str)
        prompt_text = open(self.CUSTOM_PROMPT_FILE, 'r', encoding='utf-8').read()
        prompt_text = prompt_text.replace("{events}", jsondata)
        prompt_text = prompt_text.replace("{instructions}", instructions)
        self._log('Prompt ready. Sending prompt to Gemini...')
        response = self.model.generate_content([prompt_text])
        answer, contemplator = self.parse_xml_response(response.text)
        self._log('Gemini response received')
        return answer, contemplator

    def get_start_date_from_event(self, event):
        """Some events have a datetime, others have a date"""
        start = event.get('start', {})
        date_string = start.get('date')
        datetime_string = start.get('dateTime')
        if date_string:
            return date_string
        if datetime_string:
            return datetime_string[:10]
        return 'YYYY-MM-DD'

    def parse_answer(self, answer):
        """
        Input is one calendar issue per line, like so:
        - [{event_id_from_json}] {summary of the issue in your own words}
        - [{event_id_from_json}] {summary of the issue in your own words}
        - [{event_id_from_json}] {summary of the issue in your own words}

        Output is a list of tuples, each containing the event_id and the issue summary. 
        """
        issues = []
        for line in answer.split("\n"):
            if not line.strip():
                continue
            match = re.match(r'- \[([^\]]+)\] (.*)', line.strip())
            if not match:
                self._log(f"Warning: line does not match expected format. Line: {line}")
                continue
            event_id = match.group(1)
            issue = match.group(2)
            issues.append((event_id, issue))
        return issues

    def render_issues(self, issues, events):
        """Given a list of issues, and a list of events, render the issues in a nice pretty HTML format."""
        intro = f"I'm an AI agent that has inspected {len(events)} events in your calendar for the next {self.DAYS_IN_FUTURE} days. After careful review, I have found {len(issues)} issues."
        html = f"<html><body>\n <p>{intro}</p>\n\n<hr/>\n\n"
        html += "<table border='1'>\n<thead>\n<tr><th>Date</th><th>Title</th><th>Issue</th></tr></thead>\n<tbody>\n\n"
        text = f"{intro}\n\n"
        for issue in issues:
            event_id, issue_description = issue
            event = [e for e in events if e['id'] == event_id]
            if len(event) == 0:
                self._log(f"Warning: event not found in events list. Event ID: {event_id}")
                continue
            if len(event) > 1:
                self._log(f"Warning: multiple events found for event ID: {event_id}")
                continue
            event = event[0]
            date = self.get_start_date_from_event(event)
            link = event.get('htmlLink')
            title = event.get('summary')
            html_bullet = f'<tr><td>{date}</td><td><a href="{link}">{title}</a></td><td>{issue_description}</td></tr>'
            text_bullet = f'- {date} "{title}" - {issue_description}\n'
            html += html_bullet + "\n\n"
            text += text_bullet + "\n\n"
        html += "</tbody></table>\n\n<hr/>\n\n<p>Thank you for using this AI agent. I'm not perfect, but I'm trying my best! I've attached my full reasoning and thought process in a text file.</p></body></html>"
        return html, text

    def analyze_calendar(self, user, file_id, sendmail=False):
        """Gets the calendar events, get the prompt instructions, sends to gemini, returns the answer and writes the reasoning to a file"""
        events = self.get_calendar_events(user)
        instructions = self.get_instructions(file_id)
        max_retries = 5
        retry_count = 1
        while True:
            answer, reasoning = self.prompt_against_calendar(events, instructions)
            if answer is not None and reasoning is not None:
                break
            self._log(f"No answer or reasoning from Gemini, retrying... (attempt {retry_count} of {max_retries})")
            retry_count += 1
            if retry_count > max_retries:
                self._log(f"Max retries ({max_retries}) reached, giving up!")
                return
        # save the reasoning to a temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".reasoning.txt") as reasoning_file:
            reasoning_file.write(reasoning.encode('utf-8'))
            reasoning_file.flush()
            self._log(f"Reasoning saved to {reasoning_file.name}")
            # parse the answer and format it
            issues = self.parse_answer(answer)
            html_answer, text_answer = self.render_issues(issues, events)
            # subject should have todays date
            subject = f"Upcoming Calendar Issues - {datetime.now().strftime('%Y-%m-%d')}"
            if sendmail:
                self.send_mail(user, user, user, subject, text_answer, html_answer, attachments=[reasoning_file.name])
                self._log("Email sent")
            else:
                self._log("HTML Output: \n\n" + html_answer)
                self._log("Text Output: \n\n" + text_answer)

    def find_users(self):
        """
        Finds all users who have shared a file named PROMPT.AI_AGENT.GCAL with Service Account
        Returns a list of tuples, containing the user's email address and the fileID of the instructions.
        """
        _, drive_service, _, _ = self.get_services()
        query = f"name = '{self.PROMPT_GDOC_FILENAME}'"
        results = drive_service.files().list(q=query, spaces='drive', fields='nextPageToken, files(id,owners(emailAddress))').execute() # pylint: disable=no-member
        files = results.get('files', [])
        users = []
        for file in files:
            file_id = file.get('id')
            owners = file.get('owners', [])
            for owner in owners:
                user = owner.get('emailAddress')
                users.append((user, file_id))
        return users

    def get_all_workspace_users(self, valid_domains=None):
        """Get all users in the workspace"""
        _, _, _, svc_directory = self.get_services(self.ADMIN_EMAIL)
        
        # Get all users in the domain, then get all their emails
        results = svc_directory.users().list(
            customer='my_customer',
            maxResults=500,
            orderBy='email'
        ).execute()
        users = results.get('users', [])
        emails = [u['primaryEmail'].lower() for u in users if u.get('primaryEmail')]
        self._log(f"Found {len(emails)} users in the workspace")

        # optionally filter by domains
        if valid_domains:
            emails = [e for e in emails if e.split('@')[1] in valid_domains]
            self._log(f"Filtered to {len(emails)} users in the workspace")

        return emails

    def analyze_calendars(self, sendmail=False):
        """Analyzes all calendars for all users"""
        users = self.find_users()
        self._log(f"Found {len(users)} users with shared instructions")
        for user, file_id in users:
            self._log(f"Analyzing {user}'s calendar...")
            self.analyze_calendar(user, file_id, sendmail)

    def measure_event_duration(self, event):
        """Measure the duration of an event in hours. Multi-day events return a duration of None"""
        if 'date' in event.get('start', {}):
            return None
        if 'date' in event.get('end', {}):
            return None
        start_str = event.get('start', {}).get('dateTime')
        end_str = event.get('end', {}).get('dateTime')
        # Convert to datetime objects
        start = datetime.strptime(start_str, "%Y-%m-%dT%H:%M:%S%z")
        end = datetime.strptime(end_str, "%Y-%m-%dT%H:%M:%S%z")
        duration = end - start
        # extract the total number of minutes from the duration
        return duration.total_seconds() / 60 / 60
    
    def classify_event(self, event):
        """
        Classify an event as SOLO, PERSONAL, INTERNAL, or EXTERNAL based on attendees.
        Additionally, return the first non-internal domain in the attendees list.
        """
        # Get list of attendees, removing "self" 
        attendees = event.get('attendees', [])
        attendees = [x for x in attendees if x.get('self', False) != True]

        # get the list of domains, and remove excluded domains
        domains = set([x.get('email', '').lower().split('@')[-1] for x in attendees])
        domains = domains - self.EXCLUDED_DOMAINS

        if not attendees:
            return 'SOLO', None

        # if ANY of the attendees are non-INTERNAL, non-PERSONAL, then it's an EXTERNAL category
        for domain in domains:
            if domain not in self.INTERNAL_DOMAINS and domain not in self.PERSONAL_DOMAINS:
                return 'EXTERNAL', domain

        # if ANY of the attendees are PERSONAL, then it's a PERSONAL category
        for domain in domains:
            if domain in self.PERSONAL_DOMAINS:
                return 'PERSONAL', domain

        # anything remaining is INTERNAL
        return 'INTERNAL', None
    
    def check_if_event_is_recurring(self, event):
        """Check if an event is recurring"""
        # events are recurring if they have a recurringEventId
        reid = event.get('recurringEventId', '')
        return len(reid) > 0

    def change_event_final_date(self, user, event_id, new_final_date):
        """For an event with a recurrence, change the final date."""
        scope = 'https://www.googleapis.com/auth/calendar.events.owned'
        creds = service_account.Credentials.from_service_account_info(self.gcp_creds, scopes=[scope])
        creds_to_use = creds.with_subject(user)
        svc_calendar = build('calendar', 'v3', credentials=creds_to_use)
        event = svc_calendar.events().get(calendarId='primary', eventId=event_id).execute()
        old_recurrence = event.get('recurrence', [])
        new_recurrence = self.modify_recurrence_to_add_final_date(old_recurrence, new_final_date)
        self._log(f"Found event {event_id}: old rule {old_recurrence} || new rule {new_recurrence}")
        self._log(f"About to update event {event_id}...")
        event['recurrence'] = new_recurrence
        updated_event = svc_calendar.events().update(calendarId='primary', eventId=event_id, body=event).execute()
        self._log(f"...updated event {event_id}")
        return updated_event

    def modify_recurrence_to_add_final_date(self, recurrence, final_date):
        """
        Takes a RFC 5545 recurrence string, and edits it to include a final date, 
        returning the modified recurrence string.

        https://datatracker.ietf.org/doc/html/rfc5545

        For example, turns this:
        > RRULE:FREQ=WEEKLY;BYDAY=FR
        into this:
        > RRULE:FREQ=WEEKLY;WKST=MO;UNTIL=20250822T225959Z;BYDAY=FR

        Additionally, if you pass in a list of a single string, it will return a list of a single, string, i.e.
        > ["RRULE:FREQ=WEEKLY;BYDAY=FR"]
        > ["RRULE:FREQ=WEEKLY;WKST=MO;UNTIL=20250822T225959Z;BYDAY=FR"]
        """
        # The google calendar API for some reason sends recurrence strings as a single-value array
        if isinstance(recurrence, list):
            if len(recurrence) == 1:
                return [self.modify_recurrence_to_add_final_date(recurrence[0], final_date)]
            else:
                raise ValueError("Recurrence array had multiple values which is not supported.")
        if not isinstance(recurrence, str):
            raise ValueError("Recurrence must be a string")
        # recurrence strings must start with RRULE:
        # if it does, remove the RRULE: prefix
        # then parse the remaining string KEY1=VAL1;KEY2=VAL2;KEY3=VAL3 into a dictionary
        if not recurrence.startswith('RRULE:'):
            raise ValueError("Recurrence string must start with RRULE:")
        recurrence = recurrence[6:]
        pairs = dict(v.split("=") for v in recurrence.split(";"))
        # Add week start (WKST) and final date (UNTIL)
        pairs['WKST'] = 'MO'
        pairs['UNTIL'] = datetime.combine(final_date, time.max).strftime("%Y%m%dT%H%M%SZ")
        # re-render the string
        returns = "RRULE:" + ";".join([f"{k}={v}" for k, v in pairs.items()])
        return returns
