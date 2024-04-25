import pytube
from datetime import timedelta
from openai import OpenAI
import os
os.environ['OPENAI_API_KEY'] = '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'
client = OpenAI()



class Transcribe():
  def __init__(self, url):
     self.url = url

  def audio2text(self, output_path = './download',max_duration=300):
    try:
        yt = pytube.YouTube(self.url)
    except pytube.exceptions.RegexMatchError:
        return "Invalid URL"
    self.duration = yt.length
    if self.duration > max_duration:
        raise ValueError("Video duration exceeds 5 minutes.")
    stream = yt.streams.filter(only_audio=True).first()
    filename = stream.default_filename[:-4] + ".mp3"  # Change file extension to mp4
    stream.download(output_path=output_path, filename=filename)
    self.audio_file_path = output_path + '/' + filename
    self.title = yt.title
    self.id = self.url.strip('https://www.youtube.com/watch?v=')
    audio_file = open(self.audio_file_path, "rb")
    self.transcript = client.audio.transcriptions.create(
        file=audio_file,
        model="whisper-1",
        response_format="verbose_json",
        timestamp_granularities=["segment"]
        )
    self.text_with_ts = {}
    for i in range(len(self.transcript.segments)):
      time = round(self.transcript.segments[i]['start'])
      timestamp = str(timedelta(seconds = time))
      text_seg = self.transcript.segments[i]['text']
      self.text_with_ts[timestamp] = text_seg
    self.language = self.transcript.language
    os.remove(self.audio_file_path)
