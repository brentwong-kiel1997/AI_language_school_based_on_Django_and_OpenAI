import yt_dlp as youtube_dl
from datetime import timedelta
import os
from openai import OpenAI
from datetime import datetime


os.environ['OPENAI_API_KEY'] = 'please input your own openAI API'
client = OpenAI()


class Transcribe():
    def __init__(self, url):
        self.url = url

    def audio2text(self, output_path='./download', max_duration=300):
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': os.path.join(output_path, '%(id)s.%(ext)s'),
        }

        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(self.url, download=True)
            self.duration = info_dict['duration']
            if self.duration > max_duration:
                raise ValueError("Video duration exceeds 5 minutes.")
            self.audio_file_path = ydl.prepare_filename(info_dict).replace('.webm', '.mp3').replace('.m4a', '.mp3')
            self.title = info_dict['title']
            self.id = info_dict['id']

        audio_file = open(self.audio_file_path, "rb")
        self.transcript = client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-1",
            response_format="verbose_json",
            timestamp_granularities=["segment"]
        )
        self.text_with_ts = {}

        for segment in self.transcript.segments:
            time = segment['start']
            timestamp = str(timedelta(seconds=time)).split('.')[0]
            text_seg = segment['text']
            self.text_with_ts[timestamp] = text_seg

        self.language = self.transcript.language

        # Example of converting upload_date from a different format
        upload_date_str = info_dict['upload_date']  # Assuming this is in 'YYYYMMDD' format
        upload_date = datetime.strptime(upload_date_str, '%Y%m%d').date()
        #######################

        self.upload_date = upload_date.strftime('%Y-%m-%d')
        os.remove(self.audio_file_path)


class Generator():
    def __init__(self, target_language, native_language, text):
        self.target_language = target_language
        self.native_language = native_language
        self.text = str(text)
        self.target_language_level = 'b1'
        self.prompt = f"""
        I am a naitve {self.native_language} speaker.\
           I\'m learning {self.target_language} and my {self.target_language} is at {self.target_language_level} level.
           you are my {self.target_language} tearcher. I\'ll provide a transcript of youtube news video at the end,
            you need to generate learning materials based on the transcript provided and help me learn {self.target_language}
            via the youtube video\
           you need to generate 5 sections of learning materials for me according to this article,
           please make sure those materials are appropriate to my {self.target_language} level.\n
           section 1: list 20 import words from the transcript, as in collins dictionary from {self.target_language} to {self.native_language} \n
           section 2: list 3 import grammars used in the transcript with example sentences and illustrations and explanations.\n
            section 3: ask me 3 questions based on the transcript in {self.target_language}\n
           section 4: give me answers for section 3 in {self.target_language}\n
            section 5 : give me translation of the transcript in {self.native_language}\n
         please give me the reply in json format\n
            as show in following example from German to English,
            please do not change the keys in the first level of the dictionary,
            please strictly follow the format as python libraries and make sure it strictly follows the parenthesis patterns and return in correct format \', \n\n\n
                  {dic} \n\n\n\n
                  the article:\n
                  """

    def chatbox(self,
                model='gpt-3.5-turbo'):
        self.message_history = []
        client = OpenAI()
        self.message_history.append({'role': 'user', 'content': self.prompt + self.text})
        response = client.chat.completions.create(
            model=model,
            messages=self.message_history,
            temperature=0,
            response_format={"type": "json_object"}
        )
        self.reply = response.choices[0].message.content
        self.message_history.append({'role': 'assistant', 'content': self.reply})


