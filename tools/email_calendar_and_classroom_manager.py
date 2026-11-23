"""
title: Google Services Assistant (Work + School)
description: Gmail+Calendar for work, Gmail+Classroom for school. Uses absolute paths for credentials.
"""

import os
from pathlib import Path
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

class Tools:
    def __init__(self):
        self.base_dir = str(Path(__file__).resolve().parent)
        self.token_dir = Path(__file__).resolve().parent.parent / "backend" / "data" / "google"
        
        self.credentials_files = {
            "work": os.path.join(self.base_dir, "client_secret_150764279818-lh1frivqvdp57sbh501slhiill3thkbd.apps.googleusercontent.com.json"),
            "school": os.path.join(self.base_dir, "client_secret_326982693092-f0ae6dvakoq2rlmad0i3bddh88vufu0t.apps.googleusercontent.com.json")
        }

    def _get_credentials_file(self, account: str):
        cred_file = self.credentials_files.get(account)
        if not os.path.exists(cred_file):
            raise FileNotFoundError(f"Credentials file not found: {cred_file}\nPlease place it in {self.base_dir}")
        return cred_file

    def _get_scopes(self, account: str):
        if account == "work":
            return [
                'https://www.googleapis.com/auth/gmail.readonly',
                'https://www.googleapis.com/auth/calendar'
            ]
        elif account == "school":
            return [
                'https://www.googleapis.com/auth/gmail.readonly',
                'https://www.googleapis.com/auth/classroom.courses.readonly',
                'https://www.googleapis.com/auth/classroom.coursework.students.readonly'
            ]
        raise ValueError("Account must be 'work' or 'school'")

    def _get_credentials(self, account: str = "work") -> Credentials:
        self.token_dir.mkdir(parents=True, exist_ok=True)
        token_file = str(self.token_dir / f"token_{account}.json")
        cred_file = self._get_credentials_file(account)
        scopes = self._get_scopes(account)
        
        creds = None
        if os.path.exists(token_file):
            creds = Credentials.from_authorized_user_file(token_file, scopes)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                print(f"Opening browser for {account} account authentication...")
                flow = InstalledAppFlow.from_client_secrets_file(cred_file, scopes)
                creds = flow.run_local_server(port=0)
            with open(token_file, "w") as token:
                token.write(creds.to_json())
        return creds

    # ====================== GMAIL ======================
    def list_important_emails(self, account: str = "work", query: str = "is:unread", max_results: int = 10) -> str:
        """List emails for work or school account."""
        creds = self._get_credentials(account)
        service = build('gmail', 'v1', credentials=creds)
        
        results = service.users().messages().list(userId='me', q=query, maxResults=max_results).execute()
        messages = results.get('messages', [])
        
        emails = []
        for msg in messages:
            msg_data = service.users().messages().get(userId='me', id=msg['id'], format='metadata').execute()
            headers = msg_data.get('payload', {}).get('headers', [])
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            from_ = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
            emails.append(f"From: {from_} | Subject: {subject}")
        
        return "\n".join(emails) if emails else f"No emails found for {account} account."

    # ====================== CALENDAR (Work) ======================
    def manage_calendar_event(self, action: str, title: str = None, start: str = None, 
                            end: str = None, event_id: str = None) -> str:
        """Manage calendar events (work account only)."""
        creds = self._get_credentials("work")
        service = build('calendar', 'v3', credentials=creds)
        
        if action == "list":
            events_result = service.events().list(
                calendarId='primary', timeMin='2026-06-01T00:00:00Z',
                maxResults=10, singleEvents=True, orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])
            return "\n".join([f"{e.get('summary', 'No title')} at {e['start'].get('dateTime', e['start'].get('date'))}" 
                            for e in events])
        
        elif action == "create" and title and start:
            event = {
                'summary': title,
                'start': {'dateTime': start, 'timeZone': 'UTC'},
                'end': {'dateTime': end or start, 'timeZone': 'UTC'},
            }
            created = service.events().insert(calendarId='primary', body=event).execute()
            return f"✅ Created event: {created.get('htmlLink')}"
        
        elif action == "delete" and event_id:
            service.events().delete(calendarId='primary', eventId=event_id).execute()
            return f"🗑️ Deleted event {event_id}"
        
        return "Invalid action or missing parameters."

    # ====================== CLASSROOM (School) ======================
    def get_classroom_assignments(self) -> str:
        """Get courses and assignments (school account)."""
        creds = self._get_credentials("school")
        service = build('classroom', 'v1', credentials=creds)
        
        courses = service.courses().list().execute().get('courses', [])
        if not courses:
            return "No active courses found."
        
        output = ["📚 Courses & Assignments:"]
        for course in courses[:5]:
            output.append(f"\n📘 {course['name']}")
            cw = service.courses().courseWork().list(courseId=course['id']).execute()
            items = cw.get('courseWork', [])[:6]
            for item in items:
                due = item.get('dueDate', {})
                due_str = f"{due.get('year')}-{due.get('month')}-{due.get('day')}" if due else "No due date"
                output.append(f"   • {item.get('title')} → due {due_str}")
        return "\n".join(output)
