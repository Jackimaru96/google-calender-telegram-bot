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

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

BOT_TOKEN = os.getenv('BOT_TOKEN')
GROUPCHAT_ID = os.getenv('GROUPCHAT_ID_2') # Use this for testing
# GROUPCHAT_ID = os.getenv('GROUPCHAT_ID') # Use this for actual sending to group
THEYOUNGMAKER_ID = os.getenv('THEYOUNGMAKER_ID')
SOK_CALENDAR_ID = os.getenv('SOK_CALENDAR_ID')
LL_CALENDAR_ID = os.getenv('LL_CALENDAR_ID')

SOK_BRANCH_HEADER = "================ <b><u> Stars of Kovan Branch </u></b> ================\n\n"
LL_BRANCH_HEADER = "================ <b><u> 35 Lowland Branch </u></b> ================\n\n"
SOK_KEY = "SOK"
LL_KEY = "LL"
REMINDER_MSG = """
====================================
Please arrive 5-10 mins before lesson starts.

For teachers taking the last lesson, please:
1. Tidy up the center
2. Lock up centre, switch off aircon, projector & lights. Do not switch off WiFi.
3. Please send video of aircon & projector switched off, door locked, keybox scrambled with key inside

Please remember to pass students:
1. Textbook for the relevant module if they have yet to receive
2. Student shirt for new students of TYM.

Lesson materials will be sent to you by your lesson. Please PM me to ask for lesson slides if it is not sent to you 5 days before your lesson begins.

=======================================
You are required to send a summary message after your lesson.

Module name, lesson number
- Which students were absent/present
- Completed lesson number X/Did not manage to finish lesson number X
- Ended at slide number XXX
- Which student lagging behind/too fast; request for additional lessons to complete module

======================================
Please react to lesson reminder message above to acknowledge your classes

"""

last_sent_message_id = None

