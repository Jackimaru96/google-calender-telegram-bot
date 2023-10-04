import os.path
import re
import os
import csv
from dotenv import load_dotenv
import datetime

from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar']

BOT_TOKEN = os.getenv('BOT_TOKEN')
GROUPCHAT_ID = os.getenv('GROUPCHAT_ID')
# Send to test group
# GROUPCHAT_ID = os.getenv('GROUPCHAT_ID_2')
THEYOUNGMAKER_ID = os.getenv('THEYOUNGMAKER_ID')

last_sent_message_id = None

appended_reminder_message = """
======================================================
For teachers who are taking the first lesson of the day, please arrive 5 to 10 minutes before lesson starts to open and set up the centre.

For teachers who are taking the last lesson of the day, please help to:
1. Tidy up the center by placing the laptops back onto the floating shelves
2. Clearing the trash on the table
3. Lock up the centre and switch off aircon, project and lights. Do not switch off WiFi.
4. Please send a video proof of the aircon and projector switched off, as well pushing the door to show its locked and shaking the locked keybox with key inside and scramble the lockbox pin

Please remember to pass the students:
1. Textbook for the relevant module if they have yet to receive (if there are new students joining halfway or a new module with the same students)
2. Student shirt for students who are new to The Young Maker

Lesson materials will be sent to you by your lesson. If I somehow miss out sending you the materials, please do PM me to ask for it!

======================================================
Gentle reminder to send a summary message after your lesson.

Module name, lesson number
- Which students were absent/present
- Completed lesson number X/Did not manage to finish lesson number X
- Did not finish XXXX
- Any other comments

======================================================
Please react to this message to acknowledge your classes

"""

def is_valid_date(input_date_str):
    if (input_date_str == None):
        return False

    if len(input_date_str) != 10:
        return False

    try:
        # Try to convert the string to a datetime object
        datetime.datetime.strptime(input_date_str, '%Y-%m-%d')
        return True
    except ValueError:
        # If conversion fails, then it's an invalid date string
        return False

