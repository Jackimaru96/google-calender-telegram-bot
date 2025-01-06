import os.path
import re
import os
import csv
import datetime
import pandas as pd

from dotenv import load_dotenv
from telegram import Update, Bot
from zoneinfo import ZoneInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

#region environment variables
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
GROUPCHAT_ID = os.getenv('GROUPCHAT_ID') # Use this for the actual group chat
# GROUPCHAT_ID = os.getenv('TEST_GROUPCHAT_ID') # Use this for a testing group chat

# Rename constants to a different calendar ID if needed
# This is based on specific use case where there are two calendars for vendor
SOK_CALENDAR_ID = os.getenv('SOK_CALENDAR_ID')
LL_CALENDAR_ID = os.getenv('LL_CALENDAR_ID')
#endregion

#region environment constants
PAYMENTS_EXCEL_FOLDER = "payments"
TEACHERS_25_HOURLY_RATE = ["@hoobird"] # This list consists of telegram handles where the teacher's hourly rate is $25/hr instead of default $20/hr
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
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

LAST_SENT_MESSAGE_ID = None
#endregion

#region Google Calendar Functions
def get_google_credentials():
    """
    Get Google API credentials.

    This function retrieves Google API credentials either from an existing token file
    or by initiating the OAuth flow. If the token is expired, it refreshes the credentials.

    Returns:
        google.oauth2.credentials.Credentials | google.auth.external_account_authorized_user.Credentials: A valid Google API credentials object.
    """
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

def get_formatted_events(events):
    formatted_events = {}
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
        if day_str not in formatted_events:
            formatted_events[day_str] = []
        formatted_events[day_str].append(event_text)

    return formatted_events

async def fetch_calendar_events(calendar_id, input_date_str, creds, service, number_of_days=7):
    """
    Fetch events from a Google Calendar.

    Args:
        calendar_id (str): The ID of the Google Calendar.
        input_date_str (str): The starting date for the event retrieval, formatted as 'YYYY-MM-DD'.
        creds (Credentials): Google API credentials.
        service (Resource): Google Calendar API service object.

    Returns:
        list: A list of events within the specified time range.
    """
    now = datetime.datetime.now(datetime.timezone.utc) if input_date_str is None else datetime.datetime.strptime(input_date_str, '%Y-%m-%d')
    timeMin = (now + datetime.timedelta(days=1)).isoformat() + 'Z'
    timeMax = (now + datetime.timedelta(days=number_of_days+1)).isoformat() + 'Z'

    events_result = service.events().list(calendarId=calendar_id, timeMin=timeMin, timeMax=timeMax, singleEvents=True, orderBy='startTime').execute()
    events = events_result.get('items', [])
    if not events:
        print('No upcoming events found.')
        return []
    
    return events
#endregion

