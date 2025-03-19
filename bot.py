"""A Slack bot that handles direct messages"""
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from gcal import GoogleCalendarAgent

# Initialize the Slack app with your bot token
app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET")
)
agent = GoogleCalendarAgent()

def get_user_name_and_email(user_id):
    """Given a user ID, return the user's real name and email address"""
    result = app.client.users_info(user=user_id)
    user_info = result.get('user', {})
    real_name = user_info.get('real_name')
    email = user_info.get('profile', {}).get('email')
    return real_name, email

# Handle direct messages
@app.event("message")
def handle_message(event, say):
    """Handles messages from Slack"""
    # Check if this is a DM (direct message)
    if event.get("channel_type") == "im":
        try:
            user = event.get("user")
            text = event.get("text")
            real_name, email = get_user_name_and_email(user)
            print(user, real_name, email, text)
            say(f"Looking up calendar events for {real_name} ({email}) ...")
            events = agent.get_calendar_events(email)
            say(f"Found {len(events)} events, will use prompt `{text}` ...")
            answer, _ = agent.custom_prompt_against_calendar(events, text)
            if answer:
                say(answer)
            else:
                say("Oops! Gemini didn't return an answer. Please try again later.")
        except Exception as e: # pylint: disable=broad-exception-caught
            say(f"Oops! An error occurred: {e}")

# Start your app
if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
