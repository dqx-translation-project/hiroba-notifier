from bs4 import BeautifulSoup as bs
from discord_webhook import DiscordEmbed, DiscordWebhook

import datetime
import deepl
import os
import requests
import sqlite3

# for testing. make sure you remove before commiting! :)
TESTING_WEBHOOK_URL = ''
TESTING_DEEPL_API_KEY = ''


HIROBA_URL = 'https://hiroba.dqx.jp'
DEEPL_API_KEY = os.environ.get('DEEPL_API_KEY', TESTING_DEEPL_API_KEY)
GLOSSARY_URL = 'https://raw.githubusercontent.com/dqx-translation-project/dqx-custom-translations/main/csv/glossary.csv'

CATEGORIES = {
    'ニュース': 'news',
    'イベント': 'events',
    'アップデート': 'updates',
    'メンテナンス\xa0/\xa0障害': 'maintenance'
}

WEBHOOK_URLS = {
    'news': os.environ.get('DISCORD_WEBHOOK_NEWS_URL', TESTING_WEBHOOK_URL),
    'events': os.environ.get('DISCORD_WEBHOOK_EVENTS_URL', TESTING_WEBHOOK_URL),
    'updates': os.environ.get('DISCORD_WEBHOOK_UPDATES_URL', TESTING_WEBHOOK_URL),
    'maintenance': os.environ.get('DISCORD_WEBHOOK_MAINTENANCE_URL', TESTING_WEBHOOK_URL),
}

EMBED_COLORS = {
    'news': 'b79f5c', # brownish-yellow
    'events': '40adff', # blue
    'updates': '55ffa8', # mint green
    'maintenance': 'ff3737', # red
}


def glossify(content: str):
    """Pass string through our DQX glossary to use game-specific terms."""
    response = requests.get(GLOSSARY_URL)
    rows = [ x for x in response.text.split('\n') if x ]
    for record in rows:
        k, v = record.split(",", 1)
        if v == "\"\"":
            continue
        content = content.replace(k, v)
    return content


def notify_webhook(category: str, title: str, content: str, link: str, timestamp: str):
    """Triggers a Discord webhook URL."""
    webhook = DiscordWebhook(
        url=WEBHOOK_URLS[category],
        username=f'[hiroba] {category.title()}'
    )

    embed = DiscordEmbed(
        title=title,
        description=content,
        color=EMBED_COLORS[category],
        url=link,
        timestamp=datetime.datetime.fromisoformat(timestamp),
        footer = {
            "text": "(poorly) translated by DeepL :D"
        }
    )

    webhook.add_embed(embed)
    webhook.execute()


db_file = 'state.db'
conn = sqlite3.connect(db_file)
cursor = conn.cursor()

translator = deepl.Translator(DEEPL_API_KEY)

data = requests.get('/'.join([HIROBA_URL, '/sc/news/information/']))
soup = bs(data.text, 'html.parser')

# get all news categories from each header (ニュース, イベント, アップデート, メンテナンス / 障害)
news_categories = soup.find_all(attrs={'class': 'newsList'})
for category in news_categories:

    header = category.find(attrs={'class': 'ribbonBrown_w559'}).text.strip()
    news_links = category.find_all(attrs={'class': 'newsListLnk'})

    for link in news_links:
        title = link.text
        escaped_title = title.replace("'", "''")
        link = link['href']
        table = CATEGORIES[header]

        query = f"SELECT title FROM {table} WHERE title = '{escaped_title}'"
        cursor.execute(query)
        results = cursor.fetchone()

        if not results:
            data = requests.get("/".join([HIROBA_URL, link]))
            if data.status_code != 200:
                print(f"Did not get 200 from {link}. Can't parse this link.")
                continue

            soup = bs(data.text, 'html.parser')

            news_date = soup.find(attrs={'class': 'newsDate'}).text
            content = soup.find(attrs={'class': 'newsContent'})
            for line_break in content.findAll('br'):
                line_break.replaceWith('\n')
            content = content.get_text().strip('\n')

            response = translator.translate_text(
                text=[glossify(title), glossify(content)],
                source_lang='ja',
                target_lang='en-us',
                preserve_formatting=True
            )

            # post to db
            title_trl = response[0].text
            content_trl = response[1].text
            escaped_title_trl = title_trl.replace("'", "''")
            escaped_content_trl = content_trl.replace("'", "''")
            escaped_content = content.replace("'", "''")
            insert = f"INSERT INTO {table} (date, title, title_trl, link, content, content_trl) VALUES ('{news_date}', '{title}', '{escaped_title_trl}', '{link}', '{escaped_content}', '{escaped_content_trl}')"
            cursor.execute(insert)
            conn.commit()

            # post to webhook
            if WEBHOOK_URLS[table]:
                if CATEGORIES[header] == 'maintenance':
                    # only send maintenance notifications for game server outages.
                    # '[All servers]' translated here.
                    if '[全サーバー]' not in title:
                        print(f"Maintenance notice found, but is not for all servers.")
                        continue

                notify_webhook(
                    category=CATEGORIES[header],
                    title=title_trl,
                    content=content_trl,
                    link="/".join([HIROBA_URL, link]),
                    timestamp=news_date,
                )
                print(f"Webhook was triggered for {table}.")
            else:
                print(f"Webhook URL not configured for {table}.")