dic = {
    "import_words":
        {
            "Mann": "man", "Tempel": "temple", "Gott": "God", "Leben": "life", "Krieg": "war",
            "Albträumen": "nightmares", "traumatisiert": "traumatized",
            "russischen": "Russian",
            "Okaine": "Ukraine",
            "kümmert sich um": "take care of",
            "Tod": "death",
            "Verletzten": "injured",
            "Wunde": "wound",
            "Behandlung": "treatment",
            "Ananfalls": "attacks",
            "erschießen": "shoot",
            "fliehen": "flee",
            "belasten": "burden",
            "Arbeitslos": "unemployed",
            "Tagelöner": "day laborer"

        },
    "import_grammars":
        {
            "Modal verbs (werden)":
                {
                    "Example": "Wenn eine Behandlung möglich ist, werden sie gerettet.",
                    "Explanation": "The modal verb 'werden' is used to express future tense, indicating that they will be saved if treatment is possible."
                },
            "Prepositions (um)":
                {
                    "Example": "Er zahlte umgerechnet rund 3000 Euro an allen russischen Vermittler.",
                    "Explanation": "The preposition 'um' is used to indicate the amount paid (around 3000 euros) to all Russian intermediaries."
                },
            "Comparative forms (düster)":
                {
                    "Example": "Die wirtschaftliche Lage Nepals ist düster.",
                    "Explanation": "The comparative form 'düster' (dark) is used to describe the economic situation of Nepal."
                }

        },
    "questions":
        [
            "Was hat der Mann im Tempel gemacht?",
            "Warum ist die wirtschaftliche Lage Nepals düster?",
            "Was hat die Familie des Soldaten belastet?"
        ]
    ,
    "answers":
        [
            "Der Mann ist in den Tempel gegangen, um Gott für das gerettete Leben im Krieg zu danken.",
            "Die wirtschaftliche Lage Nepals ist düster aufgrund hoher Arbeitslosigkeit und hoher Inflation.",
            "Die Familie des Soldaten wurde von Schulden belastet, die er einem Vermittler gezahlt hatte, um ihn nach Russland zu bringen."
        ],
    "translation":
        {
            "0:00:03": "A man is in this temple to thank God for saving his life in a war, far away.",
            "0:00:10": "He suffers from nightmares deeply traumatized by what he experienced in the Russian Amel in Okaine.",
            "0:00:20": "In Russia, nobody cares about death.",
            "0:00:23": "The living wounded depend on the severity of the injury.",
            "0:00:26": "If treatment is possible, they are saved.",
            "0:00:28": "At times, we were instructed to shoot the severely injured soldiers where they lay.",
            "0:00:34": "So the man managed to escape, many others did not.",
            "0:00:40": "He paid around 3000 euros to all Russian intermediaries to flee and come home.",
            "0:00:47": "Now he is not burdened by debts.",
            "0:00:49": "Since his return, he has been unemployed.",
            "0:00:52": "To find work, he is willing to work as a day laborer.",
            "0:01:09": "The economic situation in Nepal is bleak, unemployment is high, inflation is high.",
            "0:01:14": "The country relies on remittances from millions of people working abroad.",
            "0:01:20": "British intermediaries lure potential Nepalese recruits with a salary of $2000 per month and accelerated citizenship.",
            "0:01:29": "A Nepalese minister is trying to convince Russian officials not to recruit Nepalese citizens anymore.",
            "0:01:38": "But in vain.",
            "0:01:42": "I am concerned that the recruitment of our citizens into the armed forces of a nation with which we have no official pact or treaty is becoming the norm.",
            "0:01:56": "In a village outside the capital Kathmandu, this family mourns their son and husband.",
            "0:02:03": "Purner-Bahal Duw was killed three months ago on the dangerous UK-Indian front.",
            "0:02:13": "Another Nepalese soldier called his wife Lilo to deliver the news of her husband's death.",
            "0:02:23": "When I heard about my husband's death, I wanted to jump off a cliff and end my life.",
            "0:02:28": "It took weeks for me to believe it.",
            "0:02:32": "I couldn't believe he was no more, and I still feel like his call could come.",
            "0:02:45": "But that call will never come, I know.",
            "0:02:49": "The family also has no idea if they will see his body and if they will receive a proper burial.",
            "0:02:56": "Lilo Gurung is not only struggling with her grief but also with debts of 6000 euros that her husband had paid to a mediator to bring him to Russia.",
            "0:03:10": "Back in Kathmandu, the future looks uncertain for this family, marked by her husband's experiences in a foreign war.",
            "0:03:18": "Many people are still trapped in this war and do not know if they will ever return home, dead or alive."
        }
}