def is_valid_date(input_date_str):
    try:
        datetime.datetime.strptime(input_date_str, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def log_to_file(sent_text, message_id, chat_id, message_date):
    with open('message_log.csv', mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([message_date, message_id, chat_id, sent_text])

def remove_unsupported_tags(message):
    message = re.sub(r'<[/]?br>', ' ', message)
    message = re.sub(r'<[/]?(ul|ol|br|span|b)>', '', message)
    return message

def get_credentials():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials_tym.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

async def fetch_events(calendar_id, input_date_str, creds, service):
    now = datetime.datetime.utcnow() if input_date_str is None else datetime.datetime.strptime(input_date_str, '%Y-%m-%d')
    timeMin = (now + datetime.timedelta(days=1)).isoformat() + 'Z'
    timeMax = (now + datetime.timedelta(days=8)).isoformat() + 'Z'

    events_result = service.events().list(calendarId=calendar_id, timeMin=timeMin, timeMax=timeMax, singleEvents=True, orderBy='startTime').execute()
    events = events_result.get('items', [])
    if not events:
        print('No upcoming events found.')
        return

    grouped_events = {}
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        end = event['end'].get('dateTime', event['end'].get('date'))
        summary = event.get('summary', 'Unnamed Event')
        description = remove_unsupported_tags(event.get('description', ''))
        match = re.search(r"Teacher:\s*(.*)", description)
        teacher = match.group(1).strip() if match else ''
        match = re.search(r'@(\w+)', description)
        telegram_username = "@" + match.group(1) if match else ''

        start_dt = datetime.datetime.fromisoformat(start)
        end_dt = datetime.datetime.fromisoformat(end)

        event_text = f"{summary} ({start_dt.strftime('%H%Mhrs').lower()} to {end_dt.strftime('%H%Mhrs').lower()})\n <b>Teacher: </b>{teacher}"

        day_str = start_dt.strftime('%A %d %B %Y')
        if day_str not in grouped_events:
            grouped_events[day_str] = []
        grouped_events[day_str].append(event_text)

    return grouped_events

async def send_message(update, context, chat_id, is_reply=False):
    calendar_key = context.args[0] if context.args else SOK_KEY
    # Defaults to SOK calendar
    calendar_id = LL_CALENDAR_ID if calendar_key == LL_KEY else SOK_CALENDAR_ID
    input_date_str = context.args[1] if len(context.args) > 1 else None
    if input_date_str and not is_valid_date(input_date_str):
        input_date_str = None
        await update.message.reply_html("Date format is not valid, sending schedule for next 7 days starting from today instead.")

    creds = get_credentials()
    service = build('calendar', 'v3', credentials=creds)
    grouped_events = await fetch_events(calendar_id, input_date_str, creds, service)

    final_message = ""
    if(calendar_key == SOK_KEY):
        final_message += SOK_BRANCH_HEADER
    else:
        final_message += LL_BRANCH_HEADER

    for day, events in grouped_events.items():
        final_message += f"<b><u>{day}</u></b>\n\n"
        for i, event in enumerate(events):
            final_message += f"{i+1}. {event}\n\n"
        final_message += "\n"

    # final_message += appended_reminder_message
    bot = Bot(BOT_TOKEN)
    if is_reply:
        sent_message = await update.message.reply_html(final_message)
    else:
        sent_message = await bot.send_message(chat_id=chat_id, text=final_message, parse_mode='HTML')

    log_to_file(sent_message.text, sent_message.message_id, sent_message.chat_id, sent_message.date)
    global last_sent_message_id
    last_sent_message_id = sent_message.message_id
    await bot.send_message(chat_id=chat_id, text=REMINDER_MSG, parse_mode="HTML")

    await bot.send_message(chat_id=THEYOUNGMAKER_ID, text=f"Message ID: {sent_message.message_id}, Group Chat ID: {sent_message.chat_id}")
    print(f"Message with message id {sent_message.message_id} sent to group chat id {sent_message.chat_id}")

async def edit_last_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message_id = context.args[0] if context.args else None
    calendar_key = context.args[1] if len(context.args) > 1 else SOK_KEY
    calendar_id = SOK_CALENDAR_ID if calendar_key == SOK_KEY else LL_CALENDAR_ID
    input_date_str = context.args[2] if len(context.args) > 2 and is_valid_date(context.args[2]) else None

    if message_id is None:
        await update.message.reply_text("Message Id is empty.")
        return

    creds = get_credentials()
    service = build('calendar', 'v3', credentials=creds)
    grouped_events = await fetch_events(calendar_id, input_date_str, creds, service)

    # Get current date and time for the edit timestamp
    edit_timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    new_text = f"<i>Message edited on {edit_timestamp}</i>\n\n"

    if(calendar_key == SOK_KEY):
        new_text += SOK_BRANCH_HEADER
    else:
        new_text += LL_BRANCH_HEADER
    
    for day, events in grouped_events.items():
        new_text += f"<b><u>{day}</u></b>\n\n"
        for i, event in enumerate(events):
            new_text += f"{i+1}. {event}\n\n"
        new_text += "\n"

    bot = Bot(BOT_TOKEN)
    try:
       # Editing the original message
        await bot.edit_message_text(chat_id=GROUPCHAT_ID, message_id=message_id, text=new_text, parse_mode='HTML')

        # Sending a reply to the edited message indicating that it was updated
        notification_message = f"🔄 Schedule updated at {edit_timestamp}.\n Please review the changes."
        await bot.send_message(chat_id=GROUPCHAT_ID, text=notification_message, reply_to_message_id=message_id, parse_mode='HTML')

        await update.message.reply_html("Message has been edited successfully\n" + new_text)
        print(f"Message for message id {message_id} edited successfully")
    except Exception as e:
        await update.message.reply_html(f"Failed to edit message for message id {message_id}. Error: {str(e)}")
        print(f"Failed to edit message for message id {message_id}. Error: {str(e)}")

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_message = '''
    *__Bot Commands Help__*\n\n
/schedule `<calendar> <date>` \- Sends a schedule to you\. If no date is provided, it sends the upcoming schedule for a week from today\. If a date in YYYY\-MM\-DD format is provided, it sends the schedule for a week from that date\.\n\n
/send `<calendar> <date>` \- Sends the schedule to the teacher's chat group\. Without a date, it sends the upcoming schedule for a week from today\. With a date in YYYY\-MM\-DD format, it sends the schedule for a week from that date\. The bot replies with the message\_id for future edits\.\n\n
/edit `<message_id> <calendar> <date>` \- Edits a previously sent message in the teacher's chat group\. You need to provide the message\_id\. Optionally, you can provide a date in YYYY\-MM\-DD format to specify the schedule week\.\n\n
*Note*\: Replace `<calendar>` with 'SOK' or 'LL', `<date>` with your desired date in YYYY\-MM\-DD format and `<message_id>` with the actual message ID\.
    '''

    await update.message.reply_text(help_message, parse_mode='MarkdownV2')

async def get_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_message(update, context, None, is_reply=True)

async def get_schedule_to_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_message(update, context, GROUPCHAT_ID)

if __name__ == "__main__":
    print('starting bot')
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("schedule", get_schedule))
    app.add_handler(CommandHandler("send", get_schedule_to_chat))
    app.add_handler(CommandHandler("edit", edit_last_message))
    app.add_handler(CommandHandler("helpme", show_help))
    print("polling")
    app.run_polling(poll_interval=3)