#region Utility Functions
def is_valid_date(input_date_str):
    """
    Validate the input date string.

    Args:
        input_date_str (str): Date string in the format 'YYYY-MM-DD'.

    Returns:
        bool: True if the input string is a valid date, False otherwise.
    """
    try:
        datetime.datetime.strptime(input_date_str, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def remove_unsupported_tags(message):
    """
    Remove unsupported HTML tags from a string.

    Args:
        message (str): The string containing HTML tags.

    Returns:
        str: The string with unsupported HTML tags removed.
    """
    message = re.sub(r'<[/]?br>', ' ', message)
    message = re.sub(r'<[/]?(ul|ol|br|span|b)>', '', message)
    return message
#endregion

#region Payments Functions
def calculate_payment(events, venue):
    """
    Calculate payment for staff based on description from calendar events.

    Args:
        events (list): List of events retrieved from the calendar.
        venue (str): The venue name where the events occurred.

    Returns:
        tuple: A tuple containing:
            - data (list): List of payment data for individual events.
            - total_payments (dict): Dictionary of total payments for each teacher.
    """ 
    data = []
    total_payments = {}

    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        end = event['end'].get('dateTime', event['end'].get('date'))
        summary = event.get('summary', 'Unnamed Event')
        description = remove_unsupported_tags(event.get('description', ''))

        # Match main teacher and optionally shadowing or substitute teacher
        # Need to change this based on event description
        match = re.search(r"Teacher:\s*([^(@]+)\s*(@\w+)(?:\s*\(([^@]+)\s*@(\w+)\s*(shadowing|substitute|substituting)\))?", description)
        if match:
            main_teacher_name = match.group(1).strip()
            main_teacher_handle = match.group(2).strip().lower()
            other_teacher_name = match.group(3).strip() if match.group(3) else None
            other_teacher_handle = "@" + match.group(4).strip().lower() if match.group(4) else None
            other_teacher_type = match.group(5).strip() if match.group(5) else None

            if other_teacher_type and ('substitute' in other_teacher_type or 'substituting' in other_teacher_type):
                teacher_handle = other_teacher_handle
                teacher_name = other_teacher_name
                teacher_rate = 25 if other_teacher_handle in TEACHERS_25_HOURLY_RATE else 20
                teacher_hours = (datetime.datetime.fromisoformat(end) - datetime.datetime.fromisoformat(start)).total_seconds() / 3600
                teacher_remarks = "Substitute"
            else:
                teacher_handle = main_teacher_handle
                teacher_name = main_teacher_name
                teacher_rate = 25 if main_teacher_handle in TEACHERS_25_HOURLY_RATE else 20
                teacher_hours = (datetime.datetime.fromisoformat(end) - datetime.datetime.fromisoformat(start)).total_seconds() / 3600
                teacher_remarks = ""

            if "POSTPONED" in summary or "[POSTPONED]" in summary:
                teacher_rate = 0
                teacher_remarks = "Postponed"

            teacher_amount = teacher_hours * teacher_rate

            # Add payment to the total payments dictionary
            if teacher_handle not in total_payments:
                total_payments[teacher_handle] = {"name": teacher_name, "amount": 0}
            total_payments[teacher_handle]["amount"] += teacher_amount

            data.append([
                venue,
                datetime.datetime.fromisoformat(start).strftime('%Y-%m-%d'),
                datetime.datetime.fromisoformat(start).strftime('%A'),
                summary,
                datetime.datetime.fromisoformat(start).strftime('%H:%M'),
                datetime.datetime.fromisoformat(end).strftime('%H:%M'),
                teacher_hours,
                teacher_name,
                teacher_handle,
                teacher_rate,
                teacher_amount,
                teacher_remarks
            ])

            # Add shadowing teacher row if present
            if other_teacher_type and 'shadowing' in other_teacher_type:
                shadowing_rate = 15
                shadowing_hours = 1
                shadowing_amount = shadowing_hours * shadowing_rate

                # Add payment to the total payments dictionary for the shadowing teacher
                if other_teacher_handle not in total_payments:
                    total_payments[other_teacher_handle] = {"name": other_teacher_name, "amount": 0}
                total_payments[other_teacher_handle]["amount"] += shadowing_amount

                data.append([
                    venue,
                    datetime.datetime.fromisoformat(start).strftime('%Y-%m-%d'),
                    datetime.datetime.fromisoformat(start).strftime('%A'),
                    summary,
                    datetime.datetime.fromisoformat(start).strftime('%H:%M'),
                    datetime.datetime.fromisoformat(end).strftime('%H:%M'),
                    shadowing_hours,
                    other_teacher_name,
                    other_teacher_handle,
                    shadowing_rate,
                    shadowing_amount,
                    "Shadowing"
                ])

    return data, total_payments

async def generate_payment_sheet_for_all_calendars(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Generates an excel file with payment details for staff based on Google Calendar description.
    Sends excel file as a reply to user and also save the excel file in project root folder

    Args:
        update (Update): The Telegram Update object.
        context (ContextTypes.DEFAULT_TYPE): The context object passed by the Telegram handler.

    Returns:
        None
    """ 
    input_date_str = context.args[0] if len(context.args) > 0 else None
    if input_date_str and not is_valid_date(input_date_str):
        await update.message.reply_html("Date format is not valid.")
        return

    creds = get_google_credentials()
    service = build('calendar', 'v3', credentials=creds)

    # Fetch events for SOK
    sok_events = await fetch_calendar_events(SOK_CALENDAR_ID, input_date_str, creds, service)
    sok_payment_data, sok_totals = calculate_payment(sok_events, venue='SOK')

    # Fetch events for LL
    ll_events = await fetch_calendar_events(LL_CALENDAR_ID, input_date_str, creds, service)
    ll_payment_data, ll_totals = calculate_payment(ll_events, venue='LL')

    # Combine data
    payment_data = sok_payment_data + [['']*11] + ll_payment_data

    # Combine total payments
    total_payments = sok_totals
    for teacher_handle, details in ll_totals.items():
        if teacher_handle in total_payments:
            total_payments[teacher_handle]["amount"] += details["amount"]
        else:
            total_payments[teacher_handle] = details

    # Append total payments summary to the data
    payment_data.append(['', '', '', '', '', '', '', '', '', '', '', ''])  # Blank row for separation
    payment_data.append(['', '', '', '', '', '', '', '', '', '', '', ''])

    # for teacher_handle, details in total_payments.items():
    #     payment_data.append(['', '', '', '', '', '', '', details["name"], teacher_handle, '', details["amount"], ''])

    for teacher_handle, details in sorted(total_payments.items(), key=lambda item: item[1]["name"]):
        payment_data.append(['', '', '', '', '', '', '', details["name"], teacher_handle, '', details["amount"], ''])

    df = pd.DataFrame(payment_data, columns=[
        'Venue', 'Date', 'Day', 'Course', 'Start Time', 'End Time', 'Number of hours', 
        'Teacher Name', 'Teacher Handle', 'Hourly Rate', 'Amount', 'Remarks'
    ])

    start_date = datetime.datetime.strptime(input_date_str, '%Y-%m-%d') if input_date_str else datetime.datetime.utcnow()
    end_date = start_date + datetime.timedelta(days=7)
    adjusted_end_date = start_date + datetime.timedelta(days=1)
    file_name = f"Payment_{adjusted_end_date.strftime('%Y-%m-%d')}_{end_date.strftime('%Y-%m-%d')}.xlsx"

    file_path = os.path.join(PAYMENTS_EXCEL_FOLDER, file_name)
    df.to_excel(file_path, index=False)

     # Send the generated file
    bot = Bot(BOT_TOKEN)
    try:
        with open(file_path, 'rb') as file:
            await bot.send_document(chat_id=update.message.chat_id, document=file, filename=file_name, caption="Payment sheet for all venues.")
    except Exception as e:
        await update.message.reply_html(f"Failed to send the payment sheet. Error: {str(e)}")
        return

    # Notify about successful operation
    await update.message.reply_text(f"Payment sheet for all venues has been sent.")
#endregion

#region Telegram Bot Functions
async def send_message(update, context, chat_id, is_reply=False):
    """
    Pulls events from Google Calendar and sends the formatted message in the chat with event details

    Args:
        update (Update): The Telegram Update object.
        context (ContextTypes.DEFAULT_TYPE): The context object passed by the Telegram handler.
        chat_id (int): The chat ID where the message will be sent.
        is_reply (bool, optional): Whether the message is a reply to a user. Defaults to False.

    Returns:
        None
    """
    calendar_key = context.args[0] if context.args else SOK_KEY
    # Defaults to SOK calendar
    calendar_id = LL_CALENDAR_ID if calendar_key == LL_KEY else SOK_CALENDAR_ID
    input_date_str = context.args[1] if len(context.args) > 1 else None
    if input_date_str and not is_valid_date(input_date_str):
        input_date_str = None
        await update.message.reply_html("Date format is not valid, sending schedule for next 7 days starting from today instead.")

    creds = get_google_credentials()
    service = build('calendar', 'v3', credentials=creds)
    events = await fetch_calendar_events(calendar_id, input_date_str, creds, service)

    final_message = ""
    if(calendar_key == SOK_KEY):
        final_message += SOK_BRANCH_HEADER
    else:
        final_message += LL_BRANCH_HEADER

    formatted_events = get_formatted_events(events)
    
    for day, events in formatted_events.items():
        final_message += f"<b><u>{day}</u></b>\n\n"
        for i, event in enumerate(events):
            final_message += f"{i+1}. {event}\n\n"
        final_message += "\n"

    bot = Bot(BOT_TOKEN)
    if is_reply:
        sent_message = await update.message.reply_html(final_message)
    else:
        sent_message = await bot.send_message(chat_id=chat_id, text=final_message, parse_mode='HTML')

    global LAST_SENT_MESSAGE_ID
    LAST_SENT_MESSAGE_ID = sent_message.message_id
    await bot.send_message(chat_id=chat_id, text=REMINDER_MSG, parse_mode="HTML")

    user_chat_id = update.effective_user.id
    await bot.send_message(chat_id=user_chat_id, text=f"Message ID: {sent_message.message_id}, Group Chat ID: {sent_message.chat_id}")
    print(f"Message with message id {sent_message.message_id} sent to group chat id {sent_message.chat_id}")

async def edit_message_in_groupchat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Pulls events from Google Calendar and update the specified message in the chat with updated event details

    Args:
        update (Update): The Telegram Update object.
        context (ContextTypes.DEFAULT_TYPE): The context object passed by the Telegram handler.

    Returns:
        None
    """
    message_id = context.args[0] if context.args else None
    calendar_key = context.args[1] if len(context.args) > 1 else SOK_KEY
    calendar_id = SOK_CALENDAR_ID if calendar_key == SOK_KEY else LL_CALENDAR_ID
    input_date_str = context.args[2] if len(context.args) > 2 and is_valid_date(context.args[2]) else None

    if message_id is None:
        await update.message.reply_text("Message Id is empty.")
        return

    creds = get_google_credentials()
    service = build('calendar', 'v3', credentials=creds)
    events = await fetch_calendar_events(calendar_id, input_date_str, creds, service)

    # Get current date and time for the edit timestamp
    edit_timestamp = datetime.datetime.now(ZoneInfo("Asia/Singapore")).strftime('%Y-%m-%d %H:%M:%S')
    # edit_timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    new_text = f"<i>Message updated on {edit_timestamp}</i>\n\n"

    if(calendar_key == SOK_KEY):
        new_text += SOK_BRANCH_HEADER
    else:
        new_text += LL_BRANCH_HEADER

    formatted_events = get_formatted_events(events)
    
    for day, events in formatted_events.items():
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
        /payment `<calendar> <date>` \- Generates an Excel sheet with payment details for the given date range.\n\n
        *Note*\: Replace `<calendar>` with 'SOK' or 'LL', `<date>` with your desired date in YYYY\-MM\-DD format and `<message_id>` with the actual message ID\.
    '''

    await update.message.reply_text(help_message, parse_mode='MarkdownV2')

async def reply_with_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_message(update, context, None, is_reply=True)

async def send_schedule_to_groupchat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_message(update, context, GROUPCHAT_ID)
#endregion

if __name__ == "__main__":
    print('starting bot')
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("schedule", reply_with_schedule))
    app.add_handler(CommandHandler("send", send_schedule_to_groupchat))
    app.add_handler(CommandHandler("edit", edit_message_in_groupchat))
    app.add_handler(CommandHandler("helpme", show_help))
    app.add_handler(CommandHandler("paymentforall", generate_payment_sheet_for_all_calendars)) 
    print("polling")
    app.run_polling(poll_interval=3)

