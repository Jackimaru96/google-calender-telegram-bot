# TYM Telegram Bot

This is a custom Telegram bot designed to assist with sending reminders to teachers and payment tracking for the [The Young Maker](https://theyoungmaker.com/). It integrates with Google Calendar to automate lesson reminders and calculates teacher payments based on calendar event details.

---

## ✨ Features

- 📆 **Schedule Retrieval**: Automatically fetches and formats upcoming weekly lesson schedules from Google Calendar.
- 🤖 **Telegram Integration**: Sends lesson schedules and reminders to group chats or individual users.
- 💵 **Payment Generation**: Extracts lesson information to calculate payments for teachers and generates downloadable Excel files.
- ✏️ **Message Editing**: Update previously sent schedule messages in group chats.
- 📋 **Reminders**: Sends standardised lesson operation reminders to group chats.

---

## ⚙️ Setup Instructions

### 1. Clone the Repository

```bash
git clone https://github.com/your-repo/tym-telegram-bot.git
cd tym-telegram-bot
```

### 2. Create a `.env` File

The bot currently pulls from 3 calendars, as to correspond to lessons at three different locations of the programming centres.
Create a `.env` file in the root directory and populate it with the following:

```env
BOT_TOKEN=your_telegram_bot_token
TEST_GROUPCHAT_ID=your_test_group_chat_id
GROUPCHAT_ID=your_production_group_chat_id
SOK_C_CALENDAR_ID=your_sok_c_calendar_id
SOK_R_CALENDAR_ID=your_sok_r_calendar_id
LL_CALENDAR_ID=your_ll_calendar_id
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

Make sure you have a `credentials_tym.json` file (Google OAuth credentials) in your root folder.

### 4. Run the Bot

```bash
python bot.py
```

---

## 📖 Bot Commands

| Command                                | Description                                                                               |
| -------------------------------------- | ----------------------------------------------------------------------------------------- |
| `/schedule <calendar> <date>`          | Sends the schedule to the user for the next 7 days starting from `date` (default: today). |
| `/send <calendar> <date>`              | Sends the schedule to the group chat. Returns message ID for editing.                     |
| `/edit <message_id> <calendar> <date>` | Edits an existing message in the group chat.                                              |
| `/sendrm`                              | Sends a reminder message to the group chat.                                               |
| `/paymentforall <date>`                | Generates an Excel payment sheet for all venues.                                          |
| `/helpme`                              | Shows the help message with command usage.                                                |

### Supported `<calendar>` Values

- `SOK`: Stars of Kovan Coding
- `SOKR`: Stars of Kovan Robotics
- `LL`: 35 Lowland Branch

### Date Format

`YYYY-MM-DD` (e.g., `2025-05-01`)

---

## 📁 Folder Structure

```
├── payments/                     # Folder for storing generated Excel files
├── credentials_tym.json         # Google OAuth credentials
├── token.json                   # Auto-generated token file after first OAuth login
├── bot.py                       # Main bot logic
├── .env                         # Environment variables
├── README.md                    # Project documentation
```

---

## 🛡️ Permissions Required

The bot requires the following Google Calendar API scope:

```plaintext
https://www.googleapis.com/auth/calendar.readonly
```

---

## 🧠 Notes

- Teachers with Telegram handles listed in `TEACHERS_25_HOURLY_RATE` are paid \$25/hour instead of the default \$20/hour.
- Shadowing teachers are paid \$15/hour for 1 hour.
- Postponed lessons result in zero payment and are marked accordingly.

---

## 🤝 Contributing

Feel free to fork the repo and open a pull request to suggest improvements or new features.

---
