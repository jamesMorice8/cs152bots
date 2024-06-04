# bot.py
import discord
from discord.ext import commands
import os
import json
import logging
import re
import requests
from report import Report
import pdb
import queue

# Set up logging to the console
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

# There should be a file called 'tokens.json' inside the same folder as this file
token_path = 'tokens.json'
if not os.path.isfile(token_path):
    raise Exception(f"{token_path} not found!")
with open(token_path) as f:
    # If you get an error here, it means your token is formatted incorrectly. Did you put it in quotes?
    tokens = json.load(f)
    discord_token = tokens['discord']




class ModBot(discord.Client):
    def __init__(self): 
        # Existing initializations
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='.', intents=intents)
        self.group_num = None
        self.mod_channels = {} # Map from guild to the mod channel id for that guild
        self.reports = {} # Map from user IDs to the state of their report
        
        self.queues = {
            'explicit_content': queue.Queue(),
            'explicit_danger': queue.Queue(),
            'other': queue.Queue(),
            'other_danger': queue.Queue()
        }
        self.moderator_sessions = {}
        self.active_reports = {}

    def add_to_queue(self, report):
        if report.REASON == "Explicit Content" and report.IMMINENT_DANGER:
            self.queues['explicit_danger'].put(report)
        elif report.REASON == "Explicit Content":
            self.queues['explicit_content'].put(report)
        elif report.IMMINENT_DANGER:
            self.queues['other_danger'].put(report)
        else:
            self.queues['other'].put(report)

    async def process_queue(self, channel, queue_name):
        if not self.queues[queue_name].empty():
            report = self.queues[queue_name].get()
            self.active_reports[channel.id] = {'report': report, 'next_step': 'validate'}
            await channel.send(f"Author: {report.AUTHOR}\nMessages: {report.OFFENSIVE_CONTENT}\n\nDo these messages constitute a violation? (yes/no)")
        else:
            await channel.send(f"No reports to process in the {queue_name} queue.")



    async def on_ready(self):
        '''
        PROVIDED CODE
        '''
        print(f'{self.user.name} has connected to Discord! It is these guilds:')
        for guild in self.guilds:
            print(f' - {guild.name}')
        print('Press Ctrl-C to quit.')

        # Parse the group number out of the bot's name
        match = re.search('[gG]roup (\d+) [bB]ot', self.user.name)
        if match:
            self.group_num = match.group(1)
        else:
            raise Exception("Group number not found in bot's name. Name format should be \"Group # Bot\".")

        # Parse the group number out of the bot's name
        for guild in self.guilds:
            for channel in guild.text_channels:
                if channel.name == f'group-{self.group_num}-mod':
                    self.mod_channels[guild.id] = channel

    async def on_message(self, message):
        if message.author == self.user:
            return

        if message.guild:
            if message.channel.id in self.moderator_sessions:
                pass 
            else:
                if message.channel.name == f'group-{self.group_num}-mod':
                    print('message sent in mod')
                    await self.handle_mod_message(message)
                elif message.channel.name == f'group-{self.group_num}':
                    ################################### MILESTONE 3 ---- MESSAGES SENT IN REGULAR CHAT GO HERE ##############################################################
                    print('message sent in chat')
                    self.eval_text(message)
                    ################################### MILESTONE 3 ---- MESSAGES SENT IN REGULAR CHAT GO HERE ##############################################################
        else:
            await self.handle_dm(message)

    async def handle_active_report(self, message):
        report_data = self.active_reports[message.channel.id]
        report = report_data['report']

        if report_data['next_step'] == 'validate':
            if message.content.lower() == "yes":
                await message.channel.send("Please classify this report:\n1: CSAM, 2: Violent Acts, 3: Substance Abuse, 4: Nudity or Sexual Activity, 5: Other")
                report_data['next_step'] = 'classification'
            elif message.content.lower() == "no":
                await message.channel.send("The report has been marked as not a violation. Would you like to process another report? (yes/no)")
                report_data['next_step'] = 'process_next'
                return  # Early return, no further action is needed

        elif report_data['next_step'] == 'classification':
            if message.content.isdigit() and 1 <= int(message.content) <= 5:
                classifications = {1: "CSAM", 2: "Violent Acts", 3: "Substance Abuse", 4: "Nudity or Sexual Activity", 5: "Other"}
                classification = classifications[int(message.content)]
                await message.channel.send(f"Classified as {classification}. Would you like to report this to the police? (yes/no)")
                report_data['next_step'] = 'police'

        elif message.content.lower() == "yes" and report_data['next_step'] == 'police':
            await message.channel.send("The content has been reported to the police. Would you like to ban the user? (yes/no)")
            report_data['next_step'] = 'ban'

        elif message.content.lower() == "yes" and report_data['next_step'] == 'ban':
            await message.channel.send("The user has been banned. Would you like to process another report? (yes/no)")
            report_data['next_step'] = 'process_next'

        elif message.content.lower() == "no" and report_data['next_step'] == 'ban':
            await message.channel.send("No action taken against the user. Would you like to process another report? (yes/no)")
            report_data['next_step'] = 'process_next'

        elif message.content.lower() == "no" and report_data['next_step'] == 'police':
            await message.channel.send("Would you like to ban the user? (yes/no)")
            report_data['next_step'] = 'ban'

        elif message.content.lower() == "yes" and report_data['next_step'] == 'process_next':
            await self.send_next_report(message.channel)  # Send the next report

        elif message.content.lower() == "no" and report_data['next_step'] == 'process_next':
            await message.channel.send("No more reports will be processed at this time.")
            del self.active_reports[message.channel.id]  # Clean up


    async def send_next_report(self, channel):
        for queue_name, queue in self.queues.items():
            if not queue.empty():
                report = queue.get()
                self.active_reports[channel.id] = {'report': report, 'next_step': None}
                await channel.send(f"Processing next report from {queue_name}: {report}")
                return
        await channel.send("No more reports to process.")
    

    async def handle_dm(self, message):
        # Handle a help message
        if message.content == Report.HELP_KEYWORD:
            reply =  "Use the `report` command to begin the reporting process.\n"
            reply += "Use the `cancel` command to cancel the report process.\n"
            await message.channel.send(reply)
            return

        author_id = message.author.id
        responses = []

        # Only respond to messages if they're part of a reporting flow
        if author_id not in self.reports and not message.content.startswith(Report.START_KEYWORD):
            return

        # If we don't currently have an active report for this user, add one
        if author_id not in self.reports:
            self.reports[author_id] = Report(self, self.add_to_queue)

        # Let the report class handle this message; forward all the messages it returns to uss
        responses = await self.reports[author_id].handle_message(message)
        for r in responses:
            await message.channel.send(r)

        # If the report is complete or cancelled, remove it from our map
        if self.reports[author_id].report_complete():
            self.reports.pop(author_id)

    async def handle_mod_message(self, message):
        if message.author.id in self.moderator_sessions:
            if message.content.lower() == "logout":
                del self.moderator_sessions[message.author.id]
                await message.channel.send("You have been logged out as a moderator.")
                return

            if message.channel.id in self.active_reports:
                await self.handle_active_report(message)
                return 

            if message.content.lower() == "next":
                if any(not q.empty() for q in self.queues.values()):
                    for queue_name, queue in self.queues.items():
                        if not queue.empty():
                            await self.process_queue(message.channel, queue_name)
                            break
                else:
                    await message.channel.send("No more reports to process.")
                return

            if message.content.isdigit():
                queue_index = int(message.content) - 1
                queue_names = list(self.queues.keys())
                if 0 <= queue_index < len(queue_names):
                    queue_name = queue_names[queue_index]
                    if not self.queues[queue_name].empty():
                        await message.channel.send(f"Type 'next' when you are ready to process reports from the {queue_name} queue.")
                    else:
                        await message.channel.send(f"No reports to process in the {queue_name} queue.")
                else:
                    await message.channel.send("Invalid queue number. Please type a valid queue number to proceed.")
                return

        if message.content.lower() == "mod" and message.author.id not in self.moderator_sessions:
            self.moderator_sessions[message.author.id] = message.channel
            queues_list = [f"{i+1}: {qn} ({self.queues[qn].qsize()})" for i, qn in enumerate(self.queues)]
            queues_message = "\n".join(queues_list)
            await message.channel.send(f"You are now logged in as a moderator. Available queues:\n{queues_message}\nType the number of the queue to check its status.")
            return

    def eval_text(self, message):
        ''''
        Here will be code to take a given message, get its content, pass it into a classifier, and
        add it to the respective queue if it is classified as CSAM
        '''
        if len(message.attachments) > 0:
            # here will be stuff
            pass


client = ModBot()
client.run(discord_token)