def log_to_file(sent_text, message_id, chat_id, message_date):
    with open('message_log.csv', mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([ message_date,  message_id, chat_id, sent_text])

def remove_unsupported_tags(message):

    # Remove other unsupported tags
    message = re.sub(r'<[/]?br>', ' ', message)
    message = re.sub(r'<[/]?(ul|ol|br|span|b)>', '', message)

    return message

def get_credentials():
    """Get or refresh credentials."""
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials_tym.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return creds

# Fetch Events from Google Calendar
async def fetch_events(input_date_str, creds, service):
    """Fetch and process events from Google Calendar."""
     # Call the Calendar API
    now = datetime.datetime.utcnow()
    if input_date_str != None:
        now =  datetime.datetime.strptime(input_date_str, '%Y-%m-%d')

    timeMin = (now + datetime.timedelta(days=1)).isoformat() + 'Z'
    timeMax = (now + datetime.timedelta(days=8)).isoformat() + 'Z'

    events_result = service.events().list(calendarId='primary', timeMin=timeMin,
                                            timeMax=timeMax, singleEvents=True,
                                            orderBy='startTime').execute()
    events = events_result.get('items', [])

    if not events:
        print('No upcoming events found.')
        return

    grouped_events = {}

    # Prints the start and name of the next 10 events
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        end = event['end'].get('dateTime', event['end'].get('date'))
        summary = event.get('summary', 'Unnamed Event')
        description = remove_unsupported_tags(event.get('description', ''))
        match = re.search(r"Teacher:\s*(.*)", description)
        teacher = match.group(1).strip() if match else ''
        match = re.search(r'@(\w+)', description)
        telegram_username = "@" + match.group(1) if match else ''

        # Convert ISO format to datetime object for easier manipulation
        start_dt = datetime.datetime.fromisoformat(start)
        end_dt = datetime.datetime.fromisoformat(end)

        # Prepare the text for this individual event
        event_text = f"{summary} ({start_dt.strftime('%H%Mhrs').lower()} to {end_dt.strftime('%H%Mhrs').lower()})\n <b>Teacher: </b>{teacher}"

        # Group by day
        day_str = start_dt.strftime('%A %d %B %Y')
        if day_str not in grouped_events:
            grouped_events[day_str] = []
        grouped_events[day_str].append(event_text)

    return grouped_events

# General method to send message
async def send_message(update, context, chat_id, is_reply=False):
    """Send the message either as a reply or to a group chat."""
    input_date_str = context.args[0] if context.args else None
    if input_date_str and not is_valid_date(input_date_str):
        input_date_str = None
        await update.message.reply_html("Date format is not valid, sending schedule for next 7 days starting from today instead.")

    creds = get_credentials()
    service = build('calendar', 'v3', credentials=creds)
    grouped_events = await fetch_events(input_date_str, creds, service)

    final_message = ""
    for day, events in grouped_events.items():
        final_message += f"<b><u>{day}</u></b>\n\n"
        for i, event in enumerate(events):
            final_message += f"{i+1}. {event}\n\n"
        final_message += "\n"

    final_message += appended_reminder_message
    bot = Bot(BOT_TOKEN)

    if is_reply:
        sent_message = await update.message.reply_html(final_message)
    else:
        sent_message = await bot.send_message(chat_id=chat_id, text=final_message, parse_mode='HTML')

    log_to_file(sent_message.text, sent_message.message_id, sent_message.chat_id, sent_message.date)

    global last_sent_message_id
    last_sent_message_id = sent_message.message_id

    await bot.send_message(chat_id=THEYOUNGMAKER_ID, text=f"Message ID: {sent_message.message_id}, Group Chat ID: {sent_message.chat_id}")

# /schedule command to get schedule using reply; arg[0] (optional): date (YYYY-MM-DD)
async def get_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send schedule as a reply."""
    await send_message(update, context, None, is_reply=True)

# /send command to send schedule to chatgroup; arg[0] (optional): date (YYYY-MM-DD)
async def get_schedule_to_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send schedule to a group chat."""
    await send_message(update, context, GROUPCHAT_ID)

# /edit command to edit schedule; arg[0]: messageID, arg[1]: date (YYYY-MM-DD)
async def edit_last_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Edit the last sent message in the group chat."""
    message_id = context.args[0] if context.args else None

    input_date_str = context.args[1] if len(context.args) > 1 else None
    if input_date_str and not is_valid_date(input_date_str):
        input_date_str = None

    if message_id is None:
        await update.message.reply_text("Message Id is empty.")
        return

    # Fetch latest data
    creds = get_credentials()
    service = build('calendar', 'v3', credentials=creds)
    if is_valid_date(input_date_str):
        grouped_events = await fetch_events(input_date_str, creds, service)
    else:
        grouped_events = await fetch_events(None, creds, service)


    new_text = ""
    for day, events in grouped_events.items():
        new_text += f"<b><u>{day}</u></b>\n\n"
        for i, event in enumerate(events):
            new_text += f"{i+1}. {event}\n\n"
        new_text += "\n"

    new_text += appended_reminder_message

    bot = Bot(BOT_TOKEN)
    try:
        await bot.edit_message_text(chat_id=GROUPCHAT_ID, message_id=message_id, text=new_text, parse_mode='HTML')
        await update.message.reply_html("Message has been edited successfully\n" + new_text)
    except Exception as e:
        print(f"An error occurred while editing the message: {e}")


async def add_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a new recurring event to Google Calendar."""

    # Splitting the arguments based on commas
    split_args = ' '.join(context.args).split(',')

    if len(split_args) < 5:
        await update.message.reply_text("Usage: /add_event <Title>, <Start Date: YYYY-MM-DD>, <Start Time-End Time: HHMM-HHMM>, <Number of Recurrences>, <Description>")
        return

    title = split_args[0].strip()
    start_date_str = split_args[1].strip()
    start_time_str, end_time_str = split_args[2].strip().split('-')
    num_recurrences = int(split_args[3].strip())
    description = split_args[4].strip()

    # Validate the start_date_str
    if not is_valid_date(start_date_str):
        await update.message.reply_text("Invalid date format.")
        return
    
    # Extract the day of the week from the start_date_str
    start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d')
    day_of_week = start_date.strftime('%A')[:2].upper()

    # Fetch credentials and set up the Calendar service
    creds = get_credentials()
    service = build('calendar', 'v3', credentials=creds)
    
    start_datetime_str = f"{start_date_str}T{start_time_str[:2]}:{start_time_str[2:]}:00+08:00"
    end_datetime_str = f"{start_date_str}T{end_time_str[:2]}:{end_time_str[2:]}:00+08:00"
    
    event = {
        'summary': title,
        'description': description,
        'start': {
            'dateTime': start_datetime_str,
            'timeZone': 'Asia/Singapore',
        },
        'end': {
            'dateTime': end_datetime_str,
            'timeZone': 'Asia/Singapore',
        },
        'recurrence': [
            f'RRULE:FREQ=WEEKLY;COUNT={num_recurrences};BYDAY={day_of_week}'
        ],
    }
    
    try:
        created_event = service.events().insert(calendarId='primary', body=event).execute()
    except HttpError as e:
        print(f"An error occurred while creating the event: {e}")
        await update.message.reply_text("An error occurred while creating the event. Please try again.")
        return

    # Retrieve all instances of the recurring event
    instances = service.events().instances(calendarId='primary', eventId=created_event['id']).execute()

    # Update the title of each instance
    for i, instance in enumerate(instances.get('items', [])):
        instance['summary'] = f"{title} [{i+1}/{num_recurrences}]"
        service.events().update(calendarId='primary', eventId=instance['id'], body=instance).execute()
        await update.message.reply_text(f"Event ID: {instance['id']}\n Title: {instance['summary']}\n Date: {instance['start']['dateTime'][:10]}")

    await update.message.reply_text(f"Recurring events for '{title}' have been added to the calendar!")

async def postpone_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Postpone a recurring event and adjust subsequent events."""
    event_id = context.args[0]

    # Fetch credentials and set up the Calendar service
    creds = get_credentials()
    service = build('calendar', 'v3', credentials=creds)

    # Fetch the postponed event details
    event = service.events().get(calendarId='primary', eventId=event_id).execute()

    # Update the title of the postponed event
    match = re.search(r"\[(\d+)/(\d+)\]", event['summary'])
    if not match:
        await update.message.reply_text("Unable to identify sequence for the given event.")
        return

    postponed_sequence = int(match.group(1))
    max_sequence = int(match.group(2))
    
    original_title = event['summary']
    event['summary'] = f"[POSTPONED] {original_title}"
    service.events().update(calendarId='primary', eventId=event_id, body=event).execute()

   # Adjust subsequent events
    events_to_adjust = service.events().list(calendarId='primary', q=original_title).execute().get('items', [])

    # Filter out items without the 'start' key and sort events by start date for sequential processing
    events_to_adjust = [event for event in events_to_adjust if 'start' in event]
    events_to_adjust.sort(key=lambda x: x['start']['dateTime'])

    for subsequent_event in events_to_adjust:
        match = re.search(r"\[(\d+)/(\d+)\]", subsequent_event['summary'])
        
        if not match:
            continue

        current_sequence = int(match.group(1))

        # Only update events that come after the postponed one
        if current_sequence > postponed_sequence:
            updated_title = f"{original_title} [{current_sequence-1}/{max_sequence}]"
            subsequent_event['summary'] = updated_title
            updated_event = service.events().update(calendarId='primary', eventId=subsequent_event['id'], body=subsequent_event).execute()
            await update.message.reply_text(f"Event ID: {updated_event['id']}\nTitle: {updated_event['summary']}\nDate: {updated_event['start']['dateTime'][:10]}")

    # Create an additional event (a week after the original last event) with the last sequence number
    last_event = events_to_adjust[-1]
    start_datetime = datetime.datetime.fromisoformat(last_event['start']['dateTime']) + datetime.timedelta(weeks=1)
    end_datetime = datetime.datetime.fromisoformat(last_event['end']['dateTime']) + datetime.timedelta(weeks=1)

    additional_event = {
        'summary': f"{original_title} [{max_sequence}/{max_sequence}]",
        'description': last_event["description"],
        'start': {
            'dateTime': start_datetime.isoformat(),
            'timeZone': 'Asia/Singapore',
        },
        'end': {
            'dateTime': end_datetime.isoformat(),
            'timeZone': 'Asia/Singapore',
        },
    }

    service.events().insert(calendarId='primary', body=additional_event).execute()

    await update.message.reply_text(f"Event '{original_title}' has been postponed and subsequent events updated.")

if __name__ == "__main__":
    print('starting bot')
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("schedule", get_schedule))
    app.add_handler(CommandHandler("send", get_schedule_to_chat))
    app.add_handler(CommandHandler("add_event", add_event))
    app.add_handler(CommandHandler("postpone_event", postpone_event))
    app.add_handler(CommandHandler("edit", edit_last_message))
    print("polling")
    app.run_polling(poll_interval=3)