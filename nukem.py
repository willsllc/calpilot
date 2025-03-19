"""Nuke all the recurring internal events post D-DAY from the calendar"""

import datetime
import argparse
import time
from gcal import GoogleCalendarAgent

def _log(message):
    """Logs to stdout."""
    print(f"[{datetime.datetime.now().isoformat()}] - {message}")

def main__single_event(agent, d_day, user, event_id, commit):
    """Nuke a single event"""
    event = agent.get_single_event(user, event_id)
    old_recurrences = event.get('recurrence', [])
    new_recurrences = agent.modify_recurrence_to_add_final_date(old_recurrences, d_day)
    if str(old_recurrences) == str(new_recurrences):
        _log(f"No change to event {event_id} is required.")
    else:
        if commit:
            _log(f"WARNING: about to changed event {event_id} to {d_day}!")
            #agent.change_event_final_date(user, event_id, d_day) # UNCOMMENT THIS LINE TO COMMIT
        else:
            _log(f"Would have changed event {event_id} to {d_day} but --commit was not set.")

def main__all_user_events(agent, d_day, user, commit):
    """Nuke all events for a single user"""
    events = agent.get_calendar_events(user, d_day, datetime.date(2025, 12, 31))
    event_ids = set()
    for i, event in enumerate(events):
        classification, external_domain = agent.classify_event(event)
        recurring_event_id = event.get('recurringEventId')
        if classification == 'INTERNAL' and recurring_event_id is not None:
            event_ids.add(recurring_event_id)
    _log(f"Found {len(event_ids)} recurring events for {user}")
    for event_id in event_ids:
        main__single_event(agent, d_day, user, event_id, commit)

def main__all_events(agent, d_day, commit):
    """Nuke all events for every user"""
    max_users = 500
    users = agent.get_all_workspace_users()
    _log(f"Found {len(users)} users")
    for i, user in enumerate(users):
        if i >= max_users:
            break
        _log(f"Processing user {i+1} of {len(users)}: {user}")
        main__all_user_events(agent, d_day, user, commit)

def main(d_day, user=None, event_id=None, commit=None):
    """Main function"""
    agent = GoogleCalendarAgent()
    if event_id:
        return main__single_event(agent, d_day, user, event_id, commit)
    elif user:
        return main__all_user_events(agent, d_day, user, commit)
    else:
        return main__all_events(agent, d_day, commit)

def parse_date(date_string):
    """Parses a date string in YYYY-MM-DD format and returns a datetime.date object."""
    try:
        return datetime.datetime.strptime(date_string, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date format. Expected YYYY-MM-DD, got '{date_string}'") from exc

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Classify calendar events')
    parser.add_argument("d_day", help="Calendar date after which all events will be deleted", type=parse_date)
    parser.add_argument('--user', type=str, help='Only apply to a specific user')
    parser.add_argument('--event_id', type=str, help='Only apply to a specific event')
    parser.add_argument('--commit', action='store_true', help='If set, the changes will be committed, otherwise printed only.')
    args = parser.parse_args()
    config = parser.parse_args()
    main(**vars(config))
