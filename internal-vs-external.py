"""Classify events into SOLO, PERSONAL, INTERNAL, EXTERNAL"""

import datetime
import argparse
import time
from gcal import GoogleCalendarAgent

def get_classified_events(user, start_date=None, end_date=None):
    """Get and classify calendar events for a user"""
    agent = GoogleCalendarAgent()
    events = agent.get_calendar_events(user, start_date, end_date)

    classified_events = []
    for event in events:
        classification, external_domain = agent.classify_event(event)
        is_recurring = agent.check_if_event_is_recurring(event)
        event_date = event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))[0:10]
        classified_events.append({
            'user': user,
            'summary': event.get('summary', 'No title'),
            'date': event_date,
            'duration': agent.measure_event_duration(event),
            'classification': classification,
            'external_domain': external_domain,
            'is_recurring': is_recurring,
            'recurringEventId': event.get('recurringEventId')
        })

    return classified_events

def summarize_classifications(events):
    """
    Count events by classification.
    Note that we distinguish between INTERNAL and INTERNAL_RECURRING.
    """
    returns = {
        'SOLO': (0,0),
        'PERSONAL': (0,0),
        'INTERNAL': (0,0), 
        'INTERNAL_RECURRING': (0,0),
        'EXTERNAL': (0,0)
    }

    for event in events:
        classification = event['classification']
        is_recurring = event['is_recurring']
        label = 'INTERNAL_RECURRING' if (classification == 'INTERNAL' and is_recurring) else classification
        duration = event['duration'] or 0
        old_val = returns[label]
        new_val = (old_val[0] + 1, old_val[1] + duration)
        returns[label] = new_val

    return returns

def accumulate(summaries, externals, internal_recurrings, user, start_date, end_date):
    """Accumulate the classifications for a user"""
    def is_internal_recurring(event):
        return (
            event['classification'] == 'INTERNAL' and
            event['is_recurring'] and
            event['duration'] is not None
        )
    events = get_classified_events(user, start_date, end_date)
    counts = summarize_classifications(events)
    external_events = [event for event in events if event['classification'] == 'EXTERNAL']
    internal_recurring_events = [event for event in events if is_internal_recurring(event)]
    summaries.append((user, counts))
    externals.extend(external_events)
    internal_recurrings.extend(internal_recurring_events)

def get_all_workspace_users():
    """Get all users in the workspace"""
    agent = GoogleCalendarAgent()
    return agent.get_all_workspace_users(valid_domains=agent.INTERNAL_DOMAINS)

def main_all_users(start_date, end_date):
    """Main function for all users"""
    max_users = 500
    print(f"Getting all workspace users up to {max_users}")
    users = get_all_workspace_users()
    summaries = []
    externals = []
    internal_recurrings = []
    for i, u in enumerate(users):
        print(f"Processing {u} ({i+1}/{len(users)})")
        accumulate(summaries, externals, internal_recurrings, u, start_date, end_date)
        time.sleep(1)
        if i >= max_users - 1:
            break
    # write summaries to csv file
    filename = 'summaries.csv'
    columns = ['SOLO', 'PERSONAL', 'INTERNAL', 'INTERNAL_RECURRING', 'EXTERNAL']
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("user,")
        for c in columns:
            f.write(f"{c}_MEETINGS,")
            f.write(f"{c}_DURATION,")
        f.write("\n")
        for s in summaries:
            f.write(f"{s[0]},")
            for c in columns:
                f.write(f"{s[1][c][0]},")
                f.write(f"{s[1][c][1]:.2f},")
            f.write("\n")
        print(f"Wrote {len(summaries)} summaries to {filename}")
    # write externals to csv file
    filename = 'externals.csv'
    columns = ['user', 'date', 'duration', 'summary', 'external_domain']
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(",".join(columns) + "\n")
        for e in externals:
            for c in columns:
                f.write(f"{e[c]},")
            f.write("\n")
        print(f"Wrote {len(externals)} externals to {filename}")
    # write recurring internals to csv file
    filename = 'recurring_internals.csv'
    columns = ['user', 'recurringEventId', 'date', 'duration', 'summary']
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(",".join(columns) + "\n")
        for e in internal_recurrings:
            for c in columns:
                f.write(f"{e[c]},")
            f.write("\n")
        print(f"Wrote {len(internal_recurrings)} internal recurring events to {filename}")

def main_single_user(user, start_date, end_date):
    """Main function for a single user"""
    events = get_classified_events(user, start_date, end_date)
    counts = summarize_classifications(events)
    print(f"Summary for {user} from {start_date} to {end_date}:")
    for x in ['SOLO', 'PERSONAL', 'INTERNAL', 'INTERNAL_RECURRING', 'EXTERNAL']:
        print(f"  {x}: {counts[x][0]} meetings, {counts[x][1]:.2f} hours")

def main(user, start_date, end_date):
    """Main function"""
    # if the user is the string ALL, then we will run through a list of all users
    if user == 'ALL':
        return main_all_users(start_date, end_date)
    else:
        return main_single_user(user, start_date, end_date)

def parse_date(date_string):
    """Parses a date string in YYYY-MM-DD format and returns a datetime.date object."""
    try:
        return datetime.datetime.strptime(date_string, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date format. Expected YYYY-MM-DD, got '{date_string}'") from exc

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Classify calendar events')
    parser.add_argument('--user', type=str, help='User to classify events for')
    parser.add_argument("--start_date", help="Optional start date to analyze", type=parse_date)
    parser.add_argument("--end_date", help="Optional end date to analyze", type=parse_date)
    args = parser.parse_args()
    config = parser.parse_args()
    main(**vars(config))
