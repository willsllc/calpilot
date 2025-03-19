"""Runs the analyzer from command line"""

import argparse
import datetime
from gcal import GoogleCalendarAgent

def main(user, custom, start_date, end_date, sendmail):
    """Main function"""
    agent = GoogleCalendarAgent()
    if custom:
        events = agent.get_calendar_events(user, start_date, end_date)
        print(f"Found {len(events)} events, will use prompt `{custom}` ...")
        answer, reasoning = agent.custom_prompt_against_calendar(events, custom)
        print(reasoning)
        print("~"*80)
        print(answer)
        exit()
    if user:
        users = agent.find_users()
        matched = [x for x in users if x[0] == user]
        if len(matched) == 1:
            agent.analyze_calendar(matched[0][0], matched[0][1], sendmail)
        else:
            print(f"Was asked to analyze {user}, but found {len(matched)} matching users")
    else:
        agent.analyze_calendars(sendmail)

def parse_date(date_string):
    """Parses a date string in YYYY-MM-DD format and returns a datetime.date object."""
    try:
        return datetime.datetime.strptime(date_string, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format. Expected YYYY-MM-DD, got '{date_string}'")


if __name__ == '__main__':
    parser = argparse.ArgumentParser("GCal agent")
    parser.add_argument("--user", help="User's calendar to analyze")
    parser.add_argument("--custom", help="Custom prompt to use instead of the default prompt")
    parser.add_argument("--start_date", help="Optional start date to analyze", type=parse_date)
    parser.add_argument("--end_date", help="Optional end date to analyze", type=parse_date)
    parser.add_argument("--sendmail",
        help="If this flag is set, send an email to the user",
        action="store_true"
    )
    config = parser.parse_args()
    main(**vars(config))